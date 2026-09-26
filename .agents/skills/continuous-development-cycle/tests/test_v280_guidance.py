from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
 def test_version_is_280(self):
  v=(ROOT/"VERSION").read_text().strip();self.assertGreaterEqual(tuple(map(int,v.split("."))),(2,8,0))
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],v)
 def test_skill_enforces_no_idle_and_failover(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("terminal-state v2","no-idle","execution-channel supervisor","concurrent-writer reconciliation"):self.assertIn(term,t)
 def test_publication_contract_is_not_secret_scan_only(self):
  t=(ROOT/"references"/"publication-safety.md").read_text().lower()
  for term in ("secret scanning is necessary but not sufficient","every ref","conversation text","sanitized export"):self.assertIn(term,t)
 def test_control_plane_is_separated(self):
  t=(ROOT/"references"/"autonomous-continuity-and-isolation.md").read_text().lower()
  for term in ("control-plane isolation","leases","ledgers","public export"):self.assertIn(term,t)
if __name__=="__main__":unittest.main()
