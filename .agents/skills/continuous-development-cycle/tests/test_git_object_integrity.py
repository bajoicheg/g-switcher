"""Exact Git SHA proofs must ignore checkout-local replacement/graft overlays."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import execution_lease
import integration_gate
import managed_executor_handoff
import managed_executor_pool
import managed_executor_runtime
import package_transport
import worktree_worker_contract
import test_coordination_transport as coordination_fixtures
import test_live_target as live_target_fixtures
from test_package_transport import MANIFEST
import test_worktree_worker_contract as worker_contract_fixtures


class GitObjectIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def git(self, repo, *args, input=None, extra_env=None):
        env = dict(os.environ, GIT_AUTHOR_NAME="Integrity fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                   GIT_COMMITTER_NAME="Integrity fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
        env.update(extra_env or {})
        result = subprocess.run(["git", "-C", str(repo), *args], input=input, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=True)
        return result.stdout.strip()

    def repo(self, name="repo"):
        repo = self.root / name
        repo.mkdir()
        self.git(repo, "init", "-q")
        return repo

    def commit(self, repo, base=None, changes=None, parents=()):
        index = self.root / ("index-" + uuid.uuid4().hex)
        env = {"GIT_INDEX_FILE": str(index)}
        self.git(repo, "read-tree", base if base else "--empty", extra_env=env)
        for path, content in (changes or {}).items():
            if content is None:
                self.git(repo, "update-index", "--force-remove", path, extra_env=env)
            else:
                blob = self.git(repo, "hash-object", "-w", "--stdin", input=content)
                self.git(repo, "update-index", "--add", "--cacheinfo", "100644", blob, path, extra_env=env)
        tree = self.git(repo, "write-tree", extra_env=env)
        args = [item for parent in parents for item in ["-p", parent]]
        return self.git(repo, "commit-tree", tree, *args, input="fixture " + uuid.uuid4().hex)

    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_live_registry_replacement_cannot_change_watchdog_under_genuine_sha(self):
        fixture = self.fixture(live_target_fixtures.LiveTargetTests)
        fixture.resolve()
        counterfeit = copy.deepcopy(fixture.registry_data)
        counterfeit["projects"][0]["watchdog_id"] = "counterfeit-watchdog"
        replacement = self.commit(fixture.cache, fixture.registry_revision,
                                  {"fleet/registry.json": json.dumps(counterfeit)})
        self.git(fixture.cache, "replace", fixture.registry_revision, replacement)
        result = fixture.resolve()
        self.assertEqual(result["registry_revision"], fixture.registry_revision)
        self.assertEqual(result["registry"]["projects"][0]["watchdog_id"], "project-watchdog")

    def test_canonical_release_replacement_cannot_change_package_bytes_under_genuine_sha(self):
        fixture = self.fixture(live_target_fixtures.LiveTargetTests)
        fixture.resolve()
        replacement = self.commit(fixture.cache, fixture.release,
                                  {"src/continuous-development-cycle/VERSION": "0.0.0\n"})
        self.git(fixture.cache, "replace", fixture.release, replacement)
        result = fixture.resolve()
        self.assertEqual(result["release"]["release_commit"], fixture.release)
        self.assertEqual(result["release"]["package_tree"], fixture.tree)

    def test_coordination_stores_read_genuine_journals_despite_replacements(self):
        fixture = self.fixture(coordination_fixtures.CoordinationTransportTests)
        for kind in ["document", "pool", "lease"]:
            with self.subTest(kind=kind):
                store, original = fixture.fixture(kind)
                if kind == "document":
                    original = {"operations": {"once": {"status": "unknown"}}}
                    altered, filename = {"operations": {}}, "document.json"
                elif kind == "pool":
                    altered = managed_executor_pool.initial_state(store.plan, parallel_capable=False)
                    filename = "pool-state.json"
                else:
                    altered = execution_lease.acquire(original, str(uuid.uuid4()), "2026-09-28T12:00:00Z")
                    filename = "lease.json"
                revision = store.compare_and_swap(None, original)
                replacement = self.commit(store.repo, revision, {filename: json.dumps(altered, sort_keys=True, separators=(",", ":")) + "\n"})
                self.git(store.repo, "replace", revision, replacement)
                observed, actual = store.read()
                self.assertEqual(observed, revision)
                self.assertEqual(actual, original)
                newer = store.compare_and_swap(revision, original)
                self.assertEqual(store.read(), (newer, original))

    def replaced_result(self):
        repo = self.repo()
        base = self.commit(repo, changes={"seed": "base\n"})
        result = self.commit(repo, base, {"allowed.txt": "yes\n", "outside.txt": "hidden\n"}, [base])
        replacement = self.commit(repo, base, {"allowed.txt": "yes\n"}, [base])
        self.git(repo, "update-ref", "refs/heads/worker", result)
        self.git(repo, "replace", result, replacement)
        return repo, base, result

    def test_pool_result_paths_and_history_ignore_replacement_overlay(self):
        repo, base, result = self.replaced_result()
        final, touched = managed_executor_pool._verify_writer_result_git({"branch": "worker"}, base, result, repo)
        self.assertEqual(final, ["allowed.txt", "outside.txt"])
        self.assertEqual(touched, ["allowed.txt", "outside.txt"])

    def test_handoff_changed_paths_ignore_replacement_overlay(self):
        repo, base, result = self.replaced_result()
        self.assertEqual(managed_executor_handoff._git_changed_paths(repo, base, result), ["allowed.txt", "outside.txt"])

    def test_integration_diff_proof_ignores_replacement_overlay(self):
        repo, base, result = self.replaced_result()
        proof = integration_gate.resolve_git_diff(repo, worker_id="worker", task_id="task", base_sha=base,
                                                  result_sha=result, evidence_ref="git:diff")
        self.assertEqual(proof["changed_paths"], ["allowed.txt", "outside.txt"])

    def test_managed_runtime_git_object_reads_ignore_replacement_overlay(self):
        repo, _, result = self.replaced_result()
        self.assertEqual(managed_executor_runtime._git(repo, "show", result + ":outside.txt"), "hidden")

    def test_package_transport_uses_genuine_head_tree(self):
        repo = self.repo()
        actual = self.commit(repo, changes={"vendor/VERSION": "2.9.1\n"})
        fake = self.commit(repo, changes={"vendor/VERSION": "2.9.0\n"})
        self.git(repo, "update-ref", "HEAD", actual)
        self.git(repo, "replace", actual, fake)
        self.assertFalse(package_transport.verify_git_tree(copy.deepcopy(MANIFEST), repo, "vendor")["git_tree_verified"])

    def test_graft_cannot_fabricate_integration_ancestry(self):
        repo = self.repo()
        base = self.commit(repo, changes={"seed": "base"})
        unrelated = self.commit(repo, changes={"allowed.txt": "outside history"})
        (repo / ".git/info/grafts").write_text(unrelated + " " + base + "\n")
        with self.assertRaises(ValueError):
            integration_gate.resolve_git_diff(repo, worker_id="worker", task_id="task", base_sha=base,
                                             result_sha=unrelated, evidence_ref="git:diff")

    def test_replacement_cannot_fabricate_prior_wave_writer_ancestry(self):
        repo = self.repo()
        base = self.commit(repo, changes={"seed": "base"})
        integrated = self.commit(repo, base, {"work": "integrated"}, [base])
        unrelated = self.commit(repo, base, {"other": "not integrated"}, [base])
        replacement = self.commit(repo, integrated, {}, [base, unrelated])
        self.git(repo, "update-ref", "refs/heads/feature/integration", integrated)
        self.git(repo, "replace", integrated, replacement)
        evidence = self.root / "evidence"
        evidence.mkdir()
        contract, _, _, _ = worker_contract_fixtures.T().later_wave_case(evidence, integrated_head=integrated,
                                                                    plan_base=base, writer_result_shas=[unrelated])
        with self.assertRaises(ValueError):
            worktree_worker_contract.assess(contract, evidence_root=evidence, git_worktree=repo)


if __name__ == "__main__":
    unittest.main()
