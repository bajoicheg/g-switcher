import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import ref_hygiene as m
def inv():
 return {"schema":"ref-inventory/v1","policy":{"max_terminal_age_days":7,"deletable_prefixes":["refs/heads/review/","refs/heads/migration/","refs/heads/backup/"],"protected_prefixes":["refs/heads/release/"]},"refs":[]}
def r(name,**kw):
 d={"name":name,"head":"a"*40,"age_days":30,"terminal":True,"protected":False,"open_pr":False,"unreconciled_guard":False,"referenced":False};d.update(kw);return d
class T(unittest.TestCase):
 def test_expired_terminal_review_is_candidate(self):
  x=inv();x["refs"]=[r("refs/heads/review/old")];p=m.assess(x);self.assertEqual(p["delete_candidates"][0]["name"],"refs/heads/review/old");self.assertFalse(p["authorizes_delete"])
 def test_main_and_release_protected(self):
  x=inv();x["refs"]=[r("refs/heads/main"),r("refs/heads/release/v2.8.0")];self.assertEqual(len(m.assess(x)["delete_candidates"]),0)
 def test_open_pr_guard_reference_and_nonterminal_keep(self):
  x=inv();x["refs"]=[r("refs/heads/review/pr",open_pr=True),r("refs/heads/review/g",unreconciled_guard=True),r("refs/heads/review/ref",referenced=True),r("refs/heads/review/live",terminal=False)]
  self.assertEqual(len(m.assess(x)["keep"]),4)
if __name__=="__main__":unittest.main()
