import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_cloud_cli as cli
from codex_cloud_development import CodexCloudDevelopment
KEY='sha256:'+'a'*64
REQUEST={'schema':'codex-cloud-cli-request/v1','operation_key':KEY,'attempt_id':'snapshot-a1','repository':'test/project','candidate_sha':'c'*40,'environment_id':'d'*32,'environment_label':'env','source_branch':'cdc/candidate','checks':[{'id':'suite','argv':['python','-c','print("Привет мир")'],'minimum_test_count':None}]}
class SnapshotContracts(unittest.TestCase):
 def adapter(self,cls=cli.CodexCloudCLI):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  def forbidden(*a,**kw):self.fail('Snapshot or denied dispatch called provider')
  return cls(t.name,runner=forbidden)
 def test_absence_read_is_none_and_never_provider_inventory(self):
  for cls in [cli.CodexCloudCLI,CodexCloudDevelopment]:
   with self.subTest(cls=cls):self.assertIsNone(self.adapter(cls).snapshot(KEY))
 def test_invalid_operation_key_rejected_before_load(self):
  a=self.adapter()
  for k in ['../escape','sha256:short',None]:
   with self.subTest(key=k),self.assertRaises(ValueError):a.snapshot(k)
 def test_cancelled_before_send_snapshot_detached_and_persistent(self):
  a=self.adapter()
  def denied():raise ValueError('Real callback denied fixture send')
  original=a.submit(copy.deepcopy(REQUEST),launch_authorized=denied)
  self.assertEqual(original['state'],'not_submitted')
  snapshot=a.snapshot(KEY);self.assertEqual(snapshot,original)
  snapshot['request']['checks'][0]['argv'][2]='changed'
  self.assertEqual(a.snapshot(KEY)['request']['checks'][0]['argv'][2],'print("Привет мир")')
 def test_corrupt_journal_never_becomes_verified_absence(self):
  a=self.adapter();a._path(KEY).write_text('{broken')
  with self.assertRaises(ValueError):a.snapshot(KEY)
 def test_development_uses_own_locked_validator(self):
  a=self.adapter(CodexCloudDevelopment);a._path(KEY).write_text(json.dumps({'schema':'wrong','state':'running'}))
  with self.assertRaises(ValueError):a.snapshot(KEY)
 def test_non_ascii_transport_digest_remains_ascii_plain_hex(self):
  expected=json.dumps(REQUEST,sort_keys=True,separators=(',',':'),allow_nan=False)
  self.assertIn('\\u041f',expected)
  self.assertEqual(cli._canonical(REQUEST),expected)
  self.assertEqual(cli._digest(REQUEST),hashlib.sha256(expected.encode()).hexdigest())
  self.assertEqual(len(cli._digest(REQUEST)),64)
  self.assertEqual(cli.validate_request(REQUEST)['checks'],REQUEST['checks'])
if __name__=='__main__':unittest.main()
