"""Ownership and real Git CAS tests using disposable local bare remotes only."""
import concurrent.futures
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
AT = '2026-09-22T10:00:00Z'
LATER = '2026-09-22T11:00:00Z'
REPO = 'example/project'
SOURCE = 'refs/heads/main'
COORD = 'refs/heads/cdc-coordination'

class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'scripts/execution_lease.py').exists(), 'execution ownership helper is missing')
        self.lease = importlib.import_module('execution_lease')
        self.owner = str(uuid.uuid4())
        self.record = self.lease.acquire(self.lease.initialize(REPO, SOURCE), self.owner, AT)

    def test_unowned_noninitial_state_requires_matching_explicit_release(self):
        damaged = copy.deepcopy(self.record)
        damaged.update(owner_id=None, acquired_at_utc=None, heartbeat_at_utc=None, expires_at_utc=None)
        with self.assertRaises(ValueError):
            self.lease.acquire(damaged, str(uuid.uuid4()), LATER)

    def test_expiry_alone_never_allows_takeover(self):
        with self.assertRaises(ValueError):
            self.lease.acquire(self.record, str(uuid.uuid4()), LATER)

    def test_release_preserves_generation_and_next_acquire_increments(self):
        released = self.lease.release(self.record, self.owner, 1, AT)
        self.assertEqual(released['generation'], 1)
        next_record = self.lease.acquire(released, str(uuid.uuid4()), LATER)
        self.assertEqual(next_record['generation'], 2)
        for action in ('renew', 'release'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                getattr(self.lease, action)(next_record, self.owner, 1, LATER, **({'activity_ref':'log:late'} if action == 'renew' else {}))

    def test_takeover_requires_exact_prior_owner_quiescence_reference(self):
        evidence = {'owner_id':self.owner, 'generation':1, 'repository':REPO,
                    'source_ref':SOURCE, 'kind':'executor_stopped', 'reference':'runtime:shutdown/1'}
        moved = self.lease.acquire(self.record, str(uuid.uuid4()), LATER, quiescence=evidence)
        self.assertEqual(moved['generation'], 2)
        evidence['generation'] = 2
        with self.assertRaises(ValueError):
            self.lease.acquire(self.record, str(uuid.uuid4()), LATER, quiescence=evidence)

    def test_heartbeat_needs_new_activity_and_cannot_go_backwards(self):
        renewed = self.lease.renew(self.record, self.owner, 1, '2026-09-22T10:01:00Z', activity_ref='log:command/1')
        self.assertEqual(renewed['heartbeat_at_utc'], '2026-09-22T10:01:00Z')
        for at, activity in [(LATER,'log:command/1'), (AT,'log:command/2'), (LATER,'')]:
            with self.subTest(at=at, activity=activity), self.assertRaises(ValueError):
                self.lease.renew(renewed, self.owner, 1, at, activity_ref=activity)

    def intent(self):
        op = importlib.import_module('operation_intent')
        intent = op._load(ROOT / 'templates/operation-intent.json')
        intent['binding']['repository'] = REPO
        intent['source_ref'] = SOURCE
        intent['operation_key'] = op.operation_key(intent['binding'])
        receipt = op.verify_readback(intent, copy.deepcopy(intent), 'store:intent/1', intent['updated_at_utc'])
        return op.transition(intent, 'submitting', intent['updated_at_utc'], receipt=receipt)

    def test_external_guard_survives_expiry_release_and_blocks_product_writes(self):
        intent = self.intent()
        guarded = self.lease.set_guard(self.record, self.owner, 1, AT, intent, 'store:intent/submitting')
        released = self.lease.release(guarded, self.owner, 1, AT)
        new_owner = str(uuid.uuid4())
        moved = self.lease.acquire(released, new_owner, LATER)
        self.assertEqual(moved['external_guard'], guarded['external_guard'])
        with self.assertRaises(ValueError):
            self.lease.check_record(moved, new_owner, 2, LATER, action='product_write')
        self.lease.check_record(moved, new_owner, 2, LATER, action='observe')
        with self.assertRaises(ValueError):
            self.lease.set_guard(moved, self.owner, 1, LATER, intent, 'store:late')
        with self.assertRaises(ValueError):
            self.lease.clear_guard(moved, new_owner, 2, LATER, {}, 'provider:empty')

    def test_guard_clears_only_matching_terminal_provider_evidence(self):
        intent = self.intent()
        guarded = self.lease.set_guard(self.record, self.owner, 1, AT, intent, 'store:intent/submitting')
        task = {'task_id':'task-1', 'task_url':'https://example.invalid/task/1',
                'operation_key':intent['operation_key'], 'attempt_id':intent['attempt_id'],
                'binding':copy.deepcopy(intent['binding']), 'state':'terminal',
                'conclusion':'failed', 'evidence_refs':['provider:log/1']}
        observation = {'schema':'operation-observation/v1', 'operation_key':intent['operation_key'],
                       'observed_at_utc':LATER, 'lookup_complete':True, 'tasks':[task]}
        cleared = self.lease.clear_guard(guarded, self.owner, 1, LATER, observation, 'provider:observation/1')
        self.assertIsNone(cleared['external_guard'])
        self.assertEqual(cleared['last_terminal']['operation_key'], intent['operation_key'])
        observation['tasks'][0]['attempt_id'] = 'other'
        with self.assertRaises(ValueError):
            self.lease.clear_guard(guarded, self.owner, 1, LATER, observation, 'provider:wrong')

    def test_stale_heartbeat_and_unknown_guard_block_external_start(self):
        intent = self.intent()
        guarded = self.lease.set_guard(self.record, self.owner, 1, AT, intent, 'store:intent/1')
        digest = guarded['external_guard']['intent_digest']
        self.lease.check_record(guarded, self.owner, 1, AT, action='external_start', intent_digest=digest)
        with self.assertRaises(ValueError):
            self.lease.check_record(guarded, self.owner, 1, LATER, action='external_start', intent_digest=digest)
        intent = importlib.import_module('operation_intent').transition(intent, 'unknown', intent['updated_at_utc'])
        unknown = self.lease.set_guard(guarded, self.owner, 1, AT, intent, 'store:unknown')
        with self.assertRaises(ValueError):
            self.lease.check_record(unknown, self.owner, 1, AT, action='external_start', intent_digest=unknown['external_guard']['intent_digest'])
        with self.assertRaises(ValueError):
            self.lease.set_guard(unknown, self.owner, 1, AT, self.intent(), 'store:rewind')

    def test_released_executor_uuid_cannot_be_reused_and_time_cannot_rewind(self):
        released = self.lease.release(self.record, self.owner, 1, LATER)
        for owner, at in [(self.owner,LATER), (str(uuid.uuid4()),AT)]:
            with self.subTest(owner=owner, at=at), self.assertRaises(ValueError):
                self.lease.acquire(released, owner, at)

    def test_single_writer_without_explicit_assignment_is_observer_only(self):
        config = {'backend':'single_writer', 'designated_executor_id':self.owner, 'assignment_ref':'policy:owner/1'}
        self.lease.check_designated_executor(config, self.owner)
        for change in [{'designated_executor_id':str(uuid.uuid4())}, {'assignment_ref':None}, {'backend':'git'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.lease.check_designated_executor({**config, **change}, self.owner)

class GitStoreTests(unittest.TestCase):
    def setUp(self):
        LeaseTests.setUp(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.remote = base / 'remote.git'
        self.git(base, 'init', '--bare', str(self.remote))
        self.checkouts = []
        for name in ('a', 'b'):
            checkout = base / name
            self.git(base, 'clone', str(self.remote), str(checkout))
            self.checkouts.append(checkout)
        store = importlib.import_module('git_lease_store')
        self.stores = [store.GitLeaseStore(path, 'origin', COORD) for path in self.checkouts]

    def git(self, cwd, *args):
        result = subprocess.run(['git', '-C', str(cwd), *args], text=True, capture_output=True, check=True)
        return result.stdout.strip()

    def test_normal_push_cas_rejects_stale_revision_and_preserves_worktree(self):
        store = self.stores[0]
        original = self.git(self.checkouts[0], 'status', '--porcelain=v1')
        revision = store.compare_and_swap(None, self.record)
        self.assertEqual(store.read(), (revision, self.record))
        changed = self.lease.renew(self.record, self.owner, 1, AT, activity_ref='log:1')
        newer = self.stores[1].compare_and_swap(revision, changed)
        self.assertEqual(self.git(self.checkouts[1], 'rev-parse', newer + '^'), revision)
        with self.assertRaises(ValueError):
            store.compare_and_swap(revision, self.record)
        self.assertEqual(self.git(self.checkouts[0], 'status', '--porcelain=v1'), original)
        with self.assertRaises(ValueError):
            store.compare_and_swap(newer, {**changed, 'source_ref':COORD})

    def test_two_simultaneous_claimants_have_exactly_one_winner(self):
        initial = self.lease.initialize(REPO, SOURCE)
        revision = self.stores[0].compare_and_swap(None, initial)
        barrier = threading.Barrier(2)
        push_barrier = threading.Barrier(2)
        # Force both proposals to reach the actual Git push after observing the
        # same revision. This tests remote rejection, not only an early reread.
        for store in self.stores:
            original_git = store._git
            def gated_git(*args, _git=original_git, **kwargs):
                if 'push' in args:
                    push_barrier.wait(timeout=10)
                return _git(*args, **kwargs)
            store._git = gated_git
        def claim(index):
            observed, record = self.stores[index].read()
            proposal = self.lease.acquire(record, str(uuid.uuid4()), AT)
            barrier.wait(timeout=10)
            try:
                return self.stores[index].compare_and_swap(observed, proposal)
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, [0,1]))
        self.assertEqual(sum(x is not None for x in results), 1)
        current, record = self.stores[0].read()
        self.assertIn(current, results)
        self.assertEqual(record['generation'], 1)
        self.assertEqual(self.git(self.checkouts[0], 'rev-parse', current + '^'), revision)

    def test_check_refetches_revision_and_exact_binding(self):
        revision = self.stores[0].compare_and_swap(None, self.record)
        self.lease.check(self.stores[0], revision, REPO, SOURCE, self.owner, 1, AT, action='product_write')
        for repo, source in [('wrong/repo',SOURCE), (REPO,'refs/heads/other')]:
            with self.assertRaises(ValueError):
                self.lease.check(self.stores[0], revision, repo, source, self.owner, 1, AT, action='product_write')
        changed = self.lease.renew(self.record, self.owner, 1, AT, activity_ref='log:1')
        self.stores[1].compare_and_swap(revision, changed)
        with self.assertRaises(ValueError):
            self.lease.check(self.stores[0], revision, REPO, SOURCE, self.owner, 1, AT, action='product_write')

    def guarded_store(self):
        intent = LeaseTests.intent(self)
        guarded = self.lease.set_guard(self.record, self.owner, 1, AT, intent, 'store:submitting')
        revision = self.stores[0].compare_and_swap(None, guarded)
        return revision, guarded, intent

    def test_claim_consumes_submission_once_and_guard_updates_do_not_rearm(self):
        self.assertTrue(hasattr(self.lease, 'claim_submission'), 'durable submission claim is missing')
        revision, guarded, intent = self.guarded_store()
        digest = guarded['external_guard']['intent_digest']
        result = self.lease.claim_submission(self.stores[0], revision, REPO, SOURCE, self.owner, 1, AT, intent_digest=digest)
        current, consumed = self.stores[0].read()
        self.assertEqual(current, result['revision'])
        self.assertEqual(consumed['external_guard']['submission_claim'], result['grant'])
        self.assertEqual(result['grant']['attempt_id'], intent['attempt_id'])
        for expected in (revision, current):
            with self.assertRaises(ValueError):
                self.lease.claim_submission(self.stores[0], expected, REPO, SOURCE, self.owner, 1, AT, intent_digest=digest)
        same = self.lease.set_guard(consumed, self.owner, 1, AT, intent, 'store:same-intent')
        renewed = self.lease.renew(same, self.owner, 1, AT, activity_ref='log:claim')
        next_revision = self.stores[0].compare_and_swap(current, renewed)
        with self.assertRaises(ValueError):
            self.lease.claim_submission(self.stores[0], next_revision, REPO, SOURCE, self.owner, 1, AT, intent_digest=digest)
        unknown_intent = importlib.import_module('operation_intent').transition(intent, 'unknown', AT)
        unknown = self.lease.set_guard(renewed, self.owner, 1, AT, unknown_intent, 'store:unknown')
        self.assertEqual(unknown['external_guard']['submission_claim'], result['grant'])

    def test_terminal_clear_does_not_rearm_a_previously_consumed_attempt(self):
        revision, guarded, intent = self.guarded_store()
        self.lease.claim_submission(self.stores[0], revision, REPO, SOURCE, self.owner, 1, AT,
                                    intent_digest=guarded['external_guard']['intent_digest'])
        _, consumed = self.stores[0].read()
        task = {'task_id':'task-1', 'task_url':'provider:task/1', 'operation_key':intent['operation_key'],
                'attempt_id':intent['attempt_id'], 'binding':copy.deepcopy(intent['binding']),
                'state':'terminal', 'conclusion':'failed', 'evidence_refs':['provider:log/1']}
        observation = {'schema':'operation-observation/v1', 'operation_key':intent['operation_key'],
                       'observed_at_utc':AT, 'lookup_complete':True, 'tasks':[task]}
        cleared = self.lease.clear_guard(consumed, self.owner, 1, AT, observation, 'provider:terminal/1')
        with self.assertRaises(ValueError):
            self.lease.set_guard(cleared, self.owner, 1, AT, intent, 'store:replayed')

    def test_lost_claim_response_cannot_reconstruct_a_second_launch_grant(self):
        self.assertTrue(hasattr(self.lease, 'claim_submission'), 'durable submission claim is missing')
        revision, guarded, _ = self.guarded_store()
        original = self.stores[0].compare_and_swap
        def lost_response(expected, record):
            original(expected, record)
            raise ValueError('simulated lost push response after actual remote success')
        self.stores[0].compare_and_swap = lost_response
        with self.assertRaises(ValueError):
            self.lease.claim_submission(self.stores[0], revision, REPO, SOURCE, self.owner, 1, AT,
                                        intent_digest=guarded['external_guard']['intent_digest'])
        current, consumed = self.stores[1].read()
        self.assertIsNotNone(consumed['external_guard']['submission_claim'])
        with self.assertRaises(ValueError):
            self.lease.claim_submission(self.stores[1], current, REPO, SOURCE, self.owner, 1, AT,
                                        intent_digest=guarded['external_guard']['intent_digest'])

    def test_read_rejects_remote_movement_during_fetch_and_decode(self):
        revision = self.stores[0].compare_and_swap(None, self.record)
        changed = self.lease.renew(self.record, self.owner, 1, AT, activity_ref='log:movement')
        original_git = self.stores[0]._git
        def moving_git(*args, **kwargs):
            result = original_git(*args, **kwargs)
            if args[0] == 'show':
                self.stores[1].compare_and_swap(revision, changed)
            return result
        self.stores[0]._git = moving_git
        with self.assertRaises(ValueError):
            self.stores[0].read()

if __name__ == '__main__':
    unittest.main()
