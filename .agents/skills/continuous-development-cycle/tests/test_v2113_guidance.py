from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class T(unittest.TestCase):
 def test_skill_names_2113_controls(self):
  text=(ROOT/"SKILL.md").read_text(encoding="utf-8").lower()
  for term in ("multi-subscription","fleet supervisor leader","execution_liveness.py","final_response_gate.py","consumer_adoption.py"):
   self.assertIn(term,text)
 def test_reference_has_fail_closed_boundaries(self):
  text=(ROOT/"references"/"multi-subscription-coordination-and-ownership.md").read_text(encoding="utf-8").lower()
  for term in ("ttl alone","orphaned_recoverable","blocked_unknown_effects","one publication boundary","duplicate effect","package-managed","assembly manifest","terminal resolutions"):
   self.assertIn(term,text)

if __name__=="__main__":unittest.main()
