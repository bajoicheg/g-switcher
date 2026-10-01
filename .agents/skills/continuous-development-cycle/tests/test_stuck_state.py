import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import stuck_state as m
def o(a,h="a"*40,progress=False,result="provider"):
 return {"action_fingerprint":a,"head":h,"meaningful_progress":progress,"result_class":result}
class T(unittest.TestCase):
 def test_repeated_strategy_detected(self):
  r=m.detect({"schema":"stuck-state-input/v1","observations":[o("x"),o("x")],"repeat_threshold":2,"head_stall_threshold":5});self.assertTrue(r["stuck"]);self.assertEqual(r["action"],"CHANGE_STRATEGY")
 def test_head_stall_detected(self):
  r=m.detect({"schema":"stuck-state-input/v1","observations":[o("a"),o("b")],"repeat_threshold":5,"head_stall_threshold":2});self.assertTrue(r["stuck"])
 def test_progress_resets_head_stall(self):
  r=m.detect({"schema":"stuck-state-input/v1","observations":[o("a"),o("b",progress=True)],"repeat_threshold":5,"head_stall_threshold":2});self.assertFalse(r["stuck"])
if __name__=="__main__":unittest.main()
