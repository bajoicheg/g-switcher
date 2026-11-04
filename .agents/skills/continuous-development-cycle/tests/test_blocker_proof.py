import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import blocker_proof as m
def p():
 return {"schema":"blocked-state-proof/v1","dependency_id":"api:github","category":"capability","observed_at_utc":"2026-01-01T00:00:00Z","max_age_seconds":900,"evidence_refs":["api:403"],"next_action":"retry after permission change","recheck_trigger":"permission-change","same_invocation_work_exhausted":True}
class T(unittest.TestCase):
 def test_fresh_proof_is_terminal_boundary(self):
  r=m.assess(p(),"2026-01-01T00:05:00Z");self.assertTrue(r["terminal_boundary_valid"]);self.assertEqual(r["state"],"BLOCKED")
 def test_stale_proof_rejected(self):
  with self.assertRaises(ValueError):m.assess(p(),"2026-01-01T01:00:00Z")
 def test_requires_evidence(self):
  x=p();x["evidence_refs"]=[]
  with self.assertRaises(ValueError):m.validate(x)
 def test_requires_same_invocation_exhausted(self):
  x=p();x["same_invocation_work_exhausted"]=False
  with self.assertRaises(ValueError):m.validate(x)
if __name__=="__main__":unittest.main()
