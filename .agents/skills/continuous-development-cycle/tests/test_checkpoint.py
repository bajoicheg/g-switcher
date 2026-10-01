"""Recovery must bind its state to the actual validated policy."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CheckpointTests(unittest.TestCase):
    def template(self):
        text = (ROOT / "templates/work-status.md").read_text()
        return yaml.safe_load(text.split("---", 2)[1])

    def run_doc(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.md"
            path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n")
            return subprocess.run([sys.executable, str(ROOT / "scripts/validate_checkpoint.py"),
                str(path), "--adapter", str(ROOT / "templates/development-cycle.yaml")],
                capture_output=True, text=True)

    def bound(self):
        data = self.template()
        adapter = yaml.safe_load((ROOT / "templates/development-cycle.yaml").read_text())
        data["policy_digest"] = hashlib.sha256(json.dumps(adapter, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        data["policy_revision"] = adapter["policy"]["revision"]
        data["candidate_sha"] = "a" * 40
        data["observed_at_utc"] = "2026-09-22T12:00:00Z"
        data["branch"] = "feature/task"
        data["phase"] = "implementation"
        return data

    def test_recovery_template_is_valid(self):
        result = self.run_doc(self.template())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bound_implementation_is_valid(self):
        result = self.run_doc(self.bound())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_policy_digest_requires_recovery(self):
        data = self.bound()
        data["policy_digest"] = "0" * 64
        self.assertNotEqual(self.run_doc(data).returncode, 0)

    def test_unknown_phase_fails(self):
        data = self.template()
        data["phase"] = "greenish"
        self.assertNotEqual(self.run_doc(data).returncode, 0)

    def test_unknown_submission_needs_intent_binding(self):
        data = self.bound()
        data.update(phase="waiting_external", lease_state="waiting_external",
                    waiting_external_sha="a" * 40, waiting_external_kind="codex")
        self.assertNotEqual(self.run_doc(data).returncode, 0)
        intent = json.loads((ROOT / "templates/operation-intent.json").read_text())
        data.update(operation_intent_ref="coordination:intent-1", operation_key=intent["operation_key"])
        result = self.run_doc(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_green_evidence_cannot_close(self):
        data = self.bound()
        data.update(phase="complete", last_green_sha="a" * 40)
        self.assertNotEqual(self.run_doc(data).returncode, 0)

    def test_completion_conflicts_with_external_wait_even_with_previous_green(self):
        data = self.bound()
        intent = json.loads((ROOT / "templates/operation-intent.json").read_text())
        data.update(phase="complete", lease_state="waiting_external", last_green_sha="a" * 40,
                    last_green_evidence="evidence:green-1", waiting_external_sha="a" * 40,
                    waiting_external_kind="codex", operation_intent_ref="coordination:intent-1",
                    operation_key=intent["operation_key"])
        self.assertEqual(self.run_doc(data).returncode, 1)

    def test_wrong_repository_is_rejected(self):
        data = self.bound()
        data["repository"] = "other/repo"
        self.assertNotEqual(self.run_doc(data).returncode, 0)

    def test_delimiter_inside_a_value_is_not_frontmatter_end(self):
        data = self.bound()
        data["branch"] = "feature/fix---recovery"
        result = self.run_doc(data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
