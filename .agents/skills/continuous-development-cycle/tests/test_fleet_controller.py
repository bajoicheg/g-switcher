import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import fleet_controller as m
def p(state="HEALTHY",**kw):
 d={"repository":"o/r","source_ref":"refs/heads/main","state":state,"runnable_work":False,"owner_active":False,"guard_present":False,"watchdog_enabled":True,"next_action":"continue"};d.update(kw);return d
class T(unittest.TestCase):
 def test_runnable_wakes_project(self):
  r=m.plan({"schema":"fleet-control-input/v1","projects":[p(runnable_work=True)]});self.assertEqual(r["projects"][0]["action"],"WAKE_PROJECT");self.assertFalse(r["authorizes_product_write"]);self.assertFalse(r["project_specific_code_required"])
 def test_owner_and_guard_not_crossed(self):
  self.assertEqual(m.plan({"schema":"fleet-control-input/v1","projects":[p(owner_active=True)]})["projects"][0]["action"],"OBSERVE_OWNER")
  self.assertEqual(m.plan({"schema":"fleet-control-input/v1","projects":[p(guard_present=True)]})["projects"][0]["action"],"OBSERVE_GUARD")
 def test_stalled_repairs_or_kicks(self):
  self.assertEqual(m.plan({"schema":"fleet-control-input/v1","projects":[p("STALLED")]})["projects"][0]["action"],"KICK_WATCHDOG")
  self.assertEqual(m.plan({"schema":"fleet-control-input/v1","projects":[p("STALLED",watchdog_enabled=False)]})["projects"][0]["action"],"REPAIR_WATCHDOG")
if __name__=="__main__":unittest.main()
