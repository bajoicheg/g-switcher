from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_version_preserves_290_or_later_contract(self):
  version=(ROOT/"VERSION").read_text().strip();self.assertGreaterEqual(tuple(map(int,version.split("."))),(2,9,0));self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],version)
 def test_skill_names_distribution_convergence_controls(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("carrier-neutral","convergence vector","pre_run_infrastructure","version string alone"):self.assertIn(term,t)
 def test_reference_is_fail_closed(self):
  t=(ROOT/"references"/"deterministic-distribution-and-convergence.md").read_text().lower()
  for term in ("least-privilege","exact package git tree","fails closed","no source change"):self.assertIn(term,t)
if __name__=="__main__":unittest.main()
