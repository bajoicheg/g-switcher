"""Behavioral regressions for released taskless grants; no provider task is invented."""
import copy
import importlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import execution_lease_v2 as lease
import operation_intent as op
from git_lease_store import validate_coordination_transition, GitLeaseStore

NOW = '2026-10-04T17:00:05Z'
REV = 'a' * 40
OWNER = '11111111-1111-4111-8111-111111111111'
GRANT = '22222222-2222-4222-8222-222222222222'

def fixture(outcome='rejected'):
    record = lease.initialize('example/project', 'refs/heads/main')
    intent = json.loads((ROOT / 'templates/operation-intent.json').read_text())
    intent['binding']['repository'] = record['repository']
    intent['binding']['mode'] = 'PR_VALIDATION'
    intent['source_ref'] = record['source_ref']
    intent['created_at_utc'] = intent['updated_at_utc'] = '2026-10-04T17:00:00Z'
    intent['operation_key'] = op.operation_key(intent['binding'])
    receipt = op.verify_readback(intent, copy.deepcopy(intent), 'git:' + 'b' * 40, intent['updated_at_utc'])
    intent = op.transition(intent, 'submitting', '2026-10-04T17:00:01Z', receipt=receipt)
    claim = {'grant_id': GRANT, 'owner_id': OWNER, 'generation': 1,
             'operation_key': intent['operation_key'], 'attempt_id': intent['attempt_id'],
             'intent_digest': op._hash(intent), 'claimed_at_utc': '2026-10-04T17:00:02Z'}
    record['generation'] = 1
    record['last_release'] = {'owner_id': OWNER, 'generation': 1, 'invocation_id': 'worker-1',
                             'at_utc': '2026-10-04T17:00:04Z', 'checkpoint_ref': 'git:' + 'c' * 40,
                             'external_reconciliation': 'unknown_preserved', 'completion_reason': 'resumable_blocker'}
    record['submission_claims'] = [copy.deepcopy(claim)]
    record['external_guard'] = {'operation_key': intent['operation_key'], 'intent_reference': 'git:' + 'b' * 40,
                                'intent_digest': op._hash(intent), 'intent': intent, 'submission_claim': copy.deepcopy(claim)}
    lease.validate(record)
    stopped = {'invocation_id': 'worker-1', 'owner_id': OWNER, 'generation': 1, 'status': 'stopped',
               'quiescent': True, 'pending_shared_writes': False, 'observed_at_utc': NOW, 'reference': 'git:' + 'd' * 40}
    dispatch = {'outcome': outcome, 'grant_id': GRANT, 'claim_digest': op._hash(claim),
                'intent_digest': op._hash(intent), 'dispatcher_id': 'parent-1',
                'in_flight': False, 'terminal_at_utc': '2026-10-04T17:00:03Z',
                'method': 'POST', 'target': 'repos/example/project/pulls',
                'candidate_sha': intent['binding']['candidate_sha'],
                'http_status': 403 if outcome == 'rejected' else None,
                'barrier_state': None if outcome == 'rejected' else 'cancelled_before_send',
                'reference': 'git:' + 'e' * 40}
    provider = {'schema': 'operation-observation/v1', 'operation_key': intent['operation_key'],
                'lookup_complete': True, 'observed_at_utc': NOW, 'tasks': []}
    proof = {'schema': 'taskless-submission-proof/v1', 'lease_revision': REV, 'lease_digest': op._hash(record),
             'claim': copy.deepcopy(claim), 'repository': record['repository'], 'source_ref': record['source_ref'],
             'observed_at_utc': NOW, 'provider_observation': provider, 'provider_reference': 'git:' + 'f' * 40,
             'runtime': stopped, 'dispatch': dispatch,
             'dispatcher': {'dispatcher_id': 'parent-1', 'status': 'stopped', 'quiescent': True,
                            'observed_at_utc': NOW, 'reference': 'git:' + '9' * 40}}
    return record, proof

