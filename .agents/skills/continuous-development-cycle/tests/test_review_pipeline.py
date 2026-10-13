from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from review_pipeline import evaluate

def finding(state="open",ref=None):
 return {"id":"finding-1","summary":"review concern","state":state,"resolution_ref":ref}

class T(unittest.TestCase):
 def base(self): return json.loads((ROOT/"templates"/"review-pipeline.json").read_text())
 def test_template_two_stage_green(self):
  r=evaluate(self.base());self.assertTrue(r["review_green"]);self.assertEqual(r["action"],"REVIEW_GREEN")
  self.assertFalse(r["authorizes_merge"]);self.assertFalse(r["authorizes_release"])
 def test_quality_cannot_precede_spec_green(self):
  d=self.base();d["spec_compliance"]={"state":"red","reviewer_ref":"reviewer:spec","sequence":1,"evidence_refs":["review:red"],"findings":[finding()]}
  r=evaluate(d);self.assertIn("quality_review_before_spec_green",r["blockers"]);self.assertFalse(r["review_green"])
 def test_reviewers_must_be_independent(self):
  d=self.base();d["code_quality"]["reviewer_ref"]="reviewer:spec"
  self.assertIn("reviewers_not_independent",evaluate(d)["blockers"])
 def test_open_findings_block_green(self):
  d=self.base();d["code_quality"]["findings"]=[finding()]
  self.assertIn("unresolved_quality_findings",evaluate(d)["blockers"])
 def test_dispositioned_finding_is_not_open(self):
  d=self.base();d["code_quality"]["findings"]=[finding("dispositioned","decision:accepted-risk-1")]
  r=evaluate(d);self.assertTrue(r["review_green"]);self.assertNotIn("unresolved_quality_findings",r["blockers"])
 def test_resolved_finding_requires_resolution_evidence(self):
  d=self.base();d["code_quality"]["findings"]=[finding("resolved",None)]
  with self.assertRaises(ValueError): evaluate(d)
 def test_non_material_change_does_not_require_review(self):
  d=self.base();d["material_change"]=False
  d["spec_compliance"]={"state":"not_run","reviewer_ref":None,"sequence":None,"evidence_refs":[],"findings":[]}
  d["code_quality"]={"state":"not_run","reviewer_ref":None,"sequence":None,"evidence_refs":[],"findings":[]}
  r=evaluate(d);self.assertTrue(r["review_green"]);self.assertEqual(r["action"],"REVIEW_NOT_REQUIRED")
 def test_quality_required_after_spec(self):
  d=self.base();d["code_quality"]={"state":"not_run","reviewer_ref":None,"sequence":None,"evidence_refs":[],"findings":[]}
  self.assertIn("code_quality_review_required",evaluate(d)["blockers"])
if __name__=="__main__": unittest.main()
