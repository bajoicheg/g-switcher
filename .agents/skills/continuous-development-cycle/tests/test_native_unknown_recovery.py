"""Anonymized native intake CAS and physical/history fault cases."""
import copy
import hashlib
import json
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_remote_identity import remote_identity
import execution_lease_v2 as lease
import operation_intent as op
from managed_executor_runtime import _digest as native_digest

class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.remote=self.root/'remote.git'
        self.git('init','--bare',str(self.remote),cwd=self.root)
        self.git('init',str(self.repo),cwd=self.root)
        self.git('remote','add','origin',str(self.remote))
        self.store=GitDocumentStore(self.repo,'origin','refs/heads/cdc/intake',remote_identity(self.repo,'origin'))
        self.source=GitLeaseStore(self.repo,'origin','refs/heads/cdc/source-lease')
        self.srev=self.source.compare_and_swap(None,lease.initialize('example/project','refs/heads/main'))
        self.git('config','user.name','CDC fixture');self.git('config','user.email','cdc@example.invalid')
        (self.repo/'seed').write_text('base');self.git('add','seed');self.git('commit','-qm','native intake base');base=self.git('rev-parse','HEAD')
        plan={'schema':'managed-executor-pool-plan/v1','pool_id':'pool-one','change_id':'change-one','parent_invocation_id':'parent-one','base_sha':base,'integrator_id':'integrator-one','coordination_ref':'refs/heads/cdc/pool','coordination_store_id':self.store.store_id,'max_parallel':1,'total_runtime_budget_seconds':30,'total_cost_budget_units':1,'tasks':[{'id':'task-one','role':'read_only','required':True,'dependencies':[],'executor_id':'executor-one','branch':None,'worktree':None,'write_paths':[],'expected_outputs':['fixture:output'],'expected_evidence':['fixture:evidence'],'backend_preferences':['local_command'],'max_runtime_seconds':30,'max_cost_units':1}]}
        self.req={'schema':'managed-host-start/v1','repo_root':str(self.repo),'remote':'origin','journal_root':str(self.root/'journal'),'handle_root':str(self.root/'handles'),'plan':plan,'lease_coordination_ref':self.source.ref,'lease_repository':'example/project','lease_source_ref':'refs/heads/main','task_id':'task-one','attempt_id':'attempt-one','reservation_token':'reservation-one','owner_id':'11111111-1111-4111-8111-111111111111','argv':[sys.executable,'-c','pass']}
        identity={'pid':99999991,'birth':'123','boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        binding={'repository':'example/project','candidate_sha':base,'backend':'local_command','mode':'read_only','environment_id':'fixture','check_suite_fingerprint':'sha256:'+'1'*64,'environment_fingerprint':'sha256:'+'2'*64,'check_plan_digest':'sha256:'+'3'*64}
        intent=op.prepare(binding,'attempt-one','refs/heads/main','2026-10-13T11:00:00Z');receipt=op.verify_readback(intent,copy.deepcopy(intent),'sha256:'+'4'*64,'2026-10-13T11:00:00Z');intent=op.transition(intent,'submitting','2026-10-13T11:00:01Z',receipt=receipt)
        import budget
        policy={'task_limits':{'compute_starts':1,'tool_calls':40},'wake_limits':{'compute_starts':1,'tool_calls':40},'max_parallel_agents':1,'checkpoint_reserve':{'tokens':0,'tool_calls':8},'provider_max_age_seconds':60,'actions_budget':'conserve'}
        ledger=budget.new_ledger('task-one','wake-one',policy)
        ledger=budget.apply_event(ledger,{'type':'reserve','event_id':'original-start','task_id':'task-one','wake_id':'wake-one','at_utc':'2026-10-13T11:00:00Z','operation_key':intent['operation_key'],'attempt_id':'attempt-one','kind':'compute_start','scope':'registered-native-task','recovery_ref':None,'cost':{'tool_calls':7,'tokens':None,'elapsed_seconds':30}})
        ledger=budget.apply_event(ledger,{'type':'outcome','event_id':'original-unknown','task_id':'task-one','wake_id':'wake-one','at_utc':'2026-10-13T11:00:01Z','reservation_id':'original-start','status':'unknown','usage':{'tokens':None,'elapsed_seconds':None},'failure':None})
        self.row={'task':{'id':'task-one','source_sha':base,'project_id':'fixture-project','mode':'COMPUTE_ONLY','goal':'original task','checks':['fixture-check'],'write_paths':[],'required_platform':'linux','execution_platform':'linux'},'state':'unknown','operation':{'start_request':self.req,'start_request_digest':native_digest(self.req),'attempt_id':'attempt-one','executor':'executor-one','intent':intent,'handle_id':None,'controller_identity':None,'checkpoint_ref':None,'finish_result':None,'guardian':{'nonce':'nonce-one','identity':identity}},'result':None,'budget':ledger}
        self.rev=self.store.compare_and_swap(None,{'schema':'cdc-vps-control/v1','tasks':{'task-one':self.row}})
        self.pins={'original_revision':self.rev,'row_digest':op._hash(self.row),'source_revision':self.srev,'source_digest':op._hash(self.source.read()[1]),'creator':dict(identity,pid=99999992),'guardian':identity,'guardian_nonce':'nonce-one','pool_ref':'refs/heads/cdc/pool','launch_roots':[self.req['journal_root'],self.req['handle_root']]}
        controller=self.root/'controllers'/'task-one';launch=self.root/'launch'/'executor-one'/'task-one'
        controller.mkdir(parents=True,mode=0o750);launch.mkdir(parents=True,mode=0o750);(launch/'output').mkdir(mode=0o770)
        records={controller/'guardian.lock':b'',launch/'registered-record.json':json.dumps({'schema':'cdc-vps-launch/v1','task':self.row['task'],'registry':{},'task_digest':native_digest(self.row['task']),'executor':'executor-one'}).encode(),launch/'record.json':json.dumps({'operation_id':'task-one','profile_id':'fixture','source_sha':base,'source_ref':self.req['lease_source_ref'],'profile_digest':'1'*64}).encode()}
        self.pins['custody']={'controller_root':str(self.root/'controllers'),'worker_launch_root':str(self.root/'launch'),'controller_uid':os.getuid(),'worker_gid':os.getgid()}
        self.pins['launch_roots'] += [str(controller),str(launch)]
        self.pins['artifact_pins']={}
        for path,data in records.items():
            path.write_bytes(data);path.chmod(0o640)
            self.pins['artifact_pins'][str(path)]={'sha256':'sha256:'+hashlib.sha256(data).hexdigest(),'uid':os.getuid(),'gid':os.getgid(),'mode':0o640}
    def git(self,*args,cwd=None):
        p=subprocess.run(['git','-C',str(cwd or self.repo),*args],text=True,capture_output=True)
        if p.returncode:raise AssertionError(p.stderr)
        return p.stdout.strip()
    def api(self):
        try:return importlib.import_module('unknown_recovery')
        except ModuleNotFoundError:self.fail('SDK-owned prelaunch UNKNOWN disposition is missing')
    def proof(self):return self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=self.pins,at='2026-10-13T12:00:00Z')
    def test_unicode_native_start_digest_is_compatible(self):
        from managed_executor_runtime import _digest
        doc=self.store.read()[1];row=doc['tasks']['task-one']
        row['operation']['start_request']['argv'].append('docs/über.md')
        row['operation']['start_request_digest']=_digest(row['operation']['start_request'])
        self.git('push','origin',':'+self.store.ref)
        self.rev=self.store.compare_and_swap(None,doc);self.row=copy.deepcopy(row)
        self.pins.update(original_revision=self.rev,row_digest=op._hash(row))
        self.assertEqual(self.proof()['contract_digest'],_digest(row['operation']['start_request']))

    def test_native_effects_cannot_be_whitelisted_by_static_pins(self):
        import hashlib,uuid
        from managed_host_bridge import _canonical
        from managed_executor_runtime import _digest
        identity={'repo_root':str(self.repo),'store':self.store.store_id,'coordination_ref':self.req['plan']['coordination_ref'],'pool_id':self.req['plan']['pool_id'],'task_id':self.req['task_id'],'attempt_id':self.req['attempt_id']}
        handle=str(uuid.uuid5(uuid.NAMESPACE_URL,_canonical(identity)))
        native_paths=[self.root/'handles'/(handle+'.json'),self.root/'handles'/'gates'/handle/'go.json',self.root/'handles'/'locks'/(handle+'.lock'),self.root/'journal'/_digest({k:identity[k] for k in ('pool_id','task_id','attempt_id')}).split(':')[1]/'request.json']
        for path in native_paths:
            with self.subTest(path=path.name):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
                pins=copy.deepcopy(self.pins);pins['artifact_pins'][str(path)]={'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),'uid':os.getuid(),'gid':os.getgid(),'mode':path.stat().st_mode & 0o7777}
                with self.assertRaises(ValueError):self.api()._physical_and_artifacts(self.store,self.row,pins)
                path.unlink()
                # Empty native effect directories also block; remove only fixture dirs.
                if path.parent.name==handle or path.name=='request.json':path.parent.rmdir()

    def test_worker_output_and_nonstatic_controller_files_cannot_be_pinned(self):
        for path in (self.root/'launch'/'executor-one'/'task-one'/'output'/'stdout.txt',self.root/'controllers'/'task-one'/'stdout.txt'):
            with self.subTest(path=path):
                path.write_text('effect');path.chmod(0o640);pins=copy.deepcopy(self.pins)
                pins['artifact_pins'][str(path)]={'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),'uid':os.getuid(),'gid':os.getgid(),'mode':0o640}
                with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')
                path.unlink()
    def prepare_checkout(self):
        checkout=self.root/'launch'/'executor-one'/'task-one'/'worktree'
        self.git('clone','--no-local','--no-hardlinks',str(self.repo),str(checkout))
        self.git('checkout','--detach',self.row['task']['source_sha'],cwd=checkout);self.git('remote','remove','origin',cwd=checkout)
        for path in [checkout,*checkout.rglob('*')]:
            path.chmod(0o750 if path.is_dir() else (0o750 if path.stat().st_mode & 0o111 else 0o640))
            if path.is_file():self.pins['artifact_pins'][str(path)]={'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),'uid':os.getuid(),'gid':os.getgid(),'mode':path.stat().st_mode & 0o7777}
        return checkout
    def test_pinned_unknown_git_metadata_cannot_hide_worker_effects(self):
        checkout=self.prepare_checkout();path=checkout/'.git/worker-effect.json';path.write_text('{}');path.chmod(0o640)
        self.pins['artifact_pins'][str(path)]={'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),'uid':os.getuid(),'gid':os.getgid(),'mode':0o640}
        with self.assertRaises(ValueError):self.proof()
    def test_complete_sealed_preparation_checkout_is_static_and_unchanged(self):
        checkout=self.prepare_checkout()
        before={str(p):p.read_bytes() for p in checkout.rglob('*') if p.is_file()}
        self.assertIsInstance(self.proof(),self.api().PrelaunchIntakeDispositionProof)
        self.assertEqual(before,{str(p):p.read_bytes() for p in checkout.rglob('*') if p.is_file()})
        self.git('update-index','--assume-unchanged','seed',cwd=checkout);(checkout/'seed').write_text('concealed worker bytes')
        for path in [checkout/'seed',checkout/'.git/index']:self.pins['artifact_pins'][str(path)]['sha256']='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(self.git('status','--porcelain',cwd=checkout),'')
        with self.assertRaises(ValueError):self.proof()
        (checkout/'unexpected-output').write_text('effect')
        with self.assertRaises(ValueError):self.proof()

    def test_original_static_custody_bytes_owner_and_source_are_authenticated(self):
        path=self.root/'launch'/'executor-one'/'task-one'/'registered-record.json';original=path.read_bytes()
        record=json.loads(original);record['task']['goal']='substituted original';path.write_text(json.dumps(record))
        pins=copy.deepcopy(self.pins);pins['artifact_pins'][str(path)]['sha256']='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')
        path.write_bytes(original);path.chmod(0o660)
        pins=copy.deepcopy(self.pins);pins['artifact_pins'][str(path)]['mode']=0o660
        with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')
        path.chmod(0o640);pins=copy.deepcopy(self.pins);pins['artifact_pins'][str(path)]['uid']=os.getuid()+1
        with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')

    def test_missing_controller_and_worker_custody_blocks_proof(self):
        for root in self.pins['launch_roots'][-2:]:
            pins=copy.deepcopy(self.pins);pins['launch_roots'].remove(root)
            with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')

    def test_retire_original_row_preserves_liabilities_and_observes_lost_reply(self):
        m=self.api();proof=self.proof()
        result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-13T12:00:00Z')
        row=result['row'];self.assertEqual(row['state'],'retired_unknown');self.assertEqual(row['budget'],self.row['budget'])
        self.assertEqual(row['operation'],self.row['operation']);self.assertEqual(row['result']['administrative_disposition']['original_effect'],'UNKNOWN');self.assertIsNone(row['result']['administrative_disposition']['actual_wait'])
        observed=m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req))
        self.assertIsInstance(observed,m.PrelaunchIntakeDispositionProof)
        self.assertEqual(observed.revalidate_for(self.store,'task-one')['state'],'retired_unknown')
        with self.assertRaises(ValueError):m.consume_intake_start(self.store,result['revision'],'task-one',start_request_digest=native_digest(self.req),controller_identity=self.pins['creator'])
        with self.assertRaises(ValueError):m.retire_prelaunch_intake_cas(self.store,result['revision'],'task-one',dict(proof),at='2026-10-13T12:00:00Z')
    def test_start_wins_and_old_controller_history_blocks_even_when_removed(self):
        m=self.api();proof=self.proof()
        started=m.consume_intake_start(self.store,self.rev,'task-one',start_request_digest=native_digest(self.req),controller_identity={'pid':os.getpid(),'birth':m._process(os.getpid())['birth'],'boot_id':self.pins['creator']['boot_id']})
        with self.assertRaises(ValueError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-13T12:00:00Z')
        with self.assertRaises(ValueError):self.proof()
    def test_live_reused_pid_hidden_artifact_and_changed_contract_fail_closed(self):
        m=self.api()
        for kind in ('live','artifact','nonce','source'):
            with self.subTest(kind=kind):
                if kind=='live':
                    pins=copy.deepcopy(self.pins);pins['creator']['pid']=os.getpid()
                    with self.assertRaises(ValueError):m.authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')
                elif kind=='artifact':
                    key={'pool_id':self.req['plan']['pool_id'],'task_id':self.req['task_id'],'attempt_id':self.req['attempt_id']}
                    p=self.root/'journal'/native_digest(key).split(':',1)[1];p.mkdir(parents=True);(p/'.hidden').write_text('contradiction')
                    with self.assertRaises(ValueError):self.proof()
                    (p/'.hidden').unlink();p.rmdir()
                elif kind=='nonce':
                    pins=copy.deepcopy(self.pins);pins['guardian_nonce']='wrong'
                    with self.assertRaises(ValueError):m.authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')
                else:
                    self.source.compare_and_swap(self.srev,lease.initialize('example/project','refs/heads/main'))
                    with self.assertRaises(ValueError):self.proof()
    def test_raw_tombstone_and_contract_replay_under_new_task_are_rejected(self):
        m=self.api();doc=self.store.read()[1];bad=copy.deepcopy(doc);bad['tasks']['task-one']['state']='retired_unknown'
        with self.assertRaises(ValueError):self.store.compare_and_swap(self.rev,bad)
        result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',self.proof(),at='2026-10-13T12:00:00Z')
        doc=self.store.read()[1];doc['tasks']['task-two']=copy.deepcopy(self.row)
        with self.assertRaises(ValueError):self.store.compare_and_swap(result['revision'],doc)

    def test_semantic_task_replay_and_registry_migration_preserve_original_rows(self):
        m=self.api();result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',self.proof(),at='2026-10-13T12:00:00Z')
        doc=self.store.read()[1];new=copy.deepcopy(self.row);new['task']['id']='new-id';new['operation']['start_request']=dict(self.req,task_id='new-id',attempt_id='new-a1');new['operation']['start_request_digest']=native_digest(new['operation']['start_request']);doc['tasks']['new-id']=new
        with self.assertRaises(ValueError):self.store.compare_and_swap(result['revision'],doc)
        self.assertTrue(callable(getattr(m,'migrate_intake_registry_cas',None)),'native registry migration CAS is missing')
    def test_native_start_consumption_cannot_be_minted_by_raw_document_cas(self):
        self.api();doc=self.store.read()[1];doc['tasks']['task-one']['operation']['start_consumption']={'schema':'native-intake-start-consumption/v1','contract_digest':native_digest(self.req),'controller':self.pins['creator']}
        with self.assertRaises(ValueError):self.store.compare_and_swap(self.rev,doc)

    def test_complete_queued_reserved_guardian_history_is_supported(self):
        m=self.api();self.git('push','origin',':'+self.store.ref)
        queued=copy.deepcopy(self.row);queued.update(state='queued',operation=None);queued['budget']=copy.deepcopy(self.row['budget']);queued['budget']['events']=[]
        revision=self.store.compare_and_swap(None,{'schema':'cdc-vps-control/v1','registry_digest':'sha256:'+'1'*64,'tasks':{'task-one':queued}})
        reserved=copy.deepcopy(self.row);reserved['state']='reserved';reserved['operation'].pop('guardian')
        doc=self.store.read()[1];doc['tasks']['task-one']=reserved;revision=self.store.compare_and_swap(revision,doc)
        doc['tasks']['task-one']=copy.deepcopy(self.row);self.rev=self.store.compare_and_swap(revision,doc);self.pins['original_revision']=self.rev
        result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',self.proof(),at='2026-10-13T12:00:00Z')
        original=copy.deepcopy(result['row']);migration=m.migrate_intake_registry_cas(self.store,result['revision'],'sha256:'+'1'*64,'sha256:'+'2'*64)
        self.assertEqual(migration['document']['tasks']['task-one'],original)
        m.validate_prelaunch_disposition(self.store,'task-one',original)
    def test_budget_prefix_does_not_allow_history_controller_erasure(self):
        m=self.api();doc=self.store.read()[1];doc['tasks']['task-one']['operation']['controllers']=[]
        first=self.store.compare_and_swap(self.rev,doc);doc['tasks']['task-one']['operation'].pop('controllers');self.rev=self.store.compare_and_swap(first,doc)
        with self.assertRaises(ValueError):self.proof()
    def test_administrative_read_remains_valid_after_unrelated_source_revision(self):
        m=self.api();result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',self.proof(),at='2026-10-13T12:00:00Z')
        self.source.compare_and_swap(self.srev,self.source.read()[1])
        proof=m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req),source_store=self.source)
        self.assertEqual(proof.revalidate_for(self.store,'task-one')['budget'],self.row['budget'])

    def test_any_original_controller_field_even_empty_is_consumed(self):
        m=self.api();doc=self.store.read()[1];doc['tasks']['task-one']['operation']['controllers']=[]
        self.git('push','origin',':'+self.store.ref)
        self.rev=self.store.compare_and_swap(None,doc);self.row=doc['tasks']['task-one'];self.pins.update(original_revision=self.rev,row_digest=op._hash(self.row))
        with self.assertRaises(ValueError):self.proof()

    def test_cancel_start_race_has_exactly_one_native_authority(self):
        import concurrent.futures,threading
        m=self.api();proof=self.proof();gate=threading.Barrier(2)
        identity={'pid':os.getpid(),'birth':m._process(os.getpid())['birth'],'boot_id':self.pins['creator']['boot_id']}
        def retire():
            gate.wait()
            try:m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-13T12:00:00Z');return 'retired'
            except ValueError:return None
        def start():
            gate.wait()
            try:m.consume_intake_start(self.store,self.rev,'task-one',start_request_digest=native_digest(self.req),controller_identity=identity);return 'started'
            except ValueError:return None
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            results=list(executor.map(lambda fn:fn(),[retire,start]))
        self.assertEqual(sum(value is not None for value in results),1)
        row=self.store.read()[1]['tasks']['task-one'];self.assertEqual(row['budget'],self.row['budget'])
        if row['state']=='retired_unknown':
            with self.assertRaises(ValueError):m.assert_intake_start_allowed(self.store,'task-one',native_digest(self.req))
        else:
            with self.assertRaises(ValueError):self.proof()
    def test_lost_tombstone_reply_is_observed_once_without_repeating_cas(self):
        m=self.api();proof=self.proof();actual=self.store.compare_and_swap;calls=[]
        def lost(expected,document,**kw):calls.append(expected);actual(expected,document,**kw);raise OSError('lost reply')
        self.store.compare_and_swap=lost
        with self.assertRaises(OSError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-13T12:00:00Z')
        m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req),source_store=self.source)
        with self.assertRaises(ValueError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-13T12:00:00Z')
        self.assertEqual(len(calls),1)
    def test_zombie_birth_endpoint_drift_and_original_history_truncation_fail_closed(self):
        import time
        m=self.api();child=subprocess.Popen([sys.executable,'-c','pass']);self.addCleanup(child.wait)
        identity=m._process(child.pid);time.sleep(.1)
        if identity is None:self.fail('original child birth not recorded')
        pins=copy.deepcopy(self.pins);pins['creator'].update(pid=child.pid,birth=identity['birth'])
        with self.assertRaises(ValueError):m.authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=pins,at='2026-10-13T12:00:00Z')
        child.wait()
        other=self.root/'other.git';self.git('init','--bare',str(other),cwd=self.root);self.git('remote','set-url','origin',str(other))
        with self.assertRaises(ValueError):self.proof()
        self.git('remote','set-url','origin',str(self.remote));self.git('push','origin',':'+self.store.ref)
        self.store.compare_and_swap(None,{'schema':'cdc-vps-control/v1','tasks':{'task-one':copy.deepcopy(self.row)}})
        with self.assertRaises(ValueError):self.proof()

    def test_forward_native_intent_admission_history_is_supported(self):
        m=self.api();intent=copy.deepcopy(self.row['operation']['intent']);prepared=copy.deepcopy(intent);prepared.update(state='prepared',durable_intent=None,updated_at_utc=prepared['created_at_utc'])
        self.git('push','origin',':'+self.store.ref)
        earlier=copy.deepcopy(self.row);earlier['operation']['intent']=prepared;earlier['operation'].pop('guardian');earlier['state']='reserved'
        revision=self.store.compare_and_swap(None,{'schema':'cdc-vps-control/v1','tasks':{'task-one':earlier}})
        self.row['operation']['intent']=intent;self.row['operation']['observation']={'at_utc':'2026-10-13T11:00:02Z','reason':'original native start requires observation'};doc=self.store.read()[1];doc['tasks']['task-one']=copy.deepcopy(self.row);self.rev=self.store.compare_and_swap(revision,doc);self.pins.update(original_revision=self.rev,row_digest=op._hash(self.row))
        try:proof=self.proof()
        except ValueError as error:self.fail('legitimate native forward admission rejected: '+str(error))
        self.assertEqual(proof['original_effect'],'UNKNOWN')

    def test_incomplete_original_native_start_contract_cannot_issue_disposition(self):
        self.api();self.req.pop('schema');self.row['operation']['start_request_digest']=native_digest(self.req)
        doc=self.store.read()[1];doc['tasks']['task-one']=copy.deepcopy(self.row);self.rev=self.store.compare_and_swap(self.rev,doc);self.pins.update(original_revision=self.rev,row_digest=op._hash(self.row))
        with self.assertRaises(ValueError):self.proof()

    def test_same_endpoint_wrong_source_channel_is_rejected(self):
        m=self.api();other=GitLeaseStore(self.repo,'origin','refs/heads/cdc/other-source')
        revision=other.compare_and_swap(None,lease.initialize('other/project','refs/heads/other'))
        pins=copy.deepcopy(self.pins);pins.update(source_revision=revision,source_digest=op._hash(other.read()[1]))
        with self.assertRaises(ValueError):m.authenticate_prelaunch_intake(self.store,'task-one',source_store=other,trusted_contract=pins,at='2026-10-13T12:00:00Z')

    def test_mutated_native_intake_capability_cannot_manufacture_wait(self):
        proof=self.proof();proof['actual_wait']=0
        with self.assertRaises(ValueError):proof.revalidate_for(self.store,'task-one')

if __name__=='__main__':unittest.main()