class Tests(unittest.TestCase):
    def compute_fixture(self):
        record,proof=fixture('not_submitted')
        guard=record['external_guard'];intent=guard['intent']
        intent['binding'].update(mode='COMPUTE_ONLY',backend='codex_cloud_cli',environment_id='d'*32)
        intent['operation_key']=op.operation_key(intent['binding'])
        # Preserve a valid durable readback after changing this independent fixture.
        prepared=copy.deepcopy(intent);prepared.update(state='prepared',durable_intent=None,updated_at_utc=intent['created_at_utc'])
        receipt=op.verify_readback(prepared,copy.deepcopy(prepared),'git:'+'b'*40,'2026-10-04T17:00:00Z')
        intent=op.transition(prepared,'submitting','2026-10-04T17:00:01Z',receipt=receipt)
        guard.update(intent=intent,operation_key=intent['operation_key'],intent_digest=op._hash(intent))
        claim=guard['submission_claim'];claim.update(operation_key=intent['operation_key'],intent_digest=guard['intent_digest'])
        record['submission_claims']=[copy.deepcopy(claim)]
        proof.update(lease_digest=op._hash(record),claim=copy.deepcopy(claim))
        proof['provider_observation']['operation_key']=intent['operation_key']
        proof['dispatch'].update(claim_digest=op._hash(claim),intent_digest=guard['intent_digest'],method='EXEC',
            target='codex-cloud-cli:'+json.dumps(intent['binding'],sort_keys=True,separators=(',',':')))
        lease.validate(record)
        return record,proof

    def test_compute_only_exact_before_send_barrier_resolves_without_submission_authority(self):
        old,proof=self.compute_fixture()
        new=self.resolve(old,proof)
        self.assertIsNone(new['external_guard'])
        self.assertEqual(new['submission_claims'],old['submission_claims'])
        self.assertEqual(new['last_release'],old['last_release'])
        self.assertIsNone(new['owner_id'])
        self.assertIs(validate_coordination_transition(old,new),new)

    def test_compute_only_never_accepts_github_rejection_or_wrong_execution_binding(self):
        old,proof=self.compute_fixture()
        for change in ({'outcome':'rejected','http_status':403,'barrier_state':None},
                       {'target':'codex-cloud-cli:wrong-environment'}, {'method':'POST'},
                       {'barrier_state':None}, {'outcome':'unknown'}):
            bad=copy.deepcopy(proof);bad['dispatch'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.resolve(old,bad)

    def resolve(self, record, proof, at=NOW):
        try:
            module = importlib.import_module('submission_recovery')
        except ModuleNotFoundError:
            self.fail('Canonical taskless recovery is missing')
        return module.resolve_released_guard(record, proof, 'git:' + '8' * 40, at)

    def test_exact_provider_rejection_clears_guard_without_rearming_claim(self):
        old, proof = fixture()
        new = self.resolve(old, proof)
        self.assertIsNone(new['external_guard'])
        self.assertEqual(new['submission_claims'], old['submission_claims'])
        self.assertEqual(new['generation'], 1)
        self.assertIsNone(new['owner_id'])
        self.assertEqual(new['submission_resolutions'][0]['grant_id'], GRANT)
        self.assertEqual(len(new['submission_resolutions']), 1)
        self.assertIs(validate_coordination_transition(old, new), new)

    def test_cancellation_before_send_requires_both_dispatcher_and_worker_stopped(self):
        old, proof = fixture('not_submitted')
        self.assertIsNone(self.resolve(old, proof)['external_guard'])
        for field in ('runtime', 'dispatcher'):
            bad = copy.deepcopy(proof); bad[field]['quiescent'] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.resolve(old, bad)

    def test_absent_tasks_alone_still_preserve_guard(self):
        old, proof = fixture()
        self.assertEqual(op.decide(old['external_guard']['intent'], proof['provider_observation'])['action'], 'reconcile')
        bad = copy.deepcopy(proof); bad['dispatch']['outcome'] = 'unknown'
        with self.assertRaises(ValueError): self.resolve(old, bad)

    def test_wrong_claim_or_generation_is_rejected(self):
        old, proof = fixture()
        for key, value in [('grant_id', '33333333-3333-4333-8333-333333333333'), ('generation', 2), ('generation', True), ('intent_digest', 'sha256:' + '0' * 64)]:
            bad = copy.deepcopy(proof); bad['claim'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.resolve(old, bad)

    def test_incomplete_stale_or_future_provider_lookup_is_rejected(self):
        old, proof = fixture()
        for field, value in [('lookup_complete', False), ('observed_at_utc', '2026-10-04T16:40:00Z'), ('observed_at_utc', '2026-10-04T17:10:00Z')]:
            bad = copy.deepcopy(proof); bad['provider_observation'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): self.resolve(old, bad)

    def test_transport_error_or_success_response_cannot_be_called_rejection(self):
        old, proof = fixture()
        for status in (None, 200, 202, 404, 500):
            bad = copy.deepcopy(proof); bad['dispatch']['http_status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError): self.resolve(old, bad)

    def test_pending_send_or_wrong_target_cannot_clear(self):
        old, proof = fixture()
        for key, value in [('in_flight', True), ('target', 'repos/other/project/pulls'), ('candidate_sha', '0' * 40)]:
            bad = copy.deepcopy(proof); bad['dispatch'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.resolve(old, bad)

    def test_cas_rejects_unrelated_mutation_and_duplicate_resolution(self):
        old, proof = fixture(); new = self.resolve(old, proof)
        forged = copy.deepcopy(new); forged['activity_refs'].append('unrelated')
        with self.assertRaises(ValueError): validate_coordination_transition(old, forged)
        with self.assertRaises(ValueError): self.resolve(new, proof)

    def test_stale_lease_revision_prevents_any_cas(self):
        old, proof = fixture()
        class Store:
            writes = 0
            def read(self): return 'b' * 40, copy.deepcopy(old)
            def compare_and_swap(self, expected, record): self.writes += 1; raise AssertionError('Must not write stale proof')
        try: module = importlib.import_module('submission_recovery')
        except ModuleNotFoundError: self.fail('Canonical taskless recovery is missing')
        store = Store()
        with self.assertRaises(ValueError): module.reconcile_submission_cas(store, REV, proof, 'git:' + '8' * 40, NOW)
        self.assertEqual(store.writes, 0)

    def test_unknown_and_taskful_intent_never_use_taskless_path(self):
        old, proof = fixture()
        unknown = copy.deepcopy(old)
        unknown['external_guard']['intent']['state'] = 'unknown'
        unknown['external_guard']['intent_digest'] = op._hash(unknown['external_guard']['intent'])
        with self.assertRaises(ValueError): self.resolve(unknown, proof)
        bad = copy.deepcopy(proof)
        intent = old['external_guard']['intent']
        bad['provider_observation']['tasks'] = [{'task_id': 'real-task', 'task_url': 'https://example.invalid/task',
            'operation_key': intent['operation_key'], 'attempt_id': intent['attempt_id'], 'binding': intent['binding'],
            'state': 'running', 'conclusion': None, 'evidence_refs': ['provider:real']}]
        with self.assertRaises(ValueError): self.resolve(old, bad)

    def test_wrong_runtime_identity_and_stale_dispatcher_are_rejected(self):
        old, proof = fixture()
        for field, key, value in [('runtime', 'invocation_id', 'other'), ('runtime', 'owner_id', GRANT),
                                  ('runtime', 'generation', 2), ('runtime', 'pending_shared_writes', True),
                                  ('runtime', 'generation', True),
                                  ('dispatcher', 'dispatcher_id', 'other'), ('dispatcher', 'status', 'running'),
                                  ('dispatcher', 'observed_at_utc', '2026-10-04T16:50:00Z')]:
            bad = copy.deepcopy(proof); bad[field][key] = value
            with self.subTest(field=field, key=key), self.assertRaises(ValueError): self.resolve(old, bad)

    def test_absent_cancellation_barrier_cannot_be_reconstructed_from_empty_tasks(self):
        old, proof = fixture('not_submitted'); proof['dispatch']['barrier_state'] = None
        with self.assertRaises(ValueError): self.resolve(old, proof)

    def test_release_identity_cannot_be_rewritten_before_recovery(self):
        old, proof = fixture()
        for key, value in [('invocation_id', 'unrelated-stopped-worker'), ('at_utc', '2026-10-04T17:00:03Z')]:
            forged = copy.deepcopy(old); forged['last_release'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_coordination_transition(old, forged)

    def test_released_guard_cannot_be_replaced_with_an_unrelated_attempt(self):
        old, proof = fixture(); forged = copy.deepcopy(old)
        intent = forged['external_guard']['intent']
        intent['binding']['candidate_sha'] = '7' * 40
        intent = op.prepare(intent['binding'], 'unrelated-attempt', 'refs/heads/main', '2026-10-04T17:00:00Z')
        receipt = op.verify_readback(intent, copy.deepcopy(intent), 'git:' + '6' * 40, '2026-10-04T17:00:00Z')
        intent = op.transition(intent, 'submitting', '2026-10-04T17:00:01Z', receipt=receipt)
        forged['external_guard'].update(intent=intent, operation_key=intent['operation_key'], intent_digest=op._hash(intent), submission_claim=None)
        lease.validate(forged)
        with self.assertRaises(ValueError): validate_coordination_transition(old, forged)

    def test_unclaimed_released_guard_cannot_clear_without_canonical_resolution(self):
        old, proof = fixture(); old['submission_claims'] = []
        old['external_guard']['submission_claim'] = None
        lease.validate(old)
        forged = copy.deepcopy(old); forged['external_guard'] = None
        forged['activity_refs'].append('unrelated')
        with self.assertRaises(ValueError): validate_coordination_transition(old, forged)

class GitTests(unittest.TestCase):
    resolve = Tests.resolve
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); remote = root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        self.stores = []
        for n in ('a', 'b'):
            checkout = root / n
            subprocess.run(['git', 'clone', str(remote), str(checkout)], check=True, capture_output=True)
            self.stores.append(GitLeaseStore(checkout, 'origin', 'refs/heads/recovery-test'))

    def test_real_git_resolution_is_atomic_and_stale_second_contender_cannot_replay(self):
        old, proof = fixture(); store, other = self.stores
        revision = store.compare_and_swap(None, old); proof['lease_revision'] = revision
        new = self.resolve(old, proof)
        result_revision = store.compare_and_swap(revision, new)
        with self.assertRaises(ValueError): other.compare_and_swap(revision, new)
        observed_revision, observed = other.read()
        self.assertEqual(observed_revision, result_revision)
        self.assertEqual(observed['submission_claims'], old['submission_claims'])
        self.assertIsNone(observed['external_guard'])
        self.assertEqual(len(observed['submission_resolutions']), 1)

    def test_real_git_store_rejects_proof_bound_to_another_revision(self):
        old, proof = fixture(); store = self.stores[0]
        revision = store.compare_and_swap(None, old)
        new = self.resolve(old, proof)
        with self.assertRaises(ValueError): store.compare_and_swap(revision, new)
        self.assertEqual(store.read(), (revision, old))

    def test_lost_success_reply_is_observed_without_second_resolution(self):
        old, proof = fixture(); store = self.stores[0]
        revision = store.compare_and_swap(None, old); proof['lease_revision'] = revision
        actual = store.compare_and_swap
        def lost_reply(expected, record):
            actual(expected, record)
            raise OSError('reply lost after successful CAS')
        store.compare_and_swap = lost_reply
        module = importlib.import_module('submission_recovery')
        with self.assertRaises(OSError): module.reconcile_submission_cas(store, revision, proof, 'git:' + '8' * 40, NOW)
        observed_revision, observed = store.read()
        self.assertNotEqual(observed_revision, revision)
        self.assertIsNone(observed['external_guard'])
        self.assertEqual(len(observed['submission_resolutions']), 1)
        with self.assertRaises(ValueError): module.reconcile_submission_cas(store, revision, proof, 'git:' + '8' * 40, NOW)

if __name__ == '__main__': unittest.main()
