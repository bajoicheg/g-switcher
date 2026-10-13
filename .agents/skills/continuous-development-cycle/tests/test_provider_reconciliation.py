from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from provider_reconciliation import reconcile
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def obs(self):return json.loads((ROOT/"templates"/"provider-terminal-observation.json").read_text())
 def test_terminal_provider_reenters_reconciliation(self):
  r=reconcile(self.obs());self.assertEqual(r["action"],"REENTER_RECONCILIATION");self.assertTrue(r["wake_required"]);self.assertFalse(r["authorizes_takeover"])
 def test_terminal_or_ttl_alone_never_grants_takeover(self):
  r=reconcile(self.obs());self.assertFalse(r["recovery_takeover_candidate"]);self.assertFalse(r["lease_expiry_is_takeover_evidence"]);self.assertFalse(r["provider_terminal_is_takeover_evidence"])
 def test_explicit_stopped_executor_can_only_make_recovery_candidate(self):
  d=self.obs();d["owner"]={"active":False,"executor_stopped_proven":True,"pending_shared_writes":False};r=reconcile(d);self.assertTrue(r["recovery_takeover_candidate"]);self.assertFalse(r["authorizes_takeover"])
 def test_pending_writes_prevent_recovery_candidate(self):
  d=self.obs();d["owner"]={"active":False,"executor_stopped_proven":True,"pending_shared_writes":True};self.assertFalse(reconcile(d)["recovery_takeover_candidate"])
if __name__=="__main__":unittest.main()
