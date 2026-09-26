import unittest
from concurrent_writer import reconcile
def state(relation="equal",local=None,remote=None,guard=False):
 return {"schema":"writer-reconciliation/v1","expected_head":"1"*40,"observed_head":"2"*40 if relation!="equal" else "1"*40,
         "relation":relation,"local_changed_paths":local or [],"remote_changed_paths":remote or [],"pending_external_guard":guard}
class Tests(unittest.TestCase):
 def test_equal_proceeds(self):self.assertEqual(reconcile(state())["action"],"PROCEED")
 def test_nonoverlap_replays_on_fresh_head(self):
  r=reconcile(state("fast_forward",["a"],["b"]));self.assertEqual(r["action"],"REPLAY_ON_FRESH_HEAD");self.assertFalse(r["force_push_allowed"])
 def test_overlap_requires_reconcile(self):self.assertEqual(reconcile(state("fast_forward",["a"],["a"]))["reason"],"path_overlap")
 def test_divergence_never_force_pushes(self):
  r=reconcile(state("diverged",["a"],["b"]));self.assertEqual(r["action"],"RECONCILE_REQUIRED");self.assertFalse(r["force_push_allowed"])
 def test_guard_blocks_replay(self):self.assertEqual(reconcile(state("fast_forward",["a"],["b"],True))["reason"],"external_guard_present")
if __name__=="__main__":unittest.main()
