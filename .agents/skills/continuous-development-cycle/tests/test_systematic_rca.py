from pathlib import Path
import copy,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from systematic_rca import analyze
from rca_feedback import disposition

class T(unittest.TestCase):
 def base(self):
  return json.loads((ROOT/"templates"/"systematic-rca.json").read_text())
 def test_systematic_rca_feeds_bounded_disposition(self):
  r=analyze(self.base())
  self.assertEqual(r["root_cause_hypothesis_id"],"reconciliation-gap")
  self.assertTrue(r["ready_for_feedback_disposition"])
  self.assertFalse(r["authorizes_product_write"])
  self.assertFalse(r["authorizes_roadmap_write"])
  d=disposition(r["feedback"])
  self.assertEqual(d["action"],"REINFORCE_EXISTING")
  self.assertFalse(d["authorizes_roadmap_write"])
 def test_ambiguous_root_cause_rejected(self):
  d=self.base();d["hypotheses"][0]["supported"]=True
  with self.assertRaises(ValueError): analyze(d)
 def test_selected_must_be_supported(self):
  d=self.base();d["hypotheses"][1]["supported"]=False;d["hypotheses"][0]["supported"]=True
  with self.assertRaises(ValueError): analyze(d)

if __name__=="__main__":
 unittest.main()
