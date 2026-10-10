import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import recovery_recipes as m
CAT={"schema":"recovery-recipe-catalog/v1","recipes":[{"id":"orphan","diagnosis_code":"orphan_lease","priority":10,"requires_all":["invocation:completed"],"forbids":["external:running"],"actions":["inspect_exact_invocation","verify_pending_writes","reconcile_external"],"outcome":"reconcile"}]}
class T(unittest.TestCase):
 def test_exact_recipe(self):d={"schema":"recovery-diagnosis/v1","code":"orphan_lease","facts":["invocation:completed"],"reference":"health:1"};r=m.select(CAT,d);self.assertEqual(r["recipe_id"],"orphan");self.assertFalse(r["authorizes_takeover"])
 def test_forbidden_fact_blocks(self):d={"schema":"recovery-diagnosis/v1","code":"orphan_lease","facts":["invocation:completed","external:running"],"reference":"health:1"};self.assertEqual(m.select(CAT,d)["reason"],"no_deterministic_recipe")
 def test_arbitrary_action_rejected(self):
  bad={"schema":"recovery-recipe-catalog/v1","recipes":[dict(CAT["recipes"][0],actions=["shell"])]}
  with self.assertRaises(ValueError):m.validate_catalog(bad)
if __name__=="__main__":unittest.main()
