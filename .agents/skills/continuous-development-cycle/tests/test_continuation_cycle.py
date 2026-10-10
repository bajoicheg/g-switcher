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
if __name__=="__main__":
 unittest.main()
