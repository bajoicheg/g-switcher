"""Two original channels and real preconsume guardian waits; local Git only."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
if __package__:
    from . import test_native_unknown_recovery as fixture
else:
    import test_native_unknown_recovery as fixture
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_remote_identity import remote_identity
import execution_lease_v2 as lease
import operation_intent as op
from managed_executor_runtime import _digest as native_digest, _process, _boot


class TwoChannelTests(unittest.TestCase):
    git=fixture.IntakeTests.git
    api=fixture.IntakeTests.api
    proof=fixture.IntakeTests.proof

    def setUp(self):
        fixture.IntakeTests.setUp(self)
        project=self.root/'project';remote=self.root/'project.git'
        self.git('init','--bare',str(remote),cwd=self.root)
        self.git('clone','--no-local',str(self.repo),str(project),cwd=self.root)
        self.git('remote','set-url','origin',str(remote),cwd=project)
        self.git('push','origin','HEAD:refs/heads/main',cwd=project)
        self.source=GitLeaseStore(project,'origin','refs/heads/cdc/source-lease')
        source_record=lease.initialize('example/project','refs/heads/main')
        self.srev=self.source.compare_and_swap(None,source_record)
        from project_budget_store import GitProjectBudgetStore, ledger_digest
        ledger=copy.deepcopy(self.row['budget'])
        blob=self.source._git('hash-object','-w','--stdin',input=json.dumps(ledger))
        mode,lease_blob=self.source._lease_entry(self.srev)
        tree=self.source._git('mktree',input=f'100644 blob {blob}\tbudget.json\n{mode} blob {lease_blob}\tlease.json\n')
        commit=self.source._git('commit-tree',tree,'-p',self.srev,input='Original charged project budget\n')
        self.source._git('push','origin',commit+':'+self.source.ref);self.srev=commit
        self.project_budget=GitProjectBudgetStore(project,'origin',{'schema':'project-budget-binding/v1',
            'repository':'example/project','source_ref':'refs/heads/main','coordination_ref':self.source.ref,
            'coordination_store_id':self.source.store_id,'ledger_path':'budget.json','budget_field':None,
            'task_id':ledger['task_id'],'anchor_revision':commit,'anchor_ledger_digest':ledger_digest(ledger),
            'wake_authorizations':{}})
        self.req.update(repo_root=str(project),coordination_remote='origin',source_remote_id=self.source.store_id)
        self.req['plan']['coordination_store_id']=self.source.store_id
        self.row['operation']['start_request_digest']=native_digest(self.req)
        self.nonce='a'*32;self.row['operation']['guardian']['nonce']=self.nonce
        self.store=GitDocumentStore(self.repo,'origin','refs/heads/cdc/two-channel-intake',remote_identity(self.repo,'origin'))
        self.pins['channels']={'intake_store_id':self.store.store_id,'intake_ref':self.store.ref,
            'lease_store_id':self.source.store_id,'lease_ref':self.source.ref,
            'pool_store_id':self.source.store_id,'pool_ref':self.req['plan']['coordination_ref']}
        self.controller=self.root/'controllers'/'task-one'
        guardian_code=r'''import pathlib,subprocess,sys,json,time,hashlib
from datetime import datetime,timezone
p=pathlib.Path(sys.argv[1]);nonce=sys.argv[2]
def identity(pid):
 raw=pathlib.Path('/proc',str(pid),'stat').read_text();birth=raw[raw.rfind(')')+2:].split()[19]
 return {'pid':pid,'birth':birth,'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
with (p/(nonce+'.stdout')).open('xb') as out,(p/(nonce+'.stderr')).open('xb') as err:
 child=subprocess.Popen([sys.executable,'-B','-c','import sys,time;time.sleep(.15);print("CDC_VPS_ORIGINAL_CONTROLLER_RECONCILIATION_REQUIRED",file=sys.stderr);sys.exit(2)'],stdout=out,stderr=err)
 birth=identity(child.pid);code=child.wait()
receipt={'schema':'cdc-vps-controller-wait/v1','task_id':'task-one','identity':identity(__import__('os').getpid()),'controller':birth,'exit_code':code,'observed_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
for label in ('stdout','stderr'):
 path=p/(nonce+'.'+label);receipt[label+'_path']=str(path);receipt[label+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
with (p/(nonce+'.receipt.json')).open('x') as out:json.dump(receipt,out)
sys.exit(code)
'''
        with (self.controller/(self.nonce+'.guardian.stdout')).open('xb') as out,(self.controller/(self.nonce+'.guardian.stderr')).open('xb') as err:
            guardian=subprocess.Popen([sys.executable,'-B','-c',guardian_code,str(self.controller),self.nonce],stdout=out,stderr=err)
            birth=_process(guardian.pid);self.assertIsNotNone(birth)
            self.guardian={'pid':guardian.pid,'birth':birth['birth'],'boot_id':_boot()}
            self.assertEqual(guardian.wait(timeout=5),2)
        for path in self.controller.iterdir():path.chmod(0o640)
        self.wait_path=self.controller/(self.nonce+'.receipt.json')
        self.wait=json.loads(self.wait_path.read_text())
        self.assertEqual(self.wait['identity'],self.guardian)
        self.row['operation']['guardian']['identity']=self.guardian
        self.rev=self.store.compare_and_swap(None,{'schema':'cdc-vps-control/v1','tasks':{'task-one':self.row}})
        self.pins.update(original_revision=self.rev,row_digest=op._hash(self.row),source_revision=self.srev,
            source_digest=op._hash(source_record),guardian=self.guardian,guardian_nonce=self.nonce)
        self.pins['preconsume_exit']={'schema':'native-preconsume-controller-exit/v1','controller':self.wait['controller'],
            'receipt_sha256':self.hash(self.wait_path),'stdout_sha256':self.hash(self.controller/(self.nonce+'.stdout')),
            'stderr_sha256':self.hash(self.controller/(self.nonce+'.stderr')),
            'guardian_stdout_sha256':self.hash(self.controller/(self.nonce+'.guardian.stdout')),
            'guardian_stderr_sha256':self.hash(self.controller/(self.nonce+'.guardian.stderr'))}

    def hash(self,path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    def authenticate(self,pins=None):
        return self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=self.source,
            trusted_contract=pins or self.pins,at='2026-10-14T12:00:00Z')

    def test_original_bounded_site_is_documentary_without_terminal_or_refund(self):
        raw = (b'CDC_VPS_ORIGINAL_CONTROLLER_RECONCILIATION_REQUIRED\n'
               b'CDC_VPS_REJECTION_CODE=CONTRACT_OR_SCOPE_REJECTED\n'
               b'CDC_VPS_REJECTION_SITE={"function": "_validate_retired_once", "line": 192, '
               b'"module": "cdc_vps.state", "type": "ValueError"}\n')
        stderr = self.controller / (self.nonce + '.stderr')
        stderr.write_bytes(raw)
        self.wait['stderr_sha256'] = hashlib.sha256(raw).hexdigest()
        self.wait_path.write_text(json.dumps(self.wait))
        self.pins['preconsume_exit'].update(stderr_sha256=self.hash(stderr),
            receipt_sha256=self.hash(self.wait_path))
        self.creator_wait()
        before = self.source.read(), self.project_budget.read()
        proof = self.authenticate()
        result = self.api().retire_prelaunch_intake_cas(self.store, self.rev, 'task-one', proof, at=proof._at)
        entry = result['row']['result']['administrative_disposition']
        self.assertEqual(entry['original_effect'], 'UNKNOWN')
        self.assertIsNone(entry['actual_wait'])
        self.assertEqual(entry['original_row'], self.row)
        self.assertEqual(result['row']['budget'], self.row['budget'])
        self.assertEqual((self.source.read(), self.project_budget.read()), before)
        self.assertEqual(stderr.read_bytes(), raw)
        observed = self.api().observe_prelaunch_intake_disposition(self.store, 'task-one',
            contract_digest=native_digest(self.req))
        self.assertEqual(observed.revalidate_for(self.store, 'task-one')['state'], 'retired_unknown')

    def test_site_grammar_is_closed_and_cannot_carry_authority_or_extra_output(self):
        accepts = self.api()._preconsume_rejection_stderr
        marker = b'CDC_VPS_ORIGINAL_CONTROLLER_RECONCILIATION_REQUIRED\n'
        prefix = marker + b'CDC_VPS_REJECTION_CODE=CONTRACT_OR_SCOPE_REJECTED\n'
        site = {'module': 'cdc_vps.state', 'function': '_validate_retired_once',
                'line': 192, 'type': 'ValueError'}
        encode = lambda value: b'CDC_VPS_REJECTION_SITE=' + json.dumps(value).encode() + b'\n'
        self.assertTrue(accepts(marker))
        self.assertTrue(accepts(prefix))
        self.assertTrue(accepts(prefix + encode(site)))
        unavailable = dict(site, module='unavailable', function='unavailable', line=0)
        self.assertTrue(accepts(prefix + encode(unavailable)))
        for bad in (dict(site, authorizes_slot_release=True), dict(site, line=True),
                    dict(site, line=-1), dict(site, line=2**31), dict(site, module='/tmp/x'),
                    dict(site, module='x'*257), dict(site, function='x'*97),
                    dict(site, type='ValueError: secret'), dict(site, module='a..b')):
            with self.subTest(site=bad): self.assertFalse(accepts(prefix + encode(bad)))
        for bad in (marker + encode(site), prefix + encode(site) + b'extra\n',
                    prefix + encode(site)[:-1], prefix + b'CDC_VPS_REJECTION_SITE={}\n',
                    prefix + b'CDC_VPS_REJECTION_SITE={"line":1,"line":2}\n',
                    prefix + b'CDC_VPS_REJECTION_SITE=' + b' '*1025 + b'{}\n',
                    prefix + b'CDC_VPS_REJECTION_SITE=\xff\n'):
            with self.subTest(raw=bad[:100]): self.assertFalse(accepts(bad))

    def test_two_original_endpoints_and_actual_wait_retire_without_terminal_or_refund(self):
        self.assertNotEqual(self.source.store_id,self.store.store_id)
        before=self.source.read();budget_before=self.project_budget.read();proof=self.authenticate();m=self.api()
        result=m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')
        self.assertEqual(result['row']['budget'],self.row['budget']);self.assertEqual(self.source.read(),before);self.assertEqual(self.project_budget.read(),budget_before)
        entry=result['row']['result']['administrative_disposition']
        self.assertIsNone(entry['actual_wait']);self.assertEqual(entry['original_effect'],'UNKNOWN')
        self.assertEqual(entry['original_row'],self.row)
        # Default observation must derive the original project channel, not Root.
        observed=m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req))
        self.assertEqual(observed._source.store_id,self.source.store_id)
        self.assertEqual(observed.revalidate_for(self.store,'task-one')['state'],'retired_unknown')

    def creator_wait(self):
        path = self.controller / (self.nonce + '.guardian-wait.json')
        value = {'schema': 'cdc-vps-guardian-wait/v1', 'task_id': 'task-one',
            'identity': self.guardian, 'nonce': self.nonce, 'exit_code': 2,
            'observed_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'authorizes_slot_release': False}
        for stream in ('stdout', 'stderr'):
            raw = self.controller / (self.nonce + '.guardian.' + stream)
            value[stream + '_path'] = str(raw)
            value[stream + '_sha256'] = hashlib.sha256(raw.read_bytes()).hexdigest()
        path.write_text(json.dumps(value)); path.chmod(0o640)
        self.pins['creator_guardian_wait'] = {'schema': 'native-creator-guardian-wait/v1', 'sha256': self.hash(path)}
        return path, value

    def test_actual_creator_guardian_wait_is_documentary_and_preserved(self):
        path, _ = self.creator_wait(); before = path.read_bytes()
        proof = self.authenticate()
        result = self.api().retire_prelaunch_intake_cas(self.store, self.rev, 'task-one', proof, at=proof._at)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['row']['budget'], self.row['budget'])
        self.assertIsNone(result['row']['result']['administrative_disposition']['actual_wait'])
        self.assertEqual(result['row']['result']['administrative_disposition']['original_effect'], 'UNKNOWN')

    def test_creator_wait_fields_and_explicit_hash_cannot_be_substituted(self):
        path, value = self.creator_wait()
        for kind in ('schema', 'task_id', 'identity', 'nonce', 'exit_code', 'observed_at_utc',
                     'authorizes_slot_release', 'stdout_path', 'stderr_sha256', 'extra', 'hash', 'pin'):
            with self.subTest(kind=kind):
                changed = copy.deepcopy(value); pins = copy.deepcopy(self.pins)
                if kind == 'identity': changed[kind]['birth'] = '999'
                elif kind == 'exit_code': changed[kind] = 0
                elif kind == 'authorizes_slot_release': changed[kind] = True
                elif kind == 'observed_at_utc': changed[kind] = '2000-01-01T00:00:00Z'
                elif kind == 'extra': changed[kind] = 'unregistered'
                elif kind not in ('hash', 'pin'): changed[kind] = 'foreign'
                path.write_text(json.dumps(changed))
                pins['creator_guardian_wait']['sha256'] = self.hash(path)
                if kind == 'hash': pins['creator_guardian_wait']['sha256'] = 'sha256:' + '0'*64
                if kind == 'pin': del pins['creator_guardian_wait']
                with self.assertRaises(ValueError): self.authenticate(pins)

    def test_creator_wait_nonregular_or_mutable_custody_is_rejected(self):
        path, value = self.creator_wait(); raw = path.read_bytes()
        for kind in ('mode', 'symlink', 'fifo', 'hardlink'):
            with self.subTest(kind=kind):
                path.unlink()
                extra = self.root / ('creator-' + kind)
                if kind == 'symlink': extra.write_bytes(raw); path.symlink_to(extra)
                elif kind == 'fifo': os.mkfifo(path, 0o640)
                else:
                    path.write_bytes(raw); path.chmod(0o660 if kind == 'mode' else 0o640)
                    if kind == 'hardlink': os.link(path, extra)
                with self.assertRaises(ValueError): self.authenticate()

    def test_channels_cannot_be_omitted_substituted_or_borrowed_from_root(self):
        for key in (None,'intake_store_id','intake_ref','lease_store_id','lease_ref','pool_store_id','pool_ref'):
            with self.subTest(key=key):
                pins=copy.deepcopy(self.pins)
                if key is None:del pins['channels']
                else:pins['channels'][key]=self.store.store_id if key.endswith('store_id') else 'refs/heads/cdc/foreign'
                if key=='intake_store_id':pins['channels'][key]=self.source.store_id
                with self.assertRaises(ValueError):self.authenticate(pins)
        with self.assertRaises(ValueError):self.api().authenticate_prelaunch_intake(self.store,'task-one',source_store=GitLeaseStore(self.repo,'origin',self.source.ref),trusted_contract=self.pins,at='2026-10-14T12:00:00Z')

    def test_wait_artifacts_cannot_be_general_static_pins(self):
        pins=copy.deepcopy(self.pins);del pins['preconsume_exit']
        for path in self.controller.iterdir():
            pins['artifact_pins'][str(path)]={'sha256':self.hash(path),'uid':os.getuid(),'gid':os.getgid(),'mode':0o640}
        with self.assertRaises(ValueError):self.authenticate(pins)
        extra=self.controller/'extra-receipt.json';extra.write_text('{}');extra.chmod(0o640)
        with self.assertRaises(ValueError):self.authenticate()

    def test_wait_nonce_birth_status_schema_paths_and_raw_hashes_are_authenticated(self):
        original=self.wait_path.read_bytes()
        for kind in ('nonce','birth','guardian','status','schema','path','raw_hash','missing'):
            with self.subTest(kind=kind):
                wait=copy.deepcopy(self.wait);pins=copy.deepcopy(self.pins)
                if kind=='nonce':pins['guardian_nonce']='b'*32
                if kind=='birth':wait['controller']['birth']='999'
                if kind=='guardian':wait['identity']['birth']='999'
                if kind=='status':wait['exit_code']=0
                if kind=='schema':wait['schema']='foreign/v1'
                if kind=='path':wait['stderr_path']=str(self.root/'unrelated')
                if kind=='raw_hash':wait['stderr_sha256']='0'*64
                if kind=='missing':wait.pop('observed_at_utc')
                self.wait_path.write_text(json.dumps(wait));pins['preconsume_exit']['receipt_sha256']=self.hash(self.wait_path)
                with self.assertRaises(ValueError):self.authenticate(pins)
                self.wait_path.write_bytes(original)
        stderr=self.controller/(self.nonce+'.stderr');raw=stderr.read_bytes();stderr.write_text('unrelated rejection\n')
        pins=copy.deepcopy(self.pins);pins['preconsume_exit']['stderr_sha256']=self.hash(stderr)
        self.wait['stderr_sha256']=hashlib.sha256(stderr.read_bytes()).hexdigest();self.wait_path.write_text(json.dumps(self.wait));pins['preconsume_exit']['receipt_sha256']=self.hash(self.wait_path)
        with self.assertRaises(ValueError):self.authenticate(pins)
        stderr.write_bytes(raw)

    def test_mutable_receipt_mode_forged_uid_live_reused_and_zombie_controller_fail_closed(self):
        self.wait_path.chmod(0o660)
        with self.assertRaises(ValueError):self.authenticate()
        self.wait_path.chmod(0o640)
        pins=copy.deepcopy(self.pins);pins['custody']['controller_uid']=os.getuid()+1
        with self.assertRaises(ValueError):self.authenticate(pins)
        for name in ('creator','controller'):
            pins=copy.deepcopy(self.pins);current={'pid':os.getpid(),'birth':_process(os.getpid())['birth'],'boot_id':_boot()}
            if name=='creator':pins['creator']=current
            else:
                pins['preconsume_exit']['controller']=current;wait=copy.deepcopy(self.wait);wait['controller']=current
                self.wait_path.write_text(json.dumps(wait));pins['preconsume_exit']['receipt_sha256']=self.hash(self.wait_path)
            with self.assertRaises(ValueError):self.authenticate(pins)
        self.wait_path.write_text(json.dumps(self.wait));self.pins['preconsume_exit']['receipt_sha256']=self.hash(self.wait_path)
        pid=os.fork()
        if pid==0:os._exit(0)
        try:
            deadline=time.monotonic()+2
            while _process(pid)['state']!='Z' and time.monotonic()<deadline:time.sleep(.01)
            pins=copy.deepcopy(self.pins);identity={'pid':pid,'birth':_process(pid)['birth'],'boot_id':_boot()}
            pins['preconsume_exit']['controller']=identity;wait=copy.deepcopy(self.wait);wait['controller']=identity
            self.wait_path.write_text(json.dumps(wait));pins['preconsume_exit']['receipt_sha256']=self.hash(self.wait_path)
            with self.assertRaises(ValueError):self.authenticate(pins)
        finally:os.waitpid(pid,0)

    def test_consumed_history_native_effect_and_changed_source_or_budget_block(self):
        proof=self.authenticate();doc=self.store.read()[1]
        self.api().consume_intake_start(self.store,self.rev,'task-one',start_request_digest=native_digest(self.req),controller_identity={'pid':os.getpid(),'birth':_process(os.getpid())['birth'],'boot_id':_boot()})
        with self.assertRaises(ValueError):self.authenticate()
        with self.assertRaises(ValueError):self.api().retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')

    def test_original_project_pool_or_publication_effect_blocks_on_its_own_endpoint(self):
        import uuid
        from managed_host_bridge import _canonical
        identity={'repo_root':str(self.source.repo),'store':self.source.store_id,
            'coordination_ref':self.req['plan']['coordination_ref'],'pool_id':self.req['plan']['pool_id'],
            'task_id':self.req['task_id'],'attempt_id':self.req['attempt_id']}
        handle=str(uuid.uuid5(uuid.NAMESPACE_URL,_canonical(identity)))
        for ref in (self.req['plan']['coordination_ref'],'refs/heads/cdc/managed-host-publish-'+handle.replace('-','')):
            with self.subTest(ref=ref):
                effect=GitDocumentStore(self.source.repo,self.source.remote,ref,self.source.store_id)
                effect.compare_and_swap(None,{'schema':'fixture-effect/v1'})
                with self.assertRaises(ValueError):self.authenticate()
                self.git('push','origin',':'+ref,cwd=self.source.repo)

    def test_fifo_receipt_is_rejected_without_waiting_for_a_writer(self):
        self.wait_path.unlink();os.mkfifo(self.wait_path,0o640)
        probe=self.root/'fifo-probe.json'
        probe.write_text(json.dumps({'row':self.row,'pins':self.pins,'controller':str(self.controller),
            'guardian_pin':self.pins['artifact_pins'][str(self.controller/'guardian.lock')]}))
        code="""import json,pathlib,sys
