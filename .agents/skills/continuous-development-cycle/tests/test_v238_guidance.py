"""CDC 2.3.8 visible-continuity guidance contracts."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V238GuidanceTests(unittest.TestCase):
    def test_version_manifest_and_core_are_consistent(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (2, 3, 8))
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["version"], version)
        self.assertIn("v" + version, (ROOT / "SKILL.md").read_text())

    def test_announced_next_action_cannot_end_on_discovery(self):
        core = (ROOT / "SKILL.md").read_text().lower()
        self.assertIn("close every accepted execution commitment", core)
        self.assertIn("not a continuation boundary", core)
        self.assertIn("next policy-authorized fallback", core)
        self.assertIn("explicit durable handoff/blocker", core)

    def test_final_handoff_matches_release_shape(self):
        progress = (ROOT / "references" / "progress-and-checkpoints.md").read_text().lower()
        self.assertIn("commitment closure and visible continuity", progress)
        self.assertIn("release-consistent handoff", progress)
        self.assertIn("active_executor: none", progress)
        self.assertIn("lease_state: released", progress)

    def test_watchdog_distinguishes_visibility_from_progress(self):
        watchdog = (ROOT / "references" / "watchdog-recovery-and-migration.md").read_text().lower()
        self.assertIn("silent-dead-end recovery", watchdog)
        self.assertIn("execution visibility", watchdog)
        self.assertIn("meaningful development progress", watchdog)
        self.assertIn("ownership state", watchdog)

    def test_pressure_suite_covers_new_rca_modes(self):
        scenarios = (ROOT / "tests" / "pressure-scenarios.md").read_text().lower()
        self.assertIn("discovery dead-end after promised fallback", scenarios)
        self.assertIn("released lease but active checkpoint", scenarios)
        self.assertIn("partial multi-write success looks like external movement", scenarios)


if __name__ == "__main__":
    unittest.main()
