"""Draft alias regressions; synthetic fixtures, never live GPC recovery."""
import copy
import importlib
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_submission_recovery as base
from git_lease_store import validate_coordination_transition
import execution_lease_v2 as lease
import operation_intent as op

RECOVERY = importlib.import_module('submission_recovery')
REFERENCE = 'git:' + '8' * 40


def fixture(mode='required_pr_validation', backend='github_create_pull_request'):
    record, proof = base.fixture('not_submitted')
    record['repository'] = 'example/alias-project'
    record['generation'] = 30
    record['last_release']['generation'] = 30
    guard = record['external_guard']
    previous = guard['intent']
    binding = copy.deepcopy(previous['binding'])
    binding.update(repository=record['repository'], mode=mode, backend=backend)
    prepared = op.prepare(binding, previous['attempt_id'], record['source_ref'],
                          previous['created_at_utc'])
    receipt = op.verify_readback(prepared, copy.deepcopy(prepared),
                                guard['intent_reference'], prepared['created_at_utc'])
    intent = op.transition(prepared, 'submitting', previous['updated_at_utc'],
                           receipt=receipt)
    claim = guard['submission_claim']
    claim.update(generation=30, operation_key=intent['operation_key'],
                 intent_digest=op._hash(intent))
    guard.update(intent=intent, intent_digest=op._hash(intent),
                 operation_key=intent['operation_key'])
    record['submission_claims'] = [copy.deepcopy(claim)]
    proof.update(repository=record['repository'], lease_digest=op._hash(record),
                 claim=copy.deepcopy(claim))
    proof['runtime']['generation'] = 30
    proof['provider_observation']['operation_key'] = intent['operation_key']
    proof['dispatch'].update(claim_digest=op._hash(claim),
                             intent_digest=op._hash(intent),
                             target='repos/' + record['repository'] + '/pulls')
    lease.validate(record)
    return record, proof


def resolve(record, proof):
    return RECOVERY.resolve_released_guard(record, proof, REFERENCE, base.NOW)


def require_supported(record, proof):
    try:
        return resolve(record, proof)
    except ValueError as exc:
        raise AssertionError('Exact historical alias must resolve: ' + str(exc)) from exc