sys.path.insert(0,sys.argv[1]);import unknown_recovery
value=json.loads(pathlib.Path(sys.argv[2]).read_text())
print('ARTIFACT_PROBE_STARTED',flush=True)
try:unknown_recovery._preconsume_artifacts(value['row'],value['pins'],pathlib.Path(value['controller']),value['guardian_pin'])
except ValueError as error:
 assert str(error)=='protected original wait artifact custody required',str(error)
 print('NONREGULAR_ARTIFACT_REJECTED',flush=True)
else:raise AssertionError('FIFO accepted as original wait receipt')
"""
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(__file__).resolve().parents[1]/'scripts'),str(probe)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:stdout,stderr=child.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill();stdout,stderr=child.communicate()
            self.assertIn('ARTIFACT_PROBE_STARTED',stdout)
            self.fail('artifact validator blocked on FIFO before regular-file validation')
        self.assertEqual(child.returncode,0,stdout+stderr)
        self.assertIn('NONREGULAR_ARTIFACT_REJECTED',stdout)

    def test_changed_native_source_budget_fails_without_administrative_outcome(self):
        revision,ledger=self.project_budget.read()
        event={'type':'outcome','event_id':'contradictory-close','task_id':ledger['task_id'],'wake_id':'wake-one',
            'at_utc':'2026-10-14T11:00:00Z','reservation_id':'original-start','status':'failed',
            'usage':{'tokens':None,'elapsed_seconds':1},'failure':{'signature':'fixture','category':'infrastructure'}}
        self.project_budget.append_event(revision,event)
        with self.assertRaises(ValueError):self.authenticate()
        self.assertEqual(self.store.read()[1]['tasks']['task-one'],self.row)

    def test_lost_tombstone_reply_observes_original_two_channels_without_cas_replay(self):
        proof=self.authenticate();m=self.api();actual=self.store.compare_and_swap;calls=[]
        def lost(*args,**kwargs):calls.append(args[0]);actual(*args,**kwargs);raise OSError('lost reply')
        self.store.compare_and_swap=lost
        with self.assertRaises(OSError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')
        observed=m.observe_prelaunch_intake_disposition(self.store,'task-one',contract_digest=native_digest(self.req))
        self.assertEqual(observed['original_effect'],'UNKNOWN')
        with self.assertRaises(ValueError):m.retire_prelaunch_intake_cas(self.store,self.rev,'task-one',proof,at='2026-10-14T12:00:00Z')
        self.assertEqual(calls,[self.rev])


if __name__=='__main__':unittest.main()
