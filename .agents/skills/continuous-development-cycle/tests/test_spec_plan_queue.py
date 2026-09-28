from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from spec_plan_queue import evaluate

class T(unittest.TestCase):
 def base(self): return json.loads((ROOT/"templates"/"spec-plan-queue.json").read_text())
 def test_template_maps_runnable_task(self):
  r=evaluate(self.base())
  self.assertTrue(r["ready"]);self.assertEqual([x["task_id"] for x in r["continuation_items"]],["task-2"])
  self.assertFalse(r["brainstorming_required"]);self.assertFalse(r["authorizes_product_write"])
 def test_ambiguous_requires_brainstorming(self):
  d=self.base();d["ambiguity_state"]="ambiguous"
  self.assertIn("brainstorming_required_for_ambiguity",evaluate(d)["blockers"])
 def test_clear_does_not_require_brainstorming(self):
  d=self.base();d["ambiguity_state"]="clear";d["brainstorming_ref"]=None
  self.assertTrue(evaluate(d)["ready"])
 def test_complete_task_requires_evidence(self):
  d=self.base();d["tasks"][0]["evidence_refs"]=[]
  self.assertIn("complete_task_missing_evidence:task-1",evaluate(d)["blockers"])
 def test_runnable_task_requires_continuation(self):
  d=self.base();d["continuation_queue"]=[]
  self.assertIn("runnable_task_missing_continuation:task-2",evaluate(d)["blockers"])
 def test_cyclic_plan_is_rejected(self):
  d=self.base();d["tasks"][0]["dependencies"]=["task-2"]
  with self.assertRaises(ValueError): evaluate(d)
if __name__=="__main__": unittest.main()
