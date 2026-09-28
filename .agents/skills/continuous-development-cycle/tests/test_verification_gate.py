from pathlib import Path
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from verification_gate import evaluate

class T(unittest.TestCase):
 def base(self):
  return json.loads((ROOT/"templates"/"verification-gate.json").read_text())
 def test_template_allows_terminal_claim_without_granting_authority(self):
  r=evaluate(self.base())
  self.assertTrue(r["allowed"])
  self.assertTrue(r["final_claim_allowed"])
  self.assertEqual(r["blockers"],[])
  for k in ("authorizes_product_write","authorizes_takeover","authorizes_external_start","authorizes_merge","authorizes_release","authorizes_scope_expansion"):
   self.assertFalse(r[k])
 def test_stale_source_blocks(self):
  d=self.base();d["authoritative_source_fresh"]=False
  self.assertIn("authoritative_source_stale",evaluate(d)["blockers"])
 def test_head_mismatch_blocks(self):
  d=self.base();d["observed_head"]="2"*40
  self.assertIn("source_head_mismatch",evaluate(d)["blockers"])
 def test_active_lease_or_guard_blocks(self):
  d=self.base();d["ownership"]["lease_state"]="active";d["ownership"]["guard_state"]="active"
  r=evaluate(d)
  self.assertIn("lease_not_released",r["blockers"])
  self.assertIn("guard_unreconciled",r["blockers"])
 def test_wrong_sha_check_and_artifact_block(self):
  d=self.base();d["required_checks"][0]["candidate_sha"]="3"*40;d["artifacts"][0]["candidate_sha"]="4"*40
  r=evaluate(d)
  self.assertIn("required_check_wrong_sha:package",r["blockers"])
  self.assertIn("artifact_wrong_sha:package-artifact",r["blockers"])
 def test_dirty_state_blocks(self):
  d=self.base();d["clean_state"]["clean"]=False
  self.assertIn("dirty_state",evaluate(d)["blockers"])

if __name__=="__main__":
 unittest.main()
