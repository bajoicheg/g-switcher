"""Focused rejected-preparation closure tests; fixture composition only."""
import copy
import json
import sys
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import test_managed_host_bridge as fixture

bridge = fixture.bridge
pool = fixture.pool
runtime_module = fixture.runtime_module

@unittest.skipUnless(sys.platform == 'linux', 'requires Linux process proof')
class RejectedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ManagedHostBridgeTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.plan['tasks'][0]['max_runtime_seconds'] = 30
        self.f.plan['total_runtime_budget_seconds'] = 60

    def start(self, code=None):
        request = self.f.start_request()
        if code is not None:
            request['argv'] = [sys.executable, '-c', code]
        handle = bridge.start(request)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            observed = bridge.observe({'schema': bridge.OBSERVE_SCHEMA, 'handle_root': request['handle_root'], 'handle_id': handle['handle_id']})
            if observed['runtime_status'] == 'awaiting_release':
                return handle
            time.sleep(.025)
        self.fail('worker did not reach release hold')

    def rejection_request(self, handle):
        finish = self.f.finish_request(handle)
        return {key: value for key, value in dict(finish, schema='managed-host-reject-preparation/v1', review_ref='review:negative:101').items() if key not in {'output_refs', 'evidence_refs'}}

    def runtime(self, handle):
        session = bridge._load_session(str(self.f.root / 'handles'), handle['handle_id'])
        return session, bridge._runtime(session)

    def test_success_rejected_without_publication_and_exact_repeat(self):
        handle = self.start()
        request = self.rejection_request(handle)
        result = bridge.reject_preparation(request)
        session, runtime = self.runtime(handle)
        terminal = runtime.observe('closure', 'closure-a1')
        proof = runtime.verify_terminal('closure', 'closure-a1')
        self.assertTrue(proof['fresh_physical_absence'])
        self.assertEqual(terminal['status'], 'succeeded')
        self.assertGreater(terminal['runtime_seconds'], 0)
        self.assertEqual(self.f.remote_head(), self.f.base)
        self.assertIsNone(self.f.lease_store.read()[1]['owner_id'])
        before = runtime.store.read()
        row = before[1]['tasks'][0]
        self.assertEqual(row['status'], 'review_rejected')
        self.assertEqual(row['runtime_seconds'], terminal['runtime_seconds'])
        self.assertEqual(row['rejected_preparations'][0]['elapsed_seconds'], terminal['elapsed_seconds'])
        self.assertEqual(row['attempt_ids'], ['closure-a1'])
        self.assertIsNone(row['accepted_result_ref'])
        self.assertFalse(row['integrated'])
        self.assertFalse(row['discarded'])
        self.assertFalse(pool.assess(self.f.plan, before[1])['complete'])
        self.assertFalse(result['scope_complete'])
        self.assertEqual(session['worker_status'], 'succeeded')
        self.assertEqual(session['negative_review']['review_ref'], request['review_ref'])
        self.assertEqual(bridge.reject_preparation(request)['rejection_ref'], result['rejection_ref'])
        self.assertEqual(before, runtime.store.read())
        with self.assertRaisesRegex(ValueError, 'rejected'):
            bridge.finish(dict(self.f.finish_request(handle), reporting_binding=request['reporting_binding']))
        with self.assertRaisesRegex(ValueError, 'rejected'):
            runtime.accept('closure', 'closure-a1', result_commit=self.f.base, output_refs=['out:closure'], evidence_refs=['test:closure'])

    def test_finish_and_reject_serialize_before_negative_intent(self):
        handle = self.start()
        request = self.rejection_request(handle)
        entered, proceed, finish_started, finish_inner = (threading.Event() for _ in range(4))
        outcomes = {}
        actual_reject = runtime_module.ManagedExecutorRuntime.reject_preparation
        actual_finish = bridge._finish_locked
        def held(runtime, *args, **kwargs):
            if not kwargs.get('reconcile', False):
                entered.set()
                if not proceed.wait(20):
                    raise RuntimeError('test release coordination deadline')
            return actual_reject(runtime, *args, **kwargs)
        def finishing(value):
            finish_inner.set()
            return actual_finish(value)
        def reject():
            try: outcomes['reject'] = bridge.reject_preparation(request)
            except BaseException as exc: outcomes['reject_error'] = exc
        def finish():
            finish_started.set()
            try: outcomes['finish'] = bridge.finish(self.f.finish_request(handle))
            except BaseException as exc: outcomes['finish_error'] = exc
        with patch.object(runtime_module.ManagedExecutorRuntime, 'reject_preparation', held), patch.object(bridge, '_finish_locked', finishing):
            first = threading.Thread(target=reject)
            second = threading.Thread(target=finish)
            first.start()
            try:
                self.assertTrue(entered.wait(20))
                second.start()
                self.assertTrue(finish_started.wait(5))
                self.assertFalse(finish_inner.wait(.3), 'finish entered while negative closure held the handle lock')
            finally:
                proceed.set()
                first.join(30)
                if second.ident is not None: second.join(30)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        self.assertNotIn('reject_error', outcomes)
        self.assertFalse(outcomes['reject']['scope_complete'])
        self.assertIsInstance(outcomes.get('finish_error'), ValueError)
        self.assertNotIn('finish', outcomes)
        self.assertEqual(self.f.remote_head(), self.f.base)

    def test_invalid_finish_shape_fails_before_handle_read_or_lock(self):
        with patch.object(bridge, '_load_session', side_effect=AssertionError('invalid request reached durable handle')):
            for request in [None, {}, {'schema':'managed-host-finish/v2'}, {'handle_root':'/missing','handle_id':'missing'}]:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    bridge.finish(request)

    def test_changed_review_checkpoint_and_binding_denied(self):
        handle = self.start()
        request = self.rejection_request(handle)
        bridge.reject_preparation(request)
        _, runtime = self.runtime(handle)
        before = runtime.store.read()
        for field, value in [('review_ref', 'review:other'), ('checkpoint_ref', 'checkpoint:other'), ('reporting_binding', True)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                bridge.reject_preparation(dict(request, **{field: value}))
        self.assertEqual(before, runtime.store.read())

    def test_dirty_out_of_scope_candidate_can_close(self):
        code = self.f.worker()[-1] + "\nPath('outside.txt').write_text('dirty')\n"
        handle = self.start(code)
        request = self.rejection_request(handle)
        with self.assertRaisesRegex(ValueError, 'clean'):
            bridge.finish(self.f.finish_request(handle))
        self.assertFalse(bridge.reject_preparation(request)['scope_complete'])
        self.assertEqual(self.f.remote_head(), self.f.base)

    def test_failed_and_unknown_observations_denied(self):
        handle = self.start('raise SystemExit(7)')
        request = self.rejection_request(handle)
        with self.assertRaises(ValueError):
            bridge.reject_preparation(request)
        self.assertIsNotNone(self.f.lease_store.read()[1]['owner_id'])
        self.assertFalse(bridge.finish(self.f.finish_request(handle))['scope_complete'])

    def test_active_and_unknown_cannot_issue_rejection(self):
        request = self.f.start_request()
        request['argv'] = [sys.executable, '-c', 'import time;time.sleep(20)']
        handle = bridge.start(request)
        reject = self.rejection_request(handle)
        with self.assertRaises(ValueError):
            bridge.reject_preparation(reject)
        actual = runtime_module.ManagedExecutorRuntime.observe
        def unknown(runtime, task, attempt):
            observation = actual(runtime, task, attempt)
            return dict(observation, status='unknown', quiescent=False, pending_terminal_status=None)
        with patch.object(runtime_module.ManagedExecutorRuntime, 'observe', unknown):
            with self.assertRaises(ValueError):
                bridge.reject_preparation(reject)
        session, runtime = self.runtime(handle)
        self.assertIsNone(runtime.rejection(session['task_id'], session['attempt_id']))

    def test_published_result_denied(self):
        handle = self.start()
        finish = self.f.finish_request(handle)
        bridge.finish(finish)
        request = {key: value for key, value in dict(finish, schema='managed-host-reject-preparation/v1', review_ref='review:late').items() if key not in {'output_refs', 'evidence_refs'}}
        with self.assertRaises(ValueError):
            bridge.reject_preparation(request)
        self.assertNotEqual(self.f.remote_head(), self.f.base)

    def test_release_crash_and_lost_pool_reply_resume_without_charge(self):
        handle = self.start()
        request = self.rejection_request(handle)
        original = bridge._save_session
        def crash(session):
            if session.get('release_receipt') is not None:
                raise RuntimeError('after release')
            return original(session)
        with patch.object(bridge, '_save_session', crash):
            with self.assertRaisesRegex(RuntimeError, 'after release'):
                bridge.reject_preparation(request)
        self.assertIsNone(self.f.lease_store.read()[1]['owner_id'])
        original_cas = fixture.GitManagedExecutorStore.compare_and_swap
        def lost(store, revision, state):
            result = original_cas(store, revision, state)
            if state['tasks'][0]['status'] == 'review_rejected':
                raise RuntimeError('lost pool reply')
            return result
        with patch.object(fixture.GitManagedExecutorStore, 'compare_and_swap', lost):
            with self.assertRaisesRegex(RuntimeError, 'lost pool reply'):
                bridge.reject_preparation(request)
        _, runtime = self.runtime(handle)
        before = runtime.store.read()
        bridge.reject_preparation(request)
        self.assertEqual(before, runtime.store.read())
        self.assertEqual(len(list(self.f.root.glob('journal/**/launch.lock'))), 1)

    def test_retry_preserves_history_and_old_reject_does_not_mutate_new_reservation(self):
        handle = self.start()
        request = self.rejection_request(handle)
        bridge.reject_preparation(request)
        _, runtime = self.runtime(handle)
        revision, state = runtime.store.read()
        old = copy.deepcopy(state['tasks'][0])
        planned = pool.retry_task(self.f.plan, state, 'closure', expected_revision=state['revision'])
        self.assertEqual(planned['tasks'][0]['runtime_seconds'], old['runtime_seconds'])
        self.assertEqual(planned['tasks'][0]['rejected_preparations'], old['rejected_preparations'])
        with self.assertRaises(ValueError):
            pool.mark_running(self.f.plan, planned, 'closure', 'closure-a1', expected_revision=planned['revision'], reservation_token='reserve:closure')
        queued = pool.queue_task(self.f.plan, planned, 'closure', 'closure-a2', expected_revision=planned['revision'], reservation_token='reserve:new')
        runtime.store.compare_and_swap(revision, queued)
        before = runtime.store.read()
        bridge.reject_preparation(request)
        self.assertEqual(before, runtime.store.read())
        with self.assertRaises(ValueError):
            pool.fail_attempt(self.f.plan, state, 'closure', 'closure-a1', terminal_status='review_rejected', reservation_token='reserve:closure', expected_revision=state['revision'])
        for change in [lambda row: row['rejected_preparations'].append(copy.deepcopy(row['rejected_preparations'][0])), lambda row: row['rejected_preparations'][0].update(runtime_seconds=-1), lambda row: row.update(status='failed'), lambda row: row.update(rejected_preparations=[])]:
            malformed = copy.deepcopy(state)
            change(malformed['tasks'][0])
            with self.assertRaises(ValueError):
                pool.validate_state(self.f.plan, malformed)

    def test_unresolved_guard_still_blocks_successful_rejection_release(self):
        import operation_intent as op
        handle = self.start()
        revision, record = self.f.lease_store.read()
        intent = json.loads((fixture.ROOT / 'templates/operation-intent.json').read_text())
        intent['source_ref'] = record['source_ref']
        intent['binding']['repository'] = 'test/project'
        intent['operation_key'] = op.operation_key(intent['binding'])
        readback = op.verify_readback(intent, copy.deepcopy(intent), 'git:' + 'a' * 40, bridge._utc())
        intent = op.transition(intent, 'submitting', bridge._utc(), receipt=readback)
        args = (handle['owner_id'], handle['generation'], handle['invocation_id'])
        guarded = fixture.leasev2.set_guard(record, *args, bridge._utc(), intent, 'git:' + 'b' * 40)
        self.f.lease_store.compare_and_swap(revision, guarded)
        request = self.rejection_request(handle)
        before = self.f.lease_store.read()
        with self.assertRaisesRegex(ValueError, 'unresolved external guard'):
            bridge.reject_preparation(request)
        self.assertEqual(before, self.f.lease_store.read())
        self.assertEqual(self.f.remote_head(), self.f.base)

if __name__ == '__main__':
    unittest.main()
