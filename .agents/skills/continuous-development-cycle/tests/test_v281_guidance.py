from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_version_is_281(self):
  v=(ROOT/"VERSION").read_text().strip();self.assertGreaterEqual(tuple(map(int,v.split("."))),(2,8,1))
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],v)
 def test_skill_names_operational_hardening(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("watchdog self-repair","ref hygiene","blocker proof","decision authority","evidence compaction","progress enforcement"):self.assertIn(term,t)
 def test_reference_prevents_fake_blocked_state(self):
  t=(ROOT/"references"/"operational-hardening.md").read_text().lower()
  for term in ("fresh observation","same-invocation useful work","recheck trigger"):self.assertIn(term,t)
 def test_decision_classifier_never_creates_authority(self):
  t=(ROOT/"references"/"decision-authority.md").read_text().lower();self.assertIn("never creates authority",t)
if __name__=="__main__":unittest.main()
