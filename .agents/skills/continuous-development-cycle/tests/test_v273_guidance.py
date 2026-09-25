from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]

class Tests(unittest.TestCase):
 def test_version_is_273(self):
  self.assertEqual((ROOT/"VERSION").read_text().strip(),"2.7.3")
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],"2.7.3")
 def test_continue_means_terminal_state(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("продолжай","continue","terminal state","real durable terminal blocker"):
   self.assertIn(term,t)
 def test_watchdog_preserves_terminal_semantics(self):
  t=(ROOT/"templates"/"watchdog-prompt.md").read_text().lower()
  self.assertIn("bare user continuation command",t);self.assertIn("terminal state",t)
 def test_public_actions_are_visibility_aware(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("repository visibility","public repositories","unmetered","private/internal"):
   self.assertIn(term,t)
if __name__=="__main__":unittest.main()
