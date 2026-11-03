from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from continuation_cycle import decide
class T(unittest.TestCase):
 def test_continue(self):
  d=json.loads((ROOT/"templates"/"continuation-cycle.json").read_text())
  r=decide(d)
  self.assertEqual(r["action"],"CONTINUE_NOW")
  self.assertFalse(r["final_response_allowed"])
 def test_caller_progress_boolean_and_complete_label_are_not_final_authority(self):
  d=json.loads((ROOT/"templates"/"continuation-cycle.json").read_text())
  state=d['terminal_state'];state.update(decision='COMPLETE',runnable_actions=[],lease_released=True,completion_evidence_refs=['caller:complete'])
  self.assertFalse(decide(d)['final_response_allowed'])
if __name__=="__main__":
 unittest.main()
