import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'budget.py'
spec = importlib.util.spec_from_file_location('budget_parallel_bound_impl', SCRIPT)
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)

NOW = '2026-09-22T10:00:00Z'


class ParallelBoundTests(unittest.TestCase):
    def setUp(self):
        self.policy = dict(task_limits={}, wake_limits={}, max_parallel_agents=3,
                           checkpoint_reserve={'tokens': 0, 'tool_calls': 0},
                           provider_max_age_seconds=60, actions_budget='normal')
        self.ledger = budget.new_ledger('task-1', 'wake-1', self.policy)

    def event(self, event_id, event_type, **data):
        return dict(type=event_type, event_id=event_id, task_id='task-1',
                    wake_id='wake-1', at_utc=NOW, **data)

    def reserve(self, event_id, **changes):
        event = self.event(event_id, 'reserve', operation_key='sha256:' + 'a' * 64,
                           attempt_id=event_id, kind='agent_start', scope='role/' + event_id,
                           recovery_ref=None,
                           cost={'tool_calls': 1, 'tokens': 10, 'elapsed_seconds': 2})
        event.update(changes)
        return event

    def limit(self, value, event_id='limit', **changes):
        event = self.event(event_id, 'parallel_limit', max_parallel_agents=value,
                           reference='operator-note:current-capacity')
        event.update(changes)
        return event

    def outcome(self, reservation_id, **changes):
        event = self.event('outcome-' + reservation_id, 'outcome',
                           reservation_id=reservation_id, status='succeeded',
                           usage={'tokens': 12, 'elapsed_seconds': 3}, failure=None)
        event.update(changes)
        return event

    def assert_denied(self, ledger, reservation, reason):
        decision = budget.decide(ledger, reservation)
        self.assertFalse(decision['allow_reservation'])
        self.assertFalse(decision['allow_launch'])
        self.assertTrue(any(reason in item for item in decision['reasons']), decision)
        with self.assertRaises(ValueError):
            budget.apply_event(ledger, reservation)

    def test_historical_overlap_survives_tighter_future_bound(self):
        ledger = self.ledger
        for name in ('research', 'implementation', 'review'):
            reservation = self.reserve(name)
            decision = budget.decide(ledger, reservation)
            self.assertTrue(decision['allow_reservation'])
            self.assertFalse(decision['allow_launch'])
            ledger = budget.apply_event(ledger, reservation)
        self.assertEqual(budget.summarize(ledger)['active_agents'], 3)
        ledger = budget.apply_event(ledger, self.outcome('research'))
        before = copy.deepcopy(ledger)
        totals = budget.summarize(ledger)
        ledger = budget.apply_event(ledger, self.limit(2))
        budget.validate_ledger(ledger)
        self.assertEqual(ledger['events'][:-1], before['events'])
        for key in ('schema', 'task_id', 'wake_ids', 'policy', 'policy_digest'):
            self.assertEqual(ledger[key], before[key])
        self.assertEqual(budget.summarize(ledger), totals)
        self.assertEqual(totals['task']['agent_starts'], 3)
        self.assertEqual(totals['task']['tokens'], 32)
        fourth = self.reserve('fourth')
        self.assert_denied(ledger, fourth, 'maximum parallel agents')
        ledger = budget.apply_event(ledger, self.outcome('implementation'))
        ledger = budget.apply_event(ledger, fourth)
        budget.validate_ledger(ledger)
        summary = budget.summarize(ledger)
        self.assertEqual(summary['active_agents'], 2)
        self.assertEqual(summary['task']['agent_starts'], 4)
        self.assertEqual(summary['task']['tokens'], 44)
        self.assertEqual(ledger['events'][:len(before['events'])], before['events'])

    def test_lower_than_active_zero_pause_and_restore_original_cap(self):
        ledger = self.ledger
        for name in ('a', 'b', 'c'):
            ledger = budget.apply_event(ledger, self.reserve(name))
        ledger = budget.apply_event(ledger, self.limit(1))
        self.assertEqual(budget.summarize(ledger)['active_agents'], 3)
        self.assert_denied(ledger, self.reserve('d'), 'maximum parallel agents')
        for name in ('a', 'b', 'c'):
            ledger = budget.apply_event(ledger, self.outcome(name))
        ledger = budget.apply_event(ledger, self.limit(0, 'pause'))
        self.assert_denied(ledger, self.reserve('d'), 'maximum parallel agents')
        observation = self.reserve('poll', kind='status_poll')
        self.assertTrue(budget.decide(ledger, observation)['allow_reservation'])
        ledger = budget.apply_event(ledger, self.limit(3, 'restore'))
        for name in ('d', 'e', 'f'):
            ledger = budget.apply_event(ledger, self.reserve(name))
        self.assert_denied(ledger, self.reserve('g'), 'maximum parallel agents')
        self.assertEqual(ledger['policy'], self.policy)
        self.assertEqual(budget.summarize(ledger)['task']['agent_starts'], 6)

    def test_invalid_limits_and_exact_event_shape_rejected_on_apply_and_replay(self):
        invalid = [self.limit(value) for value in (-1, True, False, 4, 2.0, None)]
        invalid += [self.limit(2, reference=value) for value in ('', ' padded', 'line\nbreak', None)]
        missing = self.limit(2)
        del missing['reference']
        extra = self.limit(2)
        extra['authority'] = 'owner'
        invalid.extend((missing, extra))
        for event in invalid:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    budget.apply_event(self.ledger, event)
                stored = copy.deepcopy(self.ledger)
                stored['events'].append(event)
                before = copy.deepcopy(stored)
                with self.assertRaises(ValueError):
                    budget.validate_ledger(stored)
                self.assertEqual(stored, before)

    def test_handcrafted_reservation_after_bound_is_rejected(self):
        ledger = budget.apply_event(self.ledger, self.reserve('a'))
        ledger = budget.apply_event(ledger, self.limit(1))
        ledger['events'].append(self.reserve('b'))
        before = copy.deepcopy(ledger)
        with self.assertRaisesRegex(ValueError, 'maximum parallel agents'):
            budget.validate_ledger(ledger)
        self.assertEqual(ledger, before)

    def test_replay_conflicts_and_detached_public_results(self):
        ledger = budget.apply_event(self.ledger, self.reserve('a'))
        event = self.limit(0)
        limited = budget.apply_event(ledger, event)
        event['reference'] = 'mutated-input'
        self.assertEqual(limited['events'][-1]['reference'], 'operator-note:current-capacity')
        replay_event = copy.deepcopy(limited['events'][-1])
        replay = budget.apply_event(limited, replay_event)
        self.assertEqual(replay, limited)
        replay['events'][0]['cost']['tokens'] = 999
        replay['policy']['checkpoint_reserve']['tokens'] = 999
        self.assertEqual(limited['events'][0]['cost']['tokens'], 10)
        self.assertEqual(limited['policy']['checkpoint_reserve']['tokens'], 0)
        for change in ({'max_parallel_agents': 1}, {'reference': 'different-note'}):
            conflict = dict(replay_event, **change)
            with self.assertRaisesRegex(ValueError, 'payload conflict'):
                budget.apply_event(limited, conflict)
        duplicate = copy.deepcopy(limited)
        duplicate['events'].append(replay_event)
        with self.assertRaisesRegex(ValueError, 'duplicate event'):
            budget.validate_ledger(duplicate)
        self.assertEqual(len(ledger['events']), 1)
        replay_reservation = budget.decide(limited, self.reserve('a'))
        self.assertTrue(replay_reservation['already_recorded'])
        self.assertFalse(replay_reservation['allow_launch'])

    def test_bound_survives_begin_wake_and_old_event_replay(self):
        event = self.limit(0)
        ledger = budget.apply_event(self.ledger, event)
        next_wake = budget.begin_wake(ledger, 'wake-2')
        budget.validate_ledger(next_wake)
        self.assertEqual(budget.apply_event(next_wake, event), next_wake)
        self.assert_denied(next_wake, self.reserve('a', wake_id='wake-2'),
                           'maximum parallel agents')
        restored = budget.apply_event(next_wake, self.limit(2, 'restore', wake_id='wake-2'))
        self.assertTrue(budget.decide(restored, self.reserve('a', wake_id='wake-2'))['allow_reservation'])
        next_wake['events'][0]['reference'] = 'changed-copy'
        self.assertEqual(ledger['events'][0], event)
        self.assertEqual(ledger['wake_ids'], ['wake-1'])

    def test_provider_failure_and_unknown_usage_are_not_restored(self):
        provider = self.event('quota', 'provider', metric='tokens', remaining=10,
                              source='provider-observation')
        ledger = budget.apply_event(self.ledger, provider)
        ledger = budget.apply_event(ledger, self.reserve('a'))
        ledger = budget.apply_event(ledger, self.outcome('a'))
        before = budget.decide(ledger, self.reserve('b'))['provider']
        ledger = budget.apply_event(ledger, self.limit(2))
        ledger = budget.apply_event(ledger, self.limit(3, 'restore'))
        self.assertEqual(budget.decide(ledger, self.reserve('b'))['provider'], before)
        self.assertEqual(before['tokens']['remaining'], 0)
        self.assert_denied(ledger, self.reserve('b'), 'provider tokens exhausted')

        failed = budget.apply_event(self.ledger, self.reserve('failed', scope='shared'))
        failure = self.outcome('failed', status='setup_failed',
                               failure={'signature': 'setup:no-grant', 'category': 'infrastructure'})
        failed = budget.apply_event(failed, failure)
        failed = budget.apply_event(failed, self.limit(3))
        self.assert_denied(failed, self.reserve('retry', scope='shared'), 'failure circuit open')
        self.assertEqual(failed['events'][1], failure)
        self.assertEqual(budget.summarize(failed)['task']['agent_starts'], 1)

        policy = copy.deepcopy(self.policy)
        unknown = budget.new_ledger('task-1', 'wake-1', policy)
        unknown = budget.apply_event(unknown, self.reserve('unknown',
            cost={'tool_calls': 1, 'tokens': None, 'elapsed_seconds': None}))
        unknown = budget.apply_event(unknown, self.outcome('unknown', status='unknown',
            usage={'tokens': None, 'elapsed_seconds': None}))
        before = budget.summarize(unknown)
        unknown = budget.apply_event(unknown, self.limit(2))
        self.assertEqual(budget.summarize(unknown), before)
        self.assertIsNone(before['task']['tokens'])
        self.assertEqual(before['unknown']['tokens'], 1)
        self.assertEqual(before['active_agents'], 1)
        self.assertTrue(budget.decide(unknown, self.reserve('next'))['allow_reservation'])
        self.assertFalse(budget.decide(unknown, self.reserve('next'))['allow_launch'])

    def test_write_ledger_persists_append_and_replays_historical_overlap(self):
        ledger = self.ledger
        for name in ('a', 'b', 'c'):
            ledger = budget.apply_event(ledger, self.reserve(name))
        ledger = budget.apply_event(ledger, self.outcome('a'))
        updated = budget.apply_event(ledger, self.limit(2))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            budget.write_ledger(path, ledger)
            budget.write_ledger(path, updated, expected=ledger)
            loaded = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(loaded, updated)
            self.assertEqual(loaded['events'][:-1], ledger['events'])
            self.assertEqual(loaded['policy_digest'], ledger['policy_digest'])
            budget.validate_ledger(loaded)
            self.assert_denied(loaded, self.reserve('d'), 'maximum parallel agents')
            with self.assertRaisesRegex(ValueError, 'stale expected ledger'):
                budget.write_ledger(path, updated, expected=ledger)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), updated)


if __name__ == '__main__':
    unittest.main()
