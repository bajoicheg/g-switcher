from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from migration_transaction import plan
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def state(self):return json.loads((ROOT/"templates"/"migration-transaction.json").read_text())
 def test_batch_reserves_finalization_budget(self):
  r=plan(self.state());self.assertEqual(r["action"],"APPLY_BATCH");self.assertEqual(r["batch_paths"],["vendor/a.txt","vendor/b.txt","vendor/c.txt"]);self.assertFalse(r["authorizes_ref_move"])
 def test_budget_that_would_consume_reserve_blocks(self):
  d=self.state();d["operation_budget"]=4;r=plan(d);self.assertEqual(r["action"],"BLOCKED_BUDGET");self.assertEqual(r["batch_paths"],[])
 def test_ready_requires_exact_tree_and_policy_but_still_no_authority(self):
  d=self.state();d["completed_paths"]=[x["path"] for x in d["items"]];d["final_tree_sha"]="6"*40;d["observed_subtree_tree"]=d["expected_subtree_tree"];d["policy_reconciled"]=True;r=plan(d);self.assertEqual(r["action"],"READY_TO_ADVANCE_REF");self.assertTrue(r["ref_move_prerequisites_satisfied"]);self.assertFalse(r["authorizes_ref_move"])
 def test_tree_drift_never_advances_ref(self):
  d=self.state();d["completed_paths"]=[x["path"] for x in d["items"]];d["final_tree_sha"]="6"*40;d["observed_subtree_tree"]="7"*40;d["policy_reconciled"]=True;r=plan(d);self.assertEqual(r["action"],"RECONCILE_TREE_DRIFT");self.assertFalse(r["authorizes_ref_move"])
if __name__=="__main__":unittest.main()
