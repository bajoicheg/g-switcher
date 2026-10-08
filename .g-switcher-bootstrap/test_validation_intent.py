import pathlib,sys,unittest
from unittest.mock import patch
PACKAGE=pathlib.Path(__file__).resolve().parent.parent/'word-hang-task/cdc2121'
sys.path.insert(0,str(PACKAGE/'tests'))
import test_managed_host_bridge as fixture
import operation_intent as operation
import execution_lease_v2 as leasev2
import controller

class IntentSourceBinding(unittest.TestCase):
 def test_prepared_validation_can_arm_real_owned_project_guard(self):
  f=fixture.ManagedHostBridgeTests('runTest');f.setUp()
  try:
   request=f.start_request();request['plan']['tasks'][0].update(role='read_only',branch=None,worktree=None,write_paths=[]);request['argv']=[sys.executable,'-c','print("readonly")']
   handle=fixture.bridge.start(request)
   binding={'repository':'test/project','candidate_sha':f.base,'backend':'github_actions','mode':'CI_ONLY','check_suite_fingerprint':'sha256:'+'1'*64,'environment_fingerprint':'sha256:'+'2'*64,'check_plan_digest':'sha256:'+'3'*64,'environment_id':'windows-test'}
   with patch.object(controller,'SOURCE','refs/heads/main'):
    intent=controller.prepare_validation_intent(operation,binding,'windows-test-a1')
   receipt=operation.verify_readback(intent,intent,'test:durable-intent',controller.utc())
   intent=operation.transition(intent,'submitting',controller.utc(),receipt=receipt)
   _,record=f.lease_store.read()
   guarded=leasev2.set_guard(record,handle['owner_id'],handle['generation'],handle['invocation_id'],controller.utc(),intent,'test:intent')
   self.assertEqual(guarded['external_guard']['intent']['source_ref'],record['source_ref'])
  finally:f.doCleanups()
