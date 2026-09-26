import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'budget.py'
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('budget', SCRIPT)
    budget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(budget)
else:
    budget = None

NOW = '2026-09-22T10:00:00Z'
LATER = '2026-09-22T10:01:00Z'

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(budget, 'budget implementation must exist')
        self.policy = dict(task_limits={'compute_starts': 3, 'ci_starts': 1, 'tool_calls': 20},
                           wake_limits={'status_polls': 2}, max_parallel_agents=2,
                           checkpoint_reserve={'tokens': 10, 'tool_calls': 2},
                           provider_max_age_seconds=60, actions_budget='normal')
        self.ledger = budget.new_ledger('task-1', 'wake-1', self.policy)

    def reserve(self, event_id='r1', kind='compute_start', **changes):
        e = dict(type='reserve', event_id=event_id, task_id='task-1', wake_id='wake-1',
                 at_utc=NOW, operation_key='sha256:' + 'a'*64, attempt_id=event_id, kind=kind,
                 scope='provider/env-1', recovery_ref=None,
                 cost={'tool_calls': 1, 'tokens': None, 'elapsed_seconds': None})
        e.update(changes)
        return e

    def event(self, event_id, event_type, **data):
        return dict(dict(type=event_type, event_id=event_id, task_id='task-1', wake_id='wake-1', at_utc=NOW), **data)

    def outcome(self, reservation_id='r1', status='setup_failed', **changes):
        e = self.event('o'+reservation_id, 'outcome', reservation_id=reservation_id, status=status,
                       usage={'tokens': None, 'elapsed_seconds': None},
                       failure={'signature':'setup:no-grant', 'category':'infrastructure'})
        e.update(changes)
        return e

    def test_duplicate_event_is_idempotent_and_conflict_rejected(self):
        event = self.reserve()
        ledger = budget.apply_event(self.ledger, event)
        self.assertEqual(budget.apply_event(ledger, event), ledger)
        altered = copy.deepcopy(event); altered['cost']['tool_calls'] = 2
        with self.assertRaises(ValueError): budget.apply_event(ledger, altered)
        self.assertEqual(budget.summarize(ledger)['task']['compute_starts'], 1)
        self.assertEqual(self.ledger['events'], [])

    def test_different_event_id_cannot_charge_same_operation_attempt_kind(self):
        event = self.reserve(); ledger = budget.apply_event(self.ledger, event)
        event['event_id'] = 'other'
        with self.assertRaises(ValueError): budget.apply_event(ledger, event)

    def test_lost_response_and_setup_failure_stay_charged(self):
        for status in ('unknown', 'setup_failed'):
            ledger = budget.apply_event(self.ledger, self.reserve())
            outcome = self.outcome(status=status, failure=None if status == 'unknown' else {'signature':'setup:no-grant','category':'infrastructure'})
            ledger = budget.apply_event(ledger, outcome)
            self.assertEqual(budget.summarize(ledger)['task']['compute_starts'], 1)
            self.assertIsNone(budget.summarize(ledger)['task']['tokens'])

    def test_exhausted_actions_blocks_ci_but_allows_observation(self):
        self.policy['actions_budget'] = 'exhausted'
        ledger = budget.new_ledger('task-1','wake-1',self.policy)
        self.assertFalse(budget.decide(ledger, self.reserve(kind='ci_start'))['allow_reservation'])
        self.assertTrue(budget.decide(ledger, self.reserve(kind='status_poll'))['allow_reservation'])

    def test_task_and_wake_limits_and_checkpoint_reserve(self):
        self.policy['task_limits']['tool_calls'] = 3
        ledger = budget.new_ledger('task-1','wake-1',self.policy)
        ledger = budget.apply_event(ledger, self.reserve())
        self.assertFalse(budget.decide(ledger,self.reserve('r2'))['allow_reservation'])
        self.assertTrue(budget.decide(ledger,self.reserve('r2','checkpoint'))['allow_reservation'])
        ledger = budget.apply_event(ledger,self.reserve('p1','status_poll'))
        ledger = budget.apply_event(ledger,self.reserve('p2','status_poll'))
        self.assertFalse(budget.decide(ledger,self.reserve('p3','status_poll'))['allow_reservation'])

    def test_unknown_provider_usage_is_explicit(self):
        decision = budget.decide(self.ledger,self.reserve())
        self.assertTrue(decision['allow_reservation'])
        self.assertFalse(decision['allow_launch'])
        self.assertEqual(decision['provider'], {})
        ledger = budget.apply_event(self.ledger,self.reserve())
        self.assertEqual(budget.summarize(ledger)['unknown']['tokens'],1)
        self.assertEqual(budget.summarize(ledger)['known']['tokens'],0)

    def test_capped_unknown_tokens_cannot_approve_expensive_work(self):
        self.policy['task_limits']['tokens'] = 100
        ledger = budget.new_ledger('task-1','wake-1',self.policy)
        self.assertFalse(budget.decide(ledger,self.reserve())['allow_reservation'])
        event = self.reserve(cost={'tool_calls':1,'tokens':90,'elapsed_seconds':1})
        self.assertTrue(budget.decide(ledger,event)['allow_reservation'])
        event['cost']['tokens'] = 91
        self.assertFalse(budget.decide(ledger,event)['allow_reservation'])

    def test_known_quota_deducts_local_starts_and_stale_becomes_unknown(self):
        event = self.event('q1','provider', metric='compute_starts', remaining=1, source='provider/quota')
        ledger = budget.apply_event(self.ledger,event)
        ledger = budget.apply_event(ledger,self.reserve())
        self.assertFalse(budget.decide(ledger,self.reserve('r2'))['allow_reservation'])
        result = budget.decide(ledger,self.reserve('r2',at_utc='2026-09-22T10:02:00Z'))
        self.assertIsNone(result['provider']['compute_starts']['remaining'])
        self.assertEqual(result['provider']['compute_starts']['status'],'stale')
        self.assertFalse(result['allow_reservation'])  # no unproven restoration of a known exhausted quota

    def test_failure_circuit_requires_concrete_one_use_remedy(self):
        ledger = budget.apply_event(self.ledger,self.reserve())
        ledger = budget.apply_event(ledger,self.outcome())
        retry = self.reserve('r2', operation_key='sha256:'+'b'*64)
        self.assertFalse(budget.decide(ledger,retry)['allow_reservation'])
        remedy = self.event('fix1','remedy', scope='provider/env-1', signature='setup:no-grant',
                            reference='logs/grant-restored', kind='service_recovery', detail='Grant lookup now returns repository', at_utc=LATER)
        ledger = budget.apply_event(ledger,remedy)
        retry.update(recovery_ref='logs/grant-restored',at_utc=LATER)
        ledger = budget.apply_event(ledger,retry)
        ledger = budget.apply_event(ledger,self.outcome('r2',at_utc=LATER))
        retry.update(event_id='r3', attempt_id='r3')
        self.assertFalse(budget.decide(ledger,retry)['allow_reservation'])
        replay = dict(remedy, event_id='fix2')
        with self.assertRaises(ValueError): budget.apply_event(ledger,replay)

    def test_successful_remedied_retry_closes_its_failure_circuit(self):
        ledger = budget.apply_event(self.ledger,self.reserve())
        ledger = budget.apply_event(ledger,self.outcome())
        remedy = self.event('fix1','remedy',scope='provider/env-1',signature='setup:no-grant',
                            reference='logs/recovery',kind='service_recovery',detail='Grant lookup now succeeds')
        ledger = budget.apply_event(ledger,remedy)
        ledger = budget.apply_event(ledger,self.reserve('r2',recovery_ref='logs/recovery'))
        ledger = budget.apply_event(ledger,self.outcome('r2',status='succeeded',failure=None))
        result = budget.decide(ledger,self.reserve('r3'))
        self.assertTrue(result['allow_reservation'],result['reasons'])
        # Consumption survives circuit closure and cannot mint another retry.
        with self.assertRaises(ValueError): budget.apply_event(ledger,dict(remedy,event_id='fix2'))

    def test_successful_remedied_retry_does_not_clear_intervening_failure(self):
        self.policy['task_limits']['compute_starts'] = 4
        ledger = budget.new_ledger('task-1','wake-1',self.policy)
        ledger = budget.apply_event(ledger,self.reserve())
        ledger = budget.apply_event(ledger,self.reserve('other'))
        ledger = budget.apply_event(ledger,self.outcome())
        ledger = budget.apply_event(ledger,self.event('fix1','remedy',scope='provider/env-1',signature='setup:no-grant',
                            reference='logs/recovery',kind='service_recovery',detail='Grant lookup now succeeds'))
        ledger = budget.apply_event(ledger,self.reserve('r2',recovery_ref='logs/recovery'))
        # Same scope AND signature; only the exact failure event may be cleared.
        ledger = budget.apply_event(ledger,self.outcome('other'))
        ledger = budget.apply_event(ledger,self.outcome('r2',status='succeeded',failure=None))
        result = budget.decide(ledger,self.reserve('r3'))
        self.assertFalse(result['allow_reservation'])
        self.assertTrue(any('failure circuit open' in r for r in result['reasons']))

    def test_stale_positive_quota_does_not_restore_prior_exhaustion(self):
        ledger = budget.apply_event(self.ledger,self.event('q1','provider',metric='compute_starts',remaining=0,source='quota'))
        ledger = budget.apply_event(ledger,self.event('q2','provider',metric='compute_starts',remaining=2,source='quota',at_utc=LATER))
        fresh = budget.decide(ledger,self.reserve(at_utc=LATER))
        self.assertTrue(fresh['allow_reservation'],fresh['reasons'])
        stale = budget.decide(ledger,self.reserve(at_utc='2026-09-22T10:03:00Z'))
        self.assertFalse(stale['allow_reservation'])
        self.assertEqual(stale['provider']['compute_starts']['status'],'stale')
        self.assertIsNone(stale['provider']['compute_starts']['remaining'])
        self.assertTrue(stale['provider']['compute_starts']['exhausted'])

    def test_wrong_task_or_wake_rejected(self):
        for field, value in [('task_id','other'),('wake_id','old')]:
            with self.assertRaises(ValueError): budget.apply_event(self.ledger,self.reserve(**{field:value}))
        ledger = budget.begin_wake(self.ledger,'wake-2')
        with self.assertRaises(ValueError): budget.apply_event(ledger,self.reserve())
        with self.assertRaises(ValueError): budget.begin_wake(ledger,'wake-1')

    def test_agent_parallel_cap_persists_across_wakes_until_terminal(self):
        ledger = budget.apply_event(self.ledger,self.reserve('a1','agent_start'))
        ledger = budget.apply_event(ledger,self.reserve('a2','agent_start'))
        self.assertFalse(budget.decide(ledger,self.reserve('a3','agent_start'))['allow_reservation'])
        ledger = budget.apply_event(ledger,self.outcome('a1',status='succeeded',failure=None))
        self.assertTrue(budget.decide(ledger,self.reserve('a3','agent_start'))['allow_reservation'])
        self.assertEqual(budget.summarize(ledger)['active_agents'],1)
        ledger = budget.begin_wake(ledger,'wake-2')
        self.assertEqual(budget.summarize(ledger)['active_agents'],1)
        self.assertEqual(budget.summarize(ledger)['wake']['agent_starts'],0)

    def test_actual_usage_is_recorded_without_refunding_reservation(self):
        ledger = budget.apply_event(self.ledger,self.reserve(cost={'tool_calls':1,'tokens':50,'elapsed_seconds':20}))
        ledger = budget.apply_event(ledger,self.outcome(status='succeeded',failure=None,usage={'tokens':30,'elapsed_seconds':40}))
        s = budget.summarize(ledger)
        self.assertEqual(s['task']['tokens'],50)
        self.assertEqual(s['observed']['tokens'],30)
        self.assertEqual(s['task']['elapsed_seconds'],40)

    def test_outcome_binding_and_terminal_regression_rejected(self):
        with self.assertRaises(ValueError): budget.apply_event(self.ledger,self.outcome())
        ledger = budget.apply_event(self.ledger,self.reserve())
        ledger = budget.apply_event(ledger,self.outcome())
        with self.assertRaises(ValueError): budget.apply_event(ledger,self.outcome(event_id='replacement',status='succeeded',failure=None))

    def test_policy_rejects_negative_bool_and_unknown_fields(self):
        for value in (-1,True):
            policy = copy.deepcopy(self.policy); policy['task_limits']['tokens'] = value
            with self.assertRaises(ValueError): budget.new_ledger('task-1','wake-1',policy)
        policy = copy.deepcopy(self.policy); policy['task_limits']['pretend_quota'] = 2
        with self.assertRaises(ValueError): budget.new_ledger('task-1','wake-1',policy)

    def test_provider_quota_accounts_for_observed_overage(self):
        ledger = budget.apply_event(self.ledger,self.event('q1','provider',metric='tokens',remaining=100,source='quota'))
        ledger = budget.apply_event(ledger,self.reserve(cost={'tool_calls':1,'tokens':30,'elapsed_seconds':None}))
        ledger = budget.apply_event(ledger,self.outcome(status='succeeded',failure=None,usage={'tokens':95,'elapsed_seconds':None}))
        request = self.reserve('r2',cost={'tool_calls':1,'tokens':1,'elapsed_seconds':None})
        self.assertFalse(budget.decide(ledger,request)['allow_reservation'])
        self.assertEqual(budget.decide(ledger,request)['provider']['tokens']['remaining'],5)

    def test_same_provider_observation_cannot_replenish_quota(self):
        observation = self.event('q1','provider',metric='compute_starts',remaining=1,source='quota')
        ledger = budget.apply_event(self.ledger,observation)
        ledger = budget.apply_event(ledger,self.reserve())
        observation['event_id']='q2'
        with self.assertRaises(ValueError): budget.apply_event(ledger,observation)

    def test_wake_limits_reset_but_task_caps_do_not(self):
        ledger = budget.apply_event(self.ledger,self.reserve('p1','status_poll'))
        ledger = budget.apply_event(ledger,self.reserve('p2','status_poll'))
        self.assertFalse(budget.decide(ledger,self.reserve('p3','status_poll'))['allow_reservation'])
        ledger = budget.begin_wake(ledger,'wake-2')
        self.assertTrue(budget.decide(ledger,self.reserve('p3','status_poll',wake_id='wake-2'))['allow_reservation'])
        self.assertEqual(budget.summarize(ledger)['task']['status_polls'],2)

    def test_zero_cost_tool_call_cannot_evade_tool_cap(self):
        event = self.reserve(kind='tool_call',cost={'tool_calls':0,'tokens':None,'elapsed_seconds':None})
        with self.assertRaises(ValueError): budget.apply_event(self.ledger,event)

    def test_policy_digest_and_append_only_write_protect_history(self):
        ledger = budget.apply_event(self.ledger,self.reserve())
        tampered = copy.deepcopy(ledger); tampered['policy']['task_limits']['ci_starts']=99
        with self.assertRaises(ValueError): budget.validate_ledger(tampered)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ledger.json'; budget.write_ledger(path,ledger)
            with self.assertRaises(ValueError): budget.write_ledger(path,self.ledger,expected=ledger)

    def test_local_write_cannot_backfill_closed_wake(self):
        advanced = budget.begin_wake(self.ledger,'wake-2')
        forged = budget.apply_event(self.ledger,self.reserve())
        forged['wake_ids'].append('wake-2')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ledger.json'; budget.write_ledger(path,advanced)
            with self.assertRaises(ValueError): budget.write_ledger(path,forged,expected=advanced)

    def test_local_write_stale_expected_record_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ledger.json'
            budget.write_ledger(path,self.ledger)
            updated = budget.apply_event(self.ledger,self.reserve())
            budget.write_ledger(path,updated,expected=self.ledger)
            with self.assertRaises(ValueError): budget.write_ledger(path,self.ledger,expected=self.ledger)
            result = subprocess.run([sys.executable,str(SCRIPT),'summary','--ledger',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['task']['compute_starts'],1)

if __name__ == '__main__': unittest.main()
