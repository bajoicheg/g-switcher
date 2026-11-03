"""Real local Git CAS acknowledgements; no host tasks or model sessions."""
import copy
import os
import unittest
from unittest.mock import patch
if __package__:
    from . import test_native_unknown_recovery as fixture
else:
    import test_native_unknown_recovery as fixture
from managed_executor_runtime import _digest, _process, _boot


class ConsumptionAcknowledgementTests(unittest.TestCase):
    setUp = fixture.IntakeTests.setUp
    git = fixture.IntakeTests.git
    api = fixture.IntakeTests.api

    def identity(self):
        return {'pid': os.getpid(), 'birth': _process(os.getpid())['birth'], 'boot_id': _boot()}

    def test_committed_original_consumption_lost_reply_is_observed_without_second_push(self):
        m = self.api(); original = self.store._git; sends = []
        def lost(*args, **kwargs):
            result = original(*args, **kwargs)
            if 'push' in args:
                sends.append(args)
                raise ValueError('original push response lost')
            return result
        with patch.object(self.store, '_git', side_effect=lost):
            with self.assertRaises(ValueError) as failure:
                m.consume_intake_start(self.store, self.rev, 'task-one',
                    start_request_digest=_digest(self.req), controller_identity=self.identity())
        self.assertEqual(len(sends), 1)
        self.assertEqual(self.store.read()[1]['tasks']['task-one']['operation']['start_consumption']['controller'], self.identity())
        observation = m.reconcile_intake_start_consumption(failure.exception)
        self.assertEqual(observation['state'], 'confirmed_original')
        self.assertFalse(observation['retry_original_consumption'])
        self.assertEqual(observation.revalidate_for(self.store, 'task-one', _digest(self.req), self.identity())['state'], 'confirmed_original')
        self.assertEqual(self.store.read()[1]['tasks']['task-one']['budget'], self.row['budget'])
        with self.assertRaises(ValueError): m.reconcile_intake_start_consumption(dict(observation))
        observation['state'] = 'unconsumed'
        with self.assertRaises(ValueError): observation.revalidate_for(self.store, 'task-one', _digest(self.req), self.identity())

    def test_stale_original_head_is_retryable_only_as_same_live_controller_consumption(self):
        m = self.api(); sibling = copy.deepcopy(self.store.read()[1]); sibling['sibling'] = 'unrelated writer'
        current = self.store.compare_and_swap(self.rev, sibling)
        with self.assertRaises(ValueError) as failure:
            m.consume_intake_start(self.store, self.rev, 'task-one',
                start_request_digest=_digest(self.req), controller_identity=self.identity())
        self.assertNotIn('start_consumption', self.store.read()[1]['tasks']['task-one']['operation'])
        observation = m.reconcile_intake_start_consumption(failure.exception)
        self.assertEqual(observation['state'], 'unconsumed_before_effect')
        self.assertTrue(observation['retry_original_consumption'])
        self.assertEqual(observation.revalidate_for(self.store, 'task-one', _digest(self.req), self.identity())['revision'], current)
        with self.assertRaises(ValueError): observation.revalidate_for(self.store, 'foreign', _digest(self.req), self.identity())
        consumed = m.consume_intake_start(self.store, current, 'task-one',
            start_request_digest=_digest(self.req), controller_identity=self.identity())
        self.assertEqual(self.store.read()[0], consumed)
        self.assertEqual(self.store.read()[1]['tasks']['task-one']['budget'], self.row['budget'])
        with self.assertRaises(ValueError): observation.revalidate_for(self.store, 'task-one', _digest(self.req), self.identity())

    def test_unobserved_push_at_unchanged_head_stays_unknown_without_retry(self):
        m = self.api(); original = self.store._git; sends = []
        def uncertain(*args, **kwargs):
            if 'push' in args:
                sends.append(args); raise ValueError('push acknowledgement unavailable')
            return original(*args, **kwargs)
        with patch.object(self.store, '_git', side_effect=uncertain):
            with self.assertRaises(ValueError) as failure:
                m.consume_intake_start(self.store, self.rev, 'task-one',
                    start_request_digest=_digest(self.req), controller_identity=self.identity())
        observation = m.reconcile_intake_start_consumption(failure.exception)
        self.assertEqual(observation['state'], 'unresolved_original')
        self.assertFalse(observation['retry_original_consumption'])
        self.assertEqual(len(sends), 1)
        self.assertEqual(self.store.read()[0], self.rev)

    def unresolved(self):
        m = self.api(); original = self.store._git
        def uncertain(*args, **kwargs):
            if 'push' in args: raise ValueError('original reply unavailable')
            return original(*args, **kwargs)
        with patch.object(self.store, '_git', side_effect=uncertain):
            with self.assertRaises(m.IntakeStartConsumptionFailure) as failure:
                m.consume_intake_start(self.store, self.rev, 'task-one',
                    start_request_digest=_digest(self.req), controller_identity=self.identity())
        return m, failure.exception

    def test_matching_consumption_by_another_proposal_cannot_confirm_original(self):
        m, failure = self.unresolved()
        changed = copy.deepcopy(failure._document)
        other = m.consume_intake_start(self.store, self.rev, 'task-one',
            start_request_digest=_digest(self.req), controller_identity=self.identity())
        self.assertNotEqual(other, failure._proposal)
        with self.assertRaises(ValueError): m.reconcile_intake_start_consumption(failure)

    def test_advanced_unconsumed_sibling_allows_only_same_original_retry(self):
        m, failure = self.unresolved()
        changed = copy.deepcopy(self.store.read()[1]); changed['sibling'] = 'accepted other work'
        revision = self.store.compare_and_swap(self.rev, changed)
        proof = m.reconcile_intake_start_consumption(failure)
        self.assertEqual(proof['state'], 'unconsumed_after_head_advance')
        self.assertTrue(proof['retry_original_consumption'])
        self.assertEqual(proof.revalidate_for(self.store, 'task-one', _digest(self.req), self.identity())['revision'], revision)
        self.assertEqual(self.store.read()[1]['tasks']['task-one'], self.row)

    def test_failure_mutation_and_registry_changes_cannot_authorize_retry(self):
        m, failure = self.unresolved()
        original = failure._task; failure._task = 'foreign'
        with self.assertRaises(ValueError): m.reconcile_intake_start_consumption(failure)
        failure._task = original
        changed = copy.deepcopy(self.store.read()[1]); changed['registry_digest'] = 'sha256:' + 'b'*64
        self.store.compare_and_swap(self.rev, changed)
        with self.assertRaises(ValueError): m.reconcile_intake_start_consumption(failure)


if __name__ == '__main__': unittest.main()
