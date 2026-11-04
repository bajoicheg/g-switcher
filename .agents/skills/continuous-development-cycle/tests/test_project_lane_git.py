import importlib.util
import concurrent.futures
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from git_document_store import GitDocumentStore
from project_lanes import LaneClaim, LaneKind

if importlib.util.find_spec("project_lane_git"):
    import project_lane_git
else:
    project_lane_git = None


def git(repo, *args, input_text=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


class GitLaneResultVerifierTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(project_lane_git, "Git lane result verifier is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "src/a").mkdir(parents=True)
        (self.repo / "src/b").mkdir(parents=True)
        (self.repo / "src/a/base.txt").write_text("a\n")
        (self.repo / "src/b/outside.txt").write_text("original\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.primary = git(self.repo, "branch", "--show-current")
        self.claim = LaneClaim(
            "lane", "inv", LaneKind.WORKER, self.base, str(self.repo), "worker",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        self.verifier = project_lane_git.GitLaneResultVerifier(self.repo)

    def commit(self, path, text, message):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(self.repo, "add", str(path))
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def test_descendant_result_reports_all_touched_paths(self):
        head = self.commit(Path("src/a/new.py"), "print(1)\n", "inside")
        result = self.verifier(self.claim, head)
        self.assertTrue(result["base_ancestor"])
        self.assertEqual(result["observed_base"], self.base)
        self.assertEqual(result["touched_paths"], {"src/a/new.py"})

    def test_non_descendant_result_is_not_accepted_as_ancestry(self):
        git(self.repo, "checkout", "-qb", "other", self.base)
        other = self.commit(Path("src/a/other.py"), "x\n", "other")
        git(self.repo, "checkout", "-q", self.primary)
        master = self.commit(Path("src/a/master.py"), "m\n", "master")
        self.assertTrue(self.verifier(self.claim, master)["base_ancestor"])
        unrelated = LaneClaim(
            "lane2", "inv2", LaneKind.WORKER, other, str(self.repo), "worker2",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        self.assertFalse(self.verifier(unrelated, master)["base_ancestor"])

    def test_touched_and_restored_escape_is_still_reported(self):
        original = (self.repo / "src/b/outside.txt").read_text()
        self.commit(Path("src/b/outside.txt"), "changed\n", "outside")
        head = self.commit(Path("src/b/outside.txt"), original, "restore")
        self.assertEqual(git(self.repo, "diff", "--name-only", self.base + ".." + head), "")
        result = self.verifier(self.claim, head)
        self.assertIn("src/b/outside.txt", result["touched_paths"])

    def test_integration_verifier_proves_result_and_observed_head_ancestry(self):
        git(self.repo, "checkout", "-qb", "worker-result", self.base)
        result_commit = self.commit(Path("src/a/integrated.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        git(self.repo, "merge", "--ff-only", "worker-result")
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        verifier = project_lane_git.GitLaneIntegrationVerifier(
            self.repo, "refs/heads/" + self.primary)
        evidence = verifier(
            {"lane_id": "lane", "result_commit": result_commit},
            integrator,
            {"lane_id": "lane", "result_commit": result_commit,
             "observed_shared_head": self.base,
             "intended_integrated_head": result_commit,
             "operation_id": "op-1"})
        self.assertTrue(evidence["integrated"])
        self.assertEqual(evidence["integrated_head"], result_commit)
        self.assertFalse(evidence["conditional_update"])
        self.assertFalse(evidence["force_push"])

    def test_integration_verifier_rejects_result_not_present_on_shared_head(self):
        git(self.repo, "checkout", "-qb", "worker-result", self.base)
        result_commit = self.commit(Path("src/a/not-integrated.py"), "no\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        verifier = project_lane_git.GitLaneIntegrationVerifier(
            self.repo, "refs/heads/" + self.primary)
        with self.assertRaisesRegex(ValueError, "ancestry"):
            verifier(
                {"lane_id": "lane", "result_commit": result_commit},
                integrator,
                {"lane_id": "lane", "result_commit": result_commit,
                 "observed_shared_head": self.base,
                 "intended_integrated_head": result_commit,
                 "operation_id": "op-1"})

    def test_invalid_or_missing_commit_fails_closed(self):
        for value in ("main", "f" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verifier(self.claim, value)


class NativePublicationTests(unittest.TestCase):
    """Transport faults use actual issued runtime/pool/lease custody."""
    def setUp(self):
        import managed_host_bridge as bridge
        from test_managed_host_bridge import ManagedHostBridgeTests
        self.f=ManagedHostBridgeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.handle=bridge.start(self.f.start_request());self.f.wait_for(self.handle,'awaiting_release')
        self.session=bridge._load_session(str(self.f.root/'handles'),self.handle['handle_id'])
        self.result,_,_=bridge._result(self.session,bridge._runtime(self.session))
        self.store=GitDocumentStore(self.f.repo,'origin',self.session['publication_ref'],self.f.store_id)
        self.item={'lane_id':self.session['task_id'],'result_commit':self.result}
        self.intent=dict(self.item,operation_id=bridge._digest({'handle_id':self.handle['handle_id'],'result_commit':self.result,'observed_shared_head':self.f.base,'shared_ref':'refs/heads/main'}),observed_shared_head=self.f.base,intended_integrated_head=self.result)
        self.integrator=LaneClaim('integrator',self.session['invocation_id'],LaneKind.INTEGRATOR,self.f.base,str(self.f.repo),'main',executor_id=self.f.plan['integrator_id'],role='integrator')
    def publisher(self,cls=None,**kwargs):
        return (cls or project_lane_git.GitLaneIntegrationPublisher)(self.f.repo,'origin','refs/heads/main',self.f.store_id,attempt_store=self.store,quarantine_store=self.f.lease_store,native_handle={'handle_root':str(self.f.root/'handles'),'handle_id':self.handle['handle_id']},**kwargs)
    def publish(self,publisher):return publisher(self.item,self.integrator,self.intent)

    def install_guard(self):
        import copy,managed_host_bridge as bridge,execution_lease_v2 as lease,operation_intent as op
        binding={'repository':self.session['lease_repository'],'candidate_sha':self.result,
                 'backend':'local_command','mode':'writer','environment_id':'fixture',
                 'check_suite_fingerprint':'sha256:'+'1'*64,'environment_fingerprint':'sha256:'+'2'*64,
                 'check_plan_digest':'sha256:'+'3'*64}
        intent=op.prepare(binding,'guarded-publication',self.session['lease_source_ref'],bridge._utc())
        receipt=op.verify_readback(intent,copy.deepcopy(intent),'fixture:guard-readback',bridge._utc())
        intent=op.transition(intent,'submitting',bridge._utc(),receipt=receipt)
        intent=op.transition(intent,'unknown',bridge._utc())
        revision,row=self.f.lease_store.read()
        guarded=lease.set_guard(row,self.session['owner_id'],self.session['generation'],self.session['invocation_id'],bridge._utc(),intent,'fixture:guard-readback')
        self.f.lease_store.compare_and_swap(revision,guarded)

    def expire_ownership(self):
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc);revision,row=self.f.lease_store.read()
        row['expires_at_utc']=now.isoformat().replace('+00:00','Z')
        self.f.lease_store.compare_and_swap(revision,row)

    def test_native_guard_blocks_direct_product_publication(self):
        self.install_guard()
        with self.assertRaisesRegex(ValueError,'unresolved external guard'):self.publish(self.publisher())
        self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])

    def test_native_expired_ttl_cannot_use_backdated_publisher_clock(self):
        self.expire_ownership()
        with self.assertRaisesRegex(ValueError,'ownership is not fresh'):
            self.publish(self.publisher(clock=lambda:'2000-01-01T00:00:00Z'))
        self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])

    def test_native_stale_heartbeat_blocks_direct_product_publication(self):
        from datetime import datetime,timedelta,timezone
        import managed_host_bridge as bridge
        # Advance the native clock beyond its heartbeat gate without changing
        # the issued invocation/acquisition or waiting ten real minutes.
        at=(datetime.now(timezone.utc)+timedelta(seconds=601)).isoformat().replace('+00:00','Z')
        with mock.patch.object(bridge,'_utc',return_value=at):
            with self.assertRaisesRegex(ValueError,'ownership is not fresh'):self.publish(self.publisher())
        self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])

    def test_guard_racing_submitted_consumption_leaves_prepared_unsent(self):
        fixture=self
        class BeforeConsumption(project_lane_git.GitLaneIntegrationPublisher):
            def _transition_attempt(inner,item,intent,target,allowed):
                if target=='submitted':fixture.install_guard()
                return super()._transition_attempt(item,intent,target,allowed)
        publisher=self.publisher(BeforeConsumption)
        with self.assertRaisesRegex(ValueError,'unresolved external guard'):self.publish(publisher)
        self.assertEqual(publisher.publication_attempt(self.intent['operation_id'])['status'],'prepared')
        self.assertEqual(self.f.remote_head(),self.f.base)

    def test_postsubmitted_guard_denial_stays_unresolved_and_never_replays(self):
        fixture=self
        class AfterConsumption(project_lane_git.GitLaneIntegrationPublisher):
            def _transition_attempt(inner,item,intent,target,allowed):
                result=super()._transition_attempt(item,intent,target,allowed)
                if target=='submitted':fixture.install_guard()
                return result
        publisher=self.publisher(AfterConsumption)
        with self.assertRaisesRegex(ValueError,'unresolved external guard'):self.publish(publisher)
        self.assertEqual(self.f.remote_head(),self.f.base)
        self.assertEqual(publisher.publication_attempt(self.intent['operation_id'])['status'],'submitted')
        original=self.store.read()
        with self.assertRaises(ValueError):self.publish(self.publisher())
        self.assertEqual(self.store.read(),original)
        self.f.git('push','origin',self.result+':refs/heads/main')
        evidence=self.publish(self.publisher())
        self.assertFalse(evidence['conditional_update']);self.assertEqual(evidence['publication_attempt_state'],'submitted')
        self.assertEqual(self.store.read(),original)

    def test_guard_appearing_inside_transport_boundary_cannot_send(self):
        fixture=self
        class BeforeTransport(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(inner,*args):fixture.install_guard();return super()._push_cas(*args)
        publisher=self.publisher(BeforeTransport)
        with self.assertRaisesRegex(ValueError,'unresolved external guard'):self.publish(publisher)
        self.assertEqual(publisher.publication_attempt(self.intent['operation_id'])['status'],'submitted')
        self.assertEqual(self.f.remote_head(),self.f.base)

    def test_integration_publisher_performs_exact_head_conditional_fast_forward(self):
        publisher=self.publisher();evidence=self.publish(publisher)
        self.assertTrue(evidence['conditional_update']);self.assertEqual(self.f.remote_head(),self.result)
        self.assertEqual(self.publish(publisher),evidence)
    def test_racing_publishers_submit_one_transport_for_the_same_attempt(self):
        ready=threading.Barrier(2);calls=[]
        transition=project_lane_git.GitLaneIntegrationPublisher._transition_attempt
        push=project_lane_git.GitLaneIntegrationPublisher._push_cas
        def synchronized(publisher,item,intent,target,allowed):
            if target=='submitted':ready.wait(timeout=30)
            return transition(publisher,item,intent,target,allowed)
        def transport(publisher,*args):calls.append(args);return push(publisher,*args)
        def submit(publisher):
            try:return self.publish(publisher)
            except ValueError as exc:return str(exc)
        with mock.patch.object(project_lane_git.GitLaneIntegrationPublisher,'_transition_attempt',synchronized),mock.patch.object(project_lane_git.GitLaneIntegrationPublisher,'_push_cas',transport):
            with concurrent.futures.ThreadPoolExecutor(2) as executor:results=list(executor.map(submit,[self.publisher(),self.publisher()]))
        self.assertEqual(calls,[(self.f.base,self.result)],results)
        self.assertEqual(len([r for r in results if isinstance(r,dict)]),1,results)
    def test_preexisting_intended_remote_head_is_readback_only_without_this_intents_cas(self):
        self.f.git('push','origin',self.result+':refs/heads/main')
        legacy=project_lane_git.GitLaneIntegrationPublisher(self.f.repo,'origin','refs/heads/main',self.f.store_id,attempt_store=self.store)
        self.assertFalse(self.publish(legacy)['conditional_update'])
    def test_integration_publisher_requires_durable_attempt_state_before_push(self):
        publisher=project_lane_git.GitLaneIntegrationPublisher(self.f.repo,'origin','refs/heads/main',self.f.store_id)
        with self.assertRaisesRegex(ValueError,'durable|attempt'):self.publish(publisher)
        self.assertEqual(self.f.remote_head(),self.f.base)
    def test_lost_push_reply_reconciles_from_durable_attempt_after_restart_without_replay(self):
        class LostReply(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(inner,*args):super()._push_cas(*args);raise project_lane_git._PublicationUnknown('lost reply')
        with self.assertRaisesRegex(ValueError,'unknown'):self.publish(self.publisher(LostReply))
        class NoReplay(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(inner,*args):raise AssertionError('transport replayed')
        result=self.publish(self.publisher(NoReplay));self.assertTrue(result['conditional_update']);self.assertEqual(result['publication_attempt_state'],'confirmed')
    def test_remote_failure_porcelain_is_unknown_and_reconciles_without_replay(self):
        actual=subprocess.run
        def failure(args,*pos,**kw):
            if '--porcelain' in args and any(a.startswith('--force-with-lease=refs/heads/main:') for a in args):return subprocess.CompletedProcess(args,1,'!\t'+self.result+':refs/heads/main\t[remote failure] (remote failed to report status)\n','error')
            return actual(args,*pos,**kw)
        with mock.patch.object(project_lane_git.subprocess,'run',side_effect=failure):
            with self.assertRaisesRegex(ValueError,'unknown'):self.publish(self.publisher())
        self.assertEqual(self.publisher().publication_attempt(self.intent['operation_id'])['status'],'unknown')
        self.f.git('push','origin',self.result+':refs/heads/main')
        with mock.patch.object(project_lane_git.GitLaneIntegrationPublisher,'_push_cas',side_effect=AssertionError('replay')):self.assertTrue(self.publish(self.publisher())['conditional_update'])
    def test_prepared_but_unsent_attempt_does_not_become_proof_from_matching_head(self):
        publisher=self.publisher();publisher._prepare_attempt(self.item,self.intent)
        self.f.git('push','origin',self.result+':refs/heads/main')
        evidence=self.publish(publisher);self.assertFalse(evidence['conditional_update']);self.assertEqual(evidence['publication_attempt_state'],'prepared')
    def test_submitted_marker_without_push_outcome_does_not_become_conditional_proof(self):
        publisher=self.publisher();publisher._prepare_attempt(self.item,self.intent);publisher._transition_attempt(self.item,self.intent,'submitted',{'prepared'})
        original=self.store.read();self.f.git('push','origin',self.result+':refs/heads/main')
        evidence=self.publish(publisher);self.assertFalse(evidence['conditional_update']);self.assertEqual(evidence['publication_attempt_state'],'submitted');self.assertEqual(self.store.read(),original)
    def test_legacy_matching_unknown_observation_does_not_gain_conditional_authority(self):
        publisher=self.publisher();publisher._prepare_attempt(self.item,self.intent);publisher._transition_attempt(self.item,self.intent,'submitted',{'prepared'});publisher._transition_attempt(self.item,self.intent,'unknown',{'submitted'})
        self.f.git('push','origin',self.result+':refs/heads/main');original=self.store.read()
        legacy=project_lane_git.GitLaneIntegrationPublisher(self.f.repo,'origin','refs/heads/main',self.f.store_id,attempt_store=self.store)
        evidence=self.publish(legacy);self.assertFalse(evidence['conditional_update']);self.assertEqual(evidence['publication_attempt_state'],'unknown');self.assertEqual(self.store.read(),original)
    def test_attempt_from_other_operation_or_result_is_not_reused(self):
        publisher=self.publisher()
        for bad in (dict(self.intent,operation_id='changed-key'),dict(self.intent,lane_id='changed-lane'),dict(self.intent,result_commit=self.f.base)):
            with self.subTest(bad=bad),self.assertRaises(ValueError):publisher(self.item,self.integrator,bad)
        self.assertIsNone(self.store.read()[0]);self.assertEqual(self.f.remote_head(),self.f.base)
    def test_native_handle_cannot_borrow_another_source_lease_or_journal(self):
        import copy
        from git_lease_store import GitLeaseStore
        publisher=self.publisher();original=self.store.read()
        badlease=GitLeaseStore(self.f.repo,'origin','refs/heads/cdc/substitute-lease');publisher.quarantine_store=badlease
        with self.assertRaisesRegex(ValueError,'substituted'):self.publish(publisher)
        publisher=self.publisher();publisher.attempt_store=GitDocumentStore(self.f.repo,'origin','refs/heads/cdc/substitute-journal',self.f.store_id)
        with self.assertRaisesRegex(ValueError,'custody'):self.publish(publisher)
        publisher=self.publisher();publisher.source_ref='refs/heads/alternate';self.f.git('push','origin',self.f.base+':refs/heads/alternate')
        with self.assertRaisesRegex(ValueError,'custody'):self.publish(publisher)
        publisher=self.publisher();publisher.native_handle['handle_id']='missing-handle'
        with self.assertRaises(ValueError):self.publish(publisher)
        self.assertEqual(self.store.read(),original);self.assertEqual(self.f.remote_head(),self.f.base)
    def test_canonical_custody_absence_and_endpoint_drift_block_transport(self):
        publisher=self.publisher();self.f.git('push','origin',':'+self.f.lease_store.ref)
        with self.assertRaisesRegex(ValueError,'custody missing'):self.publish(publisher)
        self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])
    def test_forged_session_context_cannot_redirect_original_native_source(self):
        import json,managed_host_bridge as bridge
        path=bridge._session_path(str(self.f.root/'handles'),self.handle['handle_id']);original=path.read_bytes()
        session=json.loads(original);session['lease_source_ref']='refs/heads/alternate';session['context_digest']=bridge._digest(bridge._session_context(session));path.write_text(json.dumps(session))
        try:
            publisher=self.publisher();publisher.source_ref='refs/heads/alternate'
            with self.assertRaises(ValueError):self.publish(publisher)
            self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])
        finally:path.write_bytes(original)
    def test_another_live_controller_cannot_borrow_original_owned_handle(self):
        import sys
        code="""import sys
sys.path.insert(0,sys.argv[1]);import managed_host_bridge as b
s=b._load_session(sys.argv[2],sys.argv[3])
try:b._publish(s,sys.argv[4])
except ValueError:print('rejected');sys.exit(0)
sys.exit(1)
"""
        observed=subprocess.run([sys.executable,'-B','-c',code,str(Path(__file__).resolve().parents[1]/'scripts'),str(self.f.root/'handles'),self.handle['handle_id'],self.result],capture_output=True,text=True,timeout=20)
        self.assertEqual(observed.returncode,0,observed.stderr);self.assertEqual(observed.stdout.strip(),'rejected')
        self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])
    def test_consumed_pool_authority_cannot_send_with_old_native_handle(self):
        import managed_host_bridge as bridge,managed_executor_pool as pool
        runtime=bridge._runtime(self.session);revision,state=runtime.store.read()
        failed=pool.fail_attempt(runtime.plan,state,self.session['task_id'],self.session['attempt_id'],terminal_status='failed',reservation_token=self.session['reservation_token'],expected_revision=state['revision'])
        runtime.store.compare_and_swap(revision,failed)
        with self.assertRaisesRegex(ValueError,'running pool authority'):self.publish(self.publisher())
        self.assertEqual(self.f.remote_head(),self.f.base);self.assertIsNone(self.store.read()[0])
    def concurrent_commit(self):
        self.f.git('checkout','-q','--detach',self.f.base);(self.f.repo/'concurrent').write_text('other');self.f.git('add','concurrent');self.f.git('commit','-qm','concurrent');return self.f.git('rev-parse','HEAD')
    def test_concurrent_remote_move_during_cas_is_rejected_without_overwrite(self):
        concurrent=self.concurrent_commit()
        class Racing(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(inner,*args):self.f.git('push','origin',concurrent+':refs/heads/main');return super()._push_cas(*args)
        with self.assertRaisesRegex(ValueError,'rejected'):self.publish(self.publisher(Racing))
        self.assertEqual(self.f.remote_head(),concurrent);self.assertEqual(self.publisher().publication_attempt(self.intent['operation_id'])['status'],'rejected')
        self.f.git('push','origin',self.result+':refs/heads/object-seed');subprocess.run(['git','--git-dir',str(self.f.remote),'update-ref','refs/heads/main',self.result],check=True)
        evidence=self.publish(self.publisher());self.assertFalse(evidence['conditional_update']);self.assertEqual(evidence['publication_attempt_state'],'rejected')
    def test_integration_publisher_rejects_remote_head_movement_without_overwrite(self):
        concurrent=self.concurrent_commit();self.f.git('push','origin',concurrent+':refs/heads/main')
        with self.assertRaisesRegex(ValueError,'moved'):self.publish(self.publisher())
        self.assertEqual(self.f.remote_head(),concurrent);self.assertIsNone(self.store.read()[0])


if __name__ == '__main__':unittest.main()
