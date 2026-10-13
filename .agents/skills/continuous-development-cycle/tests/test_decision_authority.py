import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import decision_authority as m
def q():
 return {"schema":"decision-request/v1","action_id":"a","risk":"low","reversibility":"reversible","scope":"existing","destructive":False,"requires_secret":False,"protected_gate":False,"policy_preapproved":True,"authorization_ref":"policy:a"}
class T(unittest.TestCase):
 def test_reversible_preapproved_in_scope_auto(self):self.assertEqual(m.classify(q())["decision"],"AUTO_EXECUTE")
 def test_irreversible_requires_human(self):
  x=q();x["reversibility"]="irreversible";self.assertEqual(m.classify(x)["decision"],"REQUIRE_HUMAN")
 def test_expanded_scope_requires_human(self):
  x=q();x["scope"]="expanded";self.assertEqual(m.classify(x)["decision"],"REQUIRE_HUMAN")
 def test_missing_authority_blocks(self):
  x=q();x["authorization_ref"]=None;self.assertEqual(m.classify(x)["decision"],"BLOCKED")
 def test_classifier_never_creates_authority(self):self.assertFalse(m.classify(q())["creates_authority"])
if __name__=="__main__":unittest.main()
