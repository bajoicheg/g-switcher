from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import watchdog_sentinel as sentinel


BINDING = {"project_id": "cdc-fleet", "source_ref": "refs/heads/main",
           "role": "fleet-supervisor"}


class FakeRuntime:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reconcile(self, binding):
        self.calls.append(dict(binding))
        return self.result


class FleetSupervisorSentinelTests(unittest.TestCase):
    def test_only_fleet_supervisor_role_is_accepted(self):
        with self.assertRaises(ValueError):
            sentinel.reconcile_supervisor(
                FakeRuntime({"outcome": "no_effect", "assessment": {"overall": "HEALTHY"}}),
                {**BINDING, "role": "project-watchdog"})

    def test_healthy_or_owner_paused_supervisor_is_settled_without_effect_authority(self):
        for overall in ("HEALTHY", "OWNER_PAUSED", "PROJECT_TERMINAL"):
            runtime = FakeRuntime({"outcome": "no_effect", "assessment": {"overall": overall}})
            result = sentinel.reconcile_supervisor(runtime, BINDING)
            self.assertFalse(result["continuation_required"])
            self.assertFalse(result["authorizes_scheduler_mutation"])
            self.assertFalse(result["authorizes_product_write"])
            self.assertEqual(runtime.calls, [BINDING])

    def test_recreation_requests_continuation_until_supervisor_is_actually_woken(self):
        repaired = sentinel.reconcile_supervisor(
            FakeRuntime({"outcome": "recreated", "assessment": {"overall": "MISSING"}}),
            BINDING)
        self.assertTrue(repaired["continuation_required"])
        unknown = sentinel.reconcile_supervisor(
            FakeRuntime({"outcome": "provider_outcome_unknown",
                         "assessment": {"overall": "MISSING"}}),
            BINDING)
        self.assertTrue(unknown["continuation_required"])

    def test_remaining_duplicate_materialization_requires_another_sentinel_wake(self):
        result = sentinel.reconcile_supervisor(
            FakeRuntime({"outcome": "duplicates_quiesced",
                         "assessment": {"action": "QUIESCE_DUPLICATES"}}),
            BINDING)
        self.assertTrue(result["continuation_required"])


if __name__ == "__main__":
    unittest.main()
