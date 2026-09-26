import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import dogfood_metrics as m
class T(unittest.TestCase):
 def test_metrics(self):
  self.assertIn("command_timestamp_accuracy",m.METRICS)
  self.assertIn("feedback_loop_closure",m.METRICS)
if __name__=="__main__":
 unittest.main()
