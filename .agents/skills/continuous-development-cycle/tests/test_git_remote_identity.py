"""Endpoint identity regressions through the coordination/publication consumers."""
import subprocess
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from managed_executor_handoff import publication_remote_identity
from managed_executor_store import coordination_store_id_for_endpoint
from git_remote_identity import isolated_remote_args


class GitRemoteIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")

    @staticmethod
    def git(repo, *args):
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE,
        ).strip()

    def test_scp_home_relative_and_absolute_repositories_have_distinct_identities(self):
        # Removing SCP's leading slash changes the destination on the SSH host.
        relative = coordination_store_id_for_endpoint("alice@example.com:repo.git")
        absolute = coordination_store_id_for_endpoint("alice@example.com:/repo.git")
        self.assertNotEqual(relative, absolute)

    def test_publication_relative_remotes_in_distinct_checkouts_do_not_alias(self):
        # Hashing only '../remote.git' trusts an unrelated publication repository.
        identities = []
        for name in ("a", "b"):
            repo = self.root / name / "checkout"
            repo.mkdir(parents=True)
            remote = repo.parent / "remote.git"
            self.git(repo, "init", "-q")
            self.git(repo, "init", "--bare", "-q", str(remote))
            self.git(repo, "remote", "add", "origin", "../remote.git")
            identities.append(publication_remote_identity(repo, "origin"))
        self.assertNotEqual(*identities)

    def test_relative_endpoint_from_subdirectory_uses_git_repository_root(self):
        # Resolving from the caller's current subdirectory invents another target.
        subdir = self.repo / "nested"
        subdir.mkdir()
        expected = coordination_store_id_for_endpoint(str(self.root / "remote.git"))
        self.assertEqual(
            coordination_store_id_for_endpoint("../remote.git", repo_root=subdir), expected,
        )

    def test_coordination_and_publication_share_relative_endpoint_identity(self):
        self.git(self.repo, "remote", "add", "origin", "../remote.git")
        expected = coordination_store_id_for_endpoint(str(self.root / "remote.git"))
        self.assertEqual(publication_remote_identity(self.repo, "origin"), expected)

    def test_endpoint_identity_honors_effective_git_url_rewrite(self):
        target = str(self.root / "remote.git")
        self.git(self.repo, "config", f"url.{target}.insteadOf", "cdc-test:repo")
        self.git(self.repo, "remote", "add", "origin", "cdc-test:repo")
        expected = coordination_store_id_for_endpoint(target)
        self.assertEqual(
            coordination_store_id_for_endpoint("cdc-test:repo", repo_root=self.repo), expected,
        )
        self.assertEqual(publication_remote_identity(self.repo, "origin"), expected)

    def test_push_instead_of_cannot_redirect_an_authoritative_remote(self):
        self.git(self.repo, "remote", "add", "origin", str(self.root / "remote.git"))
        self.git(self.repo, "config", f"url.{self.root / 'other.git'}.pushInsteadOf",
                 str(self.root / "remote.git"))
        with self.assertRaises(ValueError):
            publication_remote_identity(self.repo, "origin")

    def test_ssh_usernames_remain_part_of_identity(self):
        for first, second in (
            ("alice@example.com:repo.git", "bob@example.com:repo.git"),
            ("ssh://alice@example.com/repo.git", "ssh://bob@example.com/repo.git"),
        ):
            with self.subTest(first=first):
                self.assertNotEqual(coordination_store_id_for_endpoint(first),
                                    coordination_store_id_for_endpoint(second))

    def test_invalid_endpoint_error_does_not_disclose_credentials(self):
        endpoint = "https://user:top-secret@example.invalid:private-port/repo.git"
        try:
            coordination_store_id_for_endpoint(endpoint)
        except ValueError:
            diagnostic = traceback.format_exc()
        else:
            self.fail("malformed endpoint was accepted")
        self.assertNotIn("top-secret", diagnostic)
        self.assertNotIn("private-port", diagnostic)
        self.assertNotIn("example.invalid", diagnostic)

    def test_isolated_transport_identity_error_does_not_disclose_credentials(self):
        self.git(self.repo, "remote", "add", "origin", "https://user:top-secret@example.invalid/repo.git")
        try:
            isolated_remote_args(self.repo, "origin", "sha256:" + "0" * 64)
        except ValueError:
            diagnostic = traceback.format_exc()
        else:
            self.fail("wrong transport identity was accepted")
        self.assertNotIn("top-secret", diagnostic)
        self.assertNotIn("example.invalid", diagnostic)


if __name__ == "__main__":
    unittest.main()
