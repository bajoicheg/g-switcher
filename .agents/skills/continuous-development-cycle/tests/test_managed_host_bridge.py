"""End-to-end contract for the package-owned Chat/host -> managed executor bridge."""
import json
import os
import signal
from unittest.mock import patch
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import execution_lease_v2 as leasev2
import managed_executor_pool as pool
from git_lease_store import GitLeaseStore
from managed_executor_store import GitManagedExecutorStore, coordination_store_id_for_endpoint
import managed_host_bridge as bridge
import managed_executor_runtime as runtime_module


@unittest.skipUnless(sys.platform == "linux", "managed local backend requires Linux /proc")
class ManagedHostBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.stop_test_supervisors)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "cdc@example.invalid")
        self.git("config", "user.name", "CDC Host Bridge Test")
        (self.repo / "seed").write_text("base")
        self.git("add", "seed")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "-u", "origin", "main")

        self.store_id = coordination_store_id_for_endpoint(str(self.remote), repo_root=self.repo)
        self.plan = {
            "schema": "managed-executor-pool-plan/v1",
            "pool_id": "host-bridge-pool",
            "change_id": "host-bridge-change",
            "parent_invocation_id": "chat-orchestrator",
            "base_sha": self.base,
            "integrator_id": "managed-host-bridge",
            "coordination_ref": "refs/heads/cdc/host-bridge-pool",
            "coordination_store_id": self.store_id,
            "max_parallel": 1,
            "total_runtime_budget_seconds": 30,
            "total_cost_budget_units": 5,
            "tasks": [{
                "id": "closure",
                "role": "writer",
                "required": True,
                "dependencies": [],
                "executor_id": "managed-closure",
                "branch": "cdc/host-bridge-worker",
                "worktree": "managed-worktrees/host-bridge-worker",
                "write_paths": ["docs"],
                "expected_outputs": ["out:closure"],
                "expected_evidence": ["test:closure"],
                "backend_preferences": ["local_command"],
                "max_runtime_seconds": 12,
                "max_cost_units": 1,
            }],
        }
        self.lease_store = GitLeaseStore(self.repo, "origin", "refs/heads/cdc/lease")
        self.lease_store.compare_and_swap(
            None, leasev2.initialize("test/project", "refs/heads/main"))

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE, text=True
        ).strip()

    def stop_test_supervisors(self):
        # All receipts are under this test's unique temp directory. Never touch
        # a process unless its live command still binds that exact directory.
        for path in self.root.glob("journal/**/receipt.json"):
            receipt = json.loads(path.read_text())
            pid = receipt.get("supervisor_proc_pid")
            if not isinstance(pid, int):
                continue
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
                if str(self.root).encode() in command:
                    os.killpg(pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    def finish_request(self, handle, checkpoint=None):
        return {
            "schema": "managed-host-finish/v1",
            "handle_root": str(self.root / "handles"),
            "handle_id": handle["handle_id"],
            "output_refs": ["out:closure"],
            "evidence_refs": ["test:closure"],
            "checkpoint_ref": checkpoint,
        }

    def worker(self):
        code = """from pathlib import Path
import subprocess
p=Path('docs'); p.mkdir(exist_ok=True)
(p/'closed.txt').write_text('closed')
subprocess.run(['git','add','docs/closed.txt'],check=True)
subprocess.run(['git','commit','-qm','managed closure'],check=True)
"""
        return [sys.executable, "-c", code]

    def start_request(self):
        return {
            "schema": "managed-host-start/v1",
            "repo_root": str(self.repo),
            "remote": "origin",
            "plan": self.plan,
            "journal_root": str(self.root / "journal"),
            "handle_root": str(self.root / "handles"),
            "lease_coordination_ref": "refs/heads/cdc/lease",
            "lease_repository": "test/project",
            "lease_source_ref": "refs/heads/main",
            "task_id": "closure",
            "attempt_id": "closure-a1",
            "reservation_token": "reserve:closure",
            "owner_id": "99999999-9999-4999-8999-999999999999",
            "argv": self.worker(),
        }

    def wait_for(self, handle, wanted):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            observed = bridge.observe({
                "schema": "managed-host-observe/v1",
                "handle_root": str(self.root / "handles"),
                "handle_id": handle["handle_id"],
            })
            if observed["runtime_status"] == wanted:
                return observed
            time.sleep(.025)
        self.fail("managed host bridge did not reach " + wanted)

    def remote_head(self):
        row = subprocess.check_output(
            ["git", "-C", str(self.repo), "ls-remote", "--refs", "origin", "refs/heads/main"],
            text=True,
        ).strip()
        return row.split("\t", 1)[0]

    def split_request(self):
        private = self.root / "private.git"
        subprocess.run(["git", "init", "--bare", "-q", str(private)], check=True)
        self.git("remote", "add", "control", str(private))
        GitLeaseStore(self.repo, "control", "refs/heads/cdc/lease").compare_and_swap(
            None, leasev2.initialize("test/project", "refs/heads/main"))
        # The public source must have no control-plane refs.
        self.git("push", "-q", "origin", ":refs/heads/cdc/lease")
        self.plan["coordination_store_id"] = coordination_store_id_for_endpoint(
            str(private), repo_root=self.repo)
        request = self.start_request()
        request.update(coordination_remote="control", source_remote_id=self.store_id)
        return request, private

    def test_split_routes_publish_source_and_keep_control_state_private(self):
        request, private = self.split_request()
        handle = bridge.start(request)
        self.wait_for(handle, "awaiting_release")
        finished = bridge.finish(self.finish_request(handle))
        self.assertEqual(finished["state"], "released")
        self.assertTrue(finished["final_response_allowed"])
        self.assertEqual(self.remote_head(), finished["published_commit"])
        public_refs = subprocess.check_output(
            ["git", "--git-dir", str(self.remote), "for-each-ref", "--format=%(refname)"], text=True).splitlines()
        self.assertEqual(public_refs, ["refs/heads/main"])
        private_refs = subprocess.check_output(
            ["git", "--git-dir", str(private), "for-each-ref", "--format=%(refname)"], text=True).splitlines()
        self.assertIn("refs/heads/cdc/lease", private_refs)
        self.assertIn(self.plan["coordination_ref"], private_refs)
        self.assertIn(handle["publication_ref"], private_refs)

    def test_split_routes_reject_source_identity_mismatch_before_effects(self):
        request, private = self.split_request()
        request["source_remote_id"] = self.plan["coordination_store_id"]
        with self.assertRaisesRegex(ValueError, "source.*identity"):
            bridge.start(request)
        self.assertFalse((self.root / "journal").exists())

    def test_split_routes_recovery_rejects_private_identity_drift(self):
        request, private = self.split_request()
        handle = bridge.start(request)
        self.wait_for(handle, "awaiting_release")
        self.git("remote", "set-url", "control", str(self.remote))
        with self.assertRaisesRegex(ValueError, "identity"):
            bridge.finish(self.finish_request(handle))
        self.assertEqual(self.remote_head(), self.base)

    def test_split_routes_recovery_rejects_source_identity_drift(self):
        request, private = self.split_request()
        handle = bridge.start(request)
        self.wait_for(handle, "awaiting_release")
        self.git("remote", "set-url", "origin", str(private))
        with self.assertRaisesRegex(ValueError, "identity"):
            bridge.finish(self.finish_request(handle))

    def test_split_routes_require_both_explicit_binding_fields(self):
        request, _ = self.split_request()
        for missing in ("source_remote_id", "coordination_remote"):
            incomplete = dict(request)
            del incomplete[missing]
            with self.assertRaisesRegex(ValueError, "fields/schema"):
                bridge.start(incomplete)
        self.assertFalse((self.root / "journal").exists())

    def test_split_routes_repeat_rejects_changed_source_binding(self):
        request, _ = self.split_request()
        handle = bridge.start(request)
        self.wait_for(handle, "awaiting_release")
        other = self.root / "other.git"
        subprocess.run(["git", "clone", "--bare", "-q", str(self.remote), str(other)], check=True)
        self.git("remote", "set-url", "origin", str(other))
        request["source_remote_id"] = coordination_store_id_for_endpoint(str(other), repo_root=self.repo)
        with self.assertRaisesRegex(ValueError, "conflicting immutable"):
            bridge.start(request)
        self.git("remote", "set-url", "origin", str(self.remote))
        self.assertEqual(bridge.finish(self.finish_request(handle))["state"], "released")

    def test_start_holds_exact_managed_lease_then_finish_publishes_and_releases(self):
        handle = bridge.start(self.start_request())
        self.assertEqual(handle["schema"], "managed-host-handle/v1")
        self.assertEqual(handle["state"], "running")
        self.assertTrue(handle["invocation_id"].startswith("managed-terminal:"))

        waiting = self.wait_for(handle, "awaiting_release")
        lease_revision, lease = self.lease_store.read()
        self.assertIsNotNone(lease_revision)
        self.assertEqual(lease["owner_id"], handle["owner_id"])
        self.assertEqual(lease["generation"], handle["generation"])
        self.assertEqual(lease["invocation"]["execution_surface"], "managed")
        self.assertEqual(lease["invocation"]["invocation_id"], handle["invocation_id"])
        self.assertEqual(self.remote_head(), self.base, "worker must not publish shared source before finish")
        self.assertFalse(waiting["quiescent"])

        finished = bridge.finish({
            "schema": "managed-host-finish/v1",
            "handle_root": str(self.root / "handles"),
            "handle_id": handle["handle_id"],
            "output_refs": ["out:closure"],
            "evidence_refs": ["test:closure"],
            "checkpoint_ref": None,
        })
        self.assertEqual(finished["state"], "released")
        self.assertTrue(finished["final_response_allowed"])
        self.assertEqual(self.remote_head(), finished["published_commit"])
        self.assertNotEqual(finished["published_commit"], self.base)
        self.assertEqual(finished["release_receipt"]["schema"], "execution-release-receipt/v1")

        _, released = self.lease_store.read()
        self.assertIsNone(released["owner_id"])
        observed = self.wait_for(handle, "succeeded")
        self.assertTrue(observed["quiescent"])

        pool_store = GitManagedExecutorStore(
            self.repo, "origin", self.plan["coordination_ref"], self.plan,
            protected_refs=["refs/heads/main", "refs/heads/cdc/lease"],
        )
        _, pool_state = pool_store.read()
        assessment = pool.assess(self.plan, pool_state)
        self.assertTrue(assessment["complete"])
        self.assertTrue(assessment["terminal_allowed"])

    def test_dirty_worker_is_rejected_before_publishing(self):
        request = self.start_request()
        request["argv"] = [sys.executable, "-c", request["argv"][-1] + "\nPath('dirty.txt').write_text('uncommitted')"]
        handle = bridge.start(request)
        self.wait_for(handle, "awaiting_release")
        with self.assertRaisesRegex(ValueError, "clean"):
            bridge.finish(self.finish_request(handle))
        self.assertEqual(self.remote_head(), self.base)
        self.assertIsNotNone(self.lease_store.read()[1]["owner_id"])

    def test_invalid_checkpoint_rejected_before_publication_or_lease_mutation(self):
        handle = bridge.start(self.start_request())
        self.wait_for(handle, "awaiting_release")
        revision, _ = self.lease_store.read()
        for invalid in (" ", 23, False, [], " checkpoint "):
            with self.subTest(checkpoint=invalid):
                with self.assertRaisesRegex(ValueError, "checkpoint_ref"):
                    bridge.finish(self.finish_request(handle, invalid))
                self.assertEqual(self.remote_head(), self.base)
                self.assertEqual(self.lease_store.read()[0], revision)
        # An invalid request must leave the valid retry usable.
        finished = bridge.finish(self.finish_request(handle))
        self.assertTrue(finished["final_response_allowed"])

    def test_unsuccessful_terminal_workers_release_without_publishing(self):
        request = self.start_request()
        request["argv"] = [sys.executable, "-c", "raise SystemExit(7)"]
        handle = bridge.start(request)
        waiting = self.wait_for(handle, "awaiting_release")
        self.assertEqual(waiting["pending_terminal_status"], "failed")
        finished = bridge.finish(self.finish_request(handle))
        self.assertIsNone(finished["published_commit"])
        self.assertFalse(finished["scope_complete"])
        self.assertEqual(finished["worker_status"], "failed")
        self.assertTrue(finished["final_response_allowed"])
        self.assertEqual(self.remote_head(), self.base)
        self.assertIsNone(self.lease_store.read()[1]["owner_id"])
        self.assertTrue(self.wait_for(handle, "failed")["quiescent"])
        again = bridge.finish(self.finish_request(handle))
        self.assertEqual(again["release_receipt"], finished["release_receipt"])
        self.assertIsNone(again["published_commit"])

    def test_cancelled_terminal_worker_releases_without_publishing(self):
        request = self.start_request()
        request["argv"] = [sys.executable, "-c", "import time; time.sleep(30)"]
        handle = bridge.start(request)
        bridge.cancel({"schema": "managed-host-cancel/v1",
                       "handle_root": request["handle_root"], "handle_id": handle["handle_id"]})
        waiting = self.wait_for(handle, "awaiting_release")
        self.assertEqual(waiting["pending_terminal_status"], "cancelled")
        finished = bridge.finish(self.finish_request(handle))
        self.assertEqual(finished["worker_status"], "cancelled")
        self.assertFalse(finished["scope_complete"])
        self.assertIsNone(finished["published_commit"])
        self.assertIsNone(self.lease_store.read()[1]["owner_id"])
        self.assertTrue(self.wait_for(handle, "cancelled")["quiescent"])
        self.assertEqual(self.remote_head(), self.base)

    def test_unknown_start_recovers_exact_launch_and_acquires_lease_once(self):
        original_start = bridge.LocalCommandBackend.start
        def lost_receipt(backend, request):
            receipt = original_start(backend, request)
            return {**receipt, "status": "unknown", "quiescent": False}
        # Simulate only a lost initial provider reply; the real process and its
        # durable journal remain intact for the public observe recovery path.
        with patch.object(bridge.LocalCommandBackend, "start", lost_receipt):
            handle = bridge.start(self.start_request())
        self.assertEqual(handle["state"], "start_unknown")
        waiting = self.wait_for(handle, "awaiting_release")
        self.assertTrue(waiting["lease_owned"])
        self.assertEqual(waiting["generation"], 1)
        self.assertEqual(waiting["runtime_launch_id"],
                         bridge._load_session(str(self.root / "handles"), handle["handle_id"])["runtime_launch_id"])
        self.assertEqual(len(list((self.root / "journal").glob("**/launch.lock"))), 1)
        finished = bridge.finish(self.finish_request(handle))
        self.assertTrue(finished["final_response_allowed"])
        self.assertEqual(self.lease_store.read()[1]["generation"], 1)
        self.assertEqual(len(list((self.root / "journal").glob("**/launch.lock"))), 1)

    def test_start_rejects_remote_source_drift_before_worker_effect(self):
        request = self.start_request()
        request["plan"] = dict(self.plan, base_sha="a" * 40)
        with self.assertRaisesRegex(ValueError, "source HEAD"):
            bridge.start(request)
        self.assertFalse((self.root / "journal").exists())

    def test_crash_after_launch_recovers_prepared_handle_without_relaunch(self):
        original = bridge.ManagedExecutorRuntime.start
        def crash_after_launch(runtime, *args, **kwargs):
            original(runtime, *args, **kwargs)
            raise RuntimeError("controller interrupted after launch")
        with patch.object(bridge.ManagedExecutorRuntime, "start", crash_after_launch):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                bridge.start(self.start_request())
        path = next((self.root / "handles").glob("*.json"))
        handle = json.loads(path.read_text())
        self.assertEqual(handle["state"], "prepared")
        waiting = self.wait_for(handle, "awaiting_release")
        self.assertTrue(waiting["lease_owned"])
        self.assertEqual(waiting["generation"], 1)
        self.assertEqual(len(list((self.root / "journal").glob("**/launch.lock"))), 1)
        self.assertTrue(bridge.finish(self.finish_request(handle))["final_response_allowed"])

    def test_missing_required_result_refs_rejected_before_shared_effects(self):
        handle = bridge.start(self.start_request())
        self.wait_for(handle, "awaiting_release")
        revision, _ = self.lease_store.read()
        for field in ("output_refs", "evidence_refs"):
            with self.subTest(field=field):
                request = self.finish_request(handle)
                request[field] = ["wrong:reference"]
                with self.assertRaisesRegex(ValueError, "expected"):
                    bridge.finish(request)
                self.assertEqual(self.remote_head(), self.base)
                self.assertEqual(self.lease_store.read()[0], revision)
        self.assertTrue(bridge.finish(self.finish_request(handle))["final_response_allowed"])

    def test_repeated_exact_start_recovers_original_handle_after_publication(self):
        request = self.start_request()
        handle = bridge.start(request)
        repeated = bridge.start(request)
        self.assertEqual(repeated["handle_id"], handle["handle_id"])
        self.assertEqual(len(list((self.root / "handles").glob("*.json"))), 1)
        self.wait_for(handle, "awaiting_release")
        finished = bridge.finish(self.finish_request(handle))
        repeated = bridge.start(request)
        self.assertEqual(repeated["handle_id"], handle["handle_id"])
        self.assertEqual(repeated["state"], "released")
        self.assertEqual(self.remote_head(), finished["published_commit"])
        self.assertEqual(len(list((self.root / "journal").glob("**/launch.lock"))), 1)

    def test_repeated_attempt_rejects_conflicting_immutable_request(self):
        request = self.start_request()
        handle = bridge.start(request)
        for field, value in (("argv", [sys.executable, "-c", "raise SystemExit(9)"]),
                             ("owner_id", "88888888-8888-4888-8888-888888888888")):
            with self.subTest(field=field):
                changed = {**request, field: value}
                with self.assertRaisesRegex(ValueError, "immutable"):
                    bridge.start(changed)
        self.assertEqual(len(list((self.root / "handles").glob("*.json"))), 1)
        self.wait_for(handle, "awaiting_release")
        self.assertTrue(bridge.finish(self.finish_request(handle))["final_response_allowed"])

    def test_repeated_start_resumes_prepared_request_before_launch(self):
        request = self.start_request()
        with patch.object(bridge.ManagedExecutorRuntime, "start", side_effect=RuntimeError("before launch")):
            with self.assertRaisesRegex(RuntimeError, "before launch"):
                bridge.start(request)
        original_id = next((self.root / "handles").glob("*.json")).stem
        handle = bridge.start(request)
        self.assertEqual(handle["handle_id"], original_id)
        self.wait_for(handle, "awaiting_release")
        self.assertTrue(bridge.finish(self.finish_request(handle))["final_response_allowed"])

    def test_repeated_start_resumes_unconsumed_queue_without_new_attempt(self):
        request = self.start_request()
        with patch.object(bridge.ManagedExecutorRuntime, "start_queued", side_effect=RuntimeError("before claim")):
            with self.assertRaisesRegex(RuntimeError, "before claim"):
                bridge.start(request)
        original_id = next((self.root / "handles").glob("*.json")).stem
        handle = bridge.start(request)
        self.assertEqual(handle["handle_id"], original_id)
        self.wait_for(handle, "awaiting_release")
        self.assertTrue(bridge.finish(self.finish_request(handle))["final_response_allowed"])
        self.assertEqual(len(list((self.root / "journal").glob("**/launch.lock"))), 1)

    def test_crash_after_release_before_session_save_finishes_on_retry(self):
        handle = bridge.start(self.start_request())
        self.wait_for(handle, "awaiting_release")
        original = bridge._save_session
        def crash_before_save(session):
            if session.get("release_receipt") is not None:
                raise RuntimeError("controller interrupted before receipt save")
            original(session)
        with patch.object(bridge, "_save_session", crash_before_save):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                bridge.finish(self.finish_request(handle))
        self.assertIsNone(self.lease_store.read()[1]["owner_id"])
        published = self.remote_head()
        finished = bridge.finish(self.finish_request(handle))
        self.assertEqual(finished["published_commit"], published)
        self.assertTrue(finished["final_response_allowed"])
        self.assertTrue(self.wait_for(handle, "succeeded")["quiescent"])

    def test_crash_after_release_cas_repairs_terminal_marker_on_retry(self):
        handle = bridge.start(self.start_request())
        self.wait_for(handle, "awaiting_release")
        original = runtime_module._write
        def crash_before_marker(path, value):
            if value.get("schema") == "managed-terminal-lease-release/v1":
                raise RuntimeError("controller interrupted before terminal marker")
            original(path, value)
        with patch.object(runtime_module, "_write", crash_before_marker):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                bridge.finish(self.finish_request(handle))
        self.assertIsNone(self.lease_store.read()[1]["owner_id"])
        published = self.remote_head()
        finished = bridge.finish(self.finish_request(handle))
        self.assertEqual(finished["published_commit"], published)
        self.assertTrue(finished["final_response_allowed"])
        self.assertTrue(self.wait_for(handle, "succeeded")["quiescent"])


if __name__ == "__main__":
    unittest.main()
