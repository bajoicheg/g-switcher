import copy, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from contracts import load_yaml, ContractError
from validate_checkpoint_24 import validate_checkpoint_24

class Tests(unittest.TestCase):
    def setUp(self):
        self.adapter=load_yaml(ROOT/"templates/development-cycle.yaml")
        self.data=load_yaml(ROOT/"templates/work-status-v4.md",frontmatter=True)
    def test_v4_template_validates(self): validate_checkpoint_24(self.data,self.adapter)
    def test_primitive_only_released_runnable_fails(self):
        d=copy.deepcopy(self.data); d["blocker"]="none"
        d["execution_continuity"].update(runnable_next_action=True,completion_gate="continue",primitive_steps_since_progress=2)
        with self.assertRaises(ContractError): validate_checkpoint_24(d,self.adapter)
    def test_progress_gate_requires_reference(self):
        d=copy.deepcopy(self.data); d["execution_continuity"].update(meaningful_progress=True,completion_gate="meaningful_progress",last_progress_ref=None)
        with self.assertRaises(ContractError): validate_checkpoint_24(d,self.adapter)
    def test_v3_remains_readable(self):
        old=load_yaml(ROOT/"templates/work-status.md",frontmatter=True); validate_checkpoint_24(old,self.adapter)

if __name__=="__main__": unittest.main()
