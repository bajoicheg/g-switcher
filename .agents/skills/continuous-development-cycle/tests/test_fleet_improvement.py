from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from fleet_improvement import harvest
class T(unittest.TestCase):
 def test_one(self):
  d=json.loads((ROOT/"templates"/"fleet-improvement-harvest.json").read_text())
  r=harvest(d)
  self.assertEqual(r["proposal_count"],1)
if __name__=="__main__":
 unittest.main()
