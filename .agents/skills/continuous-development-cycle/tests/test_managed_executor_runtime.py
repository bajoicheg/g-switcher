"""Real Git/process regressions: removing a CAS, isolation, or live wait must fail."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import managed_executor_pool as pool
import execution_lease_v2 as leasev2
import final_response_gate as final_gate
from git_lease_store import GitLeaseStore
import managed_executor_handoff as handoff_api
from managed_executor_store import GitManagedExecutorStore, coordination_store_id_for_endpoint
from continuity_fixtures import with_terminal_evidence

SPEC = importlib.util.find_spec("managed_executor_runtime")
runtime = __import__("managed_executor_runtime") if SPEC else None


@unittest.skipUnless(sys.platform == "linux", "local backend needs Linux child observation")
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime, "managed execution adapter is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("init", "-q", "-b", "integration")
        self.git("config", "user.email", "cdc@example.invalid")
        self.git("config", "user.name", "CDC Runtime Test")
        (self.repo / "seed").write_text("base")
        self.git("add", "seed")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.remote))
        self.plan = {
            "schema": "managed-executor-pool-plan/v1", "pool_id": "runtime-pool",
            "change_id": "change", "parent_invocation_id": "parent", "base_sha": self.base,
            "integrator_id": "integrator", "coordination_ref": "refs/heads/cdc/runtime",
            "coordination_store_id": coordination_store_id_for_endpoint(str(self.remote), repo_root=self.repo),
            "max_parallel": 2, "total_runtime_budget_seconds": 30, "total_cost_budget_units": 10,
            "tasks": [self.task(x) for x in ("a", "b")],
        }
        self.make_runtime()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE, text=True).strip()

    def task(self, task_id):
        return {"id": task_id, "role": "writer", "required": True, "dependencies": [],
                "executor_id": "executor-" + task_id, "branch": "worker-" + task_id,
                "worktree": "worktrees/" + task_id, "write_paths": ["src/" + task_id],
                "expected_outputs": ["out:" + task_id], "expected_evidence": ["test:" + task_id],
                "backend_preferences": ["local_command"], "max_runtime_seconds": 10, "max_cost_units": 1}

    def make_runtime(self, parallel=True):
        self.store = GitManagedExecutorStore(self.repo, "origin", self.plan["coordination_ref"], self.plan,
                                            protected_refs=["refs/heads/integration"])
        rev, _ = self.store.read()
        if rev is None:
            self.store.compare_and_swap(None, pool.initial_state(self.plan, parallel_capable=parallel))
        self.backend = runtime.LocalCommandBackend(self.root / "journal")
        self.rt = runtime.ManagedExecutorRuntime(self.plan, self.store, self.repo, self.backend)
        self.addCleanup(self.cleanup_workers)

    def configure_fresh_pool(self):
        # Configure before initializing a new durable pool; admitted plans are immutable.
        self.plan["pool_id"] += "-configured"
        self.plan["coordination_ref"] += "-configured"
        self.make_runtime()

    def cleanup_workers(self):
        for task in self.plan["tasks"]:
            try:
                self.rt.cancel(task["id"], task["id"] + "1")
            except (ValueError, FileNotFoundError):
                continue
        end = time.monotonic() + 4
        while time.monotonic() < end:
            live = []
            for task in self.plan["tasks"]:
                try:
                    live.append(self.rt.observe(task["id"], task["id"] + "1")["status"])
                except (ValueError, FileNotFoundError):
                    pass
            if not any(x in {"running", "starting"} for x in live):
                break
            time.sleep(.03)

    def worker(self, task, delay=.5, fail=False):
        # A real interval plus a real committed result; no synthetic backend events.
        code = '''import json, pathlib, subprocess, time, sys
p=pathlib.Path("src")/sys.argv[1]; p.mkdir(parents=True)
start=time.monotonic(); time.sleep(float(sys.argv[2])); end=time.monotonic()
(p/"interval.json").write_text(json.dumps([start,end]))
if sys.argv[3]=="fail": sys.exit(7)
subprocess.run(["git","add",str(p)],check=True)
subprocess.run(["git","commit","-qm","worker result"],check=True)
'''
        return [sys.executable, "-c", code, task, str(delay), "fail" if fail else "ok"]

    def launch(self, task="a", argv=None):
        rev, _ = self.store.read()
        return self.rt.start(rev, task, task + "1", reservation_token="reserve:" + task,
                             argv=argv or self.worker(task))

    def wait(self, task="a"):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            observed = self.rt.observe(task, task + "1")
            if observed["status"] not in {"running", "starting", "awaiting_release"}:
                return observed
            time.sleep(.025)
        self.fail("real worker did not finish")

    def interval(self, task):
        return json.loads((self.root / "worktrees" / task / "src" / task / "interval.json").read_text())

    def accept(self, task):
        commit = self.git("rev-parse", "worker-" + task)
        return self.rt.accept(task, task + "1", result_commit=commit,
                              output_refs=["out:" + task], evidence_refs=["test:" + task])

    def test_managed_runtime_capability_controls_execution_lease_terminal_lifecycle(self):
        self.launch("a", self.worker("a", 3.0))
        end=time.monotonic()+4
        while time.monotonic()<end:
            observed=self.rt.observe("a","a1")
            if observed["status"]=="running":break
            time.sleep(.01)
        self.assertEqual(observed["status"],"running")

        lease_store=GitLeaseStore(self.repo,"origin","refs/heads/cdc/runtime-lease")
        lease_revision=lease_store.compare_and_swap(
            None,leasev2.initialize("test/project","refs/heads/integration"))
        owner="99999999-9999-4999-8999-999999999999"
        at=runtime._utc()
        spoof={"invocation_id":"spoofed","automation_id":None,"conversation_id":None,
               "execution_surface":"managed","started_at_utc":at}
        with self.assertRaisesRegex(ValueError,"capability proof"):
            leasev2.acquire(leasev2.initialize("test/project","refs/heads/integration"),owner,at,invocation=spoof)

        request_file=self.root/"spoof-acquire.json"
        request_file.write_text(json.dumps({
            "expected_revision":lease_revision,"repository":"test/project","source_ref":"refs/heads/integration",
            "at":at,"invocation":spoof
        }))
        cli=subprocess.run([
            sys.executable,str(ROOT/"scripts"/"execution_lease_v2.py"),"acquire",
            "--repo",str(self.repo),"--remote","origin","--coordination-ref","refs/heads/cdc/runtime-lease",
            "--request",str(request_file)],text=True,capture_output=True)
        self.assertEqual(cli.returncode,2)
        self.assertIn("generic CLI acquisition cannot prove managed terminal capability",cli.stderr)

        acquired=self.rt.acquire_execution_lease(
            lease_store,lease_revision,"test/project","refs/heads/integration",owner,"a","a1",at)
        invocation=acquired["invocation"];invocation_id=invocation["invocation_id"]
        revision=acquired["revision"];record=acquired["record"]
        self.assertEqual(invocation["execution_surface"],"managed")
        self.assertTrue(invocation_id.startswith("managed-terminal:"))

        end=time.monotonic()+4
        held=None
        while time.monotonic()<end:
            held=self.rt.observe("a","a1")
            if held["status"]=="awaiting_release":break
            time.sleep(.01)
        self.assertEqual(held["status"],"awaiting_release")
        self.assertFalse(held["quiescent"])
        self.assertEqual(lease_store.read()[1]["owner_id"],owner)

        # Reconstructing the controller simulates controller/chat loss. The package
        # supervisor remains nonterminal until the exact lease is released.
        self.rt=runtime.ManagedExecutorRuntime(
            self.plan,self.store,self.repo,runtime.LocalCommandBackend(self.root/"journal"))
        self.assertEqual(self.rt.observe("a","a1")["status"],"awaiting_release")

        checkpoint="checkpoint:managed-terminal"
        record=leasev2.begin_finalization(
            record,owner,1,invocation_id,runtime._utc(),pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.record_checkpoint(
            record,owner,1,invocation_id,runtime._utc(),checkpoint_ref=checkpoint,pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.reconcile_finalization(
            record,owner,1,invocation_id,runtime._utc(),external_reconciliation="none")
        revision=lease_store.compare_and_swap(revision,record)
        continuity={
            "schema":"execution-continuity/v1","invocation_id":invocation_id,"current_state":"COMPLETE",
            "requested_terminal_outcome":"scope_complete","runnable_next_action":False,
            "meaningful_progress_refs":["git:"+self.base],"primitive_steps":[],"external_binding":None,
            "blocker":None,"checkpoint_ref":checkpoint,"next_action":None,
            "lease_release_required":False,"lease_released":False}
        continuity=with_terminal_evidence(continuity)
        continuity["terminal_state"]["lease_released"]=False
        record=leasev2.mark_ready(
            record,owner,1,invocation_id,runtime._utc(),continuity_state=continuity)
        revision=lease_store.compare_and_swap(revision,record)

        pre=final_gate.evaluate(
            invocation_id,record,continuity,{"owner_id":owner,"generation":1},None,None,runtime._utc())
        self.assertFalse(pre["final_response_allowed"])
        released=self.rt.release_execution_lease(
            lease_store,revision,"test/project","refs/heads/integration",owner,1,invocation_id,"a","a1",runtime._utc())
        release_record=lease_store.read_revision(released["release_receipt"]["lease_revision"])
        post=copy.deepcopy(continuity);post["lease_release_required"]=True;post["lease_released"]=True
        post["terminal_state"]["lease_released"]=True
        gate=final_gate.evaluate(
            invocation_id,released["record"],post,{"owner_id":owner,"generation":1},
            released["release_receipt"],release_record,runtime._utc())
        self.assertTrue(gate["final_response_allowed"])
        final=self.wait("a")
        self.assertEqual(final["status"],"succeeded");self.assertTrue(final["quiescent"])

    def test_ambiguous_acquire_transport_error_reconciles_authoritative_ownership_instead_of_aborting(self):
        self.launch("a", self.worker("a", 2.0))
        end=time.monotonic()+4
        while time.monotonic()<end:
            observed=self.rt.observe("a","a1")
            if observed["status"]=="running":break
            time.sleep(.01)
        self.assertEqual(observed["status"],"running")

        lease_store=GitLeaseStore(self.repo,"origin","refs/heads/cdc/runtime-lease-ambiguous-acquire")
        lease_revision=lease_store.compare_and_swap(
            None,leasev2.initialize("test/project","refs/heads/integration"))
        owner="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        at=runtime._utc()
        real_acquire=leasev2.acquire_managed_cas

        def lost_reply(*args,**kwargs):
            real_acquire(*args,**kwargs)
            raise ValueError("transport reply lost after authoritative acquire")

        with mock.patch.object(leasev2,"acquire_managed_cas",side_effect=lost_reply):
            acquired=self.rt.acquire_execution_lease(
                lease_store,lease_revision,"test/project","refs/heads/integration",
                owner,"a","a1",at)
        self.assertTrue(acquired["recovered_after_acquire"])
        self.assertEqual(acquired["record"]["owner_id"],owner)
        invocation_id=acquired["invocation"]["invocation_id"]
        paths=runtime._terminal_hold_paths(self.rt._terminal_hold_directory("a","a1"))
        self.assertTrue(paths["owned"].exists());self.assertFalse(paths["abort"].exists())

        record=acquired["record"];revision=acquired["revision"]
        checkpoint="checkpoint:ambiguous-acquire"
        record=leasev2.begin_finalization(record,owner,1,invocation_id,runtime._utc(),pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.record_checkpoint(record,owner,1,invocation_id,runtime._utc(),
                                         checkpoint_ref=checkpoint,pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.reconcile_finalization(record,owner,1,invocation_id,runtime._utc(),
                                              external_reconciliation="none")
        revision=lease_store.compare_and_swap(revision,record)
        continuity={
            "schema":"execution-continuity/v1","invocation_id":invocation_id,"current_state":"COMPLETE",
            "requested_terminal_outcome":"scope_complete","runnable_next_action":False,
            "meaningful_progress_refs":["git:"+self.base],"primitive_steps":[],"external_binding":None,
            "blocker":None,"checkpoint_ref":checkpoint,"next_action":None,
            "lease_release_required":False,"lease_released":False}
        continuity=with_terminal_evidence(continuity)
        continuity["terminal_state"]["lease_released"]=False
        record=leasev2.mark_ready(record,owner,1,invocation_id,runtime._utc(),continuity_state=continuity)
        revision=lease_store.compare_and_swap(revision,record)
        self.rt.release_execution_lease(
            lease_store,revision,"test/project","refs/heads/integration",owner,1,invocation_id,
            "a","a1",runtime._utc())
        final=self.wait("a")
        self.assertEqual(final["status"],"succeeded");self.assertTrue(final["quiescent"])

    def test_owned_marker_is_recovered_after_controller_crash_post_acquire_cas(self):
        self.launch("a", self.worker("a", 2.0))
        end=time.monotonic()+4
        while time.monotonic()<end:
            observed=self.rt.observe("a","a1")
            if observed["status"]=="running":break
            time.sleep(.01)
        self.assertEqual(observed["status"],"running")

        lease_store=GitLeaseStore(self.repo,"origin","refs/heads/cdc/runtime-lease-acquire-recovery")
        lease_revision=lease_store.compare_and_swap(
            None,leasev2.initialize("test/project","refs/heads/integration"))
        owner="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        at=runtime._utc()
        capability=self.rt.terminal_capability(
            "a","a1",lease_repository="test/project",lease_source_ref="refs/heads/integration",
            observed_at_utc=at)
        intent=self.rt._arm_terminal_hold(capability)
        acquired=leasev2.acquire_managed_cas(
            lease_store,lease_revision,"test/project","refs/heads/integration",owner,at,
            terminal_capability=capability)
        invocation_id=acquired["invocation"]["invocation_id"]
        paths=runtime._terminal_hold_paths(self.rt._terminal_hold_directory("a","a1"))
        self.assertFalse(paths["owned"].exists())

        self.rt=runtime.ManagedExecutorRuntime(
            self.plan,self.store,self.repo,runtime.LocalCommandBackend(self.root/"journal"))
        reconciled=self.rt.reconcile_execution_lease_hold(lease_store,"a","a1")
        self.assertEqual(reconciled["status"],"owned")
        owned=json.loads(paths["owned"].read_text())
        self.assertEqual(owned["capability_ref"],intent["capability_ref"])
        self.assertEqual(owned["owner_id"],owner)
        self.assertEqual(owned["generation"],1)
        self.assertEqual(owned["invocation_id"],invocation_id)
        self.assertEqual(owned["lease_revision"],acquired["revision"])

        record=acquired["record"];revision=acquired["revision"]
        checkpoint="checkpoint:acquire-recovery"
        record=leasev2.begin_finalization(record,owner,1,invocation_id,runtime._utc(),pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.record_checkpoint(record,owner,1,invocation_id,runtime._utc(),
                                         checkpoint_ref=checkpoint,pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.reconcile_finalization(record,owner,1,invocation_id,runtime._utc(),
                                              external_reconciliation="none")
        revision=lease_store.compare_and_swap(revision,record)
        continuity={
            "schema":"execution-continuity/v1","invocation_id":invocation_id,"current_state":"COMPLETE",
            "requested_terminal_outcome":"scope_complete","runnable_next_action":False,
            "meaningful_progress_refs":["git:"+self.base],"primitive_steps":[],"external_binding":None,
            "blocker":None,"checkpoint_ref":checkpoint,"next_action":None,
            "lease_release_required":False,"lease_released":False}
        continuity=with_terminal_evidence(continuity)
        continuity["terminal_state"]["lease_released"]=False
        record=leasev2.mark_ready(record,owner,1,invocation_id,runtime._utc(),continuity_state=continuity)
        revision=lease_store.compare_and_swap(revision,record)
        released=self.rt.release_execution_lease(
            lease_store,revision,"test/project","refs/heads/integration",owner,1,invocation_id,
            "a","a1",runtime._utc())
        self.assertEqual(released["release_receipt"]["release"]["owner_id"],owner)
        final=self.wait("a")
        self.assertEqual(final["status"],"succeeded");self.assertTrue(final["quiescent"])

    def test_terminal_hold_aborts_only_when_authoritative_history_proves_no_acquire(self):
        self.launch("a", self.worker("a", .4))
        end=time.monotonic()+4
        while time.monotonic()<end:
            observed=self.rt.observe("a","a1")
            if observed["status"]=="running":break
            time.sleep(.01)
        self.assertEqual(observed["status"],"running")
        lease_store=GitLeaseStore(self.repo,"origin","refs/heads/cdc/runtime-lease-no-acquire")
        lease_store.compare_and_swap(None,leasev2.initialize("test/project","refs/heads/integration"))
        capability=self.rt.terminal_capability(
            "a","a1",lease_repository="test/project",lease_source_ref="refs/heads/integration",
            observed_at_utc=runtime._utc())
        self.rt._arm_terminal_hold(capability)
        pending=self.rt.reconcile_execution_lease_hold(lease_store,"a","a1")
        self.assertEqual(pending["status"],"acquire_pending")
        self.rt._mark_terminal_acquire_done(capability,"error")
        reconciled=self.rt.reconcile_execution_lease_hold(lease_store,"a","a1")
        self.assertEqual(reconciled["status"],"aborted")
        final=self.wait("a")
        self.assertEqual(final["status"],"succeeded");self.assertTrue(final["quiescent"])

    def test_release_marker_is_recovered_after_controller_crash_post_release_cas(self):
        self.launch("a", self.worker("a", 2.0))
        end=time.monotonic()+4
        while time.monotonic()<end:
            observed=self.rt.observe("a","a1")
            if observed["status"]=="running":break
            time.sleep(.01)
        self.assertEqual(observed["status"],"running")

        lease_store=GitLeaseStore(self.repo,"origin","refs/heads/cdc/runtime-lease-recovery")
        lease_revision=lease_store.compare_and_swap(
            None,leasev2.initialize("test/project","refs/heads/integration"))
        owner="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        at=runtime._utc()
        acquired=self.rt.acquire_execution_lease(
            lease_store,lease_revision,"test/project","refs/heads/integration",owner,"a","a1",at)
        invocation_id=acquired["invocation"]["invocation_id"]
        revision=acquired["revision"];record=acquired["record"]

        end=time.monotonic()+4
        while time.monotonic()<end:
            held=self.rt.observe("a","a1")
            if held["status"]=="awaiting_release":break
            time.sleep(.01)
        self.assertEqual(held["status"],"awaiting_release")

        checkpoint="checkpoint:release-recovery"
        record=leasev2.begin_finalization(record,owner,1,invocation_id,runtime._utc(),pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.record_checkpoint(record,owner,1,invocation_id,runtime._utc(),
                                         checkpoint_ref=checkpoint,pending_shared_writes=False)
        revision=lease_store.compare_and_swap(revision,record)
        record=leasev2.reconcile_finalization(record,owner,1,invocation_id,runtime._utc(),
                                              external_reconciliation="none")
        revision=lease_store.compare_and_swap(revision,record)
        continuity={
            "schema":"execution-continuity/v1","invocation_id":invocation_id,"current_state":"COMPLETE",
            "requested_terminal_outcome":"scope_complete","runnable_next_action":False,
            "meaningful_progress_refs":["git:"+self.base],"primitive_steps":[],"external_binding":None,
            "blocker":None,"checkpoint_ref":checkpoint,"next_action":None,
            "lease_release_required":False,"lease_released":False}
        continuity=with_terminal_evidence(continuity)
        continuity["terminal_state"]["lease_released"]=False
        record=leasev2.mark_ready(record,owner,1,invocation_id,runtime._utc(),continuity_state=continuity)
        revision=lease_store.compare_and_swap(revision,record)

        direct=leasev2.release_cas(
            lease_store,revision,"test/project","refs/heads/integration",owner,1,invocation_id,runtime._utc())
        self.assertIsNone(direct["record"]["owner_id"])
        self.assertEqual(self.rt.observe("a","a1")["status"],"awaiting_release")

        self.rt=runtime.ManagedExecutorRuntime(
            self.plan,self.store,self.repo,runtime.LocalCommandBackend(self.root/"journal"))
        recovered=self.rt.release_execution_lease(
            lease_store,revision,"test/project","refs/heads/integration",owner,1,invocation_id,
            "a","a1",runtime._utc())
        self.assertTrue(recovered["recovered_after_release"])
        self.assertEqual(recovered["release_receipt"],direct["release_receipt"])
        final=self.wait("a")
        self.assertEqual(final["status"],"succeeded");self.assertTrue(final["quiescent"])

    def test_two_workers_really_overlap_and_commit_in_isolated_worktrees(self):
        self.launch("a", self.worker("a", .8))
        self.launch("b", self.worker("b", .8))
        for task in ("a", "b"):
            receipt = self.wait(task)
            self.assertEqual(receipt["status"], "succeeded")
            self.assertTrue(receipt["quiescent"])
            self.assertEqual(receipt["identity"]["base_sha"], self.base)
            self.assertEqual(receipt["identity"]["attempt_id"], task + "1")
            self.accept(task)
        a, b = self.interval("a"), self.interval("b")
        self.assertLess(max(a[0], b[0]), min(a[1], b[1]))
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)
        self.assertEqual({t["status"] for t in self.store.read()[1]["tasks"]}, {"succeeded"})

    def test_same_tasks_execute_sequentially_when_capacity_is_one(self):
        self.plan["max_parallel"] = 1
        self.configure_fresh_pool()
        self.launch("a")
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.launch("b")
        self.assertEqual(self.wait("a")["status"], "succeeded")
        self.accept("a")
        self.launch("b")
        self.assertEqual(self.wait("b")["status"], "succeeded")
        self.accept("b")
        self.assertLessEqual(self.interval("a")[1], self.interval("b")[0])

    def test_failed_worker_keeps_independent_success_runnable(self):
        self.launch("a", self.worker("a", .1, fail=True))
        self.assertEqual(self.wait("a")["status"], "failed")
        self.launch("b", self.worker("b", .1))
        self.assertEqual(self.wait("b")["status"], "succeeded")
        self.accept("b")
        states = {t["id"]: t["status"] for t in self.store.read()[1]["tasks"]}
        self.assertEqual(states, {"a": "failed", "b": "succeeded"})
        self.assertIn("a:recovery_required", pool.assess(self.plan, self.store.read()[1])["blockers"])

    def test_duplicate_or_stale_start_cannot_launch_another_process(self):
        old_rev, _ = self.store.read()
        first = self.launch("a")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.rt.start(old_rev, "b", "b1", reservation_token="reserve:b", argv=self.worker("b"))
        with self.assertRaises(ValueError):
            self.launch("a")
        self.assertEqual(self.wait("a")["launch_id"], first["launch_id"])
        self.assertFalse((self.root / "worktrees" / "b").exists())
        self.assertEqual(self.store.read()[1]["tasks"][0]["attempt_ids"], ["a1"])

    def test_claim_without_start_is_unknown_and_never_replayed_after_recovery(self):
        rev, _ = self.store.read()
        q = pool.queue_task_cas(self.store, rev, self.plan, "a", "a1", reservation_token="reserve:a")
        pool.claim_launch_cas(self.store, q["store_revision"], self.plan, "a", "a1", reservation_token="reserve:a")
        recovered = runtime.ManagedExecutorRuntime(self.plan, self.store, self.repo,
                                                   runtime.LocalCommandBackend(self.root / "journal"))
        observed = recovered.observe("a", "a1")
        self.assertEqual(observed["status"], "unknown")
        self.assertFalse(observed["quiescent"])
        with self.assertRaises(ValueError):
            self.launch("a")
        self.assertFalse((self.root / "worktrees" / "a").exists())
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")


    def descendant_worker(self, marker):
        child = "import signal,time,pathlib,os; signal.signal(signal.SIGTERM,signal.SIG_IGN); os.setsid(); p=pathlib.Path(" + repr(str(marker)) + ");\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.01)"
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(60)"
        return [sys.executable, "-c", code]

    def wait_file(self, path):
        end = time.monotonic() + 4
        while not path.exists() and time.monotonic() < end:
            time.sleep(.01)
        self.assertTrue(path.exists(), "worker did not produce its live side effect")

    def test_cancel_waits_for_detached_term_ignoring_descendant_before_quiescence(self):
        marker = self.root / "descendant-writing"
        self.launch("a", self.descendant_worker(marker))
        self.wait_file(marker)
        observed = self.rt.cancel("a", "a1")
        if not observed["quiescent"]:
            self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")
        final = self.wait("a")
        self.assertEqual(final["status"], "cancelled")
        self.assertTrue(final["quiescent"])
        content = marker.read_text()
        time.sleep(.15)
        self.assertEqual(marker.read_text(), content)
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "cancelled")

    def test_timeout_stops_descendant_and_preserves_exact_attempt(self):
        self.plan["tasks"][0]["max_runtime_seconds"] = .4
        self.configure_fresh_pool()
        marker = self.root / "timeout-writing"
        self.launch("a", self.descendant_worker(marker))
        self.wait_file(marker)
        final = self.wait("a")
        self.assertEqual(final["status"], "timed_out")
        self.assertTrue(final["quiescent"])
        before = marker.read_text()
        time.sleep(.15)
        self.assertEqual(marker.read_text(), before)
        task = self.store.read()[1]["tasks"][0]
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["attempt_ids"], ["a1"])
        self.assertGreater(final["elapsed_seconds"], .4)
        self.assertEqual(task["runtime_seconds"], .4)

    def test_exhausted_attempt_cannot_launch_effect_even_from_legacy_queue(self):
        self.plan["tasks"][0].update(role="read_only", branch=None, worktree=None,
                                      write_paths=[], max_runtime_seconds=.1)
        self.configure_fresh_pool()
        self.launch("a", [sys.executable, "-c", "import time; time.sleep(1)"])
        self.assertEqual(self.wait("a")["status"], "timed_out")
        revision, state = self.store.read()
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            pool.retry_task(self.plan, state, "a", expected_revision=state["revision"])
        # A queue persisted by older code must not bypass launch admission.
        task = state["tasks"][0]
        task.update(status="queued", active_attempt_id="a2", reservation_token="legacy-a2")
        task["attempt_ids"].append("a2")
        state["revision"] += 1
        revision = self.store.compare_and_swap(revision, state)
        marker = self.root / "forbidden-effect"
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.rt.start_queued(revision, "a", "a2", reservation_token="legacy-a2",
                                 argv=[sys.executable, "-c", "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"])
        self.assertFalse(marker.exists())
        self.assertIsNone(self.rt.journal.load_request(self.rt._identity("a", "a2")))
        self.assertIn("b", pool.dispatch(self.plan, self.store.read()[1])["task_ids"])
        self.launch("b", self.worker("b", .05))
        self.assertEqual(self.wait("b")["status"], "succeeded")

    def test_supervisor_crash_is_unknown_while_orphan_can_still_write(self):
        marker = self.root / "orphan-writing"
        code = "import os,pathlib,time; pathlib.Path(" + repr(str(self.root / "child-pid")) + ").write_text(str(os.getpid())); p=pathlib.Path(" + repr(str(marker)) + ");\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.01)"
        self.launch("a", [sys.executable, "-c", code])
        self.wait_file(marker)
        live = self.rt.observe("a", "a1")
        child_pid = int((self.root / "child-pid").read_text())
        self.addCleanup(lambda: os.kill(child_pid, signal.SIGKILL))
        os.kill(live["supervisor_pid"], signal.SIGKILL)
        time.sleep(.08)
        observed = self.rt.observe("a", "a1")
        self.assertEqual(observed["status"], "unknown")
        self.assertFalse(observed["quiescent"])
        before = marker.read_text()
        time.sleep(.04)
        self.assertNotEqual(marker.read_text(), before)
        with self.assertRaises(ValueError):
            self.launch("a")
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")

    def test_recovered_adapter_observes_same_live_worker_without_relaunch(self):
        launched = self.launch("a", self.worker("a", .5))
        self.rt = runtime.ManagedExecutorRuntime(self.plan, self.store, self.repo,
                                                 runtime.LocalCommandBackend(self.root / "journal"))
        self.assertEqual(self.wait("a")["launch_id"], launched["launch_id"])
        self.accept("a")
        self.assertEqual(self.git("rev-list", "--count", self.base + "..worker-a"), "1")

    def test_shell_string_rejected_before_queue_or_launch(self):
        rev, _ = self.store.read()
        with self.assertRaises(ValueError):
            self.launch("a", "touch should-never-exist")
        self.assertEqual(self.store.read()[0], rev)


    def completion(self):
        state = dict(schema="execution-continuity/v1", invocation_id="parent", current_state="CHECKPOINT",
                     requested_terminal_outcome="scope_complete", runnable_next_action=False,
                     meaningful_progress_refs=["git:" + self.git("rev-parse", "HEAD")], primitive_steps=[],
                     external_binding=None, blocker=None, checkpoint_ref="checkpoint:runtime",
                     next_action=None, lease_release_required=False, lease_released=True)
        state = with_terminal_evidence(state)
        state["terminal_state"]["observed_head"] = self.git("rev-parse", "HEAD")
        return state

    def publication(self, task, accepted):
        result = accepted["result"]
        handoff = {"schema": "managed-executor-handoff/v1", "pool_id": self.plan["pool_id"],
                   "change_id": "change", "task_id": task, "attempt_id": task + "1",
                   "parent_invocation_id": "parent", "executor_id": "executor-" + task,
                   "base_sha": self.base, "assigned_branch": "worker-" + task,
                   "publication_repository": "test/runtime", "publication_remote_id": handoff_api.publication_remote_identity(self.repo, "origin"),
                   "transport": "direct_branch", "source_result_commit": result["result_commit"],
                   "direct_result_commit": result["result_commit"], "artifact_ref": None,
                   "changed_paths": result["changed_paths"], "evidence_refs": result["evidence_refs"]}
        proof = {"schema": "managed-executor-publication-proof/v1", "handoff_ref": handoff_api.canonical_handoff_ref(handoff),
                 **{k: handoff[k] for k in ("pool_id", "task_id", "attempt_id", "base_sha", "assigned_branch", "publication_repository", "publication_remote_id")},
                 "published_commit": result["result_commit"], "observed_changed_paths": result["changed_paths"],
                 "evidence_refs": ["git:remote-worker-head"], "result_verified": True,
                 **{k: False for k in handoff_api.AUTHORITY_FIELDS}}
        return dict(integrator_id="integrator", handoff=handoff, proof=proof,
                    integration_commit=self.git("rev-parse", "HEAD"), integration_ref="refs/heads/integration",
                    remote="origin", trusted_repository="test/runtime", trusted_remote_id=handoff["publication_remote_id"])

    def test_parent_closure_needs_real_publication_integration_and_terminal_evidence(self):
        self.assertFalse(self.rt.evaluate_parent(self.completion())["final_response_allowed"])
        for task in ("a", "b"):
            self.launch(task, self.worker(task, .05))
            self.assertEqual(self.wait(task)["status"], "succeeded")
            accepted = self.accept(task)
            gate = self.rt.evaluate_parent(self.completion())
            self.assertFalse(gate["final_response_allowed"])
            self.assertIn(task + ":unintegrated_success", gate["pool"]["blockers"])
            publication = self.publication(task, accepted)
            with self.assertRaisesRegex(ValueError, "authoritative remote branch"):
                self.rt.record_integration(task, accepted["result_ref"], **publication)
            self.git("push", "-q", "origin", "worker-" + task)
            with self.assertRaisesRegex(ValueError, "integration does not contain"):
                self.rt.record_integration(task, accepted["result_ref"], **publication)
            self.git("merge", "--no-ff", "-qm", "integrate " + task, "worker-" + task)
            publication["integration_commit"] = self.git("rev-parse", "HEAD")
            with self.assertRaisesRegex(ValueError, "authoritative remote branch"):
                self.rt.record_integration(task, accepted["result_ref"], **publication)
            self.git("push", "-q", "origin", "integration")
            self.rt.record_integration(task, accepted["result_ref"], **publication)
        continuity = self.completion()
        gate = self.rt.evaluate_parent(continuity)
        self.assertTrue(gate["final_response_allowed"])
        self.assertTrue(gate["pool"]["complete"])
        del continuity["terminal_state"]
        self.assertFalse(self.rt.evaluate_parent(continuity)["final_response_allowed"])

    def test_dirty_process_success_cannot_be_accepted_as_finished_result(self):
        command = self.worker("a", .01)
        command[2] += "\n(p/'uncommitted').write_text('still pending')\n"
        self.launch("a", command)
        self.assertEqual(self.wait("a")["status"], "succeeded")
        with self.assertRaisesRegex(ValueError, "clean"):
            self.accept("a")
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")

    def test_out_of_scope_transient_commit_cannot_be_accepted(self):
        command = self.worker("a", .01)
        command[2] += "\nq=pathlib.Path('outside'); q.write_text('escape'); subprocess.run(['git','add','outside'],check=True); subprocess.run(['git','commit','-qm','escape'],check=True); q.unlink(); subprocess.run(['git','add','outside'],check=True); subprocess.run(['git','commit','-qm','undo escape'],check=True)\n"
        self.launch("a", command)
        self.assertEqual(self.wait("a")["status"], "succeeded")
        with self.assertRaisesRegex(ValueError, "history touched paths"):
            self.accept("a")
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")

    def test_backend_contract_needs_only_start_observe_cancel(self):
        underlying = self.backend
        class NarrowBackend:
            name = "local_command"
            def start(self, request): return underlying.start(request)
            def observe(self, request, receipt=None): return underlying.observe(request, receipt)
            def cancel(self, request, receipt=None): return underlying.cancel(request, receipt)
        self.rt = runtime.ManagedExecutorRuntime(self.plan, self.store, self.repo, NarrowBackend(),
                                                 journal_root=self.root / "journal")
        self.launch("a", self.worker("a", .05))
        self.assertEqual(self.wait("a")["status"], "succeeded")
        self.accept("a")


    def test_worker_exit_does_not_end_descendant_observation(self):
        self.plan["tasks"][0]["max_runtime_seconds"] = .4
        self.configure_fresh_pool()
        marker = self.root / "root-exited-child-writing"
        argv = self.descendant_worker(marker)
        argv[2] = argv[2].replace("; time.sleep(60)", "")
        self.launch("a", argv)
        self.wait_file(marker)
        observed = self.rt.observe("a", "a1")
        self.assertFalse(observed["quiescent"])
        self.assertEqual(self.wait("a")["status"], "timed_out")
        before = marker.read_text()
        time.sleep(.1)
        self.assertEqual(marker.read_text(), before)

    def test_controller_exit_preserves_running_supervisor_and_result(self):
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"plan": self.plan, "repo": str(self.repo),
                                        "journal": str(self.root / "journal"), "argv": self.worker("a", .3)}))
        code = """import json,os,sys
