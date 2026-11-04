import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import operation_report


def observed(value, reason=None):
    return {'value': value, 'unknown_reason': reason}


def request():
    return {
        'schema': 'operation-observation/v1', 'elapsed_seconds': 89.5,
        'observation_ref': 'run-17', 'comparison_group': 'same task/window/environment',
        'tokens': {'value': None, 'provenance': 'unknown', 'source': None, 'basis': None},
        'budget_ref': 'budget-ledger/task-1/r1',
        'phases': {name: observed(None, 'not instrumented') for name in
                   ('startup', 'implementation', 'validation', 'wait')},
        'delivery': {'delivered': observed(None, 'not observed'),
                     'escaped_defects': observed(None, 'not observed')},
    }


class OperationReportTests(unittest.TestCase):
    def test_token_comparison_retains_the_known_endpoint_without_inventing_delta(self):
        before, after = request(), request()
        before['tokens'] = {'value': 123, 'provenance': 'measured',
                            'source': 'provider usage', 'basis': None}
        result = operation_report.compare(before, after)['tokens']
        self.assertEqual(result['before'], 123)
        self.assertIsNone(result['after'])
        self.assertIsNone(result['delta'])
        self.assertEqual(result['before_provenance'], 'measured')
        self.assertEqual(result['after_provenance'], 'unknown')

    def test_unknown_values_stay_null_and_suffix_omits_tokens(self):
        report = operation_report.measure(request())
        self.assertEqual(report['schema'], 'operation-measurement/v1')
        self.assertIsNone(report['tokens']['value'])
        self.assertIsNone(report['phases']['wait']['value'])
        self.assertEqual(report['budget_ref'], 'budget-ledger/task-1/r1')
        self.assertEqual(report['observation_ref'], 'run-17')
        self.assertEqual(report['comparison_group'], 'same task/window/environment')
        self.assertEqual(operation_report.render(request()), '(1 мин)')

    def test_rounds_half_up_and_displays_only_sourced_tokens(self):
        item = request()
        item['elapsed_seconds'] = 90
        item['tokens'] = {'value': 123, 'provenance': 'measured',
                          'source': 'provider usage', 'basis': None}
        self.assertEqual(operation_report.render(item), '(2 мин; 123 токенов)')
        item['tokens'] = {'value': 140, 'provenance': 'estimated',
                          'source': 'model context sample', 'basis': '140 counted tokenizer units'}
        self.assertEqual(operation_report.render(item), '(2 мин; ≈140 токенов)')

    def test_rejects_invented_estimate_and_bad_observations(self):
        for tokens in (
            {'value': 10, 'provenance': 'estimated', 'source': 'guess', 'basis': None},
            {'value': 10, 'provenance': 'measured', 'source': None, 'basis': None},
            {'value': 10, 'provenance': 'unknown', 'source': None, 'basis': None},
        ):
            item = request(); item['tokens'] = tokens
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                operation_report.measure(item)
        item = request(); item['phases']['wait'] = observed(None)
        with self.assertRaises(ValueError): operation_report.measure(item)
        item = request(); item['delivery']['escaped_defects'] = observed(-1)
        with self.assertRaises(ValueError): operation_report.measure(item)
        item = request(); item['elapsed_seconds'] = True
        with self.assertRaises(ValueError): operation_report.measure(item)
        for key in ('observation_ref', 'comparison_group'):
            item = request(); item[key] = ' '
            with self.subTest(field=key), self.assertRaises(ValueError):
                operation_report.measure(item)

    def test_compare_reports_only_observed_deltas_not_inferred_savings(self):
        before, after = request(), request()
        after['observation_ref'] = 'run-18'
        before['phases']['startup'] = observed(40)
        after['phases']['startup'] = observed(35)
        before['delivery']['delivered'] = observed(2)
        after['delivery']['delivered'] = observed(3)
        after['elapsed_seconds'] = 60
        result = operation_report.compare(before, after)
        self.assertEqual(result['schema'], 'operation-comparison/v1')
        self.assertEqual(result['comparison_group'], 'same task/window/environment')
        self.assertEqual((result['before_ref'], result['after_ref']), ('run-17', 'run-18'))
        self.assertEqual(result['elapsed_seconds']['delta'], -29.5)
        self.assertEqual(result['phases']['startup']['delta'], -5)
        self.assertIsNone(result['phases']['wait']['delta'])
        self.assertIsNone(result['delivery']['escaped_defects']['delta'])
        self.assertEqual(result['delivery']['delivered']['delta'], 1)
        self.assertIsNone(result['tokens']['delta'])
        self.assertNotIn('savings', result)
        self.assertNotIn('quality_gain', result)

    def test_compare_rejects_different_work_window_or_environment(self):
        before, after = request(), request()
        after['comparison_group'] = 'different task/window/environment'
        with self.assertRaises(ValueError): operation_report.compare(before, after)


if __name__ == '__main__': unittest.main()
