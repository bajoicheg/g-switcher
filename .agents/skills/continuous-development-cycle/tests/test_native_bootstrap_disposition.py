"""Actual guardian bootstrap failure, original preparation, and old reader custody."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
if __package__:
    from . import test_native_unknown_recovery as fixture
else:
    import test_native_unknown_recovery as fixture
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_remote_identity import remote_identity
from project_budget_store import GitProjectBudgetStore, ledger_digest
import budget
import execution_lease_v2 as lease
import operation_intent as op
from managed_executor_runtime import _digest as native_digest


class BootstrapTests(unittest.TestCase):
    git=fixture.IntakeTests.git
    api=fixture.IntakeTests.api

    def setUp(self):
        fixture.IntakeTests.setUp(self)
        project=self.root/'project';remote=self.root/'project.git'
        self.git('init','--bare',str(remote),cwd=self.root)
        self.git('clone','--no-local',str(self.repo),str(project),cwd=self.root)
        self.git('remote','set-url','origin',str(remote),cwd=project)
        self.git('push','origin','HEAD:refs/heads/main',cwd=project)
        self.source=GitLeaseStore(project,'origin','refs/heads/cdc/source-lease')
        self.srev=self.source.compare_and_swap(None,lease.initialize('example/project','refs/heads/main'))
        project_ledger=budget.new_ledger('retained-project','wake-one',self.row['budget']['policy'])
        blob=self.source._git('hash-object','-w','--stdin',input=json.dumps(project_ledger))
        mode,lease_blob=self.source._lease_entry(self.srev)
        tree=self.source._git('mktree',input=f'100644 blob {blob}\tbudget.json\n{mode} blob {lease_blob}\tlease.json\n')
        anchor=self.source._git('commit-tree',tree,'-p',self.srev,input='Original project budget\n')
        self.source._git('push','origin',anchor+':'+self.source.ref)
        binding={'schema':'project-budget-binding/v1','repository':'example/project','source_ref':'refs/heads/main',
            'coordination_ref':self.source.ref,'coordination_store_id':self.source.store_id,'ledger_path':'budget.json',
            'budget_field':None,'task_id':'retained-project','anchor_revision':anchor,
            'anchor_ledger_digest':ledger_digest(project_ledger),'wake_authorizations':{}}
        self.project_budget=GitProjectBudgetStore(project,'origin',binding)
        self.req.update(repo_root=str(project),coordination_remote='origin',source_remote_id=self.source.store_id)
        self.req['plan']['coordination_store_id']=self.source.store_id
        self.row['task'].update(role='read_only',max_runtime_seconds=30,budget={'compute_starts':1,'agent_starts':0,
            'ci_starts':0,'tool_calls':16,'elapsed_seconds':30,'tokens':None})
        self.row['budget']['events']=self.row['budget']['events'][:1]
        self.store=GitDocumentStore(self.repo,'origin','refs/heads/cdc/bootstrap-intake',remote_identity(self.repo,'origin'))
        queued=copy.deepcopy(self.row);queued.update(state='queued',operation=None);queued['budget']['events']=[]
        self.parent=self.store.compare_and_swap(None,{'schema':'cdc-vps-control/v1','tasks':{'task-one':queued}})
        binding_intent=self.row['operation']['intent']['binding']
        prepared=op.prepare(binding_intent,'attempt-one','refs/heads/main','2026-10-14T01:00:00Z')
        event={'type':'reserve','event_id':'vps-task-one-original-compute-start','task_id':'retained-project',
            'wake_id':'wake-one','at_utc':'2026-10-14T01:00:00Z','operation_key':prepared['operation_key'],
            'attempt_id':'attempt-one','kind':'compute_start','scope':'registered-vps-project-adoption:task-one',
            'recovery_ref':None,'cost':{'tool_calls':16,'tokens':None,'elapsed_seconds':30}}
        proposal={'schema':'cdc-vps-project-budget-preparation/v1','project_id':self.row['task']['project_id'],
            'project_task_id':'retained-project','root_task_id':'task-one','attempt_id':'attempt-one',
            'operation_key':prepared['operation_key'],'registration_digest':'sha256:'+'4'*64,
            'budget_binding_digest':native_digest(binding),'start_request_digest':native_digest(self.req),
            'prepared_budget_revision':anchor,'event':event,'event_digest':native_digest(event),'authorizes_launch':False}
        self.row['state']='reserved';self.row['operation'].pop('guardian')
        self.row['operation'].update(intent=prepared,start_request_digest=native_digest(self.req),
            reservation_preparation={'schema':'cdc-vps-reservation-preparation/v1','root_parent_revision':self.parent,
                'project_budget':proposal})
        self.prepared_revision=self.store.compare_and_swap(self.parent,{'schema':'cdc-vps-control/v1','tasks':{'task-one':self.row}})
        self.project_budget.append_event(anchor,event)
        self.srev=self.project_budget.read()[0]
        receipt=copy.deepcopy(proposal);receipt.update(schema='cdc-vps-original-project-budget/v1',reservation_revision=self.srev);del receipt['prepared_budget_revision']
        durable=op.verify_readback(prepared,prepared,self.store.ref+'@'+self.prepared_revision+':tasks/task-one/operation/intent','2026-10-14T01:00:01Z')
        self.row['operation'].update(project_budget=receipt,intent=op.transition(prepared,'submitting','2026-10-14T01:00:01Z',receipt=durable))
        revision=self.store.compare_and_swap(self.prepared_revision,{'schema':'cdc-vps-control/v1','tasks':{'task-one':self.row}})
        self.nonce='b'*32;self.controller=self.root/'controllers'/'task-one'
        # The real creator observes a real guardian's birth, then reaps it. No
        # controller is forked and no wait receipt is manufactured for the SDK.
        creator_code=r'''import pathlib,subprocess,sys,json,os
p=pathlib.Path(sys.argv[1]);nonce=sys.argv[2]
def identity(pid):
 raw=pathlib.Path('/proc',str(pid),'stat').read_text();return {'pid':pid,'birth':raw[raw.rfind(')')+2:].split()[19],'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
with (p/(nonce+'.guardian.stdout')).open('xb') as out,(p/(nonce+'.guardian.stderr')).open('xb') as err:
 child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.15);raise ValueError("original guardian birth never persisted; no child launch")'],stdout=out,stderr=err)
 observation={'creator':identity(os.getpid()),'guardian':identity(child.pid)}
 pathlib.Path(sys.argv[3]).write_text(json.dumps(observation));child.wait()
'''
        observation=self.root/'process-observation.json'
        creator=subprocess.Popen([sys.executable,'-B','-c',creator_code,str(self.controller),self.nonce,str(observation)])
        self.assertEqual(creator.wait(timeout=5),0)
        identities=json.loads(observation.read_text())
        for path in self.controller.iterdir():path.chmod(0o640)
        self.row['state']='running';self.row['operation']['guardian']={'nonce':self.nonce,'identity':identities['guardian']}
        self.rev=self.store.compare_and_swap(revision,{'schema':'cdc-vps-control/v1','tasks':{'task-one':self.row}})
        self.pins.update(original_revision=self.rev,row_digest=op._hash(self.row),source_revision=self.srev,
            source_digest=op._hash(self.source.read()[1]),creator=identities['creator'],guardian=identities['guardian'],guardian_nonce=self.nonce)
        self.pins['channels']={'intake_store_id':self.store.store_id,'intake_ref':self.store.ref,'lease_store_id':self.source.store_id,
            'lease_ref':self.source.ref,'pool_store_id':self.source.store_id,'pool_ref':self.req['plan']['coordination_ref']}
        self.pins['guardian_bootstrap_failure']={'schema':'native-guardian-bootstrap-failure/v1',
            'stdout_sha256':self.hash(self.controller/(self.nonce+'.guardian.stdout')),
            'stderr_sha256':self.hash(self.controller/(self.nonce+'.guardian.stderr'))}
        self.pins['preparation_budget']={'binding':binding,'registration_digest':proposal['registration_digest']}
        registered=self.root/'launch'/'executor-one'/'task-one'/'registered-record.json'
        registered.write_text(json.dumps({'schema':'cdc-vps-launch/v1','task':self.row['task'],'registry':{},
            'task_digest':native_digest(self.row['task']),'executor':'executor-one'}))
        self.pins['artifact_pins'][str(registered)]['sha256']=self.hash(registered)

    def hash(self,path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    def authenticate(self,pins=None):
        return self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,
            project_budget_store=self.project_budget,trusted_contract=pins or self.pins,at='2026-10-14T12:00:00Z')

    def test_actual_bootstrap_streams_and_durable_preparation_retire_without_wait_or_refund(self):
        before=self.source.read();project_before=self.project_budget.read();m=self.api()
        result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',self.authenticate(),at='2026-10-14T12:00:00Z')
        entry=result['row']['result']['administrative_disposition']
        self.assertEqual(result['row']['operation'],self.row['operation']);self.assertEqual(result['row']['budget'],self.row['budget'])
        self.assertEqual(entry['original_effect'],'UNKNOWN');self.assertIsNone(entry['actual_wait'])
        self.assertEqual(self.source.read(),before);self.assertEqual(self.project_budget.read(),project_before)
        self.assertFalse(any(self.controller.glob('*.receipt.json')))
        observed=m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req))
        self.assertEqual(observed.revalidate_for(self.store,'task-one')['state'],'retired_unknown')

    def test_bootstrap_cannot_be_static_or_claim_a_wait_or_hide_other_artifacts(self):
        for name in ('extra','wait','marker','mode','hash','mixed'):
            with self.subTest(name=name):
                pins=copy.deepcopy(self.pins);stderr=self.controller/(self.nonce+'.guardian.stderr');original=stderr.read_bytes();extra=None
                if name=='extra':extra=self.controller/'unrelated';extra.write_text('effect');extra.chmod(0o640)
                if name=='wait':extra=self.controller/(self.nonce+'.receipt.json');extra.write_text('{}');extra.chmod(0o640)
                if name=='marker':stderr.write_text('ValueError: other failure\n');pins['guardian_bootstrap_failure']['stderr_sha256']=self.hash(stderr)
                if name=='mode':stderr.chmod(0o660)
                if name=='hash':pins['guardian_bootstrap_failure']['stderr_sha256']='sha256:'+'0'*64
                if name=='mixed':pins['preconsume_exit']={}
                try:
                    with self.assertRaises(ValueError):self.authenticate(pins)
                finally:
                    if extra:extra.unlink()
                    stderr.write_bytes(original);stderr.chmod(0o640)
        pins=copy.deepcopy(self.pins);del pins['guardian_bootstrap_failure']
        with self.assertRaises(ValueError):self.authenticate(pins)

    def test_project_receipt_progress_requires_original_typed_budget_and_event(self):
        pins=copy.deepcopy(self.pins);pins['preparation_budget']['registration_digest']='sha256:'+'0'*64
        with self.assertRaises(ValueError):self.authenticate(pins)
        with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,trusted_contract=self.pins,at='2026-10-14T12:00:00Z')
        revision,ledger=self.project_budget.read()
        self.project_budget.append_event(revision,{'type':'outcome','event_id':'foreign-close','task_id':'retained-project',
            'wake_id':'wake-one','at_utc':'2026-10-14T02:00:00Z','reservation_id':'vps-task-one-original-compute-start',
            'status':'failed','usage':{'tokens':None,'elapsed_seconds':1},'failure':{'signature':'fixture','category':'infrastructure'}})
        with self.assertRaises(ValueError):self.authenticate()

    def test_consumed_history_receipt_erasure_or_substitution_cannot_be_hidden(self):
        for kind in ('receipt_removed','receipt_changed','controller'):
            with self.subTest(kind=kind):
                self.doCleanups();self.setUp()
                revision,document=self.store.read();changed=copy.deepcopy(document)
                if kind=='receipt_removed':changed['tasks']['task-one']['operation'].pop('project_budget')
                if kind=='receipt_changed':changed['tasks']['task-one']['operation']['project_budget']['event_digest']='sha256:'+'0'*64
                if kind=='controller':changed['tasks']['task-one']['operation']['controllers']=[]
                revised=self.store.compare_and_swap(revision,changed)
                self.store.compare_and_swap(revised,document)
                with self.assertRaises(ValueError):self.authenticate()

    def test_live_creator_guardian_native_effect_and_retirement_start_race_block(self):
        m=self.api();current={'pid':os.getpid(),'birth':m._process(os.getpid())['birth'],'boot_id':self.pins['creator']['boot_id']}
        pins=copy.deepcopy(self.pins);pins['creator']=current
        with self.assertRaises(ValueError):self.authenticate(pins)
        pins=copy.deepcopy(self.pins);pins['guardian']=current
        with self.assertRaises(ValueError):self.authenticate(pins)
        identity={'pool_id':self.req['plan']['pool_id'],'task_id':self.req['task_id'],'attempt_id':self.req['attempt_id']}
        journal=self.root/'journal'/native_digest(identity).split(':')[1];journal.mkdir(parents=True)
        try:
            with self.assertRaises(ValueError):self.authenticate()
        finally:journal.rmdir()
        proof=self.authenticate()
        m.consume_intake_start(self.store,self.store.read()[0],'task-one',start_request_digest=native_digest(self.req),controller_identity=current)
        with self.assertRaises(ValueError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')

    def test_bootstrap_fifo_stream_is_rejected_in_a_bounded_subprocess(self):
        stderr=self.controller/(self.nonce+'.guardian.stderr');stderr.unlink();os.mkfifo(stderr,0o640)
        probe=self.root/'fifo.json';probe.write_text(json.dumps({'row':self.row,'pins':self.pins,'controller':str(self.controller),
            'guardian_pin':self.pins['artifact_pins'][str(self.controller/'guardian.lock')]}))
        code="""import sys,pathlib,json
