from pathlib import Path
import copy
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from package_transport import validate_manifest,verify_binding,verify_directory
MANIFEST={"schema":"cdc-package-transport/v1","version":"2.9.0","canonical_repository":"owner/canonical-cdc","release_ref":"refs/heads/release/v2.9.0","release_commit":"0"*40,"package_tree":"6da82272e42dff9c7690322363d8a254f6300398","hash_algorithm":"git-sha1","entries":[{"path":"VERSION","mode":"100644","blob_sha1":"c8e38b614057b7e417c63fde44726a4143de9da0","size":6}]}
class T(unittest.TestCase):
 def test_manifest_reconstructs_exact_git_tree(self):validate_manifest(copy.deepcopy(MANIFEST))
 def test_binding_is_independent_of_carrier(self):self.assertTrue(verify_binding(copy.deepcopy(MANIFEST),version="2.9.0",release_commit="0"*40,package_tree=MANIFEST["package_tree"]))
 def test_wrong_trusted_tree_is_rejected(self):
  with self.assertRaises(ValueError):verify_binding(copy.deepcopy(MANIFEST),version="2.9.0",release_commit="0"*40,package_tree="1"*40)
 def test_mode_drift_changes_tree_identity(self):
  data=copy.deepcopy(MANIFEST);data["entries"][0]["mode"]="100755"
  with self.assertRaises(ValueError):validate_manifest(data)
 def test_directory_bytes_are_verified(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,"VERSION").write_text("2.9.0\n",encoding="utf-8")
   self.assertTrue(verify_directory(copy.deepcopy(MANIFEST),d)["content_verified"])
   Path(d,"VERSION").write_text("2.9.1\n",encoding="utf-8")
   self.assertFalse(verify_directory(copy.deepcopy(MANIFEST),d)["content_verified"])
if __name__=="__main__":unittest.main()