class AliasTests(unittest.TestCase):
    def test_exact_alias_canonical_three_field_transition(self):
        old, proof = fixture()
        saved = copy.deepcopy(old)
        new = require_supported(old, proof)
        self.assertEqual(old, saved)
        self.assertIsNone(new['external_guard'])
        self.assertIs(validate_coordination_transition(old, new,
                       expected_revision=base.REV), new)
        self.assertEqual({key for key in old.keys() | new.keys()
                          if old.get(key) != new.get(key)},
                         {'external_guard', 'last_terminal', 'submission_resolutions'})
        self.assertEqual(len(new['submission_resolutions']), 1)
        self.assertEqual(new['last_terminal']['observation'], proof)
        self.assertEqual(new['submission_claims'], old['submission_claims'])
        self.assertEqual(new['last_release'], old['last_release'])
        self.assertEqual(new['generation'], 30)
        self.assertEqual(old['external_guard']['intent']['binding']['mode'],
                         'required_pr_validation')

    def test_alias_never_accepts_rejection_or_ambiguous_outcome(self):
        old, proof = fixture()
        for outcome in ('rejected', 'unknown', 'lost', 'accepted'):
            bad = copy.deepcopy(proof)
            bad['dispatch'].update(outcome=outcome,
                http_status=403 if outcome == 'rejected' else None,
                barrier_state=None if outcome == 'rejected' else 'cancelled_before_send')
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                resolve(old, bad)

    def test_modes_and_backends_are_exact(self):
        for mode, backend in (
            ('required_pr_validation', 'codex'),
            ('required_pr_validation', 'github'),
            ('REQUIRED_PR_VALIDATION', 'github_create_pull_request'),
            ('required_pr_validation ', 'github_create_pull_request'),
            ('arbitrary', 'github_create_pull_request')):
            with self.subTest(mode=mode, backend=backend), self.assertRaises(ValueError):
                old, proof = fixture(mode, backend)
                resolve(old, proof)

    def test_dispatch_barrier_method_target_candidate_and_claim_are_exact(self):
        old, proof = fixture()
        changes = (
            ('barrier_state', None), ('barrier_state', 'started'),
            ('http_status', 403), ('in_flight', True),
            ('method', 'PUT'), ('method', 'post'),
            ('target', 'repos/other/project/pulls'),
            ('target', 'repos/example/alias-project/pulls/'),
            ('target', 'repos/example/alias-project/pulls?x=1'),
            ('target', 'https://api.github.com/repos/example/alias-project/pulls'),
            ('candidate_sha', '0' * 40), ('claim_digest', 'sha256:' + '0' * 64),
            ('intent_digest', 'sha256:' + '0' * 64), ('grant_id', base.OWNER))
        for key, value in changes:
            bad = copy.deepcopy(proof)
            bad['dispatch'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                resolve(old, bad)

    def test_full_lookup_and_all_fresh_independent_stops_remain_required(self):
        old, proof = fixture()
        for path, value in (
            (('provider_observation', 'lookup_complete'), False),
            (('provider_observation', 'observed_at_utc'), '2026-10-04T16:40:00Z'),
            (('provider_observation', 'observed_at_utc'), '2026-10-04T17:10:00Z'),
            (('runtime', 'status'), 'running'),
            (('runtime', 'quiescent'), False),
            (('runtime', 'pending_shared_writes'), True),
            (('runtime', 'invocation_id'), 'other'),
            (('runtime', 'generation'), 31),
            (('runtime', 'observed_at_utc'), '2026-10-04T16:40:00Z'),
            (('dispatcher', 'status'), 'running'),
            (('dispatcher', 'quiescent'), False),
            (('dispatcher', 'dispatcher_id'), 'other'),
            (('dispatcher', 'observed_at_utc'), '2026-10-04T16:40:00Z'),
            (('claim', 'generation'), 31)):
            bad = copy.deepcopy(proof)
            bad[path[0]][path[1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolve(old, bad)
        for key in ('runtime', 'dispatcher', 'provider_observation', 'dispatch',
                    'provider_reference'):
            bad = copy.deepcopy(proof)
            del bad[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                resolve(old, bad)

    def test_proof_digest_and_original_release_bindings_remain_required(self):
        old, proof = fixture()
        for key, value in (('lease_digest', 'sha256:' + '0' * 64),
                           ('repository', 'other/project'),
                           ('source_ref', 'refs/heads/other')):
            bad = copy.deepcopy(proof)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve(old, bad)
        bad = copy.deepcopy(old)
        bad['last_release']['generation'] = 31
        with self.assertRaises(ValueError):
            resolve(bad, proof)

    def test_canonical_store_rejects_unrelated_mutation_and_history_rewrite(self):
        old, proof = fixture()
        new = require_supported(old, proof)
        forged = copy.deepcopy(new)
        forged['activity_refs'].append('unrelated')
        with self.assertRaises(ValueError):
            validate_coordination_transition(old, forged, expected_revision=base.REV)
        forged = copy.deepcopy(new)
        forged['submission_claims'] = []
        with self.assertRaises(ValueError):
            validate_coordination_transition(old, forged, expected_revision=base.REV)
        forged = copy.deepcopy(new)
        forged['submission_resolutions'] = []
        with self.assertRaises(ValueError):
            validate_coordination_transition(old, forged, expected_revision=base.REV)
        with self.assertRaises(ValueError):
            validate_coordination_transition(old, new, expected_revision='b' * 40)
        with self.assertRaises(ValueError):
            resolve(new, proof)


    def test_prior_pr_and_merge_modes_keep_rejection_and_cancellation_behavior(self):
        for mode in ('PR_VALIDATION', 'MERGE_VALIDATION'):
            for outcome in ('rejected', 'not_submitted'):
                old, proof = fixture(mode, 'codex')
                proof['dispatch'].update(outcome=outcome,
                    http_status=403 if outcome == 'rejected' else None,
                    barrier_state=None if outcome == 'rejected' else 'cancelled_before_send')
                if mode == 'MERGE_VALIDATION':
                    proof['dispatch'].update(method='PUT',
                        target='repos/' + old['repository'] + '/pulls/27/merge')
                with self.subTest(mode=mode, outcome=outcome):
                    new = require_supported(old, proof)
                    self.assertIsNone(new['external_guard'])
                    validate_coordination_transition(old, new, expected_revision=base.REV)

    def test_missing_immutable_references_and_stale_proof_are_rejected(self):
        old, proof = fixture()
        for key, value in (('observed_at_utc', '2026-10-04T16:40:00Z'),
                           ('observed_at_utc', '2026-10-04T17:10:00Z'),
                           ('provider_reference', 'mutable:latest'),
                           ('lease_revision', 'not-a-sha')):
            bad = copy.deepcopy(proof)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve(old, bad)
        for component in ('dispatch', 'runtime', 'dispatcher'):
            bad = copy.deepcopy(proof)
            bad[component]['reference'] = 'mutable:latest'
            with self.subTest(component=component), self.assertRaises(ValueError):
                resolve(old, bad)
        for component in ('claim', 'runtime'):
            bad = copy.deepcopy(proof)
            bad[component]['generation'] = True
            with self.subTest(component=component), self.assertRaises(ValueError):
                resolve(old, bad)

    def test_provider_task_and_unknown_intent_keep_guard(self):
        old, proof = fixture()
        intent = old['external_guard']['intent']
        bad = copy.deepcopy(proof)
        bad['provider_observation']['tasks'] = [{
            'task_id': 'accepted-task', 'task_url': 'https://example.invalid/task',
            'operation_key': intent['operation_key'], 'attempt_id': intent['attempt_id'],
            'binding': intent['binding'], 'state': 'running', 'conclusion': None,
            'evidence_refs': ['provider:accepted-task']}]
        with self.assertRaises(ValueError):
            resolve(old, bad)
        unknown = copy.deepcopy(old)
        unknown['external_guard']['intent']['state'] = 'unknown'
        unknown['external_guard']['intent_digest'] = op._hash(unknown['external_guard']['intent'])
        with self.assertRaises(ValueError):
            resolve(unknown, proof)
        self.assertIsNotNone(old['external_guard'])



    def test_existing_claim_and_resolution_history_are_preserved(self):
        old, proof = fixture()
        historical = copy.deepcopy(old['submission_claims'][0])
        historical.update(grant_id='33333333-3333-4333-8333-333333333333',
                          generation=29, attempt_id='prior-synthetic-attempt',
                          claimed_at_utc='2026-10-04T17:00:01Z')
        old['submission_claims'].insert(0, historical)
        old['submission_resolutions'] = [{
            key: historical[key] for key in
            ('grant_id', 'owner_id', 'generation', 'operation_key', 'attempt_id', 'intent_digest')}]
        old['submission_resolutions'][0].update(
            resolved_at_utc='2026-10-04T17:00:03Z', evidence_reference='git:' + '7' * 40,
            observation_digest='sha256:' + '7' * 64)
        lease.validate(old)
        proof['lease_digest'] = op._hash(old)
        new = require_supported(old, proof)
        self.assertEqual(new['submission_claims'], old['submission_claims'])
        self.assertEqual(new['submission_resolutions'][:-1], old['submission_resolutions'])
        self.assertEqual(len(new['submission_resolutions']), 2)
        validate_coordination_transition(old, new, expected_revision=base.REV)
        forged = copy.deepcopy(new)
        forged['submission_resolutions'][0]['evidence_reference'] = 'git:' + '6' * 40
        with self.assertRaises(ValueError):
            validate_coordination_transition(old, forged, expected_revision=base.REV)


class AliasGitTests(unittest.TestCase):
    setUp = base.GitTests.setUp

    def test_real_simultaneous_git_cas_contenders_have_one_winner(self):
        old, proof = fixture()
        left, right = self.stores
        revision = left.compare_and_swap(None, old)
        proof['lease_revision'] = revision
        new = require_supported(old, proof)
        barrier = threading.Barrier(2)
        proposals = []
        failed_pushes = []
        for store in (left, right):
            original = store._git
            def gated(*args, _original=original, _store=store, **kwargs):
                if 'push' in args:
                    proposals.append((_store, args[-1].split(':')[0]))
                    barrier.wait(timeout=20)
                    try:
                        return _original(*args, **kwargs)
                    except ValueError as exc:
                        failed_pushes.append(str(exc))
                        raise
                return _original(*args, **kwargs)
            store._git = gated
        def contend(store):
            try:
                return ('won', store.compare_and_swap(revision, new))
            except ValueError as exc:
                return ('lost', str(exc))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contend, (left, right)))
        self.assertEqual(sorted(result[0] for result in results), ['lost', 'won'])
        loser = next(result[1] for result in results if result[0] == 'lost')
        self.assertEqual(failed_pushes, [loser])
        self.assertEqual(len(proposals), 2)
        self.assertEqual(len({sha for _, sha in proposals}), 2)
        for contender, sha in proposals:
            self.assertEqual(contender._git('rev-parse', sha + '^'), revision)
        current, observed = left.read()
        self.assertEqual(current, next(result[1] for result in results if result[0] == 'won'))
        self.assertEqual(observed, new)
        self.assertEqual(left.read_revision(revision), old)
        self.assertEqual(len(observed['submission_resolutions']), 1)
        self.assertEqual(len(left._git('rev-list', current).splitlines()), 2)
        print('REAL_GIT_CAS', {'parent': revision, 'winner': current,
              'sibling_proposals': [sha for _, sha in proposals],
              'failed_actual_pushes': len(failed_pushes),
              'resolution_count': len(observed['submission_resolutions'])})

    def test_real_store_lost_reply_is_observed_and_never_retried(self):
        old, proof = fixture()
        store = self.stores[0]
        revision = store.compare_and_swap(None, old)
        proof['lease_revision'] = revision
        require_supported(old, proof)
        actual = store.compare_and_swap
        calls = []
        def lose_reply(expected, record):
            calls.append(expected)
            actual(expected, record)
            raise OSError('lost successful Git CAS reply')
        store.compare_and_swap = lose_reply
        with self.assertRaises(OSError):
            RECOVERY.reconcile_submission_cas(store, revision, proof, REFERENCE, base.NOW)
        current, observed = store.read()
        self.assertNotEqual(current, revision)
        self.assertEqual(observed, resolve(old, proof))
        self.assertEqual(store.read_revision(revision), old)
        self.assertEqual(len(observed['submission_resolutions']), 1)
        with self.assertRaises(ValueError):
            RECOVERY.reconcile_submission_cas(store, revision, proof, REFERENCE, base.NOW)
        self.assertEqual(calls, [revision])
        print('REAL_GIT_LOST_REPLY', {'before': revision, 'observed': current,
              'actual_cas_calls': len(calls),
              'resolution_count': len(observed['submission_resolutions'])})



    def test_real_alias_store_rejects_wrong_revision_and_unrelated_mutation(self):
        old, proof = fixture()
        store = self.stores[0]
        revision = store.compare_and_swap(None, old)
        wrong_revision = require_supported(old, proof)
        with self.assertRaises(ValueError):
            store.compare_and_swap(revision, wrong_revision)
        self.assertEqual(store.read(), (revision, old))
        proof['lease_revision'] = revision
        new = require_supported(old, proof)
        for field in ('activity_refs', 'last_release', 'submission_claims'):
            forged = copy.deepcopy(new)
            if field == 'activity_refs':
                forged[field].append('unrelated')
            elif field == 'last_release':
                forged[field]['checkpoint_ref'] = 'git:' + '0' * 40
            else:
                forged[field] = []
            with self.subTest(field=field), self.assertRaises(ValueError):
                store.compare_and_swap(revision, forged)
            self.assertEqual(store.read(), (revision, old))
        current = store.compare_and_swap(revision, new)
        self.assertEqual(store.read(), (current, new))


if __name__ == '__main__':
    unittest.main()