sys.path.insert(0,sys.argv[1]);import unknown_recovery as recovery
value=json.loads(pathlib.Path(sys.argv[2]).read_text())
try:recovery._bootstrap_artifacts(value['row'],value['pins'],pathlib.Path(value['controller']),value['guardian_pin'])
except ValueError as error:assert str(error)=='protected original bootstrap stream custody required'
else:raise AssertionError('FIFO accepted')
"""
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(__file__).resolve().parents[1]/'scripts'),str(probe)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:out,err=child.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill();child.communicate();self.fail('bootstrap stream validator blocked on FIFO')
        self.assertEqual(child.returncode,0,out+err)

    def test_lost_retirement_reply_observes_both_original_budgets_without_another_cas(self):
        proof=self.authenticate();m=self.api();original=self.store.compare_and_swap;calls=[]
        def lost(*args,**kwargs):calls.append(args[0]);original(*args,**kwargs);raise OSError('lost retirement reply')
        self.store.compare_and_swap=lost
        with self.assertRaises(OSError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')
        observed=m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req))
        self.assertIsNone(observed['actual_wait']);self.assertEqual(observed['original_effect'],'UNKNOWN')
        with self.assertRaises(ValueError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')
        self.assertEqual(calls,[self.rev]);self.assertEqual(self.project_budget.read()[1]['events'][-1]['type'],'reserve')

    def test_363_historical_reader_accepts_new_tombstone_and_preserves_replay_ban(self):
        legacy=os.environ.get('CDC_TEST_LEGACY_SDK_363_ROOT')
        if not legacy:self.skipTest('qualified 3.6.3 reader provided by adjacent qualification')
        result=self.api().retire_prelaunch_intake_cas(self.store,self.rev,'task-one',self.authenticate(),at='2026-10-14T12:00:00Z')
        code="""import pathlib,sys,json
