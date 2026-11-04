import copy
import hashlib
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import budget
import execution_strategy


def policy(cap=2):
    return {'task_limits': {'agent_starts': 4, 'tool_calls': 20}, 'wake_limits': {},
            'max_parallel_agents': cap, 'checkpoint_reserve': {'tokens': 0, 'tool_calls': 0},
            'provider_max_age_seconds': 60, 'actions_budget': 'normal'}


def event(name):
    return {'type': 'reserve', 'event_id': 'agent-' + name, 'task_id': 'task', 'wake_id': 'wake',
            'at_utc': '2026-10-09T10:00:00Z', 'operation_key': 'sha256:' + hashlib.sha256(name.encode()).hexdigest(),
            'attempt_id': name, 'kind': 'agent_start', 'scope': 'agent/' + name,
            'recovery_ref': None,
            'cost': {'tool_calls': 1, 'tokens': 10, 'elapsed_seconds': 60}}


def task(name, scope, *, depends=(), urgent=False, category='local_reversible'):
    return {'id': name, 'scopes': [scope], 'depends_on': list(depends),
            'small_reversible': True, 'urgent': urgent,
            'quality_assessment': {'schema': 'quality-assessment/v1', 'project_level': 'FAST',
                                   'risk_level': 'FAST', 'risk_categories': [category],
                                   'risk_reason': '', 'mandatory_check_ids': ['platform-check']}}


def request(*tasks, cap=2):
    ledger = budget.new_ledger('task', 'wake', policy(cap))
    return {'schema': 'execution-strategy/v1', 'tasks': list(tasks), 'ledger': ledger,
            'agent_reservations': [{'task_id': t['id'], 'event': event(t['id'])} for t in tasks]}


class ExecutionStrategyTests(unittest.TestCase):
    def test_same_new_reservation_cannot_cover_two_tasks(self):
        item = request(task('alpha', 'src/a'), task('beta', 'src/b'))
        item['ledger']['policy']['max_parallel_agents'] = 1
        item['ledger'] = budget.new_ledger('task', 'wake', item['ledger']['policy'])
        item['agent_reservations'][1]['event'] = copy.deepcopy(item['agent_reservations'][0]['event'])
        with self.assertRaises(ValueError):
            execution_strategy.evaluate(item)

    def test_portable_path_aliases_cannot_be_parallel_writers(self):
        for left, right in [('src/Foo.py', 'src/foo.py'),
                            ('src/café.py', 'src/cafe\u0301.py')]:
            with self.subTest(paths=(left, right)):
                item = request(task('alpha', left), task('beta', right))
                self.assertEqual(execution_strategy.evaluate(item)['action'], 'SINGLE')

    def test_disjoint_tasks_require_all_sequential_budget_admissions(self):
        item = request(task('alpha', 'src/a'), task('beta', 'src/b'))
        result = execution_strategy.evaluate(item)
        self.assertEqual(result['action'], 'PARALLEL')
        self.assertEqual(result['agent_task_ids'], ['alpha', 'beta'])
        self.assertEqual(result['integrator'], 'single')
        self.assertFalse(result['authorizes_external_start'])
        self.assertEqual(item['ledger']['events'], [])
        item['ledger']['policy'] = policy(1)
        item['ledger'] = budget.new_ledger('task', 'wake', policy(1))
        result = execution_strategy.evaluate(item)
        self.assertEqual(result['action'], 'SINGLE')
        self.assertEqual(result['agent_task_ids'], [])

    def test_overlap_or_dependency_forces_single_executor(self):
        for second in (task('beta', 'src/a/child'), task('beta', 'src/b', depends=('alpha',))):
            with self.subTest(second=second):
                result = execution_strategy.evaluate(request(task('alpha', 'src/a'), second))
                self.assertEqual(result['action'], 'SINGLE')

    def test_active_agents_replay_and_exhaustion_cannot_recommend_duplicate_launch(self):
        item = request(task('alpha', 'src/a'), task('beta', 'src/b'))
        item['ledger'] = budget.apply_event(item['ledger'], event('alpha'))
        result = execution_strategy.evaluate(item)
        self.assertEqual(result['action'], 'WAIT')
        self.assertIn('reconcile', result['reasons'][0])
        # An unrelated active agent consumes one of two available slots.
        item['ledger'] = budget.new_ledger('task', 'wake', policy())
        item['ledger'] = budget.apply_event(item['ledger'], event('gamma'))
        self.assertEqual(execution_strategy.evaluate(item)['action'], 'SINGLE')
        item['ledger'] = budget.new_ledger('task', 'wake', policy())
        item['ledger']['policy']['task_limits']['agent_starts'] = 0
        item['ledger'] = budget.new_ledger('task', 'wake', item['ledger']['policy'])
        self.assertEqual(execution_strategy.evaluate(item)['action'], 'SINGLE')

    def test_small_compatible_changes_share_candidate_without_losing_gates(self):
        item = request(task('alpha', 'src/a'), task('beta', 'src/b'), task('urgent', 'src/c', urgent=True))
        result = execution_strategy.evaluate(item)
        self.assertEqual(result['batch_candidate']['task_ids'], ['alpha', 'beta'])
        self.assertEqual(result['batch_candidate']['mandatory_check_ids'], ['platform-check'])
        self.assertNotIn('urgent', result['batch_candidate']['task_ids'])
        item['tasks'][1]['quality_assessment']['risk_categories'] = ['cdc_core']
        item['tasks'][1]['quality_assessment']['risk_reason'] = 'core change'
        result = execution_strategy.evaluate(item)
        self.assertFalse(result['batch_candidate']['eligible'])
        self.assertEqual(result['task_quality']['beta']['effective_level'], 'FULL')

    def test_medium_project_floor_is_retained_for_shared_candidate(self):
        item = request(task('alpha', 'docs/a', category='documentation'),
                       task('beta', 'docs/b', category='documentation'))
        item['tasks'][0]['quality_assessment']['project_level'] = 'MEDIUM'
        item['tasks'][1]['quality_assessment']['mandatory_check_ids'] = ['isolated-check']
        batch = execution_strategy.evaluate(item)['batch_candidate']
        self.assertTrue(batch['eligible'])
        self.assertEqual(batch['effective_level'], 'MEDIUM')
        self.assertEqual(batch['mandatory_check_ids'], ['platform-check', 'isolated-check'])

    def test_invalid_scopes_reservations_and_risk_cannot_forge_parallelism(self):
        item = request(task('alpha', 'src/a'), task('beta', 'src/b'))
        for mutation in (
            lambda x: x['tasks'][1]['scopes'].append('../escape'),
            lambda x: x['agent_reservations'][1]['event'].update(kind='compute_start'),
            lambda x: x['tasks'][1]['quality_assessment'].update(risk_categories=['invented']),
        ):
            candidate = copy.deepcopy(item); mutation(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                execution_strategy.evaluate(candidate)


if __name__ == '__main__': unittest.main()
