import copy
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
if importlib.util.find_spec("watchdog_liveness"):
    import watchdog_liveness as liveness
else:
    liveness = None

NOW = "2026-09-28T12:00:00Z"
PROJECT = {"project_id": "alpha", "source_ref": "refs/heads/main", "watchdog_id": "watchdog-alpha"}


def probe(project=None, **changes):
    project = copy.deepcopy(project or PROJECT)
    result = {
        "schema": "watchdog-liveness-probe/v1",
        "binding": {**project, "incident_id": "delivery-incident-1"},
        "signals": {
            "scheduler": {"state": "disabled", "schedule": "RRULE:FREQ=HOURLY", "prompt": "Read live project policy"},
            "invocation": {"state": "completed", "invocation_id": "previous-invocation"},
            "work": {"state": "runnable", "source_revision": "a" * 40, "terminal_proof": None},
            "owner": {"state": "released"},
            "guard": {"state": "released"},
            "external": {"state": "none"},
            "progress": {"state": "fresh"},
            "pause": {"state": "running", "owner_evidence": None},
            "policy": {"recovery_allowed": True, "revision": "policy-1", "owner_authorization": "owner:policy-1", "effects_remaining": 20},
        },
    }
    for value in result["signals"].values():
        value["observed_at_utc"] = NOW
    for name, value in changes.items():
        result["signals"][name].update(value if isinstance(value, dict) else {"state": value})
    return result


class LivenessTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(liveness, "the versioned liveness contract is not implemented")

    def test_disabled_overdue_and_premature_completion_are_critical(self):
        for scheduler, invocation in [("disabled", "idle"), ("overdue", "idle"), ("enabled", "completed")]:
            with self.subTest(scheduler=scheduler, invocation=invocation):
                value = probe(scheduler=scheduler, invocation={"state": invocation, "invocation_id": "old" if invocation == "completed" else None})
                result = liveness.assess(value, now=NOW)
                self.assertEqual(result["overall"], "CRITICAL")
                self.assertTrue(result["recovery_eligible"])
                self.assertFalse(result["authorizes_scheduler_mutation"])

    def test_current_explicit_owner_pause_wins_liveness_faults(self):
        result = liveness.assess(probe(pause={"state": "paused", "owner_evidence": "owner-message:123"}), now=NOW)
        self.assertEqual(result["overall"], "PAUSED")
        self.assertFalse(result["recovery_eligible"])

    def test_stale_future_or_unsupported_pause_never_grants_recovery(self):
        for patch in [{"owner_evidence": None}, {"observed_at_utc": "2026-09-28T11:00:00Z"}, {"observed_at_utc": "2026-09-28T12:00:01Z"}]:
            with self.subTest(patch=patch):
                result = liveness.assess(probe(pause={"state": "paused", "owner_evidence": "owner:1", **patch}), now=NOW)
                self.assertNotEqual(result["overall"], "PAUSED")
                self.assertFalse(result["recovery_eligible"])

    def test_each_stale_signal_and_each_duplicate_risk_denies_recovery(self):
        for name in probe()["signals"]:
            with self.subTest(stale=name):
                self.assertFalse(liveness.assess(probe(**{name: {"observed_at_utc": "2026-09-28T11:00:00Z"}}), now=NOW)["recovery_eligible"])
        for name, state in [("owner", "active"), ("owner", "unknown"), ("guard", "active"), ("guard", "unknown"), ("external", "submitting"), ("external", "running"), ("external", "queued"), ("external", "unknown"), ("external", "terminal_unreconciled"), ("invocation", "running"), ("invocation", "unknown"), ("progress", "unknown"), ("work", "unknown"), ("pause", "unknown")]:
            with self.subTest(name=name, state=state):
                self.assertFalse(liveness.assess(probe(**{name: state}), now=NOW)["recovery_eligible"])

    def test_policy_and_budget_are_independent_gates(self):
        for patch in [{"recovery_allowed": False}, {"effects_remaining": 0}, {"owner_authorization": None}]:
            self.assertFalse(liveness.assess(probe(policy=patch), now=NOW)["recovery_eligible"])

    def test_terminal_requires_proof_and_quietness_never_means_terminal(self):
        terminal_proof = {"project_id": PROJECT["project_id"], "source_ref": PROJECT["source_ref"], "source_revision": "a" * 40, "evidence_ref": "git:terminal-proof"}
        result = liveness.assess(probe(work={"state": "terminal", "terminal_proof": terminal_proof}), now=NOW)
        self.assertEqual(result["overall"], "COMPLETE")
        self.assertFalse(result["recovery_eligible"])
        missing = liveness.assess(probe(work={"state": "terminal", "terminal_proof": None}), now=NOW)
        self.assertNotEqual(missing["overall"], "COMPLETE")
        stale = liveness.assess(probe(progress="stale"), now=NOW)
        self.assertEqual(stale["overall"], "CRITICAL")

    def test_terminal_proof_must_match_current_project_ref_and_exact_source_revision(self):
        proof = {"project_id": PROJECT["project_id"], "source_ref": PROJECT["source_ref"], "source_revision": "a" * 40, "evidence_ref": "git:terminal-proof"}
        for name, value in [("project_id", "other"), ("source_ref", "refs/heads/other"), ("source_revision", "b" * 40)]:
            result = liveness.assess(probe(work={"state": "terminal", "terminal_proof": {**proof, name: value}}), now=NOW)
            self.assertNotEqual(result["overall"], "COMPLETE")

    def test_probe_is_bound_to_exact_project_ref_watchdog_and_incident(self):
        for name, value in [("project_id", "other"), ("source_ref", "refs/heads/other"), ("watchdog_id", "other"), ("incident_id", "other")]:
            expected = {**PROJECT, "incident_id": "delivery-incident-1"}
            actual = probe()
            actual["binding"][name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                liveness.assess(actual, now=NOW, expected_binding=expected)

    def test_running_and_completed_invocations_require_exact_identity(self):
        for state in ["running", "completed"]:
            result = liveness.assess(probe(invocation={"state": state, "invocation_id": None}), now=NOW)
            self.assertFalse(result["recovery_eligible"])

    def test_health_entrypoint_dispatches_new_schema_without_weakening_old_reader(self):
        import watchdog_health
        self.assertEqual(watchdog_health.assess(probe())["overall"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
