"""Changed-risk offline prehandle custody over actual local Git CAS stores."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import unknown_recovery as native
from git_document_store import canonical


class PrehandleTests(unittest.TestCase):
    legacy_guardian = False

    def setUp(self):
        from test_native_unknown_recovery import IntakeTests
        self.fixture=IntakeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store;self.source=self.fixture.source;self.root=self.fixture.root
        self.row=copy.deepcopy(self.fixture.row)
        if not self.legacy_guardian:
            self.row['operation']['start_consumption']={'schema':'native-intake-start-consumption/v1',
                'contract_digest':native._contract(self.row),'controller':dict(self.fixture.pins['creator'])}
        if self.legacy_guardian:
            self.row['operation']['guardian']['nonce']='a'*32
            self.fixture.git('push','origin',':'+self.store.ref)
            self.fixture.rev=self.store.compare_and_swap(None,{'schema':native.INTAKE_SCHEMA,'tasks':{'task-one':self.row}})
        else:
            self.row['operation']['controller_identity']=dict(self.fixture.pins['creator'])
            self.row['operation']['controllers']=[dict(self.fixture.pins['creator'])]
        self.document={'schema':native.INTAKE_SCHEMA,'tasks':{'task-one':self.row}}
        self.head=self.raw_commit(self.document,self.fixture.rev)
        self.at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        physical={'path':str(self.root/'root-certificate.json'),'sha256':'sha256:'+'0'*64,
            'controller_root':str(self.root/'controllers'),'worker_launch_root':str(self.root/'launch'),
            'controller_uid':os.getuid(),'controller_gid':os.getgid(),'worker_uid':os.getuid()+1,'worker_gid':os.getgid()+1}
        self.pins={'original_revision':self.head,'row_digest':native.op._hash(self.row),
            'source_revision':self.fixture.srev,'source_digest':native.op._hash(self.source.read()[1]),
            'owner_decision_reference':'fixture-owner-actual-cancel-authority','physical':physical,
            'channels':{'intake_store_id':self.store.store_id,'intake_ref':self.store.ref,
                'lease_store_id':self.source.store_id,'lease_ref':self.source.ref,
                'pool_store_id':self.source.store_id,'pool_ref':self.fixture.req['plan']['coordination_ref']}}
        # This unprivileged fixture preserves the exact root-reader request and
        # exercises its byte/custody checks with the fixture file's real UID.
        read=native._protected_json
        def certificate_reader(path,digest,*,uid,gid,mode):
            self.assertEqual((str(path),uid,gid,mode),(physical['path'],0,os.getgid(),0o640))
            return read(path,digest,uid=os.getuid(),gid=gid,mode=mode)
        self.addCleanup(patch.stopall)
        patch.object(native,'_protected_json',side_effect=certificate_reader).start()
        if self.legacy_guardian:self.write_legacy_exit()
        self.write_certificate()

    def write_legacy_exit(self):
        root=self.root/"controllers"/"task-one";nonce=self.row["operation"]["guardian"]["nonce"]
        identity=dict(self.fixture.pins["creator"],pid=99999993)
        stderr=(b"CDC_VPS_ORIGINAL_CONTROLLER_RECONCILIATION_REQUIRED\n"
            b"CDC_VPS_REJECTION_CODE=CONTRACT_OR_SCOPE_REJECTED\n"
            b'CDC_VPS_REJECTION_SITE={"module":"cdc_vps.state","function":"_validate_retired_once","line":192,"type":"ValueError"}\n')
        streams={"stdout":b"","stderr":stderr,"guardian.stdout":b"","guardian.stderr":b""}
        for suffix,data in streams.items():
            path=root/(nonce+"."+suffix);path.write_bytes(data);path.chmod(0o600)
        receipt={"schema":"cdc-vps-controller-wait/v1","task_id":"task-one",
            "identity":self.row["operation"]["guardian"]["identity"],"controller":identity,"exit_code":2,"observed_at_utc":self.at}
        for label in ("stdout","stderr"):
            receipt[label+"_path"]=str(root/(nonce+"."+label));receipt[label+"_sha256"]=hashlib.sha256(streams[label]).hexdigest()
        path=root/(nonce+".receipt.json");path.write_text(json.dumps(receipt));path.chmod(0o600)

    def raw_commit(self,document,parent):
        blob=self.store._git('hash-object','-w','--stdin',input_text=canonical(document))
        tree=self.store._git('mktree',input_text=f'100644 blob {blob}\tdocument.json\n')
        revision=self.store._git('commit-tree',tree,'-p',parent,input_text='changed-risk fixture\n')
        self.fixture.git('push','origin',revision+':'+self.store.ref)
        return revision

    def write_certificate(self,changes=None):
        controller=self.root/'controllers'/'task-one';launch=self.root/'launch'/'executor-one'/'task-one'
        artifacts={}
        for root in (controller,launch):
            for path in root.rglob('*'):
                if path.is_file():
                    info=path.stat();artifacts[str(path)]={'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),
                        'uid':info.st_uid,'gid':info.st_gid,'mode':info.st_mode&0o7777}
        self.evidence={'schema':'native-prehandle-physical/v1','task_id':'task-one','attempt_id':self.row['operation']['attempt_id'],
            'start_request_digest':native._contract(self.row),'original_revision':self.pins['original_revision'],
            'original_row_digest':self.pins['row_digest'],'intake_store_id':self.store.store_id,'intake_ref':self.store.ref,
            'source_store_id':self.source.store_id,'source_ref':self.source.ref,'source_revision':self.pins['source_revision'],
            'source_digest':self.pins['source_digest'],'boot_id':native._boot(),'observed_at_utc':self.at,
            'owner_decision_reference':self.pins['owner_decision_reference'],'disposition':native._prehandle_original(self.row),
            'controller_root':str(controller),'worker_launch_root':str(launch),'native_session_absent':True,
            'worker_output_empty':True,'pending_shared_commands':False,'service_stopped':True,'socket_stopped':True,'projects_paused':True,
            'known_births':native._recorded_births(self.row['operation']),
            'producer_scope':{'worker_uid':self.pins['physical']['worker_uid'],'launch_root':str(launch),'cwd':str(launch/'worktree'),
                'pid_namespace':os.readlink('/proc/self/ns/pid'),'cgroups':['/fixture-service'],
                'all_worker_uid_processes_checked':True,'cwd_namespace_processes_checked':True,'cgroups_checked':True,'matching_producers':[]},
            'artifact_pins':artifacts}
        if changes:self.evidence.update(changes)
        self.save_certificate()

    def save_certificate(self):
        path=Path(self.pins['physical']['path']);data=(json.dumps(self.evidence,sort_keys=True)+'\n').encode()
        path.write_bytes(data);path.chmod(0o640)
        self.pins['physical']['sha256']='sha256:'+hashlib.sha256(data).hexdigest()

    def proof(self):
        return native.authenticate_prehandle_intake(self.store,'task-one',source_store=self.source,trusted_contract=self.pins,at=self.at)

    def dispose(self,proof=None):
        return native.dispose_prehandle_intake_cas(self.store,self.head,'task-one',self.proof() if proof is None else proof,at=self.at)

    def make_reserved(self):
        self.row=copy.deepcopy(self.fixture.row);self.row['state']='reserved';self.row['operation'].pop('guardian')
        self.row['budget']['events']=self.row['budget']['events'][:1]
        # Start the isolated reserved fixture from a separate original lineage.
        self.fixture.git('push','origin',':'+self.store.ref)
        self.document={'schema':native.INTAKE_SCHEMA,'tasks':{'task-one':self.row}}
        self.head=self.store.compare_and_swap(None,self.document)
        self.pins.update(original_revision=self.head,row_digest=native.op._hash(self.row))
        self.write_certificate()

    def test_consumed_disposition_preserves_exact_unknown_operation_and_budget(self):
        result=self.dispose();row=result['row'];entry=row['result']['administrative_disposition']
        self.assertEqual(row['state'],'retired_unknown');self.assertEqual(row['operation'],self.row['operation']);self.assertEqual(row['budget'],self.row['budget'])
        self.assertEqual(entry['original_row'],self.row);self.assertEqual(entry['original_effect'],'UNKNOWN');self.assertIsNone(entry['actual_wait']);self.assertTrue(entry['replay_forbidden'])
        self.assertEqual(native.validate_intake_dispositions(self.store,result['revision'],{'task-one':row},{})['task-one'],entry)
        self.assertIsInstance(native.validate_prelaunch_disposition(self.store,'task-one'),dict)
        with self.assertRaises(ValueError):self.dispose()

    def test_reserved_cancellation_preserves_reservations_and_full_operation(self):
        self.make_reserved();result=self.dispose();row=result['row'];entry=native.validate_queued_cancellation(row)
        self.assertEqual(row['state'],'cancelled');self.assertEqual(row['operation'],self.row['operation']);self.assertEqual(row['budget'],self.row['budget'])
        self.assertEqual(entry['original_effect'],'NOT_SENT');self.assertTrue(entry['no_send']);self.assertEqual(entry['original_row'],self.row)
        self.assertTrue(native.validate_queued_cancellations(self.store,result['revision'],{'task-one':row}))
        with self.assertRaises(ValueError):native.assert_intake_start_allowed(self.store,'task-one',native._contract(self.row))

    def test_old_unconsumed_and_postlaunch_apis_cannot_authorize_consumed_prehandle(self):
        with self.assertRaises(ValueError):self.fixture.proof()
        with self.assertRaises(ValueError):native.authenticate_postlaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=self.pins,at=self.at)

    def test_missing_stale_future_or_substituted_certificate_denied(self):
        path=Path(self.pins['physical']['path']);original=path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):self.proof()
        path.write_bytes(original);path.chmod(0o640)
        path.write_bytes(original+b' ')
        with self.assertRaises(ValueError):self.proof()
        for delta in (-1801,10):
            self.write_certificate({'observed_at_utc':(datetime.now(timezone.utc)+timedelta(seconds=delta)).isoformat()})
            with self.assertRaises(ValueError):self.proof()

    def test_live_birth_and_missing_or_additional_birth_denied(self):
        for births in ([],self.evidence['known_births']+[{'pid':os.getpid(),'birth':native._process(os.getpid())['birth'],'boot_id':native._boot()}]):
            self.write_certificate({'known_births':births})
            with self.assertRaises(ValueError):self.proof()
        self.write_certificate()
        with patch.object(native,'_identity',side_effect=ValueError('recorded live PID')):
            with self.assertRaises(ValueError):self.proof()

    def test_incomplete_process_scope_live_producer_or_unstopped_service_denied(self):
        for key,value in [('service_stopped',False),('socket_stopped',False),('pending_shared_commands',True),('native_session_absent',False)]:
            self.write_certificate({key:value})
            with self.assertRaises(ValueError):self.proof()
        for key,value in [('matching_producers',[123]),('cgroups_checked',False),('cwd_namespace_processes_checked',False),('all_worker_uid_processes_checked',False)]:
            self.write_certificate();self.evidence['producer_scope'][key]=value;self.save_certificate()
            with self.assertRaises(ValueError):self.proof()

    def test_native_handle_gate_lock_journal_output_and_pool_denied(self):
        _,paths=native._prehandle_native_paths(self.row['operation']['start_request'])
        for path in paths:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
            with self.assertRaises(ValueError):self.proof()
            path.unlink()
        output=self.root/'launch'/'executor-one'/'task-one'/'output'/'result';output.write_text('actual output')
        self.write_certificate()
        with self.assertRaises(ValueError):self.proof()
        output.unlink()
        self.write_certificate()
        self.fixture.git('push','origin','HEAD:'+self.fixture.req['plan']['coordination_ref'])
        with self.assertRaises(ValueError):self.proof()

    def test_owned_guarded_or_pending_source_denied_even_with_matching_digest(self):
        read=self.source.read;revision,lease=read()
        for key,value in [('owner_id',self.fixture.req['owner_id']),('external_guard',{'kind':'unresolved'}),('finalization',{'pending_shared_writes':True})]:
            changed=copy.deepcopy(lease);changed[key]=value;self.pins['source_digest']=native.op._hash(changed);self.write_certificate()
            with patch.object(self.source,'read',return_value=(revision,changed)):
                with self.assertRaises(ValueError):self.proof()

    def test_certificate_and_original_artifact_custody_drift_denied(self):
        path=Path(self.pins['physical']['path']);path.chmod(0o660)
        with self.assertRaises(ValueError):self.proof()
        path.chmod(0o640)
        artifact=self.root/'controllers'/'task-one'/'guardian.lock';artifact.write_text('changed')
        with self.assertRaises(ValueError):self.proof()
        artifact.write_text('');artifact.chmod(0o660);self.write_certificate()
        with self.assertRaises(ValueError):self.proof()

    def test_fake_serialized_mutated_and_reused_capabilities_denied(self):
        proof=self.proof()
        with self.assertRaises(ValueError):self.dispose({'schema':native.PREHANDLE_SCHEMA,'trusted_contract':self.pins})
        proof._pins['owner_decision_reference']='forged'
        with self.assertRaises(ValueError):self.dispose(proof)
        proof=self.proof();result=self.dispose(proof)
        with self.assertRaises(ValueError):native.dispose_prehandle_intake_cas(self.store,result['revision'],'task-one',proof,at=self.at)

    def test_exact_head_and_source_drift_denied_without_second_history_fold(self):
        proof=self.proof()
        with patch.object(native,'_run_history_fold',side_effect=AssertionError('immutable proof verdict must be reused')):
            self.assertEqual(proof.revalidate_for(self.store,'task-one'),self.row)
        document=copy.deepcopy(self.document);document['unrelated']='new head'
        self.store.compare_and_swap(self.head,document)
        with self.assertRaises(ValueError):self.dispose(proof)

    def test_source_revision_drift_denied(self):
        proof=self.proof();self.source.compare_and_swap(self.fixture.srev,self.source.read()[1])
        with self.assertRaises(ValueError):self.dispose(proof)

    def test_raw_dispositions_rearm_and_semantic_replay_denied(self):
        self.make_reserved();proof=self.proof();result=self.dispose(proof);current=self.store.read()[1]
        with self.assertRaises(ValueError):self.store.compare_and_swap(result['revision'],self.document)
        with self.assertRaises(ValueError):self.store.compare_and_swap(result['revision'],dict(current,tasks={}))
        replay=copy.deepcopy(self.row);replay['task']['id']='task-replay';replay['operation']=None;replay['state']='queued';replay['budget']['events']=[]
        current['tasks']['task-replay']=replay
        with self.assertRaises(ValueError):self.store.compare_and_swap(result['revision'],current)
        bad_head=self.raw_commit(current,result['revision'])
        with self.assertRaises(ValueError):native.validate_intake_dispositions(self.store,bad_head,{}, {'task-one':result['row']})
        with self.assertRaises(ValueError):native.assert_new_intake_allowed(self.store,replay['task'])

    def test_history_cannot_erase_original_controller_or_native_handle(self):
        for field,value in [('handle_id','actual-original-native-handle'),('controllers',self.row['operation'].get('controllers',[])+[{'pid':99999989,'birth':'111','boot_id':native._boot()}])]:
            before=copy.deepcopy(self.document);before['tasks']['task-one']['operation'][field]=value
            middle=self.raw_commit(before,self.head);self.head=self.raw_commit(self.document,middle)
            self.pins.update(original_revision=self.head);self.write_certificate()
            with self.assertRaises(ValueError):self.proof()

    def test_reserved_guardian_ancestry_and_late_consumption_deny_cancellation(self):
        self.make_reserved();proof=self.proof();changed=copy.deepcopy(self.document)
        changed['tasks']['task-one']['operation']['guardian']=self.fixture.row['operation']['guardian']
        self.store.compare_and_swap(self.head,changed)
        with self.assertRaises(ValueError):self.dispose(proof)

    def test_taskstore_current_and_cached_full_history_consume_reserved_disposition(self):
        self.make_reserved()
        operation=self.row['operation'];start=operation['start_request'];start['attempt_id']='task-one-a1'
        operation['attempt_id']=start['attempt_id'];operation['start_request_digest']=native.native_digest(start)
        operation['intent']=native.op.prepare(operation['intent']['binding'],start['attempt_id'],start['lease_source_ref'],self.at)
        for event in self.row['budget']['events']:
            event['attempt_id']=start['attempt_id'];event['operation_key']=operation['intent']['operation_key']
        # The real host consumer is a pinned release-qualification fixture,
        # outside the distributed SDK. Runtime/configuration are never loaded.
        fixture_root=Path(__file__).resolve().parents[3]/'bootstrap/fixtures/cdc-taskstore'
        sys.path.insert(0,str(fixture_root))
        self.addCleanup(lambda:sys.path.remove(str(fixture_root)))
        from cdc_taskstore_fixture import state,kimi
        registry={'executors':[{'name':'executor-one'}]}
        queue=importlib.import_module('continuation_queue').initialize('example/project','refs/heads/main')
        self.document={'schema':native.INTAKE_SCHEMA,'registry_digest':state.digest(registry),'created_at_utc':self.at,
            'queue':queue,'tasks':{'task-one':self.row}}
        self.fixture.git('push','origin',':'+self.store.ref)
        self.head=self.store.compare_and_swap(None,self.document)
        self.pins.update(original_revision=self.head,row_digest=native.op._hash(self.row));self.write_certificate()
        result=self.dispose();retired_document=self.store.read()[1]
        with patch.object(state.runtime,'module',side_effect=importlib.import_module),patch.object(state,'validate_registry',side_effect=lambda value,**kw:value),patch.object(kimi,'validate_launch_task',return_value=None):
            taskstore=state.TaskStore(self.store,registry)
            self.assertEqual(taskstore.read()[1]['tasks']['task-one'],result['row'])
            self.assertEqual(taskstore.read()[0],result['revision'])
            replay=copy.deepcopy(self.row);replay['task']['id']='task-replay';replay.update(state='queued',operation=None);replay['budget']['events']=[]
            changed=copy.deepcopy(retired_document);changed['tasks']['task-replay']=replay
            bad_head=self.raw_commit(changed,result['revision']);self.raw_commit(retired_document,bad_head)
            with self.assertRaises(ValueError):taskstore.read()
            with self.assertRaises(ValueError):state.TaskStore(self.store,registry).read()

    def test_raw_serialized_disposition_cannot_initialize_or_mint_transition(self):
        result=self.dispose();from git_document_store import GitDocumentStore
        other=GitDocumentStore(self.store.repo,self.store.remote,'refs/heads/cdc/raw-disposition',self.store.store_id)
        with self.assertRaises(ValueError):other.compare_and_swap(None,{'schema':native.INTAKE_SCHEMA,'tasks':{'task-one':result['row']}})
        changed=self.store.read()[1];changed['tasks']['forged']=copy.deepcopy(result['row'])
        with self.assertRaises(ValueError):self.store.compare_and_swap(result['revision'],changed)

    def test_original_unconsumed_prelaunch_api_still_accepts_its_own_case(self):
        from test_native_unknown_recovery import IntakeTests
        fixture=IntakeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.assertIsInstance(fixture.proof(),native.PrelaunchIntakeDispositionProof)


class LegacyGuardianPrehandleTests(PrehandleTests):
    """Original guardian-only UNKNOWN needs root custody, never invented consumption."""
    legacy_guardian = True

    def test_legacy_unknown_keeps_missing_consumption_and_distinct_truthful_receipt(self):
        result=self.dispose();row=result['row'];entry=row['result']['administrative_disposition']
        self.assertNotIn('start_consumption',row['operation'])
        self.assertIsNone(row['operation']['controller_identity'])
        self.assertNotIn('controllers',row['operation'])
        self.assertEqual(entry['schema'],'legacy-guardian-prehandle-intake-disposition/v1')
        self.assertEqual(entry['reason'],'legacy_guardian_prehandle_unknown')
        self.assertEqual(entry['original_effect'],'UNKNOWN');self.assertFalse(entry['no_send'])
        self.assertEqual(row['operation'],self.row['operation']);self.assertEqual(row['budget'],self.row['budget'])
        self.assertIsInstance(native.validate_prelaunch_disposition(self.store,'task-one'),dict)
        with self.assertRaises(ValueError):native.assert_intake_start_allowed(self.store,'task-one',native._contract(self.row))

    def test_legacy_requires_unknown_and_guardian_without_canonical_controller(self):
        variants=[]
        for state in ('queued','reserved','running','starting','succeeded'):
            changed=copy.deepcopy(self.row);changed['state']=state;variants.append(changed)
        changed=copy.deepcopy(self.row);changed['operation'].pop('guardian');variants.append(changed)
        for key,value in [('controller_identity',self.fixture.pins['creator']),('controllers',[self.fixture.pins['creator']]),('controllers',[])]:
            changed=copy.deepcopy(self.row);changed['operation'][key]=value;variants.append(changed)
        for row in variants:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):native._prehandle_original(row)

    def test_legacy_cannot_erase_real_consumption_from_ancestry(self):
        before=copy.deepcopy(self.document)
        before['tasks']['task-one']['operation']['start_consumption']={
            'schema':'native-intake-start-consumption/v1','contract_digest':native._contract(self.row),
            'controller':dict(self.fixture.pins['creator'])}
        middle=self.raw_commit(before,self.head);self.head=self.raw_commit(self.document,middle)
        self.pins.update(original_revision=self.head);self.write_certificate()
        with self.assertRaises(ValueError):self.proof()

    def test_legacy_missing_or_semantically_substituted_wait_is_denied(self):
        path=self.root/'controllers'/'task-one'/('a'*32+'.receipt.json');original=path.read_bytes()
        path.unlink();self.write_certificate()
        with self.assertRaises(ValueError):self.proof()
        for key,value in [('task_id','other'),('exit_code',0),('identity',self.fixture.pins['creator']),
                          ('controller',self.row['operation']['guardian']['identity'])]:
            receipt=json.loads(original);receipt[key]=value;path.write_text(json.dumps(receipt));path.chmod(0o600)
            self.write_certificate()
            with self.subTest(key=key):
                with self.assertRaises(ValueError):self.proof()

    def test_legacy_live_receipt_controller_and_non_rejection_stderr_are_denied(self):
        path=self.root/'controllers'/'task-one'/('a'*32+'.receipt.json');receipt=json.loads(path.read_text())
        receipt['controller']={'pid':os.getpid(),'birth':native._process(os.getpid())['birth'],'boot_id':native._boot()}
        path.write_text(json.dumps(receipt));self.write_certificate()
        with self.assertRaises(ValueError):self.proof()
        self.write_legacy_exit();stderr=self.root/'controllers'/'task-one'/('a'*32+'.stderr')
        stderr.write_bytes(b'arbitrary application output\n');receipt=json.loads(path.read_text())
        receipt['stderr_sha256']=hashlib.sha256(stderr.read_bytes()).hexdigest();path.write_text(json.dumps(receipt));self.write_certificate()
        with self.assertRaises(ValueError):self.proof()


if __name__=='__main__':unittest.main()
