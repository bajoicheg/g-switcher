from pathlib import Path
import json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import cost_router as m

class Tests(unittest.TestCase):
 def test_version_is_272(self):
  self.assertEqual((ROOT/"VERSION").read_text().strip(),"2.7.2")
  self.assertEqual(json.loads((ROOT/"manifest.json").read_text())["version"],"2.7.2")
 def test_cost_policy_is_codex_first_and_actions_expensive(self):
  p=json.loads((ROOT/"templates"/"cost-routing-policy.json").read_text())
  m.validate_policy(p)
  self.assertEqual(p["primary_kind"],"codex_compute")
  self.assertIn("github_actions",p["expensive_kinds"])
  self.assertGreater(p["kind_cost_weights"]["github_actions"],p["kind_cost_weights"]["codex_compute"])
  self.assertTrue(p["github_actions_requires_reason"])
 def test_guidance_blocks_automatic_actions_on_transient_codex_failure(self):
  t=(ROOT/"references"/"cost-aware-routing.md").read_text().lower()
  for term in ("transient","waiting_compute","confirmed provider outage","product/test failure","explicit machine-readable reason"):
   self.assertIn(term,t)
 def test_watchdog_names_expensive_fallback_reasons(self):
  t=(ROOT/"templates"/"watchdog-prompt.md").read_text().lower()
  for term in ("cost-aware","final-platform","artifact production","release attestation","confirmed provider outage"):
   self.assertIn(term,t)
 def test_pressure_suite_covers_cost_failure_modes(self):
  t=(ROOT/"tests"/"pressure-scenarios.md").read_text().lower()
  for term in ("transient codex failure with expensive actions available","product failure on codex while actions is ready","expensive platform gate is genuinely required"):
   self.assertIn(term,t)

if __name__=="__main__":unittest.main()
