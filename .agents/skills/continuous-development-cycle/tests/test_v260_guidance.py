from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_core_names_v26_controls(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("fleet supervisor","version convergence","progress slo","control-plane audit"):self.assertIn(term,t)
 def test_watchdog_says_fleet_is_not_authority(self):
  t=(ROOT/"templates/watchdog-prompt.md").read_text().lower()
  self.assertIn("fleet",t);self.assertIn("never grants",t)
if __name__=="__main__":unittest.main()
