"""Separate claim-null source UNKNOWN quarantine; serialized proof is no grant."""
import copy
import importlib
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from test_submission_recovery import fixture,NOW,REV
import execution_lease_v2 as lease
import operation_intent as op
from git_lease_store import validate_coordination_transition


def source_fixture(backend="local_command"):
    record,_=fixture('not_submitted');guard=record['external_guard']
    binding=copy.deepcopy(guard['intent']['binding']);binding.update(backend=backend,mode='writer')
    intent=op.prepare(binding,'source-one',record['source_ref'],'2026-10-04T17:00:00Z')
    receipt=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc'])
    intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
    guard.update(intent=intent,operation_key=intent['operation_key'],intent_digest=op._hash(intent),submission_claim=None)
    record['submission_claims']=[];lease.validate(record)
    proof={'schema':'source-publication-quarantine-proof/v1','lease_revision':REV,'lease_digest':op._hash(record),'guard_digest':op._hash(guard),'original_lease_revision':REV,'repository':record['repository'],'source_ref':record['source_ref'],'original_release':copy.deepcopy(record['last_release']),'request_ref':'sha256:'+'1'*64,'handle_id':'handle-one','publication':{'operation_id':'publish-one','attempt_id':'publish-attempt-one','observed_shared_head':'b'*40,'intended_integrated_head':binding['candidate_sha'],'result_commit':binding['candidate_sha'],'status':'submitted','remote_id':'sha256:'+'2'*64,'shared_ref':record['source_ref']},'observed_head':'c'*40,'terminal':{'ownership':{'owner_id':record['last_release']['owner_id'],'generation':record['generation'],'invocation_id':record['last_release']['invocation_id']},'request_ref':'sha256:'+'1'*64,'status':'succeeded'},'trusted_contract':{},'observed_at_utc':NOW}
    return record,proof

class SourceTests(unittest.TestCase):
    def api(self):
        try:return importlib.import_module('source_publication_quarantine')
        except ModuleNotFoundError:self.fail('distinct native source publication UNKNOWN quarantine missing')
    def test_claim_null_guard_archived_without_inventing_claim_wait_or_cas(self):
        m=self.api();record,proof=source_fixture();new=m.quarantine_source_guard(record,proof,'git:'+'4'*40,NOW)
        entry=new['submission_retirements'][0];self.assertEqual(entry['schema'],'source-publication-quarantine/v1');self.assertEqual(entry['outcome'],'UNKNOWN');self.assertIsNone(entry['guard']['submission_claim']);self.assertIsNone(new['external_guard'])
        for key in record.keys()-{'external_guard'}:self.assertEqual(new[key],record[key])
        with self.assertRaises(ValueError):validate_coordination_transition(record,new,expected_revision=REV)
        replay=copy.deepcopy(new);replay['external_guard']=copy.deepcopy(record['external_guard'])
        with self.assertRaises(ValueError):lease.validate(replay)
    def test_changed_guard_lease_release_or_matching_old_expected_head_rejected(self):
        m=self.api();record,proof=source_fixture()
        for field,value in [('lease_digest','sha256:'+'0'*64),('guard_digest','sha256:'+'0'*64),('original_release',None),('observed_head',proof['publication']['observed_shared_head'])]:
            bad=copy.deepcopy(proof);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):m.quarantine_source_guard(record,bad,'git:'+'4'*40,NOW)
    def test_unrelated_provider_guard_cannot_use_git_source_quarantine(self):
        m=self.api();record,proof=source_fixture(backend='github-actions')
        with self.assertRaises(ValueError):m.quarantine_source_guard(record,proof,'git:'+'4'*40,NOW)

    def test_serialized_terminal_and_arbitrary_store_cannot_mint_quarantine(self):
        m=self.api();record,proof=source_fixture()
        with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(object(),terminal_proof=proof['terminal'],publication_store=object(),source_remote='origin',trusted_contract={},at=NOW)

if __name__=='__main__':unittest.main()

