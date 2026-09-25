"""Bounded read-only recovery contracts; no provider or clock dependencies."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/recovery.py'
T0 = '2026-09-22T10:00:00Z'
T1 = '2026-09-22T10:01:00Z'
T2 = '2026-09-22T10:02:00Z'
DIGEST = 'sha256:' + 'a' * 64


def policy():
    return dict(queued_seconds=60, setup_seconds=120, running_seconds=600,
                unknown_seconds=60, observation_max_age_seconds=120,
                poll_initial_seconds=5, poll_cap_seconds=60)


def state():
    return dict(schema='external-wait/v1', operation_key=DIGEST, attempt_id='attempt-1',
                task_id='task-1', candidate_sha='a' * 40, phase='queued',
                phase_started_at_utc=T0, last_successful_observation=None,
                last_poll_at_utc=None, observation_valid=False, source_valid=False,
                unchanged_polls=0, error_polls=0)


def observation(phase='queued', at=T1):
    return dict(schema='wait-observation/v1', operation_key=DIGEST, attempt_id='attempt-1',
                task_id='task-1', candidate_sha='a' * 40, phase=phase,
                observed_at_utc=at, source='provider/tasks/task-1', source_valid=True,
                observation_valid=True, lookup_complete=True, conclusion=None,
                evidence_refs=[], retry_after_seconds=None)


def snapshot():
    return dict(schema='recovery-snapshot/v1', observed_at_utc=T0, phase='waiting_external',
                bindings=dict(repository='example/project', default_branch='main',
                              working_branch='candidate', head_sha='a' * 40,
                              policy_revision='2', policy_digest=DIGEST, skill_version='2.3.0',
                              instructions=[dict(path='AGENTS.md', kind='instruction', digest=DIGEST, durable_verified=True),
                                            dict(path='spec.md', kind='specification', digest=DIGEST, durable_verified=True)],
                              task_state_fingerprint=DIGEST, checkpoint_version=3,
                              checkpoint_digest=DIGEST, lease_owner='owner-1', lease_generation=2,
                              lease_store_revision='r2', external_operations=[dict(
                                  operation_key=DIGEST, attempt_id='attempt-1', task_id=None,
                                  state='unknown', revision='r1')], pr_revision='none',
                              ci_revision='r1', release_revision='none'))


def probe(snap=None):
    snap = snap or snapshot()
    return dict(schema='recovery-probe/v1', observed_at_utc=T1, complete=True,
                source_valid=True, phase=snap['phase'], bindings=copy.deepcopy(snap['bindings']))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'bounded recovery helper missing')
        spec = importlib.util.spec_from_file_location('recovery', SCRIPT)
        self.recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.recovery)

    def wait(self, s=None, o=None, now=T1):
        return self.recovery.supervise_wait(s or state(), o, policy(), now)

    def test_same_phase_does_not_reset_deadline_and_only_diagnoses(self):
        original = state()
        result = self.wait(original, observation())
        self.assertEqual(result['action'], 'diagnose')
        self.assertEqual(result['state']['phase_started_at_utc'], T0)
        self.assertTrue(result['external_guard'])
        self.assertFalse(result['allow_submission'])
        self.assertEqual(original, state())

    def test_new_phase_has_own_threshold(self):
        result = self.wait(o=observation('setup'))
        self.assertEqual(result['action'], 'observe')
        self.assertEqual(result['state']['phase_started_at_utc'], T1)
        result = self.wait(result['state'], observation('setup', T2), T2)
        self.assertEqual(result['action'], 'observe')
        self.assertEqual(result['state']['phase_started_at_utc'], T1)

    def test_failed_poll_never_refreshes_last_success(self):
        prior = self.wait(o=observation())['state']
        result = self.wait(prior, None, T2)
        self.assertEqual(result['state']['last_poll_at_utc'], T2)
        self.assertEqual(result['state']['last_successful_observation']['observed_at_utc'], T1)
        self.assertEqual(result['state']['error_polls'], 1)
        self.assertTrue(result['external_guard'])

    def test_bad_observations_do_not_advance_phase_or_clear_guard(self):
        prior = self.wait(o=observation('running'))['state']
        variants = [dict(observed_at_utc=T0), dict(observed_at_utc='2026-09-22T11:00:00Z'),
                    dict(task_id='other'), dict(attempt_id='other'), dict(source_valid=False),
                    dict(lookup_complete=False), dict(phase='setup'), dict(candidate_sha='b' * 40)]
        for change in variants:
            with self.subTest(change=change):
                o = observation('running', T2)
                o.update(change)
                result = self.wait(prior, o, T2)
                self.assertEqual(result['action'], 'reconcile')
                self.assertEqual(result['state']['phase'], 'running')
                self.assertEqual(result['state']['last_successful_observation'], prior['last_successful_observation'])
                self.assertTrue(result['external_guard'])

    def test_stale_observation_is_rejected_even_without_previous_success(self):
        result = self.wait(o=observation(at=T0), now='2026-09-22T10:03:00Z')
        self.assertEqual(result['action'], 'reconcile')
        self.assertIsNone(result['state']['last_successful_observation'])

    def test_same_timestamp_contradiction_is_rejected(self):
        prior = self.wait(o=observation('running'))['state']
        o = observation('terminal')
        o.update(conclusion='succeeded', evidence_refs=['logs/1'])
        self.assertEqual(self.wait(prior, o)['action'], 'reconcile')

    def test_unknown_operation_stays_guarded_and_can_bind_verified_task(self):
        s = state()
        s.update(phase='unknown', task_id=None)
        self.assertTrue(self.wait(s, None)['external_guard'])
        result = self.wait(s, observation('running'))
        self.assertEqual(result['state']['task_id'], 'task-1')
        self.assertTrue(result['external_guard'])

    def test_restored_known_phase_requires_actual_task_identity(self):
        for phase in ('queued', 'setup', 'running', 'terminal'):
            with self.subTest(phase=phase):
                restored = state()
                restored.update(phase=phase, task_id=None)
                with self.assertRaisesRegex(ValueError, 'exact task identity'):
                    self.recovery.validate_wait_state(restored)

    def test_missing_task_id_stays_unknown_and_retains_rate_limit(self):
        restored = state()
        restored.update(phase='unknown', task_id=None)
        self.recovery.validate_wait_state(restored)
        response = observation()
        response.update(task_id=None, observation_valid=False,
                        lookup_complete=False, retry_after_seconds=600)
        result = self.wait(restored, response)
        self.assertEqual(result['state']['phase'], 'unknown')
        self.assertIsNone(result['state']['last_successful_observation'])
        self.assertEqual(result['next_poll_seconds'], 600)
        self.assertTrue(result['external_guard'])
        self.assertFalse(result['allow_submission'])
        self.recovery.validate_wait_state(result['state'])

    def test_provider_terminal_is_distinct_from_poll_timeout_and_never_green(self):
        o = observation('terminal')
        o.update(conclusion='timed_out', evidence_refs=['logs/1'])
        result = self.wait(o=o)
        self.assertEqual(result['action'], 'reuse_terminal')
        self.assertFalse(result['external_guard'])
        self.assertFalse(result['completion_claim_allowed'])
        self.assertTrue(self.wait(o=None)['external_guard'])
        o['source_valid'] = False
        self.assertTrue(self.wait(o=o)['external_guard'])

    def test_terminal_without_evidence_and_terminal_regression_keep_guard(self):
        o = observation('terminal')
        o['conclusion'] = 'succeeded'
        self.assertTrue(self.wait(o=o)['external_guard'])
        o['evidence_refs'] = ['logs/1']
        terminal = self.wait(o=o)['state']
        self.assertTrue(self.wait(terminal, observation('running', T2), T2)['external_guard'])

    def test_backoff_is_capped_but_provider_retry_after_is_a_floor(self):
        s = state()
        s['unchanged_polls'] = 1000000
        result = self.wait(s, observation())
        self.assertEqual(result['next_poll_seconds'], 60)
        o = observation()
        o['retry_after_seconds'] = 180
        self.assertEqual(self.wait(s, o)['next_poll_seconds'], 180)

    def test_retry_after_survives_a_failed_poll(self):
        o = observation()
        o['retry_after_seconds'] = 180
        prior = self.wait(o=o)['state']
        result = self.wait(prior, None, T2)
        self.assertEqual(result['next_poll_seconds'], 120)

    def test_authenticated_rate_limit_preserves_retry_timing_without_task_success(self):
        limited = observation()
        limited.update(observation_valid=False, lookup_complete=False, retry_after_seconds=600)
        result = self.wait(o=limited)
        self.assertEqual(result['next_poll_seconds'], 600)
        self.assertIsNone(result['state']['last_successful_observation'])
        self.assertEqual(result['state']['phase_started_at_utc'], T0)
        self.assertFalse(result['state']['observation_valid'])
        self.assertTrue(result['state']['source_valid'])
        self.assertTrue(result['external_guard'])
        persisted = json.loads(json.dumps(result['state']))
        result = self.wait(persisted, None, T2)
        self.assertEqual(result['next_poll_seconds'], 540)
        self.assertIsNone(result['state']['last_successful_observation'])

    def test_incomplete_lookup_retry_floor_survives_later_success_without_retry_header(self):
        incomplete = observation('unknown')
        incomplete.update(task_id=None, lookup_complete=False, retry_after_seconds=600)
        result = self.wait(o=incomplete)
        self.assertEqual(result['next_poll_seconds'], 600)
        result = self.wait(result['state'], observation('running', T2), T2)
        self.assertEqual(result['next_poll_seconds'], 540)
        self.assertEqual(result['state']['last_successful_observation']['phase'], 'running')

    def test_untrusted_wrong_scope_or_future_retry_header_is_ignored(self):
        for change in [dict(source_valid=False), dict(operation_key='sha256:' + 'b' * 64),
                       dict(observed_at_utc='2026-09-22T11:00:00Z')]:
            with self.subTest(change=change):
                limited = observation()
                limited.update(observation_valid=False, lookup_complete=False, retry_after_seconds=600)
                limited.update(change)
                result = self.wait(o=limited)
                self.assertLess(result['next_poll_seconds'], 600)
                self.assertIsNone(result['state'].get('trusted_retry_after'))

    def test_unknown_phase_requires_reconciliation(self):
        s = state()
        s.update(phase='unknown', task_id=None)
        o = observation('unknown')
        o['task_id'] = None
        self.assertEqual(self.wait(s, o)['action'], 'reconcile')

    def test_custom_instruction_bodies_always_loaded(self):
        s = snapshot()
        s['bindings']['instructions'].append(dict(path='policy/current.md', kind='instruction',
                                                  digest=DIGEST, durable_verified=True))
        result = self.recovery.decide_recovery(s, probe(s), T1)
        self.assertTrue(result['fast_path'])
        self.assertIn('policy/current.md', result['read_set'])

    def test_expanded_reads_include_newly_discovered_instruction(self):
        live = probe()
        live['bindings']['instructions'].append(dict(path='new/AGENTS.md', kind='instruction',
                                                    digest=DIGEST, durable_verified=True))
        result = self.recovery.decide_recovery(snapshot(), live, T1)
        self.assertFalse(result['fast_path'])
        self.assertIn('new/AGENTS.md', result['read_set'])

    def test_invalid_counters_policy_and_backward_poll_fail_closed(self):
        for field, value in [('unchanged_polls', -1), ('error_polls', True), ('phase', 'done')]:
            s = state()
            s[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.wait(s)
        s = state()
        s['last_poll_at_utc'] = T2
        with self.assertRaises(ValueError):
            self.wait(s)
        p = policy()
        p['queued_seconds'] = 0
        with self.assertRaises(ValueError):
            self.recovery.supervise_wait(state(), None, p, T1)

    def test_matching_fresh_probe_allows_only_reduced_reads(self):
        s = snapshot()
        result = self.recovery.decide_recovery(s, probe(s), T1)
        self.assertTrue(result['fast_path'])
        for path in ['SKILL.md', 'AGENTS.md', 'docs/development-cycle.yaml', 'docs/work-status/current.md', 'references/bounded-recovery.md']:
            self.assertIn(path, result['read_set'])
        self.assertNotIn('spec.md', result['read_set'])
        self.assertFalse(result['allow_write'])
        self.assertFalse(result['allow_submission'])
        self.assertFalse(result['completion_claim_allowed'])

    def test_default_reads_use_repository_conventions(self):
        result = self.recovery.decide_recovery(snapshot(), probe(), T1)
        self.assertIn('docs/development-cycle.yaml', result['read_set'])
        self.assertIn('docs/work-status/current.md', result['read_set'])
        self.assertNotIn('.development-cycle.yaml', result['read_set'])
        self.assertNotIn('WORK_STATUS.md', result['read_set'])

    def test_checkpoint_phases_have_relevant_fast_read_sets(self):
        expected = {
            'red': ['references/task-lifecycle.md', 'references/command-evidence.md'],
            'final_gate': ['references/command-evidence.md', 'references/validation-compute-and-ci.md',
                           'references/release-management.md'],
            'blocked': ['references/bounded-recovery.md', 'references/watchdog-recovery-and-migration.md',
                        'references/budget-ledger.md'],
        }
        for phase, paths in expected.items():
            with self.subTest(phase=phase):
                s = snapshot()
                s['phase'] = phase
                result = self.recovery.decide_recovery(s, probe(s), T1)
                self.assertTrue(result['fast_path'], result['reasons'])
                for path in paths:
                    self.assertIn(path, result['read_set'])
                    self.assertTrue((ROOT / path).is_file())
                self.assertFalse(result['allow_write'])
                self.assertFalse(result['allow_submission'])

    def test_every_binding_change_invalidates_fast_path_even_same_head(self):
        for field in snapshot()['bindings']:
            live = probe()
            value = live['bindings'][field]
            live['bindings'][field] = (value + 'changed') if isinstance(value, str) else None
            with self.subTest(field=field):
                result = self.recovery.decide_recovery(snapshot(), live, T1)
                self.assertFalse(result['fast_path'])
                self.assertIn('spec.md', result['read_set'])

    def test_missing_stale_future_incomplete_or_untrusted_probe_never_fast(self):
        invalid = [None, {}, dict(probe(), complete=False), dict(probe(), source_valid=False),
                   dict(probe(), observed_at_utc='2026-09-22T11:00:00Z'),
                   dict(probe(), observed_at_utc='2026-09-22T09:00:00Z')]
        for live in invalid:
            with self.subTest(live=live):
                self.assertFalse(self.recovery.decide_recovery(snapshot(), live, T1)['fast_path'])
        self.assertFalse(self.recovery.decide_recovery(snapshot(), probe(), '2026-09-22T11:00:00Z')['fast_path'])

    def test_unverified_instruction_hash_cannot_skip_unseen_instructions(self):
        s = snapshot()
        s['bindings']['instructions'][1]['durable_verified'] = False
        self.assertFalse(self.recovery.decide_recovery(s, probe(s), T1)['fast_path'])

    def test_cli_prints_deterministic_decisions_without_mutating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, data in [('state', state()), ('observation', observation()), ('policy', policy())]:
                path = Path(directory) / (name + '.json')
                path.write_text(json.dumps(data))
                paths.extend(['--' + name, str(path)])
            before = {p.name: p.read_bytes() for p in Path(directory).iterdir()}
            command = [sys.executable, '-B', str(SCRIPT), 'wait', *paths, '--now', T1]
            first = subprocess.run(command, capture_output=True, text=True)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(json.loads(first.stdout)['action'], 'diagnose')
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(directory).iterdir()})


if __name__ == '__main__':
    unittest.main()
