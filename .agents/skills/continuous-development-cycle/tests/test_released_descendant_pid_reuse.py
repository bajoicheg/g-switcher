"""Original failed/released chain with a real recorded child; isolated boot inputs."""
import copy
import unittest
from unittest import mock

import test_released_terminal_boot_recovery as original

runtime = original.runtime


class ReleasedDescendantReuseTests(unittest.TestCase):
    worker_code = (
        'import subprocess,sys,time;'
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(.35)"]);'
        'time.sleep(.65);p.wait();sys.exit(7)'
    )

    @classmethod
    def setUpClass(cls):
        original.ReleasedBootTerminalTests.setUpClass.__func__(cls)
        children = [x for x in cls.observation['process_births'] if x['role'] == 'descendant']
        if not children:
            raise AssertionError('real supervisor must record the actual worker child')
        cls.descendant = children[0]

    setUp = original.ReleasedBootTerminalTests.setUp
    verify = original.ReleasedBootTerminalTests.verify

    def foreign_process(self, birth=None):
        return {'birth': birth if birth is not None else str(int(self.descendant['birth']) + 1),
                'parent': 2, 'state': 'I', 'signal_pid': self.descendant['pid']}

    def reusing(self, identity):
        real = runtime._process
        return mock.patch.object(runtime, '_process', side_effect=lambda pid:
                                 copy.deepcopy(identity) if pid == self.descendant['pid'] else real(pid))

    def revalidate(self, proof):
        owner = proof['ownership']
        return proof.revalidate_for(self.fixture.lease_store, owner['invocation_id'],
                                   {k: owner[k] for k in ('owner_id', 'generation')},
                                   self.session['release_receipt'])

    def test_foreign_descendant_pid_allows_only_original_sealed_failed_proof(self):
        before = (self.rt.store.read(), self.fixture.lease_store.read(), self.fixture.remote_head())
        current = self.foreign_process()
        with self.reusing(current), mock.patch.object(runtime.os, 'kill') as signal:
            proof = self.verify()
            self.assertIs(type(proof), runtime.VerifiedTerminalProof)
            self.assertEqual(proof['status'], 'failed')
            self.assertFalse(proof['authorizes_release'])
            self.assertEqual(proof['reused_descendant_pids'], [{
                'pid': self.descendant['pid'], 'original_birth': self.descendant['birth'],
                'current_birth': current['birth']}])
            self.assertEqual(self.revalidate(proof)['reused_descendant_pids'], proof['reused_descendant_pids'])
            signal.assert_not_called()
        self.assertEqual((self.rt.store.read(), self.fixture.lease_store.read(), self.fixture.remote_head()), before)

    def test_same_or_unverifiable_birth_stays_denied(self):
        for identity in ({'birth': self.descendant['birth']}, {}, {'birth': None},
                         {'birth': 'unknown'}, {'birth': 123}):
            with self.subTest(identity=identity), self.reusing(identity):
                with self.assertRaisesRegex(ValueError, 'physical PID still present'):
                    self.verify()

    def test_actual_reader_failure_for_present_pid_is_not_absence(self):
        # Kernel observations are isolated; exercise the real _process error
        # path rather than replacing it with a fabricated None observation.
        procdir = '/proc/' + str(self.descendant['pid'])
        real_read = runtime.Path.read_text
        real_stat = runtime.Path.stat
        present = real_stat(runtime.Path('/proc/self'))

        def read(path, *args, **kwargs):
            if str(path) == procdir + '/stat':
                raise PermissionError('isolated unreadable process identity')
            return real_read(path, *args, **kwargs)

        def stat(path, *args, **kwargs):
            return present if str(path) == procdir else real_stat(path, *args, **kwargs)

        with mock.patch.object(runtime.Path, 'read_text', read), mock.patch.object(runtime.Path, 'stat', stat):
            with self.assertRaisesRegex(ValueError, 'physical PID identity unavailable'):
                self.verify()

    def test_ordinary_same_boot_path_denies_foreign_descendant(self):
        with self.reusing(self.foreign_process()), mock.patch.object(runtime, '_boot', return_value=self.observation['boot_id']):
            with self.assertRaisesRegex(ValueError, 'physical PID still present'):
                self.rt.verify_terminal('closure', 'closure-a1', include_controller=True,
                                        lease_store=self.fixture.lease_store,
                                        release_receipt=self.session['release_receipt'])

    def test_foreign_worker_or_supervisor_pid_stays_denied(self):
        real = runtime._process
        for role in ('worker', 'supervisor'):
            item = next(x for x in self.observation['process_births'] if x['role'] == role)
            with self.subTest(role=role), mock.patch.object(runtime, '_process', side_effect=lambda pid:
                    {'birth': str(int(item['birth']) + 1)} if pid == item['pid'] else real(pid)):
                with self.assertRaisesRegex(ValueError, 'physical PID still present'):
                    self.verify()

    def test_revalidation_denies_changed_identity_and_expired_root_record(self):
        with self.reusing(self.foreign_process()):
            proof = self.verify()
        with self.reusing({'birth': self.descendant['birth']}):
            with self.assertRaisesRegex(ValueError, 'physical PID still present'):
                self.revalidate(proof)
        with self.reusing(self.foreign_process()):
            self.record['request_ref'] = 'sha256:' + '0' * 64
            with self.assertRaises(ValueError):
                self.revalidate(proof)


if __name__ == '__main__':
    unittest.main()
