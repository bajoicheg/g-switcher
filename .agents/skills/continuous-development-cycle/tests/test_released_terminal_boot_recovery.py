"""Real failed worker/release chain; boot changes are isolated kernel inputs only."""
import copy,json,os,subprocess,sys,time,unittest,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import test_managed_host_bridge as fixture_module
import managed_host_bridge as bridge
import managed_executor_runtime as runtime
import managed_boot_transition as boots

class ReleasedBootTerminalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.fixture=fixture_module.ManagedHostBridgeTests();cls.fixture.setUp()
  cls.addClassCleanup(cls.fixture.doCleanups)
  f=cls.fixture;request=f.start_request()
  request['argv']=[sys.executable,'-c',getattr(cls,'worker_code','import time,sys;time.sleep(.4);sys.exit(7)')]
  start=f.root/'start.json';start.write_text(json.dumps(request));output=f.root/'finished.json'
  code='''import sys,json,time
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[2]]
import managed_host_bridge as b
from reporting_fixtures import binding
r=json.loads(Path(sys.argv[3]).read_text());h=b.start(r)
end=time.monotonic()+10
while time.monotonic()<end:
 if b.observe({'schema':'managed-host-observe/v1','handle_root':r['handle_root'],'handle_id':h['handle_id']})['runtime_status']=='awaiting_release':break
 time.sleep(.01)
s=b._load_session(r['handle_root'],h['handle_id']);cp='failed-original:checkpoint'
fin=b.finish({'schema':'managed-host-finish/v2','handle_root':r['handle_root'],'handle_id':h['handle_id'],'output_refs':['out:closure'],'evidence_refs':['test:closure'],'checkpoint_ref':cp,'reporting_binding':binding(b._lease_store(s),h['invocation_id'],cp)})
Path(sys.argv[4]).write_text(json.dumps({'handle':h,'finished':fin}))
'''
  completed=subprocess.run([sys.executable,'-B','-c',code,str(ROOT/'scripts'),str(ROOT/'tests'),str(start),str(output)],capture_output=True,timeout=25)
  if completed.returncode:raise AssertionError(completed.stderr.decode())
  result=json.loads(output.read_text());cls.session=bridge._load_session(str(f.root/'handles'),result['handle']['handle_id'])
  cls.rt=bridge._runtime(cls.session);cls.request=cls.rt._request('closure','closure-a1')
  deadline=time.monotonic()+4
  while time.monotonic()<deadline:
   cls.observation=cls.rt.observe('closure','closure-a1')
   if cls.observation.get('quiescent') and all(runtime._process(x['pid']) is None for x in cls.observation.get('process_births',[])):break
   time.sleep(.01)
  else:raise AssertionError('real failed supervisor not quiescent')
  if cls.observation['status']!='failed' or cls.session['state']!='released' or cls.session.get('publication') is not None:raise AssertionError('real original failure/release required')
  last=max(datetime.fromisoformat(cls.observation['quiescence_proof']['observed_at_utc'].replace('Z','+00:00')),datetime.fromisoformat(cls.session['release_receipt']['release']['at_utc'].replace('Z','+00:00')))+timedelta(seconds=1)
  cls.host=boots._current_host();cls.host['boot_id']=str(uuid.uuid4());cls.host['boot_epoch_us']=int((last+timedelta(seconds=1)).timestamp()*1000000)
  cls.now=(last+timedelta(seconds=3)).isoformat().replace('+00:00','Z')
  cls.record={'schema':'managed-original-boot-transition/v1',**{k:cls.request['identity'][k] for k in ('pool_id','task_id','attempt_id')},'request_ref':boots._digest(cls.request),'release_ref':boots._digest(cls.session['release_receipt']),'original_boot_id':cls.observation['boot_id'],'current_host':cls.host,'last_original_journal_epoch_us':int(last.timestamp()*1000000),'observed_at_utc':cls.now}
 def setUp(self):
  self.record=copy.deepcopy(type(self).record)
  for patch in [mock.patch.object(runtime,'_boot',return_value=self.host['boot_id']),mock.patch.object(boots,'_current_host',return_value=self.host),mock.patch.object(boots,'_now',return_value=self.now),mock.patch.object(boots,'_read_root_record',side_effect=lambda _:copy.deepcopy(self.record))]:
   patch.start();self.addCleanup(patch.stop)
 def verify(self):
  method=getattr(self.rt,'verify_released_terminal_after_reboot',None)
  self.assertIsNotNone(method,'explicit original released-failure boot reconciliation is missing')
  return method('closure','closure-a1',lease_store=self.fixture.lease_store,release_receipt=self.session['release_receipt'],boot_transition_path='/root/isolated-boot-fixture.json')
 def test_authentic_released_failure_issues_sealed_proof_without_state_or_source_effects(self):
  before=self.rt.store.read();head=self.fixture.remote_head();lease=self.fixture.lease_store.read()
  proof=self.verify()
  self.assertIs(type(proof),runtime.VerifiedTerminalProof);self.assertEqual(proof['status'],'failed')
  self.assertEqual(proof['boot_id'],self.observation['boot_id'])
  self.assertEqual(proof['boot_reconciliation']['current_boot_id'],self.host['boot_id'])
  self.assertFalse(proof['authorizes_release'])
  self.assertEqual(self.rt.store.read(),before);self.assertEqual(self.fixture.remote_head(),head);self.assertEqual(self.fixture.lease_store.read(),lease)
 def test_ordinary_verifier_keeps_original_same_boot_requirement(self):
  with self.assertRaisesRegex(ValueError,'birth/request/boot'):
   self.rt.verify_terminal('closure','closure-a1',include_controller=True,lease_store=self.fixture.lease_store,release_receipt=self.session['release_receipt'])
 def test_changed_request_or_release_cannot_reconcile(self):
  for key in ('request_ref','release_ref'):
   original=self.record[key];self.record[key]='sha256:'+'0'*64
   with self.subTest(key=key),self.assertRaises(ValueError):self.verify()
   self.record[key]=original
 def test_proof_revalidation_rechecks_original_root_record(self):
  proof=self.verify();owner=proof['ownership']
  expected={'owner_id':owner['owner_id'],'generation':owner['generation']}
  self.assertEqual(proof.revalidate_for(self.fixture.lease_store,owner['invocation_id'],expected,self.session['release_receipt'])['status'],'failed')
  self.record['request_ref']='sha256:'+'0'*64
  with self.assertRaises(ValueError):proof.revalidate_for(self.fixture.lease_store,owner['invocation_id'],expected,self.session['release_receipt'])
 def test_original_capability_boot_cannot_be_relabelled_as_current(self):
  path=Path(self.request['journal_directory'])/'terminal-capability-descriptor.json';raw=path.read_bytes()
  value=json.loads(raw);value['payload']['boot_id']=self.host['boot_id'];path.write_text(json.dumps(value))
  try:
   with self.assertRaisesRegex(ValueError,'controller.*boot|capability'):self.verify()
  finally:path.write_bytes(raw)
 def test_still_present_original_controller_remains_a_denial(self):
  descriptor=json.loads((Path(self.request['journal_directory'])/'terminal-capability-descriptor.json').read_text())
  original=descriptor['payload']['controller_proc_pid'];real=runtime._process
  with mock.patch.object(runtime,'_process',side_effect=lambda pid:{'birth':'1'} if pid==original else real(pid)),self.assertRaisesRegex(ValueError,'physical PID still present'):self.verify()
 def test_missing_root_record_never_falls_back_to_old_boot_receipt(self):
  with mock.patch.object(boots,'_read_root_record',side_effect=ValueError('protected record unavailable')),self.assertRaisesRegex(ValueError,'protected record'):self.verify()

if __name__=='__main__':unittest.main()
