"""Real child-process qualification for the native supervised check wrapper."""
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_check_runner.py'


def python(code):
    return [sys.executable, '-B', '-c', code]


class CheckRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cwd = self.root / 'worktree'; self.cwd.mkdir()
        self.evidence = self.root / 'journal'; self.evidence.mkdir(mode=0o700)

    def command(self, checks, provider=None, *, evidence=None):
        return [sys.executable, '-B', str(RUNNER), '--evidence-dir', str(evidence or self.evidence),
                '--tests-json', json.dumps(checks), '--', *(provider or python('pass'))]

    def run_wrapper(self, checks, provider=None, **kwargs):
        return subprocess.run(self.command(checks, provider, **kwargs), cwd=self.cwd,
                              capture_output=True, text=True, timeout=15)

    def receipt(self):
        return json.loads((self.evidence / 'checks.json').read_text())

    def test_success_preserves_provider_output_and_actual_check_evidence(self):
        check = python("from pathlib import Path; import sys; Path('scoped.txt').write_text('actual'); print('check output'); print('check error', file=sys.stderr)")
        result = self.run_wrapper([check], python("import sys; assert sys.stdin.read()==''; print('provider output'); print('provider error', file=sys.stderr)"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'provider output\n')
        self.assertEqual(result.stderr, 'provider error\n')
        self.assertEqual((self.cwd / 'scoped.txt').read_text(), 'actual')
        receipt = self.receipt()
        self.assertEqual(receipt['schema'], 'cdc-agent-checks/v1')
        self.assertEqual(receipt['provider_exit_code'], 0)
        self.assertEqual(receipt['status'], 'passed')
        self.assertEqual(len(receipt['checks']), 1)
        observed = receipt['checks'][0]
        self.assertEqual(observed['argv'], check)
        self.assertEqual(observed['exit_code'], 0)
        self.assertEqual(Path(observed['stdout']).read_text(), 'check output\n')
        self.assertEqual(Path(observed['stderr']).read_text(), 'check error\n')
        self.assertTrue(observed['started_at'].endswith('Z'))
        self.assertTrue(observed['completed_at'].endswith('Z'))
        for file in (Path(observed['stdout']), Path(observed['stderr']), self.evidence / 'checks.json'):
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_provider_failure_skips_checks_and_preserves_exit(self):
        result = self.run_wrapper([python("open('must-not-run', 'w').write('bad')")], python('raise SystemExit(7)'))
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.cwd / 'must-not-run').exists())
        self.assertEqual(self.receipt(), {'schema': 'cdc-agent-checks/v1', 'provider_exit_code': 7,
                                         'checks': [], 'status': 'not_run'})

    def test_signal_exit_is_recorded_raw_and_wrapper_normalizes_it(self):
        result = self.run_wrapper([], python('import os,signal; os.kill(os.getpid(), signal.SIGTERM)'))
        self.assertEqual(result.returncode, 143)
        self.assertEqual(self.receipt()['provider_exit_code'], -15)

    def test_failed_check_is_failfast_and_returns_real_nonzero(self):
        result = self.run_wrapper([python("print('failed check'); raise SystemExit(9)"),
                                   python("open('must-not-run', 'w').write('bad')")])
        self.assertEqual(result.returncode, 9)
        self.assertFalse((self.cwd / 'must-not-run').exists())
        self.assertEqual(self.receipt()['status'], 'failed')
        self.assertEqual([row['exit_code'] for row in self.receipt()['checks']], [9])

    def test_missing_provider_or_check_has_null_exit_and_explicit_error(self):
        result = self.run_wrapper([], [str(self.root / 'missing-provider')])
        self.assertEqual(result.returncode, 2)
        receipt = self.receipt()
        self.assertIsNone(receipt['provider_exit_code'])
        self.assertTrue(receipt['error'])
        self.assertEqual(receipt['status'], 'not_run')
        # A distinct original journal is needed for the separate check launch.
        second = self.root / 'journal-check'; second.mkdir(mode=0o700)
        result = self.run_wrapper([[str(self.root / 'missing-check')]], evidence=second)
        self.assertEqual(result.returncode, 2)
        receipt = json.loads((second / 'checks.json').read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertIsNone(receipt['checks'][0]['exit_code'])
        self.assertTrue(receipt['checks'][0]['error'])

    def test_empty_checks_record_not_run_without_changing_worktree(self):
        result = self.run_wrapper([])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(list(self.cwd.iterdir()), [])
        self.assertEqual(self.receipt()['status'], 'not_run')
        self.assertEqual(self.receipt()['checks'], [])

    def test_invalid_argument_arrays_are_rejected_before_provider_launch(self):
        provider = python("open('must-not-run', 'w').write('bad')")
        for index, checks in enumerate(({}, ['shell command'], [[]], [[1]], [['']], [['bad\x00arg']])):
            directory = self.root / ('invalid-' + str(index)); directory.mkdir()
            with self.subTest(checks=checks):
                result = self.run_wrapper(checks, provider, evidence=directory)
                self.assertEqual(result.returncode, 2)
                self.assertFalse((self.cwd / 'must-not-run').exists())
                self.assertFalse((directory / 'tests.lock').exists())

    def test_existing_receipt_or_lock_never_replays_provider(self):
        provider = python("from pathlib import Path; p=Path('starts'); p.write_text(p.read_text()+'start' if p.exists() else 'start')")
        self.assertEqual(self.run_wrapper([], provider).returncode, 0)
        self.assertEqual(self.run_wrapper([], provider).returncode, 2)
        self.assertEqual((self.cwd / 'starts').read_text(), 'start')
        second = self.root / 'receipt-only'; second.mkdir()
        (second / 'checks.json').write_text('{}')
        self.assertEqual(self.run_wrapper([], provider, evidence=second).returncode, 2)
        self.assertEqual((self.cwd / 'starts').read_text(), 'start')
        third = self.root / 'lock-only'; third.mkdir()
        (third / 'tests.lock').write_text('original start reply was lost')
        self.assertEqual(self.run_wrapper([], provider, evidence=third).returncode, 2)
        self.assertEqual((self.cwd / 'starts').read_text(), 'start')

    def test_evidence_directory_must_preexist_and_commands_never_use_a_shell(self):
        absent = self.root / 'absent'
        self.assertEqual(self.run_wrapper([], evidence=absent).returncode, 2)
        self.assertFalse(absent.exists())
        result = self.run_wrapper([['echo unsafe > escaped']])
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.cwd / 'escaped').exists())

    def test_concurrent_wrapper_calls_allow_only_one_provider_start(self):
        provider = python("from pathlib import Path; import time; Path('one-start').write_text('actual'); time.sleep(.1)")
        first = subprocess.Popen(self.command([], provider), cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.Popen(self.command([], provider), cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        first.communicate(timeout=15); second.communicate(timeout=15)
        self.assertEqual(sorted([first.returncode, second.returncode]), [0, 2])
        self.assertEqual((self.cwd / 'one-start').read_text(), 'actual')


if __name__ == '__main__':
    unittest.main()
