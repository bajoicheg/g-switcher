"""Regression tests for exact-source build provenance (standard library only)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from verify_build_revision import VerificationError, verify_revision


class BuildRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gs-build-revision-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Build fixture")
        self.git("config", "user.email", "ci@example.invalid")
        (self.root / "tracked.txt").write_text("fixture\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "--quiet", "-m", "fixture")
        self.sha = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True, capture_output=True, text=True, timeout=20,
        ).stdout

    def test_accepts_exact_clean_revision(self):
        self.assertEqual(verify_revision(self.sha, self.root, require_clean=True), self.sha)

    def test_rejects_moving_branch_instead_of_sha(self):
        with self.assertRaises(VerificationError):
            verify_revision("main", self.root)

    def test_rejects_abbreviated_sha(self):
        with self.assertRaises(VerificationError):
            verify_revision(self.sha[:12], self.root)

    def test_rejects_missing_expected_sha(self):
        with self.assertRaises(VerificationError):
            verify_revision("", self.root)

    def test_rejects_wrong_revision(self):
        with self.assertRaisesRegex(VerificationError, "does not match"):
            verify_revision("0" * 40, self.root)

    def test_rejects_modified_tracked_file(self):
        (self.root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(VerificationError, "not clean"):
            verify_revision(self.sha, self.root, require_clean=True)

    def test_rejects_staged_change(self):
        (self.root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        with self.assertRaisesRegex(VerificationError, "not clean"):
            verify_revision(self.sha, self.root, require_clean=True)

    def test_rejects_untracked_file_without_printing_name(self):
        name = "private-fixture.txt"
        (self.root / name).write_text("private fixture\n", encoding="utf-8")
        with self.assertRaises(VerificationError) as error:
            verify_revision(self.sha, self.root, require_clean=True)
        self.assertNotIn(name, str(error.exception))

    def test_missing_git_is_a_controlled_failure(self):
        with patch("verify_build_revision.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(VerificationError):
                verify_revision(self.sha, self.root)

    def test_cli_returns_nonzero_on_mismatch(self):
        script = Path(__file__).with_name("verify_build_revision.py").resolve()
        env = dict(os.environ, EXPECTED_SOURCE_SHA="0" * 40)
        result = subprocess.run(
            [__import__("sys").executable, str(script), "--require-clean"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match", result.stderr)


if __name__ == "__main__":
    unittest.main()
