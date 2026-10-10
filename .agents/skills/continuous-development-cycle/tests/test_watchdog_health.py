"""CDC 2.3.7 watchdog health vector contracts."""
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class WatchdogHealthTests(unittest.TestCase):
    def setUp(self):
        self.health = importlib.import_module("watchdog_health")

    def probe(self, **states):
        signals = {
            "scheduler": {"state": "ok"},
            "chat": {"state": "active"},
            "invocation": {"state": "idle"},
            "lease": {"state": "released"},
            "external": {"state": "none"},
            "progress": {"state": "fresh"},
        }
        for name, state in states.items():
            signals[name]["state"] = state
        return {
            "schema": "watchdog-health-probe/v1",
            "repository": "example/project",
            "observed_at_utc": "2026-09-24T06:30:00Z",
            "signals": signals,
        }

    def test_healthy_idle_watchdog(self):
        result = self.health.assess(self.probe())
        self.assertEqual(result["overall"], "HEALTHY")
        self.assertEqual(result["recovery_action"], "none")

    def test_scheduler_drift_requires_recovery(self):
        result = self.health.assess(self.probe(scheduler="drift"))
        self.assertEqual(result["overall"], "RECOVERY_REQUIRED")
        self.assertEqual(result["recovery_action"], "repair_scheduler")

    def test_archived_chat_requires_recovery(self):
        result = self.health.assess(self.probe(chat="archived"))
        self.assertEqual(result["overall"], "RECOVERY_REQUIRED")
        self.assertEqual(result["recovery_action"], "restore_chat_dependency")

    def test_completed_invocation_with_owned_lease_is_orphan_recovery(self):
        probe = self.probe(invocation="completed", lease="fresh")
        result = self.health.assess(probe)
        self.assertEqual(result["overall"], "RECOVERY_REQUIRED")
        self.assertEqual(result["recovery_action"], "reconcile_orphan_lease")
        self.assertIn("orphan", " ".join(result["reasons"]).lower())

    def test_running_external_work_is_blocked_not_failed(self):
        result = self.health.assess(self.probe(external="running"))
        self.assertEqual(result["overall"], "BLOCKED")
        self.assertEqual(result["recovery_action"], "observe_external")

    def test_unknown_external_state_requires_reconciliation(self):
        result = self.health.assess(self.probe(external="unknown"))
        self.assertEqual(result["overall"], "BLOCKED")
        self.assertEqual(result["recovery_action"], "reconcile_external")

    def test_stale_progress_without_external_guard_is_stalled(self):
        result = self.health.assess(self.probe(progress="stale"))
        self.assertEqual(result["overall"], "STALLED")
        self.assertEqual(result["recovery_action"], "diagnose_no_progress")

    def test_unknown_signal_is_degraded(self):
        result = self.health.assess(self.probe(chat="unknown"))
        self.assertEqual(result["overall"], "DEGRADED")
        self.assertEqual(result["recovery_action"], "complete_health_probe")

    def test_health_never_grants_side_effect_authority(self):
        for probe in (
            self.probe(),
            self.probe(invocation="completed", lease="fresh"),
            self.probe(external="running"),
        ):
            result = self.health.assess(probe)
            self.assertFalse(result["authorizes_takeover"])
            self.assertFalse(result["authorizes_external_start"])
            self.assertFalse(result["authorizes_product_write"])

    def test_exact_signal_set_is_required(self):
        probe = self.probe()
        del probe["signals"]["chat"]
        with self.assertRaises(ValueError):
            self.health.assess(probe)


if __name__ == "__main__":
    unittest.main()
