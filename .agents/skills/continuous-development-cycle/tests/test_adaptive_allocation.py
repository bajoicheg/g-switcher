import copy
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_execution_strategy import request as strategy_request, task, event
import budget


def sample(name, profile='inline', *, tokens=100, elapsed=60, delivered=1,
           defects=0, provenance='measured', group='same-work-env-window'):
    def observed(value):
        return {'value': value, 'unknown_reason': 'not available' if value is None else None}
    return {'profile_id': profile, 'operation': {
        'schema': 'operation-observation/v1', 'observation_ref': name,
        'comparison_group': group, 'elapsed_seconds': elapsed,
        'tokens': {'value': None if provenance == 'unknown' else tokens,
                   'provenance': provenance,
                   'source': None if provenance == 'unknown' else 'actual-runtime:'+name,
                   'basis': 'sample estimate' if provenance == 'estimated' else None},
        'budget_ref': 'actual-budget:'+name,
        'phases': {k: observed(None) for k in ('startup', 'implementation', 'validation', 'wait')},
        'delivery': {'delivered': observed(delivered), 'escaped_defects': observed(defects)}}}


def allocation(*observations):
    return {'schema': 'adaptive-allocation/v1', 'comparison_group': 'same-work-env-window',
            'strategy': strategy_request(task('alpha', 'src/a'), task('beta', 'src/b')),
            'default_profile_id': 'parallel',
            'profiles': [{'id': 'inline', 'reasoning_effort': 'high', 'max_agents': 0,
                          'agent_reservations': []},
                         {'id': 'parallel', 'reasoning_effort': 'high', 'max_agents': 2,
                          'agent_reservations': [{'task_id': name, 'event': event(name)}
                                                 for name in ('alpha', 'beta')]}],
            'observations': list(observations)}


