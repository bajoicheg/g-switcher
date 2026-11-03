from pathlib import Path
import copy
import json
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from package_transport import validate_manifest,verify_binding,verify_directory
MANIFEST={"schema":"cdc-package-transport/v1","version":"3.3.0","canonical_repository":"owner/canonical-cdc","release_ref":"refs/heads/release/v3.3.0","release_commit":"0"*40,"package_tree":"0d39564274cfe94d233f527a003c902e47c1e497","hash_algorithm":"git-sha1","entries":[{"path":"VERSION","mode":"100644","blob_sha1":"15a279981720791464e46ab21ae96b3c1c65c3b6","size":6}]}
class T(unittest.TestCase):
 def test_binding_is_independent_of_carrier(self):self.assertTrue(verify_binding(copy.deepcopy(MANIFEST),version="3.3.0",release_commit="0"*40,package_tree=MANIFEST["package_tree"]))
 def test_wrong_trusted_tree_is_rejected(self):
  with self.assertRaises(ValueError):verify_binding(copy.deepcopy(MANIFEST),version="3.3.0",release_commit="0"*40,package_tree="1"*40)
 def test_mode_drift_changes_tree_identity(self):
  data=copy.deepcopy(MANIFEST);data["entries"][0]["mode"]="100755"
  with self.assertRaises(ValueError):validate_manifest(data)
 def test_directory_bytes_are_verified(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,"VERSION").write_text("3.3.0\n",encoding="utf-8")
   self.assertTrue(verify_directory(copy.deepcopy(MANIFEST),d)["content_verified"])
   Path(d,"VERSION").write_text("3.3.1\n",encoding="utf-8")
   self.assertFalse(verify_directory(copy.deepcopy(MANIFEST),d)["content_verified"])

 def test_template_binds_current_package_version_bytes(self):
  root=Path(__file__).resolve().parents[1]
  version_bytes=(root/"VERSION").read_bytes()
  manifest=validate_manifest(json.loads((root/"templates/package-transport.json").read_text()))
  self.assertEqual(manifest["version"],version_bytes.decode().strip())
  with tempfile.TemporaryDirectory() as d:
   Path(d,"VERSION").write_bytes(version_bytes)
   self.assertTrue(verify_directory(manifest,d)["content_verified"])
 def test_package_validator_accepts_current_transport_fixture(self):
  from validate_package import validate
  root=Path(__file__).resolve().parents[1]
  self.assertEqual(validate(),(root/"VERSION").read_text().strip())
 def test_package_validator_rejects_stale_transport_version_blob(self):
  from unittest import mock
  import validate_package
  from contracts import ContractError
  from package_transport import _blob_oid,_tree_oid
  path=validate_package.ROOT/'templates/package-transport.json'
  manifest=json.loads(path.read_text());manifest['entries'][0]['blob_sha1']=_blob_oid(b'3.5.1\n')
  manifest['package_tree']=_tree_oid(manifest['entries'])
  original=Path.read_text
  def read_text(actual,*args,**kwargs):
   if actual==path:return json.dumps(manifest)
   return original(actual,*args,**kwargs)
  with mock.patch.object(Path,'read_text',read_text):
   with self.assertRaisesRegex(ContractError,'transport.*VERSION'):
    validate_package.validate()
if __name__=="__main__":unittest.main()
