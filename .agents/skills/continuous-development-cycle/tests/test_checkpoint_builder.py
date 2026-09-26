from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from contracts import load_yaml
from checkpoint_builder import build,validate_request
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def request(self):return json.loads((ROOT/"templates"/"typed-checkpoint-build.json").read_text())
 def test_builder_validates_real_checkpoint_before_return(self):
  base=load_yaml(ROOT/"templates"/"work-status-v4.md",frontmatter=True);adapter=load_yaml(ROOT/"templates"/"development-cycle.yaml");r=build(base,self.request(),adapter);self.assertIs(r["execution_continuity"]["runnable_next_action"],False)
 def test_boolean_display_text_is_never_coerced(self):
  d=self.request();d["execution_continuity"]["runnable_next_action"]="false"
  with self.assertRaises(ValueError):validate_request(d)
 def test_unknown_update_field_is_rejected(self):
  d=self.request();d["updates"]["made_up"]="x"
  with self.assertRaises(ValueError):validate_request(d)
if __name__=="__main__":unittest.main()
