from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from policy_migration import plan
BASE={"schema":"policy-migration-request/v1","expected_source_head":"1"*40,"observed_source_head":"1"*40,"current_policy_yaml":"schema: x\nunmanaged:\n  keep: true\nmaturity:\n  old: true\n","desired_sections":{"maturity":{"old":True,"transactional":True}}}
class T(unittest.TestCase):
 def test_apply_preserves_unmanaged_and_repeated_is_noop(self):
  first=plan(copy.deepcopy(BASE));self.assertEqual(first["action"],"APPLY");self.assertIn("unmanaged:",first["rendered_policy_yaml"])
  again=copy.deepcopy(BASE);again["current_policy_yaml"]=first["rendered_policy_yaml"];second=plan(again);self.assertEqual(second["action"],"NOOP");self.assertEqual(second["rendered_policy_yaml"],first["rendered_policy_yaml"])
 def test_head_move_requires_fresh_replan_without_render(self):
  d=copy.deepcopy(BASE);d["observed_source_head"]="2"*40;r=plan(d);self.assertEqual(r["action"],"REPLAN_ON_FRESH_HEAD");self.assertIsNone(r["rendered_policy_yaml"]);self.assertFalse(r["authorizes_product_write"])
 def test_duplicate_top_level_yaml_is_rejected(self):
  d=copy.deepcopy(BASE);d["current_policy_yaml"]="schema: x\nmaturity: {}\nmaturity: {}\n"
  with self.assertRaises(ValueError):plan(d)
if __name__=="__main__":unittest.main()
