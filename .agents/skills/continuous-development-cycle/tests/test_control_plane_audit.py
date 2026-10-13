import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import control_plane_audit as m
class T(unittest.TestCase):
 def test_append_and_validate(self):
  log={"schema":"control-plane-audit-log/v1","repository":"o/r","source_ref":"refs/heads/main","entries":[]}
  log,e=m.append(log,occurred_at_utc="2026-01-01T00:00:00Z",actor_invocation_id="wake-1",event_type="policy_adopt",object_ref="git:abc",outcome="success",details_digest="sha256:"+"1"*64);m.validate(log);self.assertEqual(e["sequence"],1)
 def test_tamper_breaks_chain(self):
  log={"schema":"control-plane-audit-log/v1","repository":"o/r","source_ref":"refs/heads/main","entries":[]}
  log,_=m.append(log,occurred_at_utc="2026-01-01T00:00:00Z",actor_invocation_id=None,event_type="fleet_assessment",object_ref="fleet:1",outcome="healthy",details_digest="sha256:"+"1"*64)
  log["entries"][0]["outcome"]="changed"
  with self.assertRaises(ValueError):m.validate(log)
if __name__=="__main__":unittest.main()
