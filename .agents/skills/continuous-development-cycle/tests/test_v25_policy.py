import copy, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from contracts import ContractError, load_yaml
from validate_adapter import validate_adapter

class Tests(unittest.TestCase):
 def template(self):
  d=load_yaml(ROOT/"templates/development-cycle.yaml")
  d["policy"]["skill_min_version"]="2.5.0"
  for name in ("fleet","convergence","progress_slo","audit"):d.pop(name,None)
  return d
 def test_v25_template_valid(self):validate_adapter(self.template(),"2.5.0")
 def test_v25_requires_all_three_control_sections(self):
  for name in ("routing","recovery_recipes","continuation"):
   d=self.template();d.pop(name)
   with self.subTest(name=name),self.assertRaises(ContractError):validate_adapter(d,"2.5.0")
 def test_v25_controls_rejected_under_v24_floor(self):
  d=self.template();d["policy"]["skill_min_version"]="2.4.0"
  with self.assertRaises(ContractError):validate_adapter(d,"2.5.0")
 def test_duplicate_backend_preference_rejected(self):
  d=self.template();d["routing"]["backend_kind_preference"]=["codex_compute","codex_compute"]
  with self.assertRaises(ContractError):validate_adapter(d,"2.5.0")
 def test_event_wake_cannot_be_authority(self):
  d=self.template();d["continuation"]["event_wake_is_authority"]=True
  with self.assertRaises(ContractError):validate_adapter(d,"2.5.0")
if __name__=="__main__":unittest.main()
