"""Current closeout uses actual original runtime, not supplied PID booleans."""
import json,subprocess,sys,unittest,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_managed_host_bridge as native
import managed_host_bridge as bridge
import reporting_contract as reporting
from execution_efficiency import terminal_bundle

class NativeCloseoutTests(unittest.TestCase):
 def setUp(self):
  self.fixture=native.ManagedHostBridgeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
 def request(self,handle,finished):
  f=self.fixture;s=bridge._load_session(str(f.root/'handles'),handle['handle_id']);rt=bridge._runtime(s)
  observed=rt.observe(s['task_id'],s['attempt_id'])
  processes=observed.get('process_births',[])
  pids=list(dict.fromkeys([x['pid'] for x in processes]+[json.loads((Path(rt._request(s['task_id'],s['attempt_id'])['journal_directory'])/'terminal-lease-intent.json').read_text())['controller_proc_pid']]))
  post=bridge._continuity(s,s['result_commit'],finished['release_receipt']['release']['checkpoint_ref'],s['publication'],released=True)
  post['reporting_binding']['report']=reporting.capture(s['invocation_id'],'final','Исполнители проверены; неизменяемые результаты и очередь сохранены.')
  return {'schema':'terminal-bundle/v2','invocation_id':s['invocation_id'],'owned_lease':{'owner_id':s['owner_id'],'generation':s['generation']},'release_receipt':finished['release_receipt'],'continuity':post,'runtime_binding':{'handle_root':str(f.root/'handles'),'handle_id':handle['handle_id']},'runtime':{'status':'succeeded','quiescent':True,'process_ids':pids,'evidence_ref':'actual:runtime'},'pool':{'accepted':True,'integrated':True,'evidence_ref':'actual:pool'},'physical':[{'pid':pid,'absent':True,'observed_at_utc':bridge._utc(),'evidence_ref':'actual:process-observation'} for pid in pids],'remaining_queue':[]}
 def test_caller_absent_true_cannot_hide_still_alive_original_controller(self):
  f=self.fixture;handle=bridge.start(f.start_request());f.wait_for(handle,'awaiting_release');finished=bridge.finish(f.finish_request(handle))
  request=self.request(handle,finished)
  with self.assertRaisesRegex(ValueError,'physical PID still present'):
   terminal_bundle(request,f.lease_store)
 def test_managed_finish_is_preparatory_and_never_owner_final_while_controller_alive(self):
  f=self.fixture;handle=bridge.start(f.start_request());f.wait_for(handle,'awaiting_release');finished=bridge.finish(f.finish_request(handle))
  self.assertFalse(finished['final_response_allowed'])
  self.assertTrue(finished['managed_finish_allowed']);self.assertTrue(finished['controller_exit_required'])
  import final_response_gate
  request=self.request(handle,finished);authority=reporting.authenticate(f.lease_store,request['continuity']['reporting_binding'],handle['invocation_id'],request['continuity']['checkpoint_ref'])
  _,actual=f.lease_store.read();historical=f.lease_store.read_revision(finished['release_receipt']['lease_revision'])
  denied=final_response_gate.evaluate(handle['invocation_id'],actual,request['continuity'],request['owned_lease'],request['release_receipt'],historical,bridge._utc(),reporting_authority=authority)
  self.assertFalse(denied['final_response_allowed'])
 def test_local_controller_pid_substitution_is_not_canonical_absence(self):
  f=self.fixture;handle=bridge.start(f.start_request());f.wait_for(handle,'awaiting_release');finished=bridge.finish(f.finish_request(handle))
  session=bridge._load_session(str(f.root/'handles'),handle['handle_id']);rt=bridge._runtime(session)
  path=Path(rt._request(session['task_id'],session['attempt_id'])['journal_directory'])/'terminal-lease-intent.json'
  intent=json.loads(path.read_text());intent['controller_proc_pid']=99999999;intent['controller_birth']='1';path.write_text(json.dumps(intent))
  request=self.request(handle,finished)
  with self.assertRaisesRegex(ValueError,'controller.*binding'):
   terminal_bundle(request,f.lease_store)
 def test_actual_controller_exit_then_full_native_closeout(self):
  f=self.fixture;request_path=f.root/'start.json';request_path.write_text(json.dumps(f.start_request()))
  code=f.root/'controller.py';output=f.root/'controller-result.json'
  code.write_text('''import sys,json,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
import managed_host_bridge as b
from reporting_fixtures import binding
r=json.loads(Path(sys.argv[3]).read_text());h=b.start(r)
s=b._load_session(r['handle_root'],h['handle_id']);rt=b._runtime(s)
end=time.monotonic()+6
while time.monotonic()<end:
 if rt.observe(s['task_id'],s['attempt_id'])['status']=='awaiting_release':break
 time.sleep(.01)
cp='native-closeout:checkpoint'
fin=b.finish({'schema':'managed-host-finish/v2','handle_root':r['handle_root'],'handle_id':h['handle_id'],'output_refs':['out:closure'],'evidence_refs':['test:closure'],'checkpoint_ref':cp,'reporting_binding':binding(b._lease_store(s),h['invocation_id'],cp)})
Path(sys.argv[4]).write_text(json.dumps({'handle':h,'finished':fin}))
''')
  p=subprocess.run([sys.executable,'-B',str(code),str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parent),str(request_path),str(output)],capture_output=True,timeout=20)
  (f.root/'controller.stdout').write_bytes(p.stdout);(f.root/'controller.stderr').write_bytes(p.stderr)
  self.assertEqual(p.returncode,0,p.stderr.decode())
  result=json.loads(output.read_text());request=self.request(result['handle'],result['finished'])
  accepted=terminal_bundle(request,f.lease_store)
  self.assertTrue(accepted['accepted'],accepted.get('blockers'))
  self.assertTrue(accepted['native_terminal']['fresh_physical_absence'])
  self.assertTrue(accepted['reporting']['report']['text'].startswith('['))
  import final_response_gate
  session=bridge._load_session(str(f.root/'handles'),result['handle']['handle_id']);rt=bridge._runtime(session)
  proof=rt.verify_terminal(session['task_id'],session['attempt_id'],include_controller=True,lease_store=f.lease_store,release_receipt=request['release_receipt'])
  authority=reporting.authenticate(f.lease_store,request['continuity']['reporting_binding'],session['invocation_id'],request['continuity']['checkpoint_ref'])
  _,actual=f.lease_store.read();historical=f.lease_store.read_revision(request['release_receipt']['lease_revision'])
  arguments=(session['invocation_id'],actual,request['continuity'],request['owned_lease'],request['release_receipt'],historical,bridge._utc())
  self.assertFalse(final_response_gate.evaluate(*arguments,reporting_authority=authority,native_terminal=dict(proof))['final_response_allowed'])
  self.assertFalse(final_response_gate.evaluate(*arguments,reporting_authority=authority,native_terminal=True)['final_response_allowed'])
  self.assertTrue(final_response_gate.evaluate(*arguments,reporting_authority=authority,native_terminal=proof)['final_response_allowed'])

  # A rewritten local receipt is not the original canonical process set.
  session=bridge._load_session(str(f.root/'handles'),result['handle']['handle_id']);rt=bridge._runtime(session)
  path=Path(rt._request(session['task_id'],session['attempt_id'])['journal_directory'])/'receipt.json'
  observation=json.loads(path.read_text());original=observation['worker_pid'];observation['worker_pid']=99999998
  for row in observation['process_births']:
   if row['pid']==original:row.update(pid=99999998,birth='1')
  from managed_executor_runtime import _digest
  observation['quiescence_proof']['process_births_digest']=_digest(observation['process_births']);path.write_text(json.dumps(observation))
  with self.assertRaisesRegex(ValueError,'original canonical runtime process'):
   terminal_bundle(self.request(result['handle'],result['finished']),f.lease_store)


if __name__=='__main__':unittest.main()
