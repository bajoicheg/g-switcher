"""Composed development advice preserves independent validation gates."""
from pathlib import Path
import copy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import development_contract as contract


def request():
    sha = '2' * 40
    return {
        'schema': 'development-assessment/v1', 'candidate_sha': sha,
        'quality': {
            'schema': 'quality-assessment/v1', 'project_level': 'FAST',
            'risk_level': 'FAST', 'risk_categories': ['local_reversible'],
            'risk_reason': 'scoped reversible change',
            'mandatory_check_ids': ['focused']},
        'cycle': {
            'schema': 'validation-cycle/v1', 'cycle_number': 1,
            'max_validation_cycles': 2, 'changed_inputs': [], 'risk_reason': '',
            'prior_evidence_insufficient_reason': '', 'strategy_revision_ref': None,
            'budget_observation': {
                'time_seconds': 2, 'tokens': None, 'external_starts': 0,
                'time_limit_seconds': 100, 'token_limit': None,
                'external_start_limit': 2, 'unknown_reason': 'tokens unmeasured'}},
        'required_checks': [{'id': 'focused', 'exact_candidate_required': False}],
        'completed_checks': [{'check_id': 'focused', 'state': 'success',
                              'candidate_sha': sha, 'evidence_ref': 'run:focused'}],
        'reuse_requests': [],
        'change': {'kind': 'text_layout', 'tdd_risk_reasons': [],
                   'compatible_change_ids': [], 'urgent': False},
    }


def reuse():
    inputs = {'dependency_fingerprints': {'src/a.py': 'a' * 64},
              'argv': ['python', 'test.py'], 'parameters': {},
              'environment_fingerprint': 'b' * 64,
              'check_definition_fingerprint': 'c' * 64}
    return {'schema': 'evidence-reuse/v1', 'check_id': 'focused',
            'source_candidate_sha': '1' * 40, 'target_candidate_sha': '2' * 40,
            'source_evidence_ref': 'run:original', 'source_state': 'success',
            'original_inputs': inputs, 'current_inputs': copy.deepcopy(inputs),
            'coverage_refs': ['review:coverage'], 'exact_candidate_required': False}


