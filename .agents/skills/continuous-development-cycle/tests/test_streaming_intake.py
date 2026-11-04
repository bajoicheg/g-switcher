"""Parent-hosted tests for the remaining prelaunch intake history reader."""
import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import immutable_history_cache as cache
import unknown_recovery as native
from git_document_store import canonical, MAX_BYTES


class StreamingIntakeTests(unittest.TestCase):
    def setUp(self):
        from test_native_bootstrap_disposition import BootstrapTests
        self.fixture = BootstrapTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.head, self.document = self.store.read()

    def commit(self, payload, parent, extra=False):
        blob = self.store._git('hash-object', '-w', '--stdin', input_text=payload)
        entries = f'100644 blob {blob}\tdocument.json\n'
        if extra:
            entries += f'100644 blob {blob}\textra\n'
        tree = self.store._git('mktree', input_text=entries)
        return self.store._git('commit-tree', tree, '-p', parent, input_text='synthetic intake history\n')

    def publish(self, revision):
        self.fixture.git('push', '--force', 'origin', revision + ':' + self.store.ref)

    def authenticate(self):
        with patch.object(native, '_history', side_effect=AssertionError('materialized history')):
            return self.fixture.authenticate()

    def test_prepared_submitting_original_current_proof_and_first_anchor(self):
        history = native._history(self.store)
        first = next((rev, doc['tasks']['task-one']) for rev, doc in history
                     if doc['tasks']['task-one'].get('operation') is not None)
        self.assertEqual(first[0], self.fixture.prepared_revision)
        expected = native._preparation_receipt(self.store, self.fixture.row, self.fixture.pins,
                                              self.fixture.project_budget, first)
        with patch.object(native, '_preparation_receipt', wraps=native._preparation_receipt) as receipt:
            proof = self.authenticate()
            self.assertEqual(proof.revalidate_for(self.store, 'task-one'), self.fixture.row)
        self.assertEqual(receipt.call_args.args[-1], first)
        self.assertEqual(expected['prepared_revision'], first[0])
        self.assertEqual(proof['original_effect'], 'UNKNOWN')
        self.assertIsNone(proof['actual_wait'])
        snapshot = cache._cache.get(cache._context(self.store, 'document'))
        self.assertEqual(snapshot['documents'], [])
        self.assertEqual(native._history(self.store), history)

    def test_mutation_deletion_consumption_receipt_removal_and_rank_regression(self):
        variants = []
        changed = copy.deepcopy(self.document); changed['tasks']['task-one']['task']['goal'] = 'changed'
        variants.append((changed, 'task contract changed'))
        deleted = copy.deepcopy(self.document); deleted['tasks'].clear()
        variants.append((deleted, 'task row was deleted'))
        consumed = copy.deepcopy(self.document); consumed['tasks']['task-one']['operation']['controllers'] = []
        variants.append((consumed, 'history consumed'))
        removed = copy.deepcopy(self.document); del removed['tasks']['task-one']['operation']['project_budget']
        variants.append((removed, 'receipt was removed'))
        prepared = self.store.read_revision(self.fixture.prepared_revision)
        variants.append((prepared, 'receipt was removed'))
        wrong = copy.deepcopy(self.document); wrong['tasks']['task-one']['operation']['project_budget']['event_digest'] = 'sha256:' + '0' * 64
        variants.append((wrong, 'receipt history changed'))
        for document, message in variants:
            with self.subTest(message=message), patch.object(cache, '_cache', cache._HistoryCache()):
                bad = self.commit(canonical(document), self.head)
                restored = self.commit(canonical(self.document), bad)
                self.publish(restored)
                with self.assertRaisesRegex(ValueError, message):
                    self.authenticate()
                snapshot = cache._cache.get(cache._context(self.store, 'document'))
                self.assertEqual(snapshot['chain'][-1][0], restored)
                self.assertEqual(snapshot['documents'], [])
                self.publish(self.head)
                with self.assertRaisesRegex(ValueError, 'rewound or rewritten'):
                    self.authenticate()

    def test_semantic_denial_and_bad_pin_still_authenticate_all_objects_without_partial_cache(self):
        changed = copy.deepcopy(self.document); changed['tasks'].clear()
        semantic = self.commit(canonical(changed), self.head)
        for payload, extra in [('{"a":1,"a":2}\n', False), ('{ "a": 1 }\n', False),
                               ('[]\n', False), ('{"a":NaN}\n', False), ('not JSON\n', False),
                               ('{}\n', True), ('{"padding":"' + 'x' * MAX_BYTES + '"}\n', False)]:
            for bad_pin in [False, True]:
                with self.subTest(payload=payload[:20], extra=extra, bad_pin=bad_pin), patch.object(cache, '_cache', cache._HistoryCache()):
                    self.publish(self.head)
                    self.authenticate()
                    before = cache._cache.get(cache._context(self.store, 'document'))
                    bad = self.commit(payload, semantic, extra)
                    restored = self.commit(canonical(self.document), bad)
                    self.publish(restored)
                    pins = copy.deepcopy(self.fixture.pins)
                    if bad_pin:
                        pins['row_digest'] = 'sha256:' + '0' * 64
                    with patch.object(self.fixture, 'pins', pins):
                        with self.assertRaises(ValueError) as rejected:
                            self.authenticate()
                    self.assertNotIn('task row was deleted', str(rejected.exception))
                    self.assertNotIn('pinned original unconsumed', str(rejected.exception))
                    self.assertEqual(cache._cache.get(cache._context(self.store, 'document')), before)

    def test_first_preparation_cannot_be_replaced_by_later_valid_prepared_row(self):
        prepared = self.store.read_revision(self.fixture.prepared_revision)
        bad = copy.deepcopy(prepared)
        bad['tasks']['task-one']['state'] = 'starting'
        first = self.commit(canonical(bad), self.fixture.parent)
        later = self.commit(canonical(prepared), first)
        restored = self.commit(canonical(self.document), later)
        self.publish(restored)
        with patch.object(cache, '_cache', cache._HistoryCache()), patch.dict(self.fixture.pins, original_revision=restored):
            with self.assertRaisesRegex(ValueError, 'preparation boundary changed'):
                self.authenticate()

    def test_prepared_receipt_and_submitting_readback_or_rank_changes_are_denied(self):
        variants = []
        prepared = self.store.read_revision(self.fixture.prepared_revision)
        changed = copy.deepcopy(prepared)
        changed['tasks']['task-one']['operation']['project_budget'] = copy.deepcopy(self.fixture.row['operation']['project_budget'])
        variants.append((changed, self.fixture.prepared_revision, 'prepared progress changed'))
        changed = copy.deepcopy(self.document)
        changed['tasks']['task-one']['operation']['intent']['state'] = 'unknown'
        variants.append((changed, self.head, 'intent is not monotonic'))
        changed = copy.deepcopy(self.document)
        changed['tasks']['task-one']['operation']['intent']['updated_at_utc'] = '2026-10-14T01:00:02Z'
        variants.append((changed, self.head, 'submitted preparation/readback changed'))
        for document, parent, message in variants:
            with self.subTest(message=message), patch.object(cache, '_cache', cache._HistoryCache()):
                bad = self.commit(canonical(document), parent)
                restored = self.commit(canonical(self.document), bad)
                self.publish(restored)
                with patch.dict(self.fixture.pins, original_revision=restored):
                    with self.assertRaisesRegex(ValueError, message):
                        self.authenticate()

    def test_retired_proof_authenticates_original_and_current_without_replay_or_refund(self):
        source_before = self.fixture.source.read()
        budget_before = self.fixture.project_budget.read()
        proof = self.authenticate()
        with patch.object(native, '_history', side_effect=AssertionError('materialized history')):
            result = native.retire_prelaunch_intake_cas(self.store, self.head, 'task-one', proof,
                                                       at='2026-10-14T12:00:00Z')
            self.assertEqual(result['proof'].revalidate_for(self.store, 'task-one'), result['row'])
        self.assertEqual(result['row']['budget'], self.fixture.row['budget'])
        self.assertEqual(result['row']['operation'], self.fixture.row['operation'])
        self.assertEqual(result['row']['result']['administrative_disposition']['original_row'], self.fixture.row)
        self.assertEqual(self.fixture.source.read(), source_before)
        self.assertEqual(self.fixture.project_budget.read(), budget_before)

    def test_original_anchor_must_be_in_complete_chain_and_matches_authenticated_row(self):
        pins = copy.deepcopy(self.fixture.pins); pins['original_revision'] = self.fixture.parent
        with patch.object(self.fixture, 'pins', pins):
            with self.assertRaises(ValueError):
                self.authenticate()
        pins['original_revision'] = '0' * 40
        with patch.object(self.fixture, 'pins', pins):
            with self.assertRaisesRegex(ValueError, 'outside current history'):
                self.authenticate()
        read_revision = self.store.read_revision
        def substituted(revision):
            document = read_revision(revision)
            if revision == self.head:
                document['tasks']['task-one']['task']['goal'] = 'substituted detached read'
            return document
        pins = copy.deepcopy(self.fixture.pins)
        changed = copy.deepcopy(self.fixture.row); changed['task']['goal'] = 'substituted detached read'
        pins['row_digest'] = native.op._hash(changed)
        with patch.object(self.fixture, 'pins', pins), patch.object(self.store, 'read_revision', side_effect=substituted):
            with self.assertRaises(ValueError):
                self.authenticate()

    def test_fresh_head_checks_and_actual_move_with_identical_row(self):
        read = self.store.read
        for move_at in [4, 5]:
            calls = []
            def moved():
                revision, document = read(); calls.append(True)
                return ('0' * 40 if len(calls) == move_at else revision), document
            with self.subTest(move_at=move_at), patch.object(self.store, 'read', side_effect=moved):
                with self.assertRaises(ValueError):
                    self.authenticate()
        newer = self.commit(canonical(self.document), self.head)
        objects = self.store._read_document_objects
        moved = False
        def moving(revisions):
            nonlocal moved
            revisions=tuple(revisions)
            for document in objects(revisions):
                if revisions != (self.head,) and not moved:
                    self.publish(newer)
                    moved = True
                yield document
        with patch.object(self.store, '_read_document_objects', side_effect=moving):
            with self.assertRaisesRegex(ValueError, 'history moved during authentication'):
                self.authenticate()
        self.assertTrue(moved)
        self.assertEqual(self.store._remote_revision(),newer)


if __name__ == '__main__':
    unittest.main()