root=pathlib.Path(sys.argv[1]);assert (root/'VERSION').read_text().strip()=='3.6.3'
sys.path.insert(0,str(root/'scripts'))
import unknown_recovery as recovery
from git_document_store import GitDocumentStore
assert pathlib.Path(recovery.__file__).resolve().parent==(root/'scripts').resolve()
store=GitDocumentStore(sys.argv[2],'origin',sys.argv[3],sys.argv[4]);entry=recovery.validate_prelaunch_disposition(store,'task-one')
assert entry['original_effect']=='UNKNOWN' and entry['actual_wait'] is None
row=store.read()[1]['tasks']['task-one'];task=dict(row['task'],id='new-name')
try:recovery.assert_new_intake_allowed(store,task)
except ValueError:pass
else:raise AssertionError('old reader admitted retired original contract')
print('SDK363_HISTORICAL_READER_COMPATIBLE_NO_REPLAY')
"""
        read=subprocess.run([sys.executable,'-B','-I','-c',code,legacy,str(self.repo),self.store.ref,self.store.store_id],capture_output=True,text=True,timeout=30)
        self.assertEqual(read.returncode,0,read.stdout+read.stderr)
        self.assertIn('SDK363_HISTORICAL_READER_COMPATIBLE_NO_REPLAY',read.stdout)


if __name__=='__main__':unittest.main()
