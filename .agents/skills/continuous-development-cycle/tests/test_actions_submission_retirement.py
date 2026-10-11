"""Anonymized real-Git administrative Actions quarantine; never a provider send."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import execution_lease_v2 as lease
import operation_intent as op
from git_lease_store import validate_coordination_transition
from test_submission_recovery import fixture, NOW, REV

WORKFLOW_BYTES=b'on: [workflow_dispatch]\npermissions:\n  contents: read\njobs:\n  pilot:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo anonymized-read-only-pilot\n'

def actions_fixture(candidate_sha='a'*40):
    record,old=fixture('not_submitted');guard=record['external_guard']
    binding=copy.deepcopy(guard['intent']['binding'])
    binding.update(backend='github-actions',mode='ordinary-unsigned-pilot',candidate_sha=candidate_sha,environment_id='github-actions/workflow/ordinary-unsigned-pilot.yml/ubuntu-latest')
    intent=op.prepare(binding,'original-pilot',record['source_ref'],'2026-10-04T17:00:00Z')
    receipt=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc'])
    intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
    claim=guard['submission_claim'];claim.update(operation_key=intent['operation_key'],intent_digest=op._hash(intent),attempt_id=intent['attempt_id'])
    guard.update(intent=intent,operation_key=intent['operation_key'],intent_digest=op._hash(intent));record['submission_claims']=[copy.deepcopy(claim)]
    scope={'backend':'github-actions','mode':'ordinary-unsigned-pilot','method':'POST','workflow':'ordinary-unsigned-pilot.yml','target':'repos/example/project/actions/workflows/ordinary-unsigned-pilot.yml/dispatches','candidate_sha':binding['candidate_sha'],'read_only':True}
    decision={'action':'retire_actions_unknown_without_replay','operation_key':claim['operation_key'],'grant_id':claim['grant_id'],'owner_id':claim['owner_id'],'generation':claim['generation'],'scope':copy.deepcopy(scope),'at_utc':NOW}
    proof={'schema':'actions-unknown-retirement-proof/v1','lease_revision':REV,'lease_digest':op._hash(record),'original_lease_revision':REV,'guard_digest':op._hash(guard),'repository':record['repository'],'source_ref':record['source_ref'],'observed_at_utc':NOW,'scope':scope,'owner_decision':decision,'original_ui':{'closed_without_run':True,'final_run_clicked':False,'original_ci_submitted':False,'at_utc':'2026-10-04T17:00:03Z'},'transport':{'outcome':'UNKNOWN','cancellation_barrier':None,'dispatcher_birth':None,'no_in_flight':None},'runtime':copy.deepcopy(old['runtime']),'provider_observation':copy.deepcopy(old['provider_observation']),'evidence':{}}
    proof['provider_observation']['operation_key']=claim['operation_key']
    proof['physical_stop']={'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'executor_pid':1500001,'executor_birth':'11111','supervisor_pid':1500002,'supervisor_birth':'11112','absent':True,'invocation_id':old['runtime']['invocation_id'],'owner_id':claim['owner_id'],'generation':claim['generation'],'observed_at_utc':NOW}
    proof['provider_lookup']={'repository':record['repository'],'workflow':scope['workflow'],'candidate_sha':binding['candidate_sha'],'operation_key':claim['operation_key'],'grant_id':claim['grant_id'],'surfaces':['status','check_runs','actions'],'pagination_complete':True,'observed_at_utc':NOW,'evidence_refs':['sha256:'+'2'*64,'sha256:'+'3'*64,'sha256:'+'4'*64]}
    proof['workflow_definition']='sha256:'+hashlib.sha256(WORKFLOW_BYTES).hexdigest()
    for name in ['scope','owner_decision','original_ui','runtime','provider_observation','physical_stop','provider_lookup']:
        proof['evidence'][name]={'revision':REV,'ref':'refs/heads/cdc/actions-evidence','path':'evidence.json','pointer':'/'+name,'sha256':'sha256:'+'1'*64}
    proof['evidence']['workflow_definition']={'revision':candidate_sha,'ref':'refs/heads/main','path':'.github/workflows/'+scope['workflow'],'pointer':'/','sha256':proof['workflow_definition']}
    lease.validate(record);return record,proof

class Tests(unittest.TestCase):
    def module(self):
        m=importlib.import_module('submission_retirement')
        self.assertTrue(callable(getattr(m,'retire_actions_unknown_guard',None)), 'Canonical administrative Actions UNKNOWN quarantine is required; UI closure is not positive cancellation')
        return m

    def retire(self,old,proof):return self.module().retire_actions_unknown_guard(old,proof,'git:'+'5'*40,NOW)

    def test_unknown_preserved_without_manufactured_transport_terminal(self):
        old,proof=actions_fixture();new=self.retire(old,proof);entry=new['submission_retirements'][0]
        self.assertIsNone(new['external_guard']);self.assertEqual(entry['outcome'],'UNKNOWN');self.assertIs(entry['replay_forbidden'],True)
        self.assertEqual(entry['guard'],old['external_guard']);self.assertEqual(entry['original_release'],old['last_release'])
        self.assertEqual(entry['proof']['transport'],proof['transport'])
        for k in old.keys()-{'external_guard'}:self.assertEqual(new[k],old[k],k)

    def test_scope_identity_and_missing_evidence_rejected(self):
        old,proof=actions_fixture()
        edits=[('scope','mode','required-release'),('scope','backend','native_git'),('scope','method','PUT'),('scope','target','repos/other/project/actions/workflows/ordinary-unsigned-pilot.yml/dispatches'),('scope','candidate_sha','f'*40),('scope','read_only',False),('original_ui','final_run_clicked',True),('original_ui','original_ci_submitted',True),('runtime','quiescent',False),('runtime','pending_shared_writes',True),('runtime','invocation_id','another'),('provider_observation','lookup_complete',False),('owner_decision','action','cancelled_before_send'),('transport','cancellation_barrier','cancelled_before_send'),('transport','no_in_flight',False)]
        for section,key,value in edits:
            p=copy.deepcopy(proof);p[section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):self.retire(old,p)
        for key in ['owner_decision','original_ui','runtime','provider_observation']:
            p=copy.deepcopy(proof);p['evidence'].pop(key)
            with self.subTest(missing=key),self.assertRaises(ValueError):self.retire(old,p)

    def test_provider_absence_never_becomes_positive_cancellation(self):
        from submission_recovery import resolve_released_guard
        old,proof=actions_fixture();_,positive=fixture('not_submitted')
        positive.update(lease_digest=op._hash(old),claim=old['external_guard']['submission_claim'])
        positive['provider_observation']['operation_key']=old['external_guard']['operation_key']
        positive['dispatch'].update(claim_digest=op._hash(positive['claim']),intent_digest=old['external_guard']['intent_digest'],target=proof['scope']['target'])
        with self.assertRaises(ValueError):resolve_released_guard(old,positive,'git:'+'8'*40,NOW)

    def test_attempt_ref_mode_backend_environment_disguises_never_rearm(self):
        old,proof=actions_fixture();new=self.retire(old,proof)
        for mode,backend in [('ordinary-unsigned-pilot','github-actions'),('COMPUTE_ONLY','codex_cloud_cli'),('SOURCE_RELEASE','native_git')]:
            binding=copy.deepcopy(old['external_guard']['intent']['binding']);binding.update(mode=mode,backend=backend,environment_id='changed')
            intent=op.prepare(binding,'new-disguised-attempt','refs/heads/new-ref','2026-10-04T17:00:00Z')
            receipt=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc']);intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
            bad=copy.deepcopy(new);bad['external_guard']={'operation_key':intent['operation_key'],'intent':intent,'intent_digest':op._hash(intent),'intent_reference':'git:'+'b'*40,'submission_claim':None}
            with self.subTest(mode=mode,backend=backend),self.assertRaises(ValueError):lease.validate(bad)

    def test_raw_history_append_and_guard_clear_are_not_authenticated_authority(self):
        old,proof=actions_fixture();new=self.retire(old,proof)
        with self.assertRaisesRegex(ValueError,'authenticated|verified'):validate_coordination_transition(old,new,expected_revision=REV)
        bad=copy.deepcopy(old);bad['external_guard']=None
        with self.assertRaises(ValueError):validate_coordination_transition(old,bad,expected_revision=REV)

    def test_same_sha_fresh_native_compute_only_source_write_is_not_globally_blocked(self):
        old,proof=actions_fixture();new=self.retire(old,proof)
        # Exercise the existing fresh managed product_write gate. No external
        # operation is armed; this is source correction, not a disguised send.
        from unittest.mock import patch
        invocation={'invocation_id':'fresh-native-correction','automation_id':None,'conversation_id':None,'execution_surface':'managed','started_at_utc':NOW}
        # Only the runtime-capability issuer is isolated, as in the existing
        # lease unit fixture; canonical acquisition/write/history checks run.
        with patch.object(lease.terminal_capability_api,'validate_verified',return_value={}):
            owned=lease.acquire(new,'33333333-3333-4333-8333-333333333333','2026-10-04T17:00:06Z',invocation=invocation,terminal_capability=object())
        lease.check_record(owned,owned['owner_id'],2,owned['invocation']['invocation_id'],'2026-10-04T17:00:07Z',action='product_write')
        self.assertIsNone(owned['external_guard']);self.assertEqual(owned['submission_retirements'][0]['outcome'],'UNKNOWN')

    def test_local_stop_and_complete_provider_lookup_are_required_distinct_from_transport(self):
        old,proof=actions_fixture()
        for field in ['physical_stop','provider_lookup']:
            p=copy.deepcopy(proof);p[field]=None
            with self.subTest(field=field),self.assertRaises(ValueError):self.retire(old,p)

    def test_missing_original_birth_or_incomplete_provider_surfaces_cannot_be_retired(self):
        old,proof=actions_fixture()
        self.assertIn('physical_stop',proof,'Original executor birth-bound local stop proof required, separate from missing dispatcher proof')
        for section,key,val in [('physical_stop','executor_birth',None),('physical_stop','supervisor_birth',None),('physical_stop','absent',False),('provider_lookup','surfaces',['actions']),('provider_lookup','pagination_complete',False)]:
            p=copy.deepcopy(proof);p[section][key]=val
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):self.retire(old,p)

    def test_complete_original_stop_and_lookup_are_supported_without_cancellation_barrier(self):
        old,proof=actions_fixture()
        try:new=self.module().retire_actions_unknown_guard(old,proof,'git:'+'5'*40,NOW)
        except ValueError as e:self.fail('Complete original physical-stop/provider-lookup proof must be supported without manufacturing a transport barrier: '+str(e))
        self.assertEqual(new['submission_retirements'][0]['outcome'],'UNKNOWN')

class GitTests(unittest.TestCase):
    module=Tests.module
    retire=Tests.retire
    def setUp(self):
        from test_submission_recovery import GitTests as GitFixture
        GitFixture.setUp(self)

    def authenticated(self,workflow_bytes=WORKFLOW_BYTES,*,legacy=False,supervisor_pid=None,supervisor_birth=None,ranged_ui=False):
        store=self.stores[0];repo=store.repo
        def git(*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
        git('checkout','--orphan','main');path=repo/'.github/workflows/ordinary-unsigned-pilot.yml';path.parent.mkdir(parents=True);path.write_bytes(workflow_bytes)
        git('add','.github');git('-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','Anonymized original pilot source');candidate=git('rev-parse','HEAD');git('push','origin','HEAD:refs/heads/main')
        old,proof=actions_fixture(candidate)
        if legacy:old,proof=legacy_fixture(old,proof,supervisor_pid,supervisor_birth)
        proof['workflow_definition']='sha256:'+hashlib.sha256(workflow_bytes).hexdigest();proof['evidence']['workflow_definition']['sha256']=proof['workflow_definition']
        revision=synthetic_legacy_native_history(store,old,proof,git) if legacy else store.compare_and_swap(None,old);proof.update(lease_revision=revision,original_lease_revision=revision)
        git('checkout','-B','evidence',revision)
        body={k:proof[k] for k in proof['evidence'] if k!='workflow_definition'};raw=(json.dumps(body,sort_keys=True,indent=2)+'\n').encode();(repo/'evidence.json').write_bytes(raw)
        ui_raw=None
        if ranged_ui:
            ui_raw=(json.dumps(proof['original_ui'],sort_keys=True)+'\n').encode();(repo/'ui-record.txt').write_bytes(b'HEADER\n'+ui_raw+b'TRAILER\n');git('add','ui-record.txt')
        (repo/'checkpoint.json').write_text('{"original":"preserved"}\n');git('add','evidence.json','checkpoint.json');git('-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','Authenticated original-channel evidence')
        commit=git('rev-parse','HEAD');git('push','origin','HEAD:refs/heads/cdc/actions-evidence')
        git('push','origin','HEAD:'+store.ref);proof['lease_revision']=commit
        pins={k:dict(revision=commit,ref='refs/heads/cdc/actions-evidence',path='evidence.json',pointer='/'+k,sha256='sha256:'+hashlib.sha256(raw).hexdigest()) for k in body}
        pins['workflow_definition']=proof['evidence']['workflow_definition']
        if legacy:pins['original_ui']['normalization']='legacy-ui/v1'
        if ranged_ui:
            raw_file=(repo/'ui-record.txt').read_bytes();pins['original_ui'].update(path='ui-record.txt',pointer='/',sha256='sha256:'+hashlib.sha256(raw_file).hexdigest(),byte_range=[7,7+len(ui_raw)],range_sha256='sha256:'+hashlib.sha256(ui_raw).hexdigest())
        proof['evidence']=copy.deepcopy(pins)
        capability=self.module().authenticate_actions_retirement(store,proof,pins,NOW)
        return old,proof,store,capability

    def test_real_git_authenticated_quarantine_cas_and_race(self):
        old,proof,store,cap=self.authenticated();m=self.module()
        result=m.retire_actions_unknown_cas(store,proof['lease_revision'],proof,'git:'+'5'*40,NOW,evidence_capability=cap)
        self.assertIs(result['authorizes_submission'],False);self.assertIs(result['authorizes_release'],False)
        rev,new=self.stores[1].read();self.assertEqual(new,result['record']);self.assertEqual(len(new['submission_retirements']),1)
        neighbor=subprocess.check_output(['git','-C',str(store.repo),'show',rev+':checkpoint.json']).decode();self.assertEqual(neighbor,'{"original":"preserved"}\n')
        with self.assertRaises(ValueError):self.stores[1].compare_and_swap(proof['lease_revision'],new,retirement_capability=cap)
        bad=copy.deepcopy(new);bad['submission_retirements']=[]
        with self.assertRaises(ValueError):store.compare_and_swap(rev,bad)

    def test_native_evidence_missing_substitution_or_caller_bool_cannot_write(self):
        old,proof,store,cap=self.authenticated();m=self.module()
        for alteration in [dict(runtime=dict(proof['runtime'],quiescent=False)),dict(evidence={}),dict(guard_digest='sha256:'+'0'*64)]:
            p=copy.deepcopy(proof);p.update(alteration)
            with self.subTest(alteration=list(alteration)),self.assertRaises(ValueError):m.authenticate_actions_retirement(store,p,proof['evidence'],NOW)
        p=copy.deepcopy(proof);p['runtime']['reference']='git:'+'8'*40
        with self.assertRaisesRegex(ValueError,'authenticated'):m.authenticate_actions_retirement(store,p,proof['evidence'],NOW)
        p=copy.deepcopy(proof);p['evidence']['original_ui']['sha256']='sha256:'+'0'*64
        with self.assertRaisesRegex(ValueError,'bytes'):m.authenticate_actions_retirement(store,p,p['evidence'],NOW)
        with self.assertRaises(ValueError):m.retire_actions_unknown_cas(store,proof['lease_revision'],proof,'git:'+'5'*40,NOW,evidence_capability=True)
        self.assertEqual(store.read()[1],old)

    def test_actual_write_permission_workflow_is_outside_unsigned_read_only_scope(self):
        with self.assertRaisesRegex(ValueError,'read.only|permission'):
            self.authenticated(WORKFLOW_BYTES.replace(b'contents: read',b'contents: write'))

    def test_lost_reply_is_same_entry_readback_not_cas_or_submission_replay(self):
        old,proof,store,cap=self.authenticated();original=store.compare_and_swap;calls=[]
        def lost(expected,record,**kw):calls.append(expected);original(expected,record,**kw);raise OSError('lost reply')
        store.compare_and_swap=lost;m=self.module()
        with self.assertRaises(OSError):m.retire_actions_unknown_cas(store,proof['lease_revision'],proof,'git:'+'5'*40,NOW,evidence_capability=cap)
        result=m.observe_actions_retirement(store,proof,'git:'+'5'*40)
        self.assertEqual(result['outcome'],'UNKNOWN');self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):m.retire_actions_unknown_cas(store,proof['lease_revision'],proof,'git:'+'5'*40,NOW,evidence_capability=cap)
        self.assertEqual(len(calls),1)


def bind_synthetic_legacy_descriptor(old,proof,*,managed_revision='b'*40,store_id='sha256:'+'1'*64,owned_revision=REV):
    """Synthetic pinned historical descriptor; never issue a new old capability."""
    import managed_executor_pool as pool
    import managed_terminal_capability as terminal
    registry=proof['original_registry'];physical=proof['physical_stop'];owner=old['last_release']['owner_id']
    task_id='synthetic-original-task';attempt='synthetic-original';pool_ref='refs/heads/cdc/synthetic-original-pool'
    task={'id':task_id,'role':'writer','required':True,'dependencies':[],'executor_id':owner,'branch':'cdc/synthetic-original','worktree':'synthetic-original','write_paths':['fixture'],'expected_outputs':['fixture:original'],'expected_evidence':['fixture:evidence'],'backend_preferences':['local_command'],'max_runtime_seconds':100,'max_cost_units':1}
    plan={'schema':'managed-executor-pool-plan/v1','pool_id':'synthetic-original-pool','change_id':'synthetic-original-change','parent_invocation_id':'synthetic-parent','base_sha':proof['scope']['candidate_sha'],'integrator_id':owner,'coordination_ref':pool_ref,'coordination_store_id':store_id,'max_parallel':1,'total_runtime_budget_seconds':100,'total_cost_budget_units':1,'tasks':[task]}
    state=pool.initial_state(plan,parallel_capable=False);state['revision']=2
    state['tasks'][0].update(status='running',attempt_ids=[attempt],active_attempt_id=attempt,reservation_token='synthetic-reservation')
    pool.validate_state(plan,state)
    identity={**{k:plan[k] for k in ['pool_id','change_id','parent_invocation_id','base_sha','integrator_id','coordination_ref','coordination_store_id']},**{k:task[k] for k in ['executor_id','role','branch','worktree']},'task_id':task_id,'attempt_id':attempt,'plan_ref':op._hash(plan)}
    claim={'schema':'managed-executor-launch-claim/v1','store_revision':managed_revision,'state_revision':2,'state_ref':pool.canonical_state_ref(state),'task_id':task_id,'attempt_id':attempt,'reservation_token':'synthetic-reservation','launch_allowed':True,**{k:False for k in pool.AUTHORITY_FIELDS}}
    request=registry['request'];request.update(identity=identity,claim=claim)
    receipt=registry['receipt'];receipt.update(identity=copy.deepcopy(identity),claim=copy.deepcopy(claim),request_ref=op._hash(request),launch_id=op._hash(request),created_at_utc='2026-10-04T17:00:00Z')
    cap={'schema':'managed-terminal-capability/v1','execution_surface':'managed','managed_store_ref':pool_ref,'managed_store_id':store_id,'managed_store_revision':managed_revision,'managed_state_revision':2,'pool_id':plan['pool_id'],'task_id':task_id,'attempt_id':attempt,'request_ref':receipt['request_ref'],'launch_id':receipt['launch_id'],'lease_repository':old['repository'],'lease_source_ref':old['source_ref'],'observed_at_utc':'2026-10-04T17:00:00Z','started_at_utc':receipt['created_at_utc']}
    identity_keys=['pool_id','task_id','attempt_id','launch_id','managed_store_revision','lease_repository','lease_source_ref']
    cap['invocation_id']='managed-terminal:'+terminal._digest({k:cap[k] for k in identity_keys}).split(':',1)[1]
    owned=registry['owned'];owned.update(capability_ref=terminal._digest(cap),invocation_id=cap['invocation_id'],lease_revision=owned_revision)
    registry.update(schema='actions-original-registry/v2',capability_descriptor={'schema':'historical-managed-capability-descriptor/v1','provenance':'hash_matching_reconstruction','payload':cap},intent={'schema':'managed-terminal-lease-intent/v1','capability_ref':owned['capability_ref'],'invocation_id':cap['invocation_id'],'lease_repository':old['repository'],'lease_source_ref':old['source_ref'],'armed_at_utc':'2026-10-04T17:00:00Z','controller_proc_pid':1500003,'controller_birth':'11113'})
    old['last_release']['invocation_id']=cap['invocation_id'];proof['runtime']['invocation_id']=cap['invocation_id'];physical['invocation_id']=cap['invocation_id'];proof['lease_digest']=op._hash(old)
    return plan,state

def synthetic_legacy_native_history(store,old,proof,git):
    from unittest.mock import patch
    plan,state=bind_synthetic_legacy_descriptor(old,proof,store_id=store.store_id)
    git('checkout','-B','synthetic-pool',proof['scope']['candidate_sha'])
    (store.repo/'pool-state.json').write_text(json.dumps(state,sort_keys=True)+'\n');git('add','pool-state.json');git('-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','Synthetic original running pool')
    pool_revision=git('rev-parse','HEAD');git('push','origin','HEAD:'+plan['coordination_ref'])
    bind_synthetic_legacy_descriptor(old,proof,managed_revision=pool_revision,store_id=store.store_id)
    cap=proof['original_registry']['capability_descriptor']['payload']
    invocation={'invocation_id':cap['invocation_id'],'automation_id':None,'conversation_id':None,'execution_surface':'managed','started_at_utc':cap['started_at_utc']}
    # Only fixture admission is isolated. Historical records are real Git objects.
    # The descriptor above is not a sealed capability and is never an old launch grant.
    with patch.object(lease.terminal_capability_api,'validate_verified',return_value={}):
        owned_record=lease.acquire(lease.initialize(old['repository'],old['source_ref']),old['last_release']['owner_id'],cap['observed_at_utc'],invocation=invocation,terminal_capability=object())
    owned_revision=store.compare_and_swap(None,owned_record)
    proof['original_registry']['owned']['lease_revision']=owned_revision
    git('checkout','-B','synthetic-released',owned_revision)
    (store.repo/'lease.json').write_text(json.dumps(old,sort_keys=True)+'\n');git('add','lease.json');git('-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','Synthetic original released UNKNOWN guard')
    released_revision=git('rev-parse','HEAD');git('push','origin','HEAD:'+store.ref)
    return released_revision

def legacy_fixture(old,proof,supervisor_pid=1500002,supervisor_birth='11112'):
    """Synthetic original shapes only. UNKNOWN birth/transport are never filled."""
    binding=copy.deepcopy(old['external_guard']['intent']['binding']);binding['environment_id']='github-actions/workflow/67890/ubuntu-latest'
    intent=op.prepare(binding,'original-pilot',old['source_ref'],'2026-10-04T17:00:00Z')
    receipt=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc']);intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
    guard=old['external_guard'];claim=guard['submission_claim'];claim.update(operation_key=intent['operation_key'],intent_digest=op._hash(intent),attempt_id=intent['attempt_id'])
    guard.update(intent=intent,operation_key=intent['operation_key'],intent_digest=op._hash(intent));old['submission_claims']=[copy.deepcopy(claim)]
    proof.update(lease_digest=op._hash(old),guard_digest=op._hash(guard));proof['provider_observation']['operation_key']=claim['operation_key']
    proof['scope']['target']='repos/example/project/actions/workflows/67890/dispatches'
    proof['owner_decision'].update(scope=copy.deepcopy(proof['scope']),operation_key=claim['operation_key'])
    proof['provider_lookup']['operation_key']=claim['operation_key']
    proof['workflow_mapping']={'id':12345,'workflow_id':67890,'path':'.github/workflows/ordinary-unsigned-pilot.yml','head_sha':binding['candidate_sha'],'event':'push','repository':{'full_name':'example/project'}}
    proof['original_ui']={'evidence_ref':'Synthetic prior controller explicitly observed final Run never clicked and Close completed','form_closed':True,'incidental_push_not_final_guarded_dispatch':True,'incidental_push_run':12345,'observed_at_utc':'2026-10-04T17:00:03Z','submitted':False}
    physical=proof['physical_stop'];physical.update(schema='original-registry-stopped/v1',executor_birth=None,supervisor_pid=supervisor_pid,supervisor_birth=supervisor_birth,absent=False,supervisor_state='Z',worker_pids=[1500001],worker_absent=True,live_descendants=0,pending_shared_commands=False)
    request={'schema':'managed-executor-start/v1','identity':{'executor_id':claim['owner_id'],'attempt_id':'synthetic-original'},'claim':{'attempt_id':'synthetic-original'},'argv':['synthetic-read-only'], 'cwd':'synthetic-original','journal_directory':'synthetic-original','repo_root':'synthetic-original','timeout_seconds':100}
    native_receipt={'schema':'managed-executor-observation/v1','identity':copy.deepcopy(request['identity']),'claim':copy.deepcopy(request['claim']),'request_ref':op._hash(request),'boot_id':physical['boot_id'],'supervisor_proc_pid':supervisor_pid,'supervisor_birth':supervisor_birth,'worker_pid':1500001,'status':'succeeded','quiescent':True,'exit_code':0}
    owned={'schema':'managed-terminal-lease-owned/v1','capability_ref':'sha256:'+'1'*64,'owner_id':claim['owner_id'],'generation':claim['generation'],'invocation_id':old['last_release']['invocation_id'],'lease_revision':REV}
    proof['original_registry']={'schema':'actions-original-registry/v1','request':request,'receipt':native_receipt,'owned':owned,'worker_pids':[1500001],'worker_births':{'1500001':None}}
    for name in ['workflow_mapping','original_registry']:
        proof['evidence'][name]={'revision':REV,'ref':'refs/heads/cdc/actions-evidence','path':'evidence.json','pointer':'/'+name,'sha256':'sha256:'+'1'*64}
    proof['evidence']['original_ui']['normalization']='legacy-ui/v1'
    bind_synthetic_legacy_descriptor(old,proof)
    return old,proof

class LegacyTests(unittest.TestCase):
    module=Tests.module
    retire=Tests.retire
    def test_legacy_raw_ui_numeric_workflow_and_stopped_zombie_preserve_unknown(self):
        old,p=legacy_fixture(*actions_fixture());new=self.retire(old,p);saved=new['submission_retirements'][0]['proof']
        self.assertEqual(saved['original_ui'],p['original_ui']);self.assertIsNone(saved['physical_stop']['executor_birth'])
        self.assertFalse(saved['physical_stop']['absent']);self.assertEqual(saved['physical_stop']['supervisor_state'],'Z')
        self.assertEqual(saved['transport'],p['transport']);self.assertEqual(new['submission_retirements'][0]['outcome'],'UNKNOWN')

    def test_legacy_identity_mapping_and_original_registry_negative_cases(self):
        old,p=legacy_fixture(*actions_fixture())
        changes=[('physical_stop','supervisor_birth','999'),('physical_stop','executor_pid',1500003),('physical_stop','supervisor_state','S'),('physical_stop','live_descendants',1),('physical_stop','pending_shared_commands',True),('workflow_mapping','workflow_id',1),('workflow_mapping','path','.github/workflows/unrelated.yml'),('workflow_mapping','head_sha','f'*40),('original_ui','submitted',True),('original_ui','form_closed',False),('provider_lookup','pagination_complete',False),('provider_lookup','observed_at_utc','2020-01-01T00:00:00Z')]
        for section,key,value in changes:
            bad=copy.deepcopy(p);bad[section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):self.retire(old,bad)
        bad=copy.deepcopy(p);bad['evidence'].pop('original_registry')
        with self.assertRaises(ValueError):self.retire(old,bad)
        bad=copy.deepcopy(p);bad['evidence']['original_registry']['path']='/tmp/unbound-local-file'
        with self.assertRaises(ValueError):self.retire(old,bad)

    def test_workflow_filename_must_bind_environment_even_for_pure_proposal(self):
        old,p=actions_fixture();binding=copy.deepcopy(old['external_guard']['intent']['binding']);binding['environment_id']='github-actions/workflow/unrelated.yml/ubuntu-latest'
        intent=op.prepare(binding,'original-pilot',old['source_ref'],'2026-10-04T17:00:00Z');rr=op.verify_readback(intent,copy.deepcopy(intent),'git:'+'b'*40,intent['updated_at_utc']);intent=op.transition(intent,'submitting','2026-10-04T17:00:01Z',receipt=rr)
        guard=old['external_guard'];claim=guard['submission_claim'];claim.update(operation_key=intent['operation_key'],intent_digest=op._hash(intent));guard.update(intent=intent,operation_key=intent['operation_key'],intent_digest=op._hash(intent));old['submission_claims']=[copy.deepcopy(claim)];p.update(lease_digest=op._hash(old),guard_digest=op._hash(guard));p['provider_observation']['operation_key']=claim['operation_key'];p['provider_lookup']['operation_key']=claim['operation_key'];p['owner_decision']['operation_key']=claim['operation_key']
        with self.assertRaises(ValueError):self.retire(old,p)

class LegacyGitTests(unittest.TestCase):
    module=Tests.module
    retire=Tests.retire
    setUp=GitTests.setUp
    authenticated=GitTests.authenticated

    def zombie(self):
        import os,time
        pid=os.fork()
        if pid==0:os._exit(0)
        self.addCleanup(os.waitpid,pid,0)
        from managed_executor_runtime import _process
        end=time.monotonic()+2
        while time.monotonic()<end:
            observed=_process(pid)
            if observed and observed['state']=='Z':return pid,observed['birth']
            time.sleep(.001)
        self.fail('actual synthetic supervisor failed to reach kernel zombie state')

    def test_real_git_pinned_legacy_zombie_raw_ui_range_numeric_mapping_unknown_cas(self):
        pid,birth=self.zombie();old,p,store,cap=self.authenticated(legacy=True,supervisor_pid=pid,supervisor_birth=birth,ranged_ui=True)
        result=self.module().retire_actions_unknown_cas(store,p['lease_revision'],p,'git:'+'5'*40,NOW,evidence_capability=cap)
        entry=result['record']['submission_retirements'][0]
        self.assertEqual(entry['outcome'],'UNKNOWN');self.assertIsNone(entry['proof']['physical_stop']['executor_birth'])
        self.assertEqual(entry['proof']['physical_stop']['supervisor_state'],'Z');self.assertFalse(entry['proof']['physical_stop']['absent'])
        self.assertEqual(entry['proof']['original_ui'],p['original_ui']);self.assertIs(result['authorizes_submission'],False)
        self.assertEqual(self.module().observe_actions_retirement(store,p,'git:'+'5'*40)['record'],result['record'])

    def test_real_git_legacy_wrong_birth_live_process_and_substituted_worker_rejected(self):
        import os
        pid,birth=self.zombie();old,p,store,cap=self.authenticated(legacy=True,supervisor_pid=pid,supervisor_birth=birth)
        for kind in ['birth','worker','live']:
            bad=copy.deepcopy(p)
            if kind=='birth':
                bad['physical_stop']['supervisor_birth']='999';bad['original_registry']['receipt']['supervisor_birth']='999'
            elif kind=='worker':
                bad['physical_stop']['worker_pids']=[os.getpid()];bad['physical_stop']['executor_pid']=os.getpid()
                bad['original_registry']['worker_pids']=[os.getpid()];bad['original_registry']['worker_births']={str(os.getpid()):None};bad['original_registry']['receipt']['worker_pid']=os.getpid()
            else:
                from managed_executor_runtime import _process
                bad['physical_stop']['supervisor_pid']=os.getpid();bad['physical_stop']['supervisor_birth']=_process(os.getpid())['birth']
                bad['original_registry']['receipt'].update(supervisor_proc_pid=os.getpid(),supervisor_birth=bad['physical_stop']['supervisor_birth'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.module().authenticate_actions_retirement(store,bad,p['evidence'],NOW)
        self.assertEqual(store.read()[1],old)

    def test_real_git_changed_raw_ui_range_or_mapping_never_authorizes_write(self):
        pid,birth=self.zombie();old,p,store,cap=self.authenticated(legacy=True,supervisor_pid=pid,supervisor_birth=birth,ranged_ui=True)
        bad=copy.deepcopy(p);bad['original_ui']['evidence_ref']='altered raw observation'
        with self.assertRaisesRegex(ValueError,'authenticated'):self.module().authenticate_actions_retirement(store,bad,p['evidence'],NOW)
        bad=copy.deepcopy(p);bad['workflow_mapping']['workflow_id']=1
        with self.assertRaises(ValueError):self.module().authenticate_actions_retirement(store,bad,p['evidence'],NOW)
        bad=copy.deepcopy(p);bad['evidence']['original_ui']['range_sha256']='sha256:'+'0'*64
        with self.assertRaisesRegex(ValueError,'range'):self.module().authenticate_actions_retirement(store,bad,bad['evidence'],NOW)
        self.assertEqual(store.read()[1],old)

class OwnershipLaunchBindingTests(unittest.TestCase):
    module=Tests.module
    retire=Tests.retire
    setUp=GitTests.setUp
    authenticated=GitTests.authenticated
    zombie=LegacyGitTests.zombie

    def repin_registry(self,p,store):
        repo=store.repo
        def git(*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
        git('checkout','-B','evidence',p['lease_revision'])
        body={k:p[k] for k in p['evidence'] if k!='workflow_definition'}
        raw=(json.dumps(body,sort_keys=True,indent=2)+'\n').encode();(repo/'evidence.json').write_bytes(raw)
        git('add','evidence.json');git('-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','Synthetic independently pinned mixed registry')
        revision=git('rev-parse','HEAD');git('push','origin','HEAD:refs/heads/cdc/actions-evidence');git('push','origin','HEAD:'+store.ref)
        p['lease_revision']=revision
        for name in body:p['evidence'][name].update(revision=revision,sha256='sha256:'+hashlib.sha256(raw).hexdigest())
        return p

    def test_mixed_prior_task_attempt_cannot_join_original_ownership_even_in_proposal(self):
        old,p=legacy_fixture(*actions_fixture())
        request=p['original_registry']['request'];request['identity'].update(task_id='different-task',attempt_id='different-prior-attempt')
        receipt=p['original_registry']['receipt'];receipt.update(identity=copy.deepcopy(request['identity']),request_ref=op._hash(request))
        with self.assertRaisesRegex(ValueError,'capability|ownership|launch|registry'):self.retire(old,p)

    def test_native_authenticated_owned_revision_must_exist_on_original_history(self):
        pid,birth=self.zombie();old,p,store,cap=self.authenticated(legacy=True,supervisor_pid=pid,supervisor_birth=birth)
        p['original_registry']['owned']['lease_revision']='f'*40
        self.repin_registry(p,store)
        with self.assertRaises(ValueError):self.module().authenticate_actions_retirement(store,p,p['evidence'],NOW)
        self.assertEqual(store.read()[1],old)

    def test_original_owned_revision_cannot_be_replaced_with_released_lease(self):
        pid,birth=self.zombie();old,p,store,cap=self.authenticated(legacy=True,supervisor_pid=pid,supervisor_birth=birth)
        p['original_registry']['owned']['lease_revision']=p['original_lease_revision'];self.repin_registry(p,store)
        with self.assertRaises(ValueError):self.module().authenticate_actions_retirement(store,p,p['evidence'],NOW)
        self.assertEqual(store.read()[1],old)

    def test_hash_matching_descriptor_cannot_be_minted_or_relabelled(self):
        old,p=legacy_fixture(*actions_fixture())
        for change in ['hash','intent','invocation','pool_revision']:
            bad=copy.deepcopy(p);registry=bad['original_registry']
            if change=='hash':registry['owned']['capability_ref']='sha256:'+'0'*64
            elif change=='intent':registry['intent']['invocation_id']='different-original'
            elif change=='invocation':registry['capability_descriptor']['payload']['invocation_id']='different-original'
            else:registry['capability_descriptor']['payload']['managed_store_revision']='f'*40
            with self.subTest(change=change),self.assertRaises(ValueError):self.retire(old,bad)
