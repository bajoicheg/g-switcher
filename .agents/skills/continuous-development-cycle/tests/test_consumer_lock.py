import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from consumer_lock import validate
class Tests(unittest.TestCase):
 def template(self): return json.loads((ROOT/"templates"/"consumer-lock.json").read_text())
 def test_template_valid(self): validate(self.template())
 def test_release_ref_is_version_bound(self):
  d=self.template();d["release_ref"]="refs/heads/release/v2.6.0"
  with self.assertRaises(ValueError): validate(d)
 def test_exact_commit_and_tree_are_required(self):
  for name in ("release_commit","package_tree"):
   d=self.template();d[name]="not-a-sha"
   with self.subTest(name=name),self.assertRaises(ValueError): validate(d)
 def test_safe_boundary_cannot_be_disabled(self):
  d=self.template();d["safe_boundary_required"]=False
  with self.assertRaises(ValueError): validate(d)
 def test_local_core_edits_are_forbidden(self):
  d=self.template();d["local_core_modifications_allowed"]=True
  with self.assertRaises(ValueError): validate(d)
if __name__=="__main__": unittest.main()