class DevelopmentContractTests(unittest.TestCase):
    def test_valid_focused_assessment_has_no_effect_authority(self):
        result = contract.evaluate(request())
        self.assertTrue(result['validation_recommended'])
        self.assertEqual(result['quality']['effective_level'], 'FAST')
        self.assertEqual(result['cycle']['action'], 'VALIDATE')
        self.assertEqual(result['check_results'][0]['status'], 'satisfied')
        self.assertEqual(result['tdd'], {'recommended': False, 'reasons': []})
        for key in ('authorizes_external_start', 'authorizes_product_write',
                    'authorizes_merge', 'authorizes_release', 'authorizes_adoption'):
            self.assertIs(result[key], False)

    def test_core_risk_escalates_and_selects_tdd_for_explicit_boundary(self):
        d = request()
        d['quality']['risk_categories'] = ['cdc_core']
        d['quality']['risk_reason'] = 'modifies core boundary'
        d['change']['kind'] = 'feature'
        d['change']['tdd_risk_reasons'] = ['critical_boundary']
        r = contract.evaluate(d)
        self.assertEqual(r['quality']['effective_level'], 'FULL')
        self.assertEqual(r['quality']['mandatory_check_ids'], ['focused'])
        self.assertEqual(r['tdd'], {'recommended': True, 'reasons': ['critical_boundary']})

    def test_declared_critical_risk_selects_tdd_without_repeating_reason(self):
        d = request(); d['quality']['risk_categories'] = ['executor_authority']
        r = contract.evaluate(d)
        self.assertEqual(r['quality']['effective_level'], 'FULL')
        self.assertTrue(r['tdd']['recommended'])
        self.assertIn('critical_risk:executor_authority', r['tdd']['reasons'])

    def test_critical_risk_without_declared_gate_fails_closed(self):
        d = request()
        d['quality']['risk_categories'] = ['authentication']
        d['quality']['mandatory_check_ids'] = []
        r = contract.evaluate(d)
        self.assertFalse(r['validation_recommended'])
        self.assertIn('critical_mandatory_checks_missing', r['blockers'])

    def test_missing_or_failed_mandatory_check_fails_closed(self):
        for completed in ([], [{'check_id': 'focused', 'state': 'failed',
                               'candidate_sha': '2' * 40, 'evidence_ref': 'run:failed'}]):
            with self.subTest(completed=completed):
                d = request(); d['completed_checks'] = completed
                r = contract.evaluate(d)
                self.assertFalse(r['validation_recommended'])
                self.assertIn('mandatory_check_unsatisfied:focused', r['blockers'])

    def test_unknown_check_evidence_and_wrong_candidate_fail_closed(self):
        d = request(); d['completed_checks'][0]['state'] = 'unknown'
        with self.assertRaises(ValueError): contract.evaluate(d)
        d = request(); d['completed_checks'][0]['candidate_sha'] = '3' * 40
        r = contract.evaluate(d)
        self.assertFalse(r['validation_recommended'])
        self.assertIn('mandatory_check_unsatisfied:focused', r['blockers'])

    def test_repeat_economics_reuses_existing_cycle_rejection(self):
        d = request(); d['cycle']['cycle_number'] = 2
        r = contract.evaluate(d)
        self.assertFalse(r['validation_recommended'])
        self.assertIn('unchanged_repeat', r['blockers'])
        self.assertIn('prior_evidence_not_invalidated', r['blockers'])

    def test_reuse_retains_original_sha_when_dependencies_match(self):
        d = request(); d['completed_checks'] = []; d['reuse_requests'] = [reuse()]
        r = contract.evaluate(d)
        self.assertTrue(r['validation_recommended'])
        self.assertEqual(r['check_results'][0]['source_candidate_sha'], '1' * 40)
        self.assertEqual(r['check_results'][0]['status'], 'satisfied')

    def test_changed_reuse_input_blocks_mandatory_check(self):
        d = request(); d['completed_checks'] = []; d['reuse_requests'] = [reuse()]
        d['reuse_requests'][0]['current_inputs']['environment_fingerprint'] = 'd' * 64
        r = contract.evaluate(d)
        self.assertFalse(r['validation_recommended'])
        self.assertIn('inputs_changed:environment_fingerprint', r['reuse_results'][0]['blockers'])
        self.assertIn('mandatory_check_unsatisfied:focused', r['blockers'])

    def test_exact_candidate_gate_cannot_be_downgraded_by_reuse_claim(self):
        d = request(); d['required_checks'][0]['exact_candidate_required'] = True
        d['completed_checks'] = []; d['reuse_requests'] = [reuse()]
        r = contract.evaluate(d)
        self.assertFalse(r['validation_recommended'])
        self.assertIn('exact_candidate_required', r['reuse_results'][0]['blockers'])
        self.assertIn('mandatory_check_unsatisfied:focused', r['blockers'])

    def test_low_risk_compatible_batch_recommendation_retains_checks(self):
        d = request(); d['change']['compatible_change_ids'] = ['a', 'b']
        r = contract.evaluate(d)
        self.assertTrue(r['batching']['recommended'])
        self.assertEqual(r['batching']['candidate_change_ids'], ['a', 'b'])
        self.assertEqual(r['quality']['mandatory_check_ids'], ['focused'])
        d['change']['urgent'] = True
        self.assertFalse(contract.evaluate(d)['batching']['recommended'])
        d['change']['urgent'] = False; d['quality']['risk_categories'] = ['authentication']
        self.assertFalse(contract.evaluate(d)['batching']['recommended'])

    def test_schema_is_strict_and_evidence_must_be_declared(self):
        d = request(); d['extra'] = 'ignored'
        with self.assertRaises(ValueError): contract.evaluate(d)
        d = request(); d['completed_checks'][0]['check_id'] = 'undeclared'
        with self.assertRaises(ValueError): contract.evaluate(d)
        d = request(); d['required_checks'] = []; d['completed_checks'] = []
        self.assertFalse(contract.evaluate(d)['validation_recommended'])


if __name__ == '__main__':
    unittest.main()
