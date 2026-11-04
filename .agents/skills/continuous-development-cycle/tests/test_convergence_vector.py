from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from convergence_vector import normalize
BASE={"schema":"cdc-convergence-observation/v1","repository":"owner/project","source_ref":"refs/heads/main","source_head":"1"*40,"cdc_version":"2.9.0","package_tree":"2"*40,"consumer_lock":{"version":"2.9.0","release_commit":"3"*40,"package_tree":"2"*40},"policy_digest":"sha256:"+"4"*64,"checkpoint":{"valid":True,"source_head":"1"*40,"policy_digest":"sha256:"+"4"*64},"lease":{"state":"released"},"guard":{"state":"none"},"adoption_state":"integrated"}
class T(unittest.TestCase):
 def test_exact_vector_integrates(self):
  r=normalize(copy.deepcopy(BASE));self.assertTrue(r["integrated"]);self.assertEqual(r["adoption_state"],"integrated");self.assertEqual(r["blockers"],[])
 def test_version_string_alone_cannot_integrate(self):
  d=copy.deepcopy(BASE);d["package_tree"]="5"*40
  r=normalize(d);self.assertFalse(r["integrated"]);self.assertIn("lock_tree_matches",r["blockers"])
 def test_checkpoint_must_bind_same_head_and_policy(self):
  d=copy.deepcopy(BASE);d["checkpoint"]["source_head"]="6"*40
  r=normalize(d);self.assertFalse(r["integrated"]);self.assertIn("checkpoint_head_matches",r["blockers"])
 def test_live_owner_or_guard_prevents_integrated(self):
  for key,value in (("lease",{"state":"owned"}),("guard",{"state":"running"})):
   d=copy.deepcopy(BASE);d[key]=value
   self.assertFalse(normalize(d)["integrated"])
if __name__=="__main__":unittest.main()
