import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import dogfood_metrics as m
def d():
 return {"schema":"cdc-dogfood-input/v1","window":"release:2.8.2","metrics":{n:{"pass_count":1,"total_count":1} for n in m.METRICS}}
class T(unittest.TestCase):
 def test_full_compliance_is_measurement_not_authority(self):
  r=m.measure(d());self.assertEqual(r["compliance_percent"],100.0);self.assertFalse(r["authorizes_release"]);self.assertFalse(r["authorizes_policy_change"])
 def test_partial_rate(self):
  x=d();x["metrics"]["no_idle_compliance"]={"pass_count":0,"total_count":1};self.assertLess(m.measure(x)["compliance_percent"],100)
if __name__=="__main__":unittest.main()
