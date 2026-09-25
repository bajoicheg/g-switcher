import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import capability_router as m
REG={"schema":"backend-capability-registry/v1","observed_at_utc":"2026-09-24T18:00:00Z","backends":[{"backend_id":"codex-linux","kind":"codex_compute","enabled":True,"state":"ready","rank":10,"capabilities":["os:linux","jdk:17"],"configuration_digest":"sha256:"+"1"*64,"last_verified_at_utc":"2026-09-24T17:59:00Z","evidence_refs":["env:1"]},{"backend_id":"gha-win","kind":"github_actions","enabled":True,"state":"ready","rank":20,"capabilities":["os:windows","dotnet:8.0.425"],"configuration_digest":"sha256:"+"2"*64,"last_verified_at_utc":"2026-09-24T17:59:00Z","evidence_refs":["workflow:win"]}]}
REQ={"schema":"capability-request/v1","task_id":"t1","candidate_sha":"a"*40,"required_capabilities":["os:windows","dotnet:8.0.425"],"preferred_kinds":["codex_compute","local","github_actions"],"forbidden_backend_ids":[],"required_backend_id":None,"max_registry_age_seconds":600}
class T(unittest.TestCase):
 def test_selects_compatible(self):self.assertEqual(m.route(REG,REQ,"2026-09-24T18:01:00Z")["backend_id"],"gha-win")
 def test_no_match_waits(self):q=copy.deepcopy(REQ);q["required_capabilities"].append("gpu");self.assertEqual(m.route(REG,q,"2026-09-24T18:01:00Z")["action"],"waiting_external")
 def test_stale_blocks(self):self.assertEqual(m.route(REG,REQ,"2026-09-24T19:00:00Z")["reason"],"registry_stale")
 def test_never_authorizes_start(self):self.assertFalse(m.route(REG,REQ,"2026-09-24T18:01:00Z")["authorizes_external_start"])
if __name__=="__main__":unittest.main()
