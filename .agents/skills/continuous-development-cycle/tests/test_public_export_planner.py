import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import public_export_planner as m
def q():
 return {"schema":"public-export-request/v1","source_repository":"private/repo","target_repository":"public/repo","publication_guard_green":True,"history_clean":True,"control_plane_externalized":True,"allowed_paths":["src/","README.md"],"excluded_paths":["coordination/"]}
class T(unittest.TestCase):
 def test_green_plans_new_history_not_visibility_toggle(self):
  r=m.plan(q());self.assertEqual(r["action"],"EXPORT_NEW_HISTORY");self.assertTrue(r["preserve_private_history"]);self.assertFalse(r["authorizes_visibility_change"]);self.assertFalse(r["authorizes_push"])
 def test_failed_guard_blocks(self):
  x=q();x["publication_guard_green"]=False;self.assertEqual(m.plan(x)["action"],"BLOCKED")
if __name__=="__main__":unittest.main()
