from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from branch_finish import evaluate

class T(unittest.TestCase):
 def base(self): return json.loads((ROOT/"templates"/"branch-finish.json").read_text())
 def test_ready_for_cdc_terminal_without_granting_merge(self):
  r=evaluate(self.base());self.assertTrue(r["ready"]);self.assertEqual(r["action"],"READY_FOR_CDC_TERMINAL")
  self.assertFalse(r["authorizes_merge"]);self.assertFalse(r["authorizes_release"])
 def test_stale_or_moved_candidate_blocks(self):
  d=self.base();d["validation_fresh"]=False;d["observed_head"]="2"*40
  r=evaluate(d);self.assertIn("validation_stale",r["blockers"]);self.assertIn("candidate_head_mismatch",r["blockers"])
 def test_open_findings_block(self):
  d=self.base();d["unresolved_findings"]=["spec discrepancy"]
  self.assertIn("unresolved_review_findings",evaluate(d)["blockers"])
 def test_review_green_required(self):
  d=self.base();d["spec_compliance_green"]=False
  self.assertIn("spec_compliance_not_green",evaluate(d)["blockers"])
 def test_required_check_sha_binding(self):
  d=self.base();d["required_checks"][0]["candidate_sha"]="3"*40
  self.assertIn("required_check_wrong_sha:unit",evaluate(d)["blockers"])
if __name__=="__main__": unittest.main()
