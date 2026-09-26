"""Default compute admission must allow four starts without widening Actions."""
import json
from pathlib import Path
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import budget


class ComputeDefaultTests(unittest.TestCase):
    def test_four_starts_then_denial_and_preserved_ci_policy(self):
        adapter = yaml.safe_load((ROOT / 'templates/development-cycle.yaml').read_text())
        example = json.loads((ROOT / 'templates/budget-ledger.json').read_text())
        budget.validate_ledger(example)
        for policy, ci_limit in [(adapter['orchestration']['budget'], 1), (example['policy'], 2)]:
            with self.subTest(policy=policy):
                self.assertEqual(policy['wake_limits'].get('compute_starts'), 4)
                self.assertEqual(policy['actions_budget'], 'conserve')
                self.assertEqual(policy['task_limits']['ci_starts'], ci_limit)
                ledger = budget.new_ledger('task', 'wake', policy)
                for number in range(1, 6):
                    event = dict(type='reserve', event_id=f'r{number}', task_id='task',
                                 wake_id='wake', at_utc='2026-09-23T05:00:00Z',
                                 operation_key='sha256:' + 'a' * 64, attempt_id=str(number),
                                 kind='compute_start', scope='codex/test', recovery_ref=None,
                                 cost=dict(tool_calls=1, tokens=None, elapsed_seconds=None))
                    decision = budget.decide(ledger, event)
                    self.assertEqual(decision['allow_reservation'], number <= 4)
                    self.assertFalse(decision['allow_launch'])
                    if number <= 4:
                        ledger = budget.apply_event(ledger, event)


if __name__ == '__main__':
    unittest.main()