class AdaptiveAllocationTests(unittest.TestCase):
    def evaluate(self, request):
        self.assertIsNotNone(importlib.util.find_spec('adaptive_allocation'),
                             'measured adaptive allocator has not been implemented')
        return importlib.import_module('adaptive_allocation').evaluate(request)

    def test_two_measured_samples_select_lower_cost_profile(self):
        request = allocation(sample('i1'), sample('i2'),
                             sample('p1', 'parallel', tokens=300, elapsed=30),
                             sample('p2', 'parallel', tokens=300, elapsed=30))
        result = self.evaluate(request)
        self.assertEqual(result['profile_id'], 'inline')
        self.assertEqual(result['selection'], 'measured')
        self.assertEqual(result['action'], 'SINGLE')
        self.assertEqual(result['measurement']['observation_refs'], ['i1', 'i2'])
        self.assertEqual(result['measurement']['tokens_per_delivered'], 100)

    def test_sparse_measurements_retain_safe_default(self):
        for observations in ([], [sample('one')]):
            result = self.evaluate(allocation(*observations))
            self.assertEqual(result['profile_id'], 'parallel')
            self.assertEqual(result['selection'], 'default')
            self.assertIsNone(result['measurement'])

    def test_unknown_and_estimated_tokens_cannot_prove_savings(self):
        for provenance in ('unknown', 'estimated'):
            result = self.evaluate(allocation(sample('a', provenance=provenance),
                                              sample('b', provenance=provenance)))
            self.assertEqual(result['selection'], 'default')
            self.assertEqual(result['profile_id'], 'parallel')

    def test_any_observed_defect_disqualifies_measured_profile(self):
        result = self.evaluate(allocation(sample('a'), sample('b'), sample('c', defects=1)))
        self.assertEqual(result['selection'], 'default')
        self.assertEqual(result['profile_id'], 'parallel')
        self.assertIn('inline', result['excluded_profile_ids'])

    def test_unknown_delivery_or_defects_and_zero_delivery_do_not_qualify(self):
        for field, value in [('delivered', None), ('defects', None), ('delivered', 0)]:
            observations = [sample('a', **{field: value}), sample('b', **{field: value})]
            self.assertEqual(self.evaluate(allocation(*observations))['selection'], 'default')

    def test_defective_default_blocks_even_if_tokens_or_delivery_are_unknown(self):
        for changes in ({'provenance': 'unknown'}, {'provenance': 'estimated'}, {'delivered': 0}):
            result = self.evaluate(allocation(sample('bad', 'parallel', defects=1, **changes)))
            self.assertEqual(result['action'], 'WAIT')
            self.assertEqual(result['agent_task_ids'], [])

    def test_selected_profile_uses_its_own_prospective_costs(self):
        request = allocation()
        policy = copy.deepcopy(request['strategy']['ledger']['policy'])
        policy['task_limits']['tokens'] = 50
        request['strategy']['ledger'] = budget.new_ledger('task', 'wake', policy)
        for reservation in request['profiles'][1]['agent_reservations']:
            reservation['event']['cost']['tokens'] = 60
        result = self.evaluate(request)
        self.assertEqual(result['action'], 'SINGLE')
        self.assertEqual(result['reservation_event_ids'], ['agent-alpha', 'agent-beta'])

    def test_aggregate_elapsed_overflow_is_controlled_rejection(self):
        with self.assertRaises(ValueError):
            self.evaluate(allocation(sample('a', elapsed=1e308), sample('b', elapsed=1e308)))

    def test_aggregate_token_and_delivery_overflow_is_controlled_rejection(self):
        for field in ('tokens', 'delivered'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.evaluate(allocation(sample('a', **{field: 10 ** 308}),
                                         sample('b', **{field: 10 ** 308})))

    def test_comparison_groups_and_duplicate_observation_refs_are_rejected(self):
        for observations in ([sample('a', group='another-env')], [sample('a'), sample('a')]):
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                self.evaluate(allocation(*observations))

    def test_full_quality_floor_cannot_select_low_effort(self):
        request = allocation(sample('a'), sample('b'))
        request['profiles'][0]['reasoning_effort'] = 'medium'
        request['strategy']['tasks'][0]['quality_assessment'].update(
            risk_categories=['cdc_core'], risk_reason='core allocation')
        result = self.evaluate(request)
        self.assertEqual(result['profile_id'], 'parallel')
        self.assertEqual(result['task_quality']['alpha']['effective_level'], 'FULL')
        request['profiles'][1]['reasoning_effort'] = 'medium'
        with self.assertRaises(ValueError): self.evaluate(request)

    def test_default_profile_below_minimum_floor_is_rejected(self):
        request = allocation()
        request['profiles'][1]['reasoning_effort'] = 'low'
        with self.assertRaises(ValueError): self.evaluate(request)

    def test_budget_exhaustion_preserves_single_execution(self):
        request = allocation(sample('a', 'parallel'), sample('b', 'parallel'))
        policy = copy.deepcopy(request['strategy']['ledger']['policy'])
        policy['task_limits']['agent_starts'] = 0
        request['strategy']['ledger'] = budget.new_ledger('task', 'wake', policy)
        self.assertEqual(self.evaluate(request)['action'], 'SINGLE')

    def test_recorded_reservation_preserves_wait(self):
        request = allocation(sample('a'), sample('b'))
        request['strategy']['ledger'] = budget.apply_event(request['strategy']['ledger'], event('alpha'))
        result = self.evaluate(request)
        self.assertEqual(result['action'], 'WAIT')
        self.assertEqual(result['agent_task_ids'], [])

    def test_profile_cannot_override_overlap_or_dependency(self):
        for mutate in (lambda r: r['strategy']['tasks'][1].update(scopes=['src/a/child']),
                       lambda r: r['strategy']['tasks'][1].update(depends_on=['alpha'])):
            request = allocation(sample('a', 'parallel'), sample('b', 'parallel'))
            mutate(request)
            self.assertEqual(self.evaluate(request)['action'], 'SINGLE')

    def test_agent_profile_cap_and_input_immutability(self):
        request = allocation()
        request['profiles'][1]['max_agents'] = 1
        before = copy.deepcopy(request)
        result = self.evaluate(request)
        self.assertEqual(result['action'], 'SINGLE')
        self.assertEqual(request, before)
        for key in ('authorizes_external_start', 'authorizes_product_write', 'authorizes_release',
                    'authorizes_takeover', 'authorizes_scheduler_mutation'):
            self.assertFalse(result[key])

    def test_elapsed_breaks_equal_measured_cost_ties(self):
        result = self.evaluate(allocation(sample('i1', elapsed=90), sample('i2', elapsed=90),
                                          sample('p1', 'parallel', elapsed=30),
                                          sample('p2', 'parallel', elapsed=30)))
        self.assertEqual(result['profile_id'], 'parallel')
        self.assertEqual(result['action'], 'PARALLEL')
        self.assertEqual(result['agent_task_ids'], ['alpha', 'beta'])

    def test_cost_is_normalized_by_observed_delivery(self):
        result = self.evaluate(allocation(sample('i1', tokens=150, delivered=3),
                                          sample('i2', tokens=150, delivered=3),
                                          sample('p1', 'parallel'), sample('p2', 'parallel')))
        self.assertEqual(result['profile_id'], 'inline')
        self.assertEqual(result['measurement']['tokens_per_delivered'], 50)

    def test_invalid_fields_numbers_and_profile_ids_are_rejected(self):
        mutations = [lambda r: r.update(extra=True),
                     lambda r: r['profiles'][0].update(max_agents=True),
                     lambda r: r['profiles'][0].update(max_agents=-1),
                     lambda r: r['profiles'][0].update(reasoning_effort='max'),
                     lambda r: r['profiles'][0].update(id='parallel'),
                     lambda r: r.update(default_profile_id='absent'),
                     lambda r: r['observations'][0].update(profile_id='absent'),
                     lambda r: r['observations'][0]['operation'].update(elapsed_seconds=float('inf'))]
        for mutate in mutations:
            request = allocation(sample('a'))
            mutate(request)
            with self.subTest(request=request), self.assertRaises(ValueError): self.evaluate(request)

    def test_json_cli_uses_same_validated_recommendation(self):
        self.evaluate(allocation())
        script = Path(__file__).resolve().parents[1] / 'scripts/adaptive_allocation.py'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            path.write_text(json.dumps(allocation()))
            result = subprocess.run([sys.executable, '-B', str(script), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['selection'], 'default')
            entry = subprocess.run([sys.executable, '-B', str(script.with_name('cdc.py')),
                                    'allocate', str(path)], capture_output=True, text=True)
            self.assertEqual(entry.returncode, 0, entry.stderr)
            self.assertEqual(json.loads(entry.stdout), json.loads(result.stdout))
            path.write_text('{"schema":"bad"}')
            failed = subprocess.run([sys.executable, '-B', str(script), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)

    def test_cli_rejects_duplicate_json_fields(self):
        self.evaluate(allocation())
        script = Path(__file__).resolve().parents[1] / 'scripts/adaptive_allocation.py'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            raw = json.dumps(allocation())
            path.write_text(raw.replace('"default_profile_id": "parallel"',
                                        '"default_profile_id":"inline","default_profile_id":"parallel"'))
            failed = subprocess.run([sys.executable, '-B', str(script), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)

    def test_malformed_strategy_inputs_fail_closed_in_api_and_both_clis(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/adaptive_allocation.py'
        mutations = [lambda r: r['profiles'][1]['agent_reservations'][0]['event']['cost'].update(tokens=10 ** 309),
                     lambda r: r['strategy']['ledger']['policy'].update(max_parallel_agents=10 ** 309),
                     lambda r: r['profiles'][1]['agent_reservations'][0].update(task_id=[])]
        for mutate in mutations:
            request = allocation()
            mutate(request)
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.evaluate(request)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'request.json'
                path.write_text(json.dumps(request))
                for argv in ([sys.executable, '-B', str(script), str(path)],
                             [sys.executable, '-B', str(script.with_name('cdc.py')), 'allocate', str(path)]):
                    failed = subprocess.run(argv, capture_output=True, text=True)
                    with self.subTest(argv=argv):
                        self.assertEqual(failed.returncode, 2)
                        self.assertEqual(failed.stdout, '')
                        self.assertNotIn('Traceback', failed.stderr)


if __name__ == '__main__': unittest.main()
