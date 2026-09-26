from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_version_preserves_291_or_later_contract(self):
  version=(ROOT/"VERSION").read_text().strip()
  self.assertGreaterEqual(tuple(map(int,version.split("."))),(2,9,1))
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],version)
 def test_skill_names_transactional_controls(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("fresh head","schema-typed","detached tree","terminal-provider reconciliation"):
   self.assertIn(term,t)
if __name__=="__main__":
 unittest.main()