class NativeSourceTests(unittest.TestCase):
    def setUp(self):
        from test_managed_host_bridge import ManagedHostBridgeTests
        self.fixture=ManagedHostBridgeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def native(self,interrupted=False):
        import json,subprocess
        import managed_host_bridge as bridge
        f=self.fixture;path=f.root/'start.json';path.write_text(json.dumps(f.start_request()));output=f.root/'finished.json'
        code=f.root/'controller.py'
        code.write_text('''import json,sys,time,copy
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
import managed_host_bridge as b,execution_lease_v2 as l,operation_intent as op
from project_lane_git import GitLaneIntegrationPublisher
r=json.loads(Path(sys.argv[3]).read_text());h=b.start(r);s=b._load_session(r['handle_root'],h['handle_id']);rt=b._runtime(s);store=b._lease_store(s)
interrupted=sys.argv[5]=='interrupted'
end=time.monotonic()+8
while time.monotonic()<end:
 if rt.observe(s['task_id'],s['attempt_id'])['status']=='awaiting_release':break
 time.sleep(.01)
s['worker_status']='succeeded';result,_,_=b._result(s,rt)
binding={'repository':s['lease_repository'],'candidate_sha':result,'backend':'local_command','mode':'writer','environment_id':'fixture','check_suite_fingerprint':'sha256:'+'1'*64,'environment_fingerprint':'sha256:'+'2'*64,'check_plan_digest':'sha256:'+'3'*64}
i=op.prepare(binding,'original-source',s['lease_source_ref'],b._utc());rec=op.verify_readback(i,copy.deepcopy(i),'fixture:durable',b._utc());i=op.transition(i,'submitting',b._utc(),receipt=rec)
actual=GitLaneIntegrationPublisher._push_cas
def lost(self,*args):actual(self,*args);raise SystemExit('transport reply lost')
GitLaneIntegrationPublisher._push_cas=lost
try:b._publish(s,result)
except SystemExit:pass
# The send was admitted while unguarded. Its lost reply is then durably
# preserved, as an old submitted journal may already be under an UNKNOWN guard.
rev,row=store.read();row=l.set_guard(row,s['owner_id'],s['generation'],s['invocation_id'],b._utc(),i,'fixture:durable');rev=store.compare_and_swap(rev,row)
if not interrupted:
 s.update(result_commit=result,publication=None,state='published');b._save_session(s)
rev,row=store.read();owner=(s['owner_id'],s['generation'],s['invocation_id']);cp='fixture:checkpoint'
row=l.begin_finalization(row,*owner,b._utc(),pending_shared_writes=False);rev=store.compare_and_swap(rev,row)
row=l.record_checkpoint(row,*owner,b._utc(),checkpoint_ref=cp,pending_shared_writes=False);rev=store.compare_and_swap(rev,row)
row=l.reconcile_finalization(row,*owner,b._utc(),external_reconciliation='unknown_preserved');rev=store.compare_and_swap(rev,row)
continuity=b._continuity(s,result,cp,None,released=False)
row=l.mark_ready(row,*owner,b._utc(),continuity_state=continuity);rev=store.compare_and_swap(rev,row)
receipt=rt.release_execution_lease(store,rev,s['lease_repository'],s['lease_source_ref'],*owner,s['task_id'],s['attempt_id'],b._utc())['release_receipt']
if not interrupted:
 s.update(state='released',release_receipt=receipt,lease_revision=receipt['lease_revision']);b._save_session(s)
b._wait_terminal(rt,s);b._complete_pool(s,rt,result,['out:closure'],['test:closure'])
Path(sys.argv[4]).write_text(json.dumps({'handle':h,'release_receipt':receipt}))
''')
        p=subprocess.run([sys.executable,'-B',str(code),str(ROOT/'scripts'),str(ROOT/'tests'),str(path),str(output),'interrupted' if interrupted else 'saved'],capture_output=True,timeout=40)
        self.assertEqual(p.returncode,0,p.stderr.decode())
        data=json.loads(output.read_text());session=bridge._load_session(str(f.root/'handles'),data['handle']['handle_id'])
        if interrupted:
            # The controller never saved either informational result or release.
            # Only supported observation reconciles the authentic runtime release.
            self.assertIsNone(session['result_commit']);self.assertIsNone(session['release_receipt'])
            observed=bridge.observe({'schema':'managed-host-observe/v1','handle_root':str(f.root/'handles'),'handle_id':data['handle']['handle_id']})
            self.assertTrue(observed['quiescent']);self.assertFalse(observed['lease_owned'])
            session=bridge._load_session(str(f.root/'handles'),data['handle']['handle_id'])
            self.assertIsNone(session['result_commit']);self.assertEqual(session['release_receipt'],data['release_receipt'])
        runtime=bridge._runtime(session)
        native=runtime.verify_terminal(session['task_id'],session['attempt_id'],include_controller=True,lease_store=f.lease_store,release_receipt=data['release_receipt'])
        from git_document_store import GitDocumentStore
        publication=GitDocumentStore(f.repo,'origin',session['publication_ref'],f.store_id)
        p_rev,doc=publication.read();operation,next_entry=next(iter(doc['attempts'].items()));rev,row=f.lease_store.read()
        pins={'lease_revision':rev,'lease_digest':op._hash(row),'original_lease_revision':rev,'handle_root':str(f.root/'handles'),'handle_id':session['handle_id'],'request_ref':native['request_ref'],'publication_revision':p_rev,'publication_digest':op._hash(next_entry),'operation_id':operation,'source_remote_id':f.store_id,'control_store_id':f.store_id,'owner_decision':{'action':'quarantine_source_unknown_without_replay','guard_digest':op._hash(row['external_guard']),'reference':'sha256:'+'5'*64},'publication_processes':[{'pid':99999993,'birth':'123','boot_id':native['boot_id']}]}
        return f,native,publication,pins

    def test_interrupted_result_cache_uses_fresh_native_accepted_result_without_repair(self):
        import managed_host_bridge as bridge
        m=SourceTests().api();f,native,publication,pins=self.native(interrupted=True)
        session_path=bridge._session_path(pins['handle_root'],pins['handle_id']);session_bytes=session_path.read_bytes()
        original_publication=publication.read();original_source=f.remote_head();original_lease=f.lease_store.read()
        capability=m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=bridge._utc())
        self.assertEqual(session_path.read_bytes(),session_bytes)
        self.assertEqual(capability.proof['publication']['result_commit'],original_source)
        self.assertEqual(capability.proof['terminal']['status'],'succeeded')
        result=m.quarantine_source_publication_cas(f.lease_store,pins['lease_revision'],capability,'sha256:'+'6'*64,bridge._utc())
        self.assertEqual(result['outcome'],'UNKNOWN');self.assertFalse(result['conditional_update'])
        self.assertEqual(result['record']['submission_retirements'][0]['guard'],original_lease[1]['external_guard'])
        self.assertEqual(publication.read(),original_publication);self.assertEqual(f.remote_head(),original_source)
        self.assertEqual(session_path.read_bytes(),session_bytes)

    def test_interrupted_cache_cannot_replace_result_acceptance_or_original_release(self):
        import json,managed_host_bridge as bridge
        m=SourceTests().api();f,native,publication,pins=self.native(interrupted=True)
        session=bridge._load_session(pins['handle_root'],pins['handle_id']);runtime=bridge._runtime(session)
        path=bridge._session_path(pins['handle_root'],pins['handle_id']);original_session=path.read_bytes()
        def authenticate():return m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=bridge._utc())
        for field,value in [('result_commit',f.base),('release_receipt',None)]:
            changed=copy.deepcopy(session);changed[field]=value;path.write_text(json.dumps(changed))
            try:
                with self.subTest(field=field),self.assertRaises(ValueError):authenticate()
            finally:path.write_bytes(original_session)
        request=runtime._request(session['task_id'],session['attempt_id']);result_path=Path(request['journal_directory'])/'result.json';original_result=result_path.read_bytes()
        changed=json.loads(original_result);changed['result_commit']=f.base;result_path.write_text(json.dumps(changed))
        try:
            with self.assertRaisesRegex(ValueError,'actual accepted/integrated'):authenticate()
        finally:result_path.write_bytes(original_result)
        revision,state=runtime.store.read();unintegrated=copy.deepcopy(state);unintegrated['revision']+=1
        next(row for row in unintegrated['tasks'] if row['id']==session['task_id'])['integrated']=False
        runtime.store.compare_and_swap(revision,unintegrated)
        with self.assertRaisesRegex(ValueError,'actual accepted/integrated'):authenticate()
        self.assertIsNotNone(f.lease_store.read()[1]['external_guard'])
        self.assertEqual(publication.read()[1]['attempts'][pins['operation_id']]['status'],'submitted')

    def test_interrupted_result_tampering_after_fresh_proof_is_rejected(self):
        import json,managed_host_bridge as bridge
        from unittest.mock import patch
        m=SourceTests().api();f,native,publication,pins=self.native(interrupted=True)
        session=bridge._load_session(pins['handle_root'],pins['handle_id']);runtime=bridge._runtime(session)
        path=Path(runtime._request(session['task_id'],session['attempt_id'])['journal_directory'])/'result.json'
        original=path.read_bytes();actual=native.revalidate_for
        def changed_after_verification(*args):
            evidence=actual(*args);changed=json.loads(original)
            # Even a changed evidence field with the same candidate cannot
            # borrow acceptance of the original native result digest.
            changed['evidence_refs']=['fixture:substituted-evidence'];path.write_text(json.dumps(changed))
            return evidence
        try:
            with patch.object(native,'revalidate_for',side_effect=changed_after_verification):
                with self.assertRaisesRegex(ValueError,'exact native accepted/integrated result'):
                    m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=bridge._utc())
        finally:path.write_bytes(original)
        self.assertIsNotNone(f.lease_store.read()[1]['external_guard'])
        self.assertEqual(publication.read()[1]['attempts'][pins['operation_id']]['status'],'submitted')
    def test_missing_or_substituted_custody_never_sends(self):
        from project_lane_git import GitLaneIntegrationPublisher
        from git_document_store import GitDocumentStore
        from git_lease_store import GitLeaseStore
        from project_lanes import LaneClaim,LaneKind
        f,native,publication,pins=self.native();candidate=publication.read()[1]['attempts'][pins['operation_id']]['result_commit']
        f.git('push','origin',f.base+':refs/heads/alternate')
        fresh=GitDocumentStore(f.repo,'origin','refs/heads/cdc/substitute-journal',f.store_id)
        integrator=LaneClaim('integrator','invocation',LaneKind.INTEGRATOR,f.base,str(f.repo),'alternate',executor_id='integrator',role='integrator')
        item={'lane_id':'new-lane','result_commit':candidate};intent=dict(item,operation_id='changed-key',observed_shared_head=f.base,intended_integrated_head=candidate)
        for store in (None,GitLeaseStore(f.repo,'origin','refs/heads/cdc/substitute-lease')):
            with self.subTest(omitted=store is None):
                publisher=GitLaneIntegrationPublisher(f.repo,'origin','refs/heads/alternate',f.store_id,attempt_store=fresh,quarantine_store=store)
                with self.assertRaises(ValueError):publisher(item,integrator,intent)
                self.assertEqual(f.git('ls-remote','origin','refs/heads/alternate').split()[0],f.base)

    def test_genuine_unicode_native_request_and_source_quarantine(self):
        import managed_host_bridge as bridge
        self.fixture.plan['tasks'][0]['worktree']='managed-worktrees/über-worker'
        f,native,publication,pins=self.native()
        from managed_executor_runtime import _digest
        request=bridge._runtime(bridge._load_session(pins['handle_root'],pins['handle_id']))._request(native['task_id'],native['attempt_id'])
        self.assertIn('über-worker',request['cwd'])
        self.assertEqual(native['request_ref'],_digest(request));self.assertNotEqual(native['request_ref'],op._hash(request))
        capability=SourceTests().api().authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=bridge._utc())
        result=SourceTests().api().quarantine_source_publication_cas(f.lease_store,pins['lease_revision'],capability,'sha256:'+'6'*64,bridge._utc())
        self.assertEqual(result['outcome'],'UNKNOWN')

    def test_real_native_claim_null_quarantine_and_lost_reply_observation(self):
        import managed_host_bridge as bridge
        m=SourceTests().api();f,native,publication,pins=self.native();at=bridge._utc()
        capability=m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=at)
        public=capability.proof;original_terminal=copy.deepcopy(public['terminal']);public['terminal']['ownership']['owner_id']='forged-owner'
        self.assertEqual(capability.proof['terminal'],original_terminal,'sealed source evidence must not retain caller mutations')
        self.assertGreater(capability.proof['observed_at_utc'],at,'source physical/readback observation must use actual observation completion time')
        at=bridge._utc()
        original=f.lease_store.compare_and_swap;calls=[]
        def lost(expected,row,**kw):calls.append(expected);original(expected,row,**kw);raise OSError('reply lost')
        f.lease_store.compare_and_swap=lost
        with self.assertRaises(OSError):m.quarantine_source_publication_cas(f.lease_store,pins['lease_revision'],capability,'sha256:'+'6'*64,at)
        observed=m.observe_source_publication_quarantine(f.lease_store,operation_key=capability._store.read()[1]['submission_retirements'][0]['guard']['operation_key'],evidence_reference='sha256:'+'6'*64)
        self.assertEqual(observed['outcome'],'UNKNOWN');self.assertFalse(observed['conditional_update']);self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):m.quarantine_source_publication_cas(f.lease_store,pins['lease_revision'],capability,'sha256:'+'6'*64,at)
        self.assertEqual(len(calls),1)
        self.assertEqual(publication.read_revision(pins['publication_revision'])['attempts'][pins['operation_id']]['status'],'submitted')
    def test_publisher_rejects_original_candidate_under_new_ref_and_operation(self):
        import managed_host_bridge as bridge
        from project_lane_git import GitLaneIntegrationPublisher
        m=SourceTests().api();f,native,publication,pins=self.native();at=bridge._utc()
        capability=m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=at)
        at=bridge._utc()
        m.quarantine_source_publication_cas(f.lease_store,pins['lease_revision'],capability,'sha256:'+'6'*64,at)
        candidate=capability.proof['publication']['result_commit']
        publisher=GitLaneIntegrationPublisher(f.repo,'origin','refs/heads/other',f.store_id,attempt_store=publication,quarantine_store=f.lease_store,native_handle={'handle_root':pins['handle_root'],'handle_id':pins['handle_id']})
        from project_lanes import LaneClaim,LaneKind
        integrator=LaneClaim('integrator','new-invocation',LaneKind.INTEGRATOR,f.base,str(f.repo),'main',executor_id='integrator',role='integrator')
        item={'lane_id':'new-lane','result_commit':candidate};intent={'operation_id':'new-id','lane_id':'new-lane','result_commit':candidate,'observed_shared_head':f.base,'intended_integrated_head':candidate}
        with self.assertRaisesRegex(ValueError,'quarantined'):publisher(item,integrator,intent)
        # A distinct corrective source uses a new genuinely issued native handle,
        # fresh ownership, canonical journal and one-use expected-head publication.
        request=f.start_request();plan=copy.deepcopy(request['plan'])
        plan.update(pool_id='corrective-pool',coordination_ref='refs/heads/cdc/corrective-pool',base_sha=candidate)
        plan['tasks'][0].update(id='corrective-task',branch='cdc/corrective-worker',worktree='managed-worktrees/corrective-worker')
        request.update(owner_id='88888888-8888-4888-8888-888888888888',plan=plan,task_id='corrective-task',attempt_id='corrective-a1',reservation_token='corrective-reservation',argv=[sys.executable,'-c',"from pathlib import Path; import subprocess; Path('docs/correction.txt').write_text('corrective'); subprocess.run(['git','add','docs/correction.txt'],check=True); subprocess.run(['git','commit','-qm','distinct correction'],check=True)"])
        newhandle=bridge.start(request);f.wait_for(newhandle,'awaiting_release')
        session=bridge._load_session(request['handle_root'],newhandle['handle_id']);corrective,_,_=bridge._result(session,bridge._runtime(session))
        self.assertNotEqual(corrective,candidate);evidence=bridge._publish(session,corrective)
        self.assertTrue(evidence['conditional_update']);self.assertEqual(f.remote_head(),corrective)
        self.assertEqual(f.lease_store.read()[1]['submission_retirements'][0]['outcome'],'UNKNOWN')

    def test_native_serialization_live_sender_endpoint_and_journal_drift_fail_closed(self):
        import managed_host_bridge as bridge
        import os
        m=SourceTests().api();f,native,publication,pins=self.native();at=bridge._utc()
        with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=dict(native),publication_store=publication,source_remote='origin',trusted_contract=pins,at=at)
        bad=copy.deepcopy(pins);bad['publication_processes'][0]['pid']=os.getpid()
        with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=bad,at=at)
        bad=copy.deepcopy(pins);bad['publication_digest']='sha256:'+'0'*64
        with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=bad,at=at)
        import json
        session_path=bridge._session_path(pins['handle_root'],pins['handle_id']);session=json.loads(session_path.read_text());original=copy.deepcopy(session)
        session['result_commit']=f.base;session_path.write_text(json.dumps(session))
        try:
            with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=at)
        finally:session_path.write_text(json.dumps(original))
        revision,document=publication.read();document['attempts'][pins['operation_id']]['status']='confirmed';document['attempts'][pins['operation_id']]['resolved_at_utc']=at;publication.compare_and_swap(revision,document)
        with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=at)
        other=f.root/'other.git';f.git('init','--bare',str(other));f.git('remote','set-url','origin',str(other))
        with self.assertRaises(ValueError):m.authenticate_source_publication_quarantine(f.lease_store,terminal_proof=native,publication_store=publication,source_remote='origin',trusted_contract=pins,at=at)
        f.git('remote','set-url','origin',str(f.remote))
