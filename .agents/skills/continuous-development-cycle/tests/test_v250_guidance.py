from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_core_has_all_v25_subsystems(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("capability router","deterministic recovery","continuation queue"):self.assertIn(term,t)
 def test_watchdog_keeps_scheduler_fallback(self):
  t=(ROOT/"templates/watchdog-prompt.md").read_text().lower()
  for term in ("continuation","scheduler fallback","capability"):self.assertIn(term,t)
if __name__=="__main__":unittest.main()
