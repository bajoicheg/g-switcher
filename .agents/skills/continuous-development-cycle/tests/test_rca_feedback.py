from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from rca_feedback import disposition
class T(unittest.TestCase):
 def test_reinforce(self):
  d=json.loads((ROOT/"templates"/"rca-feedback.json").read_text())
  r=disposition(d)
  self.assertEqual(r["action"],"REINFORCE_EXISTING")
if __name__=="__main__":
 unittest.main()
