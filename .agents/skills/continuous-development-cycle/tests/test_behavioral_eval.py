from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from behavioral_eval import evaluate_suite,validate_suite

class T(unittest.TestCase):
 def test_core_suite_red_to_green(self):
  d=json.loads((ROOT/"templates"/"behavioral-eval-suite.json").read_text())
  r=evaluate_suite(d)
  self.assertTrue(r["all_regressions_green"])
  self.assertEqual(r["case_count"],10)
  self.assertEqual(r["passed"],10)
  self.assertTrue(all(x["baseline"]=="RED" and x["corrected"]=="GREEN" for x in r["cases"]))
  self.assertFalse(r["authorizes_product_write"])
  self.assertFalse(r["authorizes_takeover"])
  self.assertFalse(r["authorizes_release"])
 def test_missing_core_scenario_fails(self):
  d=json.loads((ROOT/"templates"/"behavioral-eval-suite.json").read_text())
  d["cases"]=d["cases"][:-1]
  with self.assertRaises(ValueError): validate_suite(d)

if __name__=="__main__":
 unittest.main()
