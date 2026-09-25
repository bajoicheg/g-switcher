import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"));import progress_slo as m
P={"schema":"progress-slo-policy/v1","degraded_after_seconds":1200,"stalled_after_seconds":3600,"blocked_pauses_clock":True,"waiting_external_pauses_clock":True,"primitive_activity_is_progress":False}
def obs(now="2026-01-01T00:10:00Z",last="2026-01-01T00:05:00Z"):
 return {"schema":"progress-observation/v1","observed_at_utc":now,"last_meaningful_progress_at_utc":last,"last_activity_at_utc":"2026-01-01T00:09:59Z","primitive_steps_since_progress":99,"blocker":False,"waiting_external":False,"phase":"implementation","evidence_refs":["git:x"]}
class T(unittest.TestCase):
 def test_primitive_activity_does_not_reset_progress(self):self.assertEqual(m.classify(P,obs("2026-01-01T01:10:00Z"))["state"],"STALLED")
 def test_degraded_window(self):self.assertEqual(m.classify(P,obs("2026-01-01T00:30:00Z"))["state"],"DEGRADED")
 def test_blocker_pauses_clock(self):o=obs("2026-01-01T05:00:00Z");o["blocker"]=True;self.assertEqual(m.classify(P,o)["state"],"BLOCKED")
 def test_unknown_progress_requires_recovery(self):o=obs();o["last_meaningful_progress_at_utc"]=None;self.assertEqual(m.classify(P,o)["state"],"RECOVERY_REQUIRED")
if __name__=="__main__":unittest.main()
