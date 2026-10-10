"""Executable policy and pressure-fixture integrity; prose is not runtime proof."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cost_router


class GuidanceFixtures(unittest.TestCase):
    def test_default_cost_policy_keeps_configured_primary_and_expensive_gate(self):
        policy = json.loads((ROOT / 'templates/cost-routing-policy.json').read_text())
        cost_router.validate_policy(policy)
        self.assertEqual(policy['primary_kind'], 'codex_compute')
        self.assertIn('github_actions', policy['expensive_kinds'])
        self.assertGreater(policy['kind_cost_weights']['github_actions'],
                           policy['kind_cost_weights']['codex_compute'])
        self.assertTrue(policy['github_actions_requires_reason'])

    def test_pressure_fixture_ids_remain_unique_and_contiguous(self):
        text = (ROOT / 'tests/pressure-scenarios.md').read_text()
        numbers = [int(x) for x in re.findall(r'(?m)^## (\d+)\.', text)]
        self.assertTrue(numbers)
        self.assertEqual(numbers, list(range(1, max(numbers) + 1)))


if __name__ == '__main__':
    unittest.main()
