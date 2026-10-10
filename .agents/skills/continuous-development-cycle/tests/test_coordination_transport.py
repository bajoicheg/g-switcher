"""Actual Git transport must not write local product refs as a side effect."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import execution_lease
from git_lease_store import GitLeaseStore
from git_document_store import GitDocumentStore
from git_remote_identity import endpoint_identity
from managed_executor_store import GitManagedExecutorStore
import managed_executor_pool
from test_managed_executor_store import plan


class CoordinationTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def git(self, repo, *args, input=None):
        result = subprocess.run(["git", "-C", str(repo), *args], input=input, text=True, capture_output=True, check=True)
        return result.stdout.strip()

    def fixture(self, kind, name="controller"):
        remote = self.root / (kind + ".git")
        if not remote.exists():
            self.git(self.root, "init", "--bare", "-q", str(remote))
        repo = self.root / (kind + "-" + name)
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.name", "CDC transport test")
        self.git(repo, "config", "user.email", "cdc@example.invalid")
        self.git(repo, "remote", "add", "origin", str(remote))
        ref = "refs/heads/cdc/" + kind
        if kind == "lease":
            return GitLeaseStore(repo, "origin", ref), execution_lease.initialize("owner/project", "refs/heads/main")
        if kind == "document":
            return GitDocumentStore(repo, "origin", ref, endpoint_identity(str(remote)), protected_refs=["refs/heads/main"]), {"value": 1}
        pool_plan = plan(ref, endpoint_identity(str(remote)))
        return GitManagedExecutorStore(repo, "origin", ref, pool_plan, protected_refs=["refs/heads/main"]), managed_executor_pool.initial_state(pool_plan, parallel_capable=True)

    def mapped_product_refs(self, store):
        blob = self.git(store.repo, "hash-object", "-w", "--stdin", input="product data\n")
        tree = self.git(store.repo, "mktree", input=f"100644 blob {blob}\tproduct.txt\n")
        commit = self.git(store.repo, "commit-tree", tree, input="product commit\n")
        refs = ["refs/heads/main", "refs/heads/integration", "refs/heads/worker"]
        self.git(store.repo, "config", "--unset-all", "remote.origin.fetch")
        for ref in refs:
            self.git(store.repo, "update-ref", ref, commit)
            self.git(store.repo, "config", "--add", "remote.origin.fetch", "+" + store.ref + ":" + ref)
        return self.git(store.repo, "for-each-ref", "--format=%(refname) %(objectname)")

    def test_lease_fetch_preserves_all_local_refs_with_product_fetch_mappings(self):
        self.check_fetch("lease")

    def test_pool_fetch_preserves_all_local_refs_with_product_fetch_mappings(self):
        self.check_fetch("pool")

    def check_fetch(self, kind):
        store, state = self.fixture(kind)
        revision = store.compare_and_swap(None, state)
        before = self.mapped_product_refs(store)
        self.assertEqual(store.read(), (revision, state))
        self.assertEqual(self.git(store.repo, "for-each-ref", "--format=%(refname) %(objectname)"), before)

    def test_lease_push_preserves_all_local_refs_with_product_tracking_mappings(self):
        self.check_push("lease")

    def test_pool_push_preserves_all_local_refs_with_product_tracking_mappings(self):
        self.check_push("pool")

    def check_push(self, kind):
        store, state = self.fixture(kind)
        before = self.mapped_product_refs(store)
        # An empty remote skips fetch entirely, isolating push's local updates.
        revision = store.compare_and_swap(None, state)
        self.assertEqual(self.git(store.repo, "for-each-ref", "--format=%(refname) %(objectname)"), before)
        self.assertEqual(store.read(), (revision, state))
        updated = store.compare_and_swap(revision, state)
        self.assertEqual(store.read(), (updated, state))
        self.assertEqual(self.git(store.repo, "for-each-ref", "--format=%(refname) %(objectname)"), before)

    def test_document_historical_readback_survives_successor_cas(self):
        store, state = self.fixture("document")
        first = store.compare_and_swap(None, state)
        second_state = {"value": 2}
        second = store.compare_and_swap(first, second_state)
        self.assertEqual(store.read_revision(first), state)
        self.assertEqual(store.read_revision(second), second_state)
        blob = self.git(store.repo, "hash-object", "-w", "--stdin", input='{"value":3}\n')
        tree = self.git(store.repo, "mktree", input=f"100644 blob {blob}\tdocument.json\n")
        unrelated = store._git("commit-tree", tree, input_text="unrelated document\n")
        with self.assertRaisesRegex(ValueError, "authoritative document ancestry"):
            store.read_revision(unrelated)

    def test_lease_remote_repointing_after_construction_is_rejected(self):
        store, state = self.fixture("lease")
        other = self.root / "other.git"
        self.git(self.root, "init", "--bare", "-q", str(other))
        self.git(store.repo, "remote", "set-url", "origin", str(other))
        with self.assertRaises(ValueError):
            store.compare_and_swap(None, state)
        self.assertEqual(self.git(self.root, "--git-dir=" + str(other), "for-each-ref"), "")

    def test_identical_lease_proposals_under_fixed_clock_have_one_winner(self):
        first, state = self.fixture("lease")
        second, _ = self.fixture("lease", "second")
        revision = first.compare_and_swap(None, state)
        barrier = threading.Barrier(2, timeout=10)
        first_push_done = threading.Event()
        proposals = []
        for index, store in enumerate([first, second]):
            original = store._git
            def coordinated(*args, _git=original, _index=index, **kwargs):
                if "push" in args:
                    if _index == 1:
                        self.assertTrue(first_push_done.wait(10))
                    try:
                        return _git(*args, **kwargs)
                    finally:
                        if _index == 0:
                            first_push_done.set()
                result = _git(*args, **kwargs)
                if args[0] == "commit-tree":
                    proposals.append(result)
                    barrier.wait()
                return result
            store._git = coordinated
        def attempt(store):
            try:
                return store.compare_and_swap(revision, state)
            except ValueError:
                return None
        clock = {"GIT_AUTHOR_DATE": "2026-09-28T12:00:00+00:00", "GIT_COMMITTER_DATE": "2026-09-28T12:00:00+00:00"}
        with mock.patch.dict(os.environ, clock), concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, [first, second]))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(set(proposals)), 2)

    def test_raw_alias_transport_preserves_single_rewrite_and_push_instead_of(self):
        for kind in ["lease", "pool", "document"]:
            with self.subTest(kind=kind):
                store, state = self.fixture(kind)
                target = str(self.root / (kind + ".git"))
                wrong = self.root / (kind + "-wrong.git")
                self.git(self.root, "init", "--bare", "-q", str(wrong))
                raw = "cdc-transport:repository"
                self.git(store.repo, "remote", "set-url", "origin", raw)
                self.git(store.repo, "config", f"url.{target}.insteadOf", raw)
                self.git(store.repo, "config", f"url.{target}.pushInsteadOf", raw)
                # Reusing the resolved target as a new Git URL would redirect it.
                self.git(store.repo, "config", f"url.{wrong}.insteadOf", target)
                self.assertEqual(self.git(store.repo, "remote", "get-url", "origin"), target)
                self.assertEqual(self.git(store.repo, "remote", "get-url", "--push", "origin"), target)
                before = self.mapped_product_refs(store)
                revision = store.compare_and_swap(None, state)
                self.assertEqual(store.read(), (revision, state))
                self.assertEqual(self.git(store.repo, "for-each-ref", "--format=%(refname) %(objectname)"), before)
                self.assertEqual(self.git(self.root, "--git-dir=" + str(wrong), "for-each-ref"), "")
                self.assertEqual(self.git(store.repo, "remote"), "origin")

    def test_raw_explicit_pushurl_is_preserved_without_a_second_rewrite(self):
        store, state = self.fixture("document")
        target = str(self.root / "document.git")
        wrong = self.root / "wrong-push.git"
        self.git(self.root, "init", "--bare", "-q", str(wrong))
        self.git(store.repo, "remote", "set-url", "origin", "cdc-fetch:repo")
        self.git(store.repo, "remote", "set-url", "--push", "origin", "cdc-push:repo")
        self.git(store.repo, "config", "--add", f"url.{target}.insteadOf", "cdc-fetch:repo")
        self.git(store.repo, "config", "--add", f"url.{target}.insteadOf", "cdc-push:repo")
        self.git(store.repo, "config", f"url.{wrong}.insteadOf", target)
        revision = store.compare_and_swap(None, state)
        self.assertEqual(store.read(), (revision, state))
        self.assertEqual(self.git(self.root, "--git-dir=" + str(wrong), "for-each-ref"), "")


if __name__ == "__main__":
    unittest.main()
