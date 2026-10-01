"""Behavioral regression checks for the repository policy boundary."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def template(self):
        return yaml.safe_load((ROOT / "templates/development-cycle.yaml").read_text())

    def run_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adapter.yaml"
            path.write_text(text, encoding="utf-8")
            return subprocess.run([sys.executable, str(ROOT / "scripts/validate_adapter.py"),
                                   str(path)], capture_output=True, text=True)

    def check(self, document):
        return self.run_text(yaml.safe_dump(document, sort_keys=False))

    def test_template_is_valid(self):
        self.assertEqual(self.check(self.template()).returncode, 0)

    def test_comments_cannot_supply_required_sections(self):
        # Old validator sees every required section name, even though most are comments.
        source = (ROOT / "templates/development-cycle.yaml").read_text()
        runtime = source[source.index("execution:"):source.index("progress:")]
        text = "\n".join("# " + line for line in source.splitlines()) + "\n" + runtime
        result = self.run_text(text)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_scalar_containing_configuration_is_not_an_adapter(self):
        source = (ROOT / "templates/development-cycle.yaml").read_text()
        result = self.run_text("'" + source.replace("'", "''") + "'\n")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_equivalent_json_flow_mapping_is_accepted(self):
        result = self.run_text(json.dumps(self.template()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_boolean_string_is_rejected(self):
        data = self.template()
        data["validation"]["final_remote_required"] = "true"
        self.assertNotEqual(self.check(data).returncode, 0)

    def test_duplicate_keys_are_rejected(self):
        source = (ROOT / "templates/development-cycle.yaml").read_text()
        self.assertNotEqual(self.run_text(source + "\nrepository: {}\n").returncode, 0)

    def test_unknown_fields_are_rejected(self):
        data = self.template()
        data["compute"]["preferance"] = "local_first"
        self.assertNotEqual(self.check(data).returncode, 0)

    def test_enabled_unconfigured_compute_is_rejected(self):
        data = self.template()
        data["compute"]["codex_backend"]["enabled"] = True
        self.assertNotEqual(self.check(data).returncode, 0)

    def test_repo_can_restrict_work_subagents(self):
        data = self.template()
        data["execution"]["work"]["subagents"] = "disabled"
        self.assertEqual(self.check(data).returncode, 0)

    def test_legacy_schema_requires_explicit_migration(self):
        data = self.template()
        data["schema"] = "continuous-development-cycle/v1"
        result = self.check(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migrat", result.stdout.lower())

    def test_incompatible_skill_version_is_rejected(self):
        data = self.template()
        data["policy"] = {"revision": "1", "skill_min_version": "99.0.0",
                          "skill_max_version_exclusive": "100.0.0", "approved_exceptions": []}
        self.assertNotEqual(self.check(data).returncode, 0)

    def test_exception_must_match_effective_setting(self):
        data = self.template()
        data["policy"] = {"revision": "1", "skill_min_version": "2.2.0",
                          "skill_max_version_exclusive": "3.0.0", "approved_exceptions": [
            {"setting": "execution.work.subagents", "value": "disabled", "source": "user:approved-1",
             "reason": "Temporary restriction", "recorded_at_utc": "2026-09-22T12:00:00Z"}]}
        self.assertNotEqual(self.check(data).returncode, 0)

    def test_malformed_yaml_fails_without_traceback(self):
        result = self.run_text("[broken:\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
