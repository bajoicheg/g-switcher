from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_version_preserves_2101_or_later_contract(self):
  v=(ROOT/"VERSION").read_text().strip()
  self.assertGreaterEqual(tuple(map(int,v.split("."))),(2,10,1))
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],v)
 def test_review_guidance(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("spec-compliance review","code-quality review","selective brainstorming","spec → plan","branch finishing","independent reviewers"):
   self.assertIn(term,t)
  r=(ROOT/"references"/"specification-review-and-finishing.md").read_text().lower()
  for term in ("superpowers","spec compliance","code quality","continuation queue","no merge authority"):
   self.assertIn(term,r)
if __name__=="__main__": unittest.main()
