"""Focused future-source contracts; no historical journals or real task starts."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
source = os.environ.get('CDC_RUNTIME_SOURCE', str(ROOT / 'scripts/managed_executor_runtime.py'))
spec = importlib.util.spec_from_file_location('signal_candidate', source)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

IDENTITY = {'state': 'S', 'parent': 40, 'birth': '123', 'signal_pid': 7}


class SignalBoundaryTests(unittest.TestCase):
    def test_procfs_birth_and_signal_namespace_translation(self):
        stat = '50 (name with ) spaces) ' + ' '.join(['S', '40'] + ['0'] * 17 + ['123'])
        for own, expected in (('NSpid: 40 6', 7), ('NSpid: 40', 50),
                              ('NSpid: 40 6 2', None)):
            with self.subTest(own=own), mock.patch.object(Path, 'read_text',
                    side_effect=[stat, 'NSpid: 50 7', own]):
                row = runtime._process(50)
                self.assertEqual(row['birth'], '123')
                self.assertEqual(row['parent'], 40)
                self.assertEqual(row['signal_pid'], expected)
        with mock.patch.object(Path, 'read_text', side_effect=[stat, 'Name: hidden']):
            self.assertIsNone(runtime._process(50))

    def test_pidfd_rechecks_birth_and_namespace_mapping(self):
        for changed in ({**IDENTITY, 'birth': '124'},
                        {**IDENTITY, 'signal_pid': 8}, None):
            with self.subTest(changed=changed), \
                 mock.patch.object(runtime, '_process', side_effect=[IDENTITY, changed]), \
                 mock.patch.object(runtime.os, 'pidfd_open', return_value=90, create=True) as opened, \
                 mock.patch.object(runtime.signal, 'pidfd_send_signal', create=True) as sent, \
                 mock.patch.object(runtime.os, 'close') as closed, \
                 mock.patch.object(runtime.os, 'kill') as unsafe:
                result = runtime._signal_descendant(50, IDENTITY, signal.SIGKILL)
                self.assertEqual(result['result'], 'identity_changed')
                opened.assert_called_once_with(7, 0)
                sent.assert_not_called()
                unsafe.assert_not_called()
                closed.assert_called_once_with(90)

    def test_success_esrch_eperm_and_fd_cleanup(self):
        for error, expected in ((None, 'sent'),
                                (ProcessLookupError(errno.ESRCH, 'gone'), 'error'),
                                (PermissionError(errno.EPERM, 'denied'), 'error')):
            with self.subTest(error=error), \
                 mock.patch.object(runtime, '_process', return_value=IDENTITY), \
                 mock.patch.object(runtime.os, 'pidfd_open', return_value=90, create=True), \
                 mock.patch.object(runtime.signal, 'pidfd_send_signal', side_effect=error, create=True), \
                 mock.patch.object(runtime.os, 'close') as closed:
                result = runtime._signal_descendant(50, IDENTITY, signal.SIGTERM)
                self.assertEqual(result['result'], expected)
                if error:
                    self.assertEqual(result['errno'], error.errno)
                    self.assertEqual(result['error_type'], type(error).__name__)
                closed.assert_called_once_with(90)

    def test_unavailable_pidfd_or_namespace_never_falls_back_to_kill(self):
        for identity in (IDENTITY, {**IDENTITY, 'signal_pid': None},
                         {**IDENTITY, 'signal_pid': 0}):
            with self.subTest(identity=identity), \
                 mock.patch.object(runtime, '_process', return_value=identity), \
                 mock.patch.object(runtime.os, 'kill') as unsafe:
                with mock.patch.object(runtime.os, 'pidfd_open', create=True):
                    del runtime.os.pidfd_open
                    result = runtime._signal_descendant(50, identity, signal.SIGTERM)
                self.assertIn(result['result'], {'pidfd_unavailable', 'namespace_unavailable'})
                unsafe.assert_not_called()

    def test_pidfd_open_race_is_recorded_without_send(self):
        with mock.patch.object(runtime, '_process', return_value=IDENTITY), \
             mock.patch.object(runtime.os, 'pidfd_open',
                               side_effect=ProcessLookupError(errno.ESRCH, 'gone'), create=True), \
             mock.patch.object(runtime.signal, 'pidfd_send_signal', create=True) as sent:
            result = runtime._signal_descendant(50, IDENTITY, signal.SIGKILL)
            self.assertEqual(result['errno'], errno.ESRCH)
            sent.assert_not_called()

    def test_unknown_cannot_issue_terminal_proof(self):
        from managed_executor_store import GitManagedExecutorStore
        rt = object.__new__(runtime.ManagedExecutorRuntime)
        rt.backend = object.__new__(runtime.LocalCommandBackend)
        rt.store = object.__new__(GitManagedExecutorStore)
        rt.journal = object.__new__(runtime.ExecutionJournal)
        with mock.patch.object(rt, '_request', return_value={}), \
             mock.patch.object(rt, 'observe', return_value={'status': 'unknown', 'quiescent': False}):
            with self.assertRaisesRegex(ValueError, 'not terminal/quiescent'):
                rt.verify_terminal('future', 'future-attempt')

    def supervise(self, error=None, *, close_after_denial=False):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            request = {'identity': {'role': 'writer', 'branch': 'refs/heads/future', 'base_sha': 'a' * 40},
                       'claim': {'opaque': 'unchanged'}, 'cwd': str(directory/'worktree'),
                       'repo_root': tmp, 'timeout_seconds': 10}
            (directory/'request.json').write_text(json.dumps(request))
            (directory/'cancel.json').write_text('{}')
            clock = [0.0]
            def sleep(interval):
                clock[0] += interval
                if clock[0] > 2:
                    raise AssertionError('termination loop exceeded finite bound')
            calls = [0]
            def wait(*args):
                calls[0] += 1
                if close_after_denial and calls[0] > 1:
                    raise ChildProcessError()
                return (0, 0)
            writes = []
            original_write = runtime._write
            def write(path, value):
                writes.append(json.loads(json.dumps(value)))
                original_write(path, value)
            with mock.patch.object(runtime.ctypes, 'CDLL') as libc, \
                 mock.patch.object(runtime, '_git'), \
                 mock.patch.object(runtime, '_process', return_value=IDENTITY), \
                 mock.patch.object(runtime, '_descendants', return_value={50: IDENTITY}), \
                 mock.patch.object(runtime.os, 'waitpid', side_effect=wait), \
                 mock.patch.object(runtime.os, 'kill', side_effect=error), \
                 mock.patch.object(runtime.os, 'pidfd_open', return_value=90, create=True), \
                 mock.patch.object(runtime.signal, 'pidfd_send_signal', side_effect=error, create=True), \
                 mock.patch.object(runtime.os, 'close'), \
                 mock.patch.object(runtime.time, 'monotonic', side_effect=lambda: clock[0]), \
                 mock.patch.object(runtime.time, 'sleep', side_effect=sleep), \
                 mock.patch.object(runtime, '_write', side_effect=write):
                libc.return_value.prctl.return_value = 0
                runtime._supervise(directory)
            result = json.loads((directory/'receipt.json').read_text())
            runtime.ManagedExecutorRuntime._validate_receipt(request, result)
            return result, writes

    def test_denial_is_durable_unknown_and_bounded(self):
        result, writes = self.supervise(PermissionError(errno.EPERM, 'Operation not permitted'))
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['quiescent'])
        self.assertIsNone(result['finished_at_utc'])
        self.assertNotIn('quiescence_proof', result)
        self.assertEqual(result['termination_reason'], 'cancelled')
        self.assertEqual(result['signal_failure']['errno'], errno.EPERM)
        self.assertEqual(result['signal_failure']['pid'], 50)
        self.assertEqual(result['signal_failure']['signal_pid'], 7)
        self.assertEqual(result['signal_failure']['birth'], '123')
        self.assertTrue(any(row.get('signal_failure', {}).get('errno') == errno.EPERM
                            and row['elapsed_seconds'] < 1 for row in writes))
        self.assertEqual(result['claim'], {'opaque': 'unchanged'})

    def test_successful_signal_without_echild_is_still_bounded_unknown(self):
        result, _ = self.supervise()
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['quiescent'])
        self.assertNotIn('quiescence_proof', result)

    def test_esrch_without_echild_never_proves_closure(self):
        result, _ = self.supervise(ProcessLookupError(errno.ESRCH, 'gone'))
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['quiescent'])

    def test_only_actual_echild_allows_terminal_after_denial(self):
        result, writes = self.supervise(PermissionError(errno.EPERM, 'denied'), close_after_denial=True)
        self.assertEqual(result['status'], 'cancelled')
        self.assertTrue(result['quiescent'])
        self.assertEqual(result['quiescence_proof']['method'], 'waitpid_ECHILD')
        self.assertEqual(result['signal_failure']['errno'], errno.EPERM)
        self.assertTrue(any(row['status'] == 'unknown' for row in writes))

    def test_genuine_kernel_eperm_when_runner_has_cross_uid_target(self):
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            self.skipTest('pidfd unavailable; actual UID qualification remains required')
        try:
            fd = os.pidfd_open(1, 0)
        except OSError as exc:
            self.skipTest('PID 1 not accessible: ' + str(exc))
        try:
            try:
                signal.pidfd_send_signal(fd, 0)
            except PermissionError as exc:
                actual_error = exc
            else:
                self.skipTest('runner can signal PID 1; no genuine EPERM evidence')
        finally:
            os.close(fd)
        self.assertEqual(actual_error.errno, errno.EPERM)
        result, _ = self.supervise(actual_error)
        self.assertEqual(result['signal_failure']['errno'], errno.EPERM)
        self.assertFalse(result['quiescent'])


if __name__ == '__main__':
    unittest.main()
