import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import progress_enforcer as m
def s(state="HEALTHY"):
 return {"schema":"progress-enforcement/v1","progress_state":state,"runnable_work":False,"watchdog_enabled":True,"external_wait":False,"blocker_proven":False}
class T(unittest.TestCase):
 def test_runnable_work_no_idle(self):
  x=s();x["runnable_work"]=True;r=m.enforce(x);self.assertEqual(r["action"],"CONTINUE_NOW");self.assertFalse(r["final_response_allowed"])
 def test_stalled_kicks_watchdog(self):self.assertEqual(m.enforce(s("STALLED"))["action"],"KICK_WATCHDOG")
 def test_stalled_repairs_disabled_watchdog(self):
  x=s("STALLED");x["watchdog_enabled"]=False;self.assertEqual(m.enforce(x)["action"],"REPAIR_WATCHDOG")
 def test_proven_blocker_terminal_allowed(self):
  x=s("BLOCKED");x["blocker_proven"]=True;self.assertTrue(m.enforce(x)["final_response_allowed"])
 def test_degraded_continues(self):self.assertEqual(m.enforce(s("DEGRADED"))["action"],"INSPECT_AND_CONTINUE")
if __name__=="__main__":unittest.main()
