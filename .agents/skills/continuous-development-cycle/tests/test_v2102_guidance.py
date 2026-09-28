from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parents[1]
class T(unittest.TestCase):
 def test_version(self):
  v=(ROOT/"VERSION").read_text().strip()
  self.assertGreaterEqual(tuple(map(int,v.split("."))),(2,10,2))
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],v)
 def test_package_validator_binds_gate_result_fixture(self):
  s=(ROOT/"scripts"/"validate_package.py").read_text()
  self.assertIn("'templates/wave-integration-gate-result.json'",s)
  self.assertIn("'templates/parallel-benchmark-plan.json'",s)
  self.assertIn("validate_gate_result(gate_result)",s)
  self.assertIn("integration gate result artifact digest",s)
 def test_parallel_guidance(self):
  t=(ROOT/"SKILL.md").read_text().lower()
  for term in ("worktree-isolated parallel development","ordinary chatgpt chat remains sequential","write-set","single integrator","ready_for_integrator","observed parallel benchmark","content-addressed prior integration","actual plan artifact"):
   self.assertIn(term,t)
  r=(ROOT/"references"/"worktree-parallelism-and-integration.md").read_text().lower()
  for term in ("worktree","single integrator","shared branch","observed parallel benchmark","no shared-branch write"):
   self.assertIn(term,r)
if __name__=="__main__": unittest.main()
