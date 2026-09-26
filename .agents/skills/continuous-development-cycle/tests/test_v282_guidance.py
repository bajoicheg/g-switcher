from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_version_preserves_282_or_later_contract(self):
  version=(ROOT/"VERSION").read_text().strip()
  self.assertGreaterEqual(tuple(map(int,version.split("."))),(2,8,2))
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],version)
 def test_skill_names_p2_controls(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("project-independent fleet","stuck-state","counterfactual recovery","sanitized public export","dogfooding"):self.assertIn(term,t)
 def test_publication_reference_requires_new_history(self):
  t=(ROOT/"references"/"fleet-and-publication-maturity.md").read_text().lower()
  for term in ("sanitized export","new public history","preserve private history"):self.assertIn(term,t)
 def test_dogfood_has_no_release_authority(self):
  t=(ROOT/"references"/"fleet-and-publication-maturity.md").read_text().lower();self.assertIn("never release authority",t)
if __name__=="__main__":unittest.main()
