"""Compatibility and cross-component policy guards for iteration two."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from contracts import ContractError, load_yaml
from validate_adapter import validate_adapter
from validate_checkpoint import validate_checkpoint
from recovery import decide_recovery
import operation_intent

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    return {
        "execution_lease": {"backend": "single_writer", "remote": None,
            "coordination_ref": None, "designated_executor_id": None, "assignment_ref": None},
        "wait": {"queued_seconds": 900, "setup_seconds": 1800, "running_seconds": 3600,
            "unknown_seconds": 300, "observation_max_age_seconds": 300,
            "poll_initial_seconds": 30, "poll_cap_seconds": 300},
        "recovery": {"max_snapshot_age_seconds": 300},
        "budget": {"task_limits": {"compute_starts": 3, "ci_starts": 1, "agent_starts": 4},
            "wake_limits": {"status_polls": 4, "tool_calls": 40}, "max_parallel_agents": 2,
            "checkpoint_reserve": {"tokens": 4000, "tool_calls": 8},
            "provider_max_age_seconds": 300, "actions_budget": "conserve"},
    }


class OrchestrationPolicyTests(unittest.TestCase):
    def adapter(self):
        data = load_yaml(ROOT / "templates/development-cycle.yaml")
        data["orchestration"] = configuration()
        data["policy"]["skill_min_version"] = "2.3.0"
        data["checkpoint"]["schema"] = "development-work-status/v3"
        for name in ("routing", "recovery_recipes", "continuation", "fleet", "convergence", "progress_slo", "audit", "autonomy", "publication", "hardening", "maturity"):
            data.pop(name, None)
        return data

    def test_v22_adapter_stays_compatible_without_new_section(self):
        data = self.adapter()
        data.pop("orchestration")
        data["policy"]["skill_min_version"] = "2.2.0"
        data["execution"]["lease"]["terminal_external_takeover_without_fresh_heartbeat"] = True
        validate_adapter(data, "2.3.0")

    def test_valid_v23_configuration_is_accepted(self):
        validate_adapter(self.adapter(), "2.3.0")

    def test_new_controls_reject_legacy_timer_only_takeover(self):
        data = self.adapter()
        data["execution"]["lease"]["terminal_external_takeover_without_fresh_heartbeat"] = True
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")

    def test_new_controls_require_version_floor(self):
        data = self.adapter()
        data["policy"]["skill_min_version"] = "2.2.0"
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")

    def test_budget_cannot_override_exhausted_actions(self):
        data = self.adapter()
        data["ci"]["actions_budget"] = "exhausted"
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")

    def test_git_lease_requires_separate_well_formed_coordination_ref(self):
        data = self.adapter()
        data["orchestration"]["execution_lease"].update(backend="git", remote="origin",
                                                       coordination_ref="refs/heads/../main")
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")
        data["orchestration"]["execution_lease"]["coordination_ref"] = "refs/heads/cdc-coordination"
        validate_adapter(data, "2.3.0")

    def test_partial_designation_is_not_valid_single_writer_assignment(self):
        data = self.adapter()
        data["orchestration"]["execution_lease"]["designated_executor_id"] = "11111111-1111-4111-8111-111111111111"
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")

    def test_wait_backoff_and_budget_types_are_validated(self):
        data = self.adapter()
        data["orchestration"]["wait"]["poll_cap_seconds"] = 1
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")
        data = self.adapter()
        data["orchestration"]["budget"]["max_parallel_agents"] = True
        with self.assertRaises(ContractError):
            validate_adapter(data, "2.3.0")

    def test_old_intent_is_readable_and_new_intent_records_producer_version(self):
        old = json.loads((ROOT / "templates/operation-intent.json").read_text())
        old["skill_version"] = "2.2.0"
        operation_intent.validate_intent(old)
        new = operation_intent.prepare(old["binding"], "new-attempt", old["source_ref"], old["created_at_utc"])
        self.assertEqual(new["skill_version"], "2.3.0")

    def test_legacy_checkpoint_has_no_new_pointer_requirement(self):
        adapter = self.adapter()
        adapter.pop("orchestration")
        adapter["policy"]["skill_min_version"] = "2.2.0"
        data = load_yaml(ROOT / "templates/work-status.md", frontmatter=True)
        data.pop("control")
        validate_checkpoint(data, adapter)

    def test_control_pointers_require_policy_and_valid_identity(self):
        adapter = self.adapter()
        data = load_yaml(ROOT / "templates/work-status.md", frontmatter=True)
        adapter.pop("orchestration")
        with self.assertRaises(ContractError):
            validate_checkpoint(data, adapter)
        adapter = self.adapter()
        data["control"]["executor_id"] = "named-owner"
        with self.assertRaises(ContractError):
            validate_checkpoint(data, adapter)

    def test_lease_revision_pointer_needs_reference_and_generation(self):
        data = load_yaml(ROOT / "templates/work-status.md", frontmatter=True)
        data["control"]["execution_lease_revision"] = "a" * 40
        with self.assertRaises(ContractError):
            validate_checkpoint(data, self.adapter())
        data["control"].update(execution_lease_ref="refs/heads/cdc-coordination", lease_generation=2)
        validate_checkpoint(data, self.adapter())

    def test_recovery_maps_actual_policy_digest_without_changing_checkpoint_contract(self):
        binding = validate_adapter(self.adapter())
        checkpoint = load_yaml(ROOT / "templates/work-status.md", frontmatter=True)
        checkpoint["policy_digest"] = binding["policy_digest"]
        validate_checkpoint(checkpoint, self.adapter())
        snapshot = json.loads((ROOT / "templates/recovery-snapshot.json").read_text())
        snapshot["bindings"]["policy_revision"] = binding["policy_revision"]
        snapshot["bindings"]["policy_digest"] = "sha256:" + checkpoint["policy_digest"]
        probe = copy.deepcopy(snapshot)
        probe.update(schema="recovery-probe/v1", complete=True, source_valid=True)
        result = decide_recovery(snapshot, probe, snapshot["observed_at_utc"])
        self.assertTrue(result["fast_path"], result)
        self.assertFalse(result["allow_write"])
        probe["bindings"]["policy_digest"] = "sha256:" + "b" * 64
        self.assertFalse(decide_recovery(snapshot, probe, snapshot["observed_at_utc"])["fast_path"])


if __name__ == "__main__":
    unittest.main()
