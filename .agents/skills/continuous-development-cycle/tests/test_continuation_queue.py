import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import continuation_queue as m
def event():
 e={"schema":"continuation-event/v1","event_id":"evt-1","event_type":"ci_terminal","repository":"example/project","source_ref":"refs/heads/feature","candidate_sha":"a"*40,"operation_key":None,"task_id":"run-1","observed_at_utc":"2026-09-24T18:00:00Z","source":"github-actions","evidence_refs":["run:1"],"dedupe_key":""};e["dedupe_key"]=m.dedupe_key(e);return e
class T(unittest.TestCase):
 def test_duplicate_idempotent(self):q=m.initialize("example/project","refs/heads/feature");q,r=m.ingest(q,event());q2,r2=m.ingest(q,event());self.assertTrue(r["wake_required"]);self.assertFalse(r2["wake_required"]);self.assertEqual(q,q2)
 def test_claim_ack_bound(self):q,_=m.ingest(m.initialize("example/project","refs/heads/feature"),event());q,e=m.claim_next(q,"wake-1","2026-09-24T18:01:00Z");self.assertEqual(e["event_id"],"evt-1");self.assertRaises(ValueError,m.ack,q,"evt-1","wake-2","2026-09-24T18:02:00Z","checkpoint:1")
 def test_expired_claim_requeues(self):q,_=m.ingest(m.initialize("example/project","refs/heads/feature"),event());q,_=m.claim_next(q,"wake-1","2026-09-24T18:01:00Z",60);q,e=m.claim_next(q,"wake-2","2026-09-24T18:02:01Z");self.assertEqual(e["event_id"],"evt-1")
if __name__=="__main__":unittest.main()
