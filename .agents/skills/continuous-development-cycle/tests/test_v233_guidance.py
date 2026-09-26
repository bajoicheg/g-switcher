"""CDC 2.3.3 guidance contracts for larger compute budgets and lean provisioning."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V233GuidanceTests(unittest.TestCase):
    def test_version_and_manifest_are_consistent(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (2, 3, 3))
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["version"], version)
        self.assertIn("v" + version, (ROOT / "SKILL.md").read_text())

    def test_higher_compute_budget_is_capacity_not_retry_permission(self):
        core = (ROOT / "SKILL.md").read_text().lower()
        budget = (ROOT / "references" / "budget-ledger.md").read_text().lower()
        self.assertIn("higher compute capacity", core)
        self.assertIn("information gain", core)
        self.assertIn("not a retry instruction", core)
        self.assertIn("higher compute budget", budget)
        self.assertIn("distinct information", budget)
        self.assertIn("concrete correction", budget)

    def test_compute_environment_guidance_is_lean_and_missing_only(self):
        compute = (ROOT / "references" / "codex-compute.md").read_text().lower()
        for phrase in (
            "reuse the provider runtime",
            "missing-only",
            "allow-list",
            "do not reinstall",
            "third-party package sources",
        ):
            self.assertIn(phrase, compute)

    def test_failures_are_classified_before_another_start(self):
        compute = (ROOT / "references" / "codex-compute.md").read_text().lower()
        self.assertIn("classify the failure", compute)
        for category in ("setup", "network", "runtime", "product"):
            self.assertIn(category, compute)
        self.assertIn("before another compute start", compute)

    def test_pressure_scenarios_cover_new_failure_modes(self):
        scenarios = (ROOT / "tests" / "pressure-scenarios.md").read_text().lower()
        self.assertIn("larger compute budget tempts retries", scenarios)
        self.assertIn("heavy bootstrap repeats provider tools", scenarios)


if __name__ == "__main__":
    unittest.main()