sys.path.insert(0,sys.argv[1])
from managed_executor_runtime import ManagedExecutorRuntime,LocalCommandBackend
from managed_executor_store import GitManagedExecutorStore
s=json.load(open(sys.argv[2])); p=s['plan']
store=GitManagedExecutorStore(s['repo'],'origin',p['coordination_ref'],p,protected_refs=['refs/heads/integration'])
r=ManagedExecutorRuntime(p,store,s['repo'],LocalCommandBackend(s['journal']))
r.start(store.read()[0],'a','a1',reservation_token='reserve:a',argv=s['argv'])
os._exit(0)
"""
        subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts"), str(settings)], check=True)
        self.assertEqual(self.wait("a")["status"], "succeeded")
        self.accept("a")
        self.assertEqual(self.git("rev-list", "--count", self.base + "..worker-a"), "1")

    def test_receipt_from_another_claim_cannot_release_or_accept_worker(self):
        self.launch("a", self.worker("a", .01))
        self.assertEqual(self.wait("a")["status"], "succeeded")
        receipt_path = next((self.root / "journal").glob("*/receipt.json"))
        receipt = json.loads(receipt_path.read_text())
        receipt["claim"]["reservation_token"] = "other-reservation"
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "identity/claim"):
            self.rt.observe("a", "a1")
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")


    def test_queued_recovery_consumes_claim_once_before_real_start(self):
        revision, _ = self.store.read()
        queued = pool.queue_task_cas(self.store, revision, self.plan, "a", "a1", reservation_token="reserve:a")
        launched = self.rt.start_queued(queued["store_revision"], "a", "a1", reservation_token="reserve:a",
                                        argv=self.worker("a", .05))
        with self.assertRaisesRegex(ValueError, "stale"):
            self.rt.start_queued(queued["store_revision"], "a", "a1", reservation_token="reserve:a",
                                 argv=self.worker("a", .05))
        self.assertEqual(self.wait("a")["launch_id"], launched["launch_id"])
        self.assertEqual(self.git("rev-list", "--count", self.base + "..worker-a"), "1")


    def test_read_only_worker_cannot_hide_a_committed_change(self):
        self.plan["tasks"][0].update(role="read_only", branch=None, worktree=None, write_paths=[])
        self.configure_fresh_pool()
        code = "import pathlib,subprocess; pathlib.Path('seed').write_text('changed'); subprocess.run(['git','add','seed'],check=True); subprocess.run(['git','commit','-qm','hidden change'],check=True)"
        self.launch("a", [sys.executable, "-c", code])
        self.assertEqual(self.wait("a")["status"], "succeeded")
        with self.assertRaisesRegex(ValueError, "non-writer changed"):
            self.rt.accept("a", "a1", result_commit=None, output_refs=["out:a"], evidence_refs=["test:a"])


    def test_live_plan_expansion_cannot_relabel_an_out_of_scope_result(self):
        argv = self.worker("a", .01)
        argv[2] += "\nq=pathlib.Path('outside'); q.write_text('escape'); subprocess.run(['git','add','outside'],check=True); subprocess.run(['git','commit','-qm','escape'],check=True)\n"
        self.launch("a", argv)
        self.assertEqual(self.wait("a")["status"], "succeeded")
        self.plan["tasks"][0]["write_paths"].append("outside")
        with self.assertRaisesRegex(ValueError, "durable request identity"):
            self.accept("a")
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "running")

    def test_queued_assignment_cannot_expand_scope_even_after_reconstruction(self):
        revision, _ = self.store.read()
        queued = pool.queue_task_cas(self.store, revision, self.plan, "a", "a1", reservation_token="queued-a")
        expanded = copy.deepcopy(self.plan)
        expanded["tasks"][0]["write_paths"].append("outside")
        rebound_store = GitManagedExecutorStore(self.repo, "origin", expanded["coordination_ref"], expanded,
                                                protected_refs=["refs/heads/integration"])
        rebound = runtime.ManagedExecutorRuntime(expanded, rebound_store, self.repo, self.backend)
        marker = self.root / "expanded-effect"
        with self.assertRaisesRegex(ValueError, "plan.*(digest|binding)|assignment"):
            rebound.start_queued(queued["store_revision"], "a", "a1", reservation_token="queued-a",
                                 argv=[shutil.which("touch"), str(marker)])
        self.assertFalse(marker.exists())
        self.assertEqual(self.store.read()[1]["tasks"][0]["status"], "queued")

    def test_preparation_deadline_prevents_worker_effect(self):
        self.plan["tasks"][0]["max_runtime_seconds"] = .1
        self.configure_fresh_pool()
        hook = self.repo / ".git/hooks/post-checkout"
        hook.write_text("#!/bin/sh\nsleep 0.5\n")
        hook.chmod(0o755)
        marker = self.root / "late-effect"
        self.launch("a", [shutil.which("touch"), str(marker)])
        observation = self.wait("a")
        self.assertEqual(observation["status"], "timed_out")
        self.assertTrue(observation["quiescent"])
        self.assertFalse(marker.exists())
        self.assertNotIn("worker_pid", observation)

    def test_preparation_cancellation_prevents_worker_effect(self):
        hook = self.repo / ".git/hooks/post-checkout"
        hook.write_text("#!/bin/sh\nsleep 0.5\n")
        hook.chmod(0o755)
        marker = self.root / "cancelled-effect"
        self.launch("a", [shutil.which("touch"), str(marker)])
        self.rt.cancel("a", "a1")
        observation = self.wait("a")
        self.assertEqual(observation["status"], "cancelled")
        self.assertTrue(observation["quiescent"])
        self.assertFalse(marker.exists())
        self.assertNotIn("worker_pid", observation)


if __name__ == "__main__":
    unittest.main()
