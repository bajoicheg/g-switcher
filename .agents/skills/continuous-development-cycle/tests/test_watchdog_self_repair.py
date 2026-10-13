import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import watchdog_self_repair as m
def s():
 return {"schema":"watchdog-repair-state/v1","desired_enabled":True,"scheduler_state":"ok","chat_state":"active","backend_state":"ready","scheduler_fallback_configured":True,"repair_attempts":0,"max_repair_attempts":3,"evidence_refs":["scheduler:readback"]}
class T(unittest.TestCase):
 def test_healthy(self):self.assertEqual(m.plan(s())["action"],"HEALTHY")
 def test_scheduler_disabled_repairs(self):
  x=s();x["scheduler_state"]="disabled";self.assertEqual(m.plan(x)["action"],"REPAIR_SCHEDULER")
 def test_archived_chat_rebinds(self):
  x=s();x["chat_state"]="archived";self.assertEqual(m.plan(x)["action"],"REBIND_CHAT")
 def test_backend_uses_fallback(self):
  x=s();x["backend_state"]="unavailable";self.assertEqual(m.plan(x)["action"],"USE_FALLBACK")
 def test_budget_exhausted_blocks_without_authority(self):
  x=s();x["repair_attempts"]=3;r=m.plan(x);self.assertEqual(r["action"],"BLOCKED");self.assertFalse(r["authorizes_scheduler_mutation"])
if __name__=="__main__":unittest.main()
