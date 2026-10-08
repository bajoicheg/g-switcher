"""Real canonical acquire/failed release/guard inheritance/resolve/successful release."""
import pathlib,sys,time,unittest,uuid
PACKAGE=pathlib.Path(__file__).resolve().parent.parent/'word-hang-task/cdc2121'
sys.path.insert(0,str(PACKAGE/'tests'))
import test_managed_host_bridge as fixture
import operation_intent as op
import execution_lease_v2 as leasev2
import controller

class InheritedGuard(unittest.TestCase):
 def test_new_managed_owner_resolves_exact_old_failed_claim(self):
  f=fixture.ManagedHostBridgeTests('runTest');f.setUp()
  try:
   request=f.start_request();request['plan']['tasks'][0].update(role='read_only',branch=None,worktree=None,write_paths=[]);request['argv']=[sys.executable,'-c','raise SystemExit(1)']
   first=fixture.bridge.start(request)
   binding={'repository':'test/project','candidate_sha':f.base,'backend':'github_actions','mode':'CI_ONLY','check_suite_fingerprint':'sha256:'+'1'*64,'environment_fingerprint':'sha256:'+'2'*64,'check_plan_digest':'sha256:'+'3'*64,'environment_id':'windows-test'}
   intent=op.prepare(binding,'prior-ci-a1','refs/heads/main',controller.utc());receipt=op.verify_readback(intent,intent,'test:intent',controller.utc());intent=op.transition(intent,'submitting',controller.utc(),receipt=receipt)
   rev,record=f.lease_store.read();record=leasev2.set_guard(record,first['owner_id'],1,first['invocation_id'],controller.utc(),intent,'test:intent');rev=f.lease_store.compare_and_swap(rev,record)
   claim=leasev2.claim_submission(f.lease_store,rev,'test/project','refs/heads/main',first['owner_id'],1,first['invocation_id'],controller.utc(),intent_digest=op._hash(intent))
   observe={'schema':'managed-host-observe/v1','handle_root':request['handle_root'],'handle_id':first['handle_id']};deadline=time.monotonic()+10
   while fixture.bridge.observe(observe)['runtime_status']!='awaiting_release':self.assertLess(time.monotonic(),deadline);time.sleep(.05)
   finished=fixture.bridge.finish({'schema':'managed-host-finish/v1','handle_root':request['handle_root'],'handle_id':first['handle_id'],'output_refs':['failure:worker:failed'],'evidence_refs':['failure:test'],'checkpoint_ref':None})
   self.assertTrue(finished['final_response_allowed']);self.assertIsNone(f.lease_store.read()[1]['owner_id']);self.assertIsNotNone(f.lease_store.read()[1]['external_guard'])
   second_request=f.start_request();second_request['plan']['pool_id']='second-managed-pool';second_request['plan']['coordination_ref']='refs/heads/cdc/second-managed-pool';second_request['plan']['tasks'][0].update(role='read_only',branch=None,worktree=None,write_paths=[]);second_request['argv']=[sys.executable,'-c','print("readonly")'];second_request['attempt_id']='closure-a2';second_request['owner_id']=str(uuid.uuid4())
   second=fixture.bridge.start(second_request);self.assertEqual(second['generation'],2)
   rev,record=f.lease_store.read();self.assertEqual(record['external_guard']['submission_claim'],claim['grant'])
   task={'task_id':'prior-run:1','task_url':'https://example.invalid/prior','operation_key':intent['operation_key'],'attempt_id':intent['attempt_id'],'binding':binding,'state':'terminal','conclusion':'setup_failed','evidence_refs':['test:authenticated-failure-before-compute']}
   observation={'schema':'operation-observation/v1','operation_key':intent['operation_key'],'observed_at_utc':controller.utc(),'lookup_complete':True,'tasks':[task]}
   record=leasev2.clear_guard(record,second['owner_id'],2,second['invocation_id'],controller.utc(),observation,'test:terminal-proof');f.lease_store.compare_and_swap(rev,record)
   self.assertEqual(record['submission_resolutions'][-1]['generation'],1);self.assertEqual(record['submission_resolutions'][-1]['grant_id'],claim['grant']['grant_id'])
   observe['handle_id']=second['handle_id'];deadline=time.monotonic()+10
   while fixture.bridge.observe(observe)['runtime_status']!='awaiting_release':self.assertLess(time.monotonic(),deadline);time.sleep(.05)
   finish={'schema':'managed-host-finish/v1','handle_root':request['handle_root'],'handle_id':second['handle_id'],'output_refs':['out:closure'],'evidence_refs':['test:closure'],'checkpoint_ref':'test:old-effect-resolved-readonly'}
   self.assertTrue(fixture.bridge.finish(finish)['final_response_allowed']);self.assertIsNone(f.lease_store.read()[1]['owner_id']);self.assertIsNone(f.lease_store.read()[1]['external_guard'])
  finally:f.doCleanups()
