import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from contracts import ContractError, load_yaml
from validate_adapter import validate_adapter
class T(unittest.TestCase):
 def template(self):
  d=load_yaml(ROOT/"templates/development-cycle.yaml")
  d["policy"]["skill_min_version"]="2.6.0"
  d["convergence"]["target_version"]="2.6.0"
  for name in ("autonomy","publication","hardening","maturity"):d.pop(name,None)
  return d
 def test_v26_template_valid(self):validate_adapter(self.template(),"2.6.0")
 def test_requires_all_v26_sections(self):
  for name in ("fleet","convergence","progress_slo","audit"):
   d=self.template();d.pop(name)
   with self.subTest(name=name),self.assertRaises(ContractError):validate_adapter(d,"2.6.0")
 def test_v26_controls_rejected_under_v25_floor(self):
  d=self.template();d["policy"]["skill_min_version"]="2.5.0"
  with self.assertRaises(ContractError):validate_adapter(d,"2.6.0")
 def test_fleet_cannot_gain_product_authority(self):
  d=self.template();d["fleet"]["product_write_authority"]=True
  with self.assertRaises(ContractError):validate_adapter(d,"2.6.0")
 def test_primitive_activity_cannot_be_progress(self):
  d=self.template();d["progress_slo"]["primitive_activity_is_progress"]=True
  with self.assertRaises(ContractError):validate_adapter(d,"2.6.0")
 def test_stalled_threshold_must_exceed_degraded(self):
  d=self.template();d["progress_slo"]["stalled_after_seconds"]=d["progress_slo"]["degraded_after_seconds"]
  with self.assertRaises(ContractError):validate_adapter(d,"2.6.0")
if __name__=="__main__":unittest.main()
