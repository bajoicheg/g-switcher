import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_cloud_profile as m
import test_codex_cloud_profile as fixtures
class NativeMetadata(unittest.TestCase):
 def test_unknown_display_label_does_not_erase_authentic_native_id_host_binding(self):
  p=fixtures.profile();p['environments']['native_runtime']['label']=None;q=fixtures.probe(p);r=m.assess_profile(p,q,fixtures.NOW)
  self.assertEqual(r['modes']['native_runtime']['status'],'READY')
  self.assertFalse(r['authorizes_external_start'])
 def test_unknown_cli_label_still_blocks_remote_exact_transport_mapping(self):
  p=fixtures.profile();p['environments']['official_cli']['label']=None;q=fixtures.probe(p);r=m.assess_profile(p,q,fixtures.NOW)
  self.assertNotEqual(r['modes']['official_cli']['status'],'READY')
if __name__=='__main__':unittest.main()
