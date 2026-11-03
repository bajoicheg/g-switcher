"""Hosted checks for bounded-memory, complete native disposition authentication.

These checks deliberately use real local Git objects, including invalid middle
commits; a valid latest document must never hide discarded historical data.
"""
import copy
import gc
import pathlib
import sys
import tracemalloc
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import immutable_history_cache as cache
import unknown_recovery as native
from git_document_store import canonical, MAX_BYTES


class StreamingDispositionTests(unittest.TestCase):
    def setUp(self):
        from test_native_unknown_recovery import IntakeTests
        self.fixture = IntakeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        proof = self.fixture.proof()
        native.retire_prelaunch_intake_cas(self.store, self.fixture.rev, 'task-one', proof,
                                         at='2026-10-13T12:00:00Z')
        self.head, self.document = self.store.read()
        self.rows = {'task-one': self.document['tasks']['task-one']}

    def commit(self, payload, parent, *, extra=False):
        blob = self.store._git('hash-object', '-w', '--stdin', input_text=payload)
        tree_input = f'100644 blob {blob}\tdocument.json\n'
        if extra:
            tree_input += f'100644 blob {blob}\textra\n'
        tree = self.store._git('mktree', input_text=tree_input)
        return self.store._git('commit-tree', tree, '-p', parent, input_text='fixture\n')

    def publish(self, revision):
        self.fixture.git('push', '--force', 'origin', revision + ':' + self.store.ref)

    def validate(self, revision=None, rows=None):
        return native.validate_prelaunch_dispositions(
            self.store, revision or self.head, self.rows if rows is None else rows)

    def test_stream_matches_full_history_receipts_and_preserves_unknown_charges(self):
        history = native._history(self.store)
        expected = native._disposition_from_history(
            self.store, 'task-one', self.rows['task-one'], history, dict(history))
        with patch.object(native, '_history', side_effect=AssertionError('full history materialized')):
            result = self.validate()
            self.assertEqual(result, {'task-one': expected})
            self.assertEqual(native.validate_prelaunch_disposition(self.store, 'task-one'), expected)
        self.assertEqual(result['task-one']['original_row']['budget'], self.fixture.row['budget'])
        self.assertEqual(result['task-one']['original_effect'], 'UNKNOWN')
        self.assertTrue(result['task-one']['replay_forbidden'])
        result['task-one']['original_row']['task']['goal'] = 'caller mutation'
        self.assertEqual(self.validate()['task-one'], expected)

    def test_multiple_selected_rows_with_distinct_original_anchors_match_old_receipts(self):
        other = copy.deepcopy(self.fixture.row)
        other['task']['id'] = 'task-two'
        request = other['operation']['start_request']
        request['task_id'] = 'task-two'
        other['operation']['start_request_digest'] = native.native_digest(request)
        document = copy.deepcopy(self.document)
        document['tasks']['task-two'] = other
        anchor = self.commit(canonical(document), self.head)
        entry = copy.deepcopy(self.rows['task-one']['result']['administrative_disposition'])
        entry.update(task_id='task-two', original_revision=anchor, original_row=copy.deepcopy(other),
                     contract_digest=native._contract(other))
        entry['trusted_contract'].update(original_revision=anchor, row_digest=native.op._hash(other))
        retired = copy.deepcopy(other)
        retired.update(state='retired_unknown', result={'administrative_disposition':entry})
        native._validate_prelaunch_disposition_row(retired)
        document['tasks']['task-two'] = retired
        head = self.commit(canonical(document), anchor)
        self.publish(head)
        rows = document['tasks']
        history = native._history(self.store)
        expected = {key:native._disposition_from_history(self.store, key, row, history, dict(history))
                    for key,row in rows.items()}
        self.assertEqual(self.validate(head, rows), expected)

    def test_stream_cache_keeps_lineage_without_full_documents_and_general_api_still_works(self):
        self.validate()
        snapshot = cache._cache.get(cache._context(self.store, 'document'))
        self.assertEqual(snapshot['documents'], [])
        self.assertEqual(snapshot['chain'][-1][0], self.head)
        history = native._history(self.store)
        self.assertEqual(history[-1], (self.head, self.document))
        self.assertEqual(history[0][1]['tasks']['task-one'], self.fixture.row)
        history[0][1]['tasks']['task-one']['task']['goal'] = 'mutated generation'
        self.assertEqual(self.validate()['task-one']['original_row'], self.fixture.row)

    def test_malformed_intermediate_documents_rejected_even_with_empty_selection(self):
        for payload, extra in [('{"a":1,"a":1}\n', False), ('{ "a": 1 }\n', False),
                               ('[]\n', False), ('{"a":NaN}\n', False),
                               ('not JSON\n', False), ('{}\n', True),
                               ('{"padding":"' + 'x' * MAX_BYTES + '"}\n', False)]:
            with self.subTest(payload=payload[:20], extra=extra):
                bad = self.commit(payload, self.head, extra=extra)
                restored = self.commit(canonical(self.document), bad)
                self.publish(restored)
                with self.assertRaises(ValueError):
                    self.validate(restored, {})

    def test_deleted_rearmed_tampered_and_consumed_history_never_pass(self):
        variants = []
        deleted = copy.deepcopy(self.document); deleted['tasks'].clear()
        variants.append(('deleted', deleted, self.head, 'history deleted'))
        rearmed = copy.deepcopy(self.document)
        rearmed['tasks']['task-one'] = copy.deepcopy(self.fixture.row)
        variants.append(('rearmed', rearmed, self.head, 'was rearmed'))
        tampered = copy.deepcopy(self.document)
        tampered['tasks']['task-one']['task']['goal'] = 'tampered'
        variants.append(('tampered', tampered, self.head, 'history rewritten'))
        consumed = {'schema': native.INTAKE_SCHEMA, 'tasks': {'task-one': copy.deepcopy(self.fixture.row)}}
        consumed['tasks']['task-one']['operation']['controllers'] = []
        variants.append(('consumed before retirement', consumed, self.fixture.rev, 'consumed controller/effect'))
        for label, document, parent, message in variants:
            with self.subTest(label=label):
                bad = self.commit(canonical(document), parent)
                restored = self.commit(canonical(self.document), bad)
                self.publish(restored)
                with patch.object(cache, '_cache', cache._HistoryCache()):
                    with self.assertRaisesRegex(ValueError, message):
                        self.validate(restored)

    def test_tampered_original_anchor_or_channel_never_passes(self):
        for kind in ['original', 'channel', 'missing anchor']:
            with self.subTest(kind=kind):
                changed = copy.deepcopy(self.document)
                row = changed['tasks']['task-one']
                entry = row['result']['administrative_disposition']
                if kind == 'original':
                    row['task']['goal'] = 'counterfeit original'
                    entry['original_row']['task']['goal'] = row['task']['goal']
                    entry['trusted_contract']['row_digest'] = native.op._hash(entry['original_row'])
                elif kind == 'channel':
                    entry['trusted_contract']['channels'] = {}
                else:
                    entry['original_revision'] = '0' * 40
                    entry['trusted_contract']['original_revision'] = '0' * 40
                # The selected current row is structurally valid; the ancestry
                # join or original channel check must reject its asserted past.
                native._validate_prelaunch_disposition_row(row)
                altered = self.commit(canonical(changed), self.fixture.rev)
                self.publish(altered)
                message = 'channels' if kind == 'channel' else 'original ancestry/task mismatch'
                with patch.object(cache, '_cache', cache._HistoryCache()):
                    with self.assertRaisesRegex(ValueError, message):
                        self.validate(altered, {'task-one': row})

    def test_stale_head_substituted_row_and_both_final_head_checks_fail_closed(self):
        with self.assertRaises(ValueError):
            self.validate(self.fixture.rev)
        changed = copy.deepcopy(self.rows); changed['task-one']['task']['goal'] = 'substitution'
        with self.assertRaises(ValueError):
            self.validate(rows=changed)
        read = self.store.read
        for moved_at in [2, 3]:
            calls = []
            def moving():
                calls.append(True)
                revision, document = read()
                return ('0' * 40 if len(calls) == moved_at else revision), document
            with self.subTest(moved_at=moved_at), patch.object(self.store, 'read', side_effect=moving):
                with self.assertRaises(ValueError):
                    self.validate()

    def test_actual_head_move_with_identical_selected_row_is_rejected(self):
        newer = self.commit(canonical(self.document), self.head)
        read_objects = self.store._read_document_objects
        moved = False
        def moving(revisions):
            nonlocal moved
            revisions=tuple(revisions)
            for document in read_objects(revisions):
                if revisions != (self.head,) and not moved:
                    self.publish(newer)
                    moved = True
                yield document
        with patch.object(self.store, '_read_document_objects', side_effect=moving):
            with self.assertRaisesRegex(ValueError, 'history moved during authentication'):
                self.validate()
        self.assertTrue(moved)
        self.assertEqual(self.store._remote_revision(),newer)

    def test_rewind_is_rejected_across_stream_and_general_history_apis(self):
        # Each pairing must remember the original longer chain in the existing
        # endpoint-bound cache context. Chain-only data is never a receipt.
        for first, second in [('stream', 'stream'), ('stream', 'full'), ('full', 'stream')]:
            with self.subTest(first=first, second=second), patch.object(cache, '_cache', cache._HistoryCache()):
                self.publish(self.head)
                self.validate() if first == 'stream' else native._history(self.store)
                self.publish(self.fixture.rev)
                with self.assertRaisesRegex(ValueError, 'rewound or rewritten'):
                    self.validate(self.fixture.rev, {}) if second == 'stream' else native._history(self.store)

    def test_semantic_failure_remembers_chain_and_cannot_erase_rewind_detection(self):
        deleted = copy.deepcopy(self.document)
        deleted['tasks'].clear()
        bad = self.commit(canonical(deleted), self.head)
        restored = self.commit(canonical(self.document), bad)
        self.publish(restored)
        with self.assertRaisesRegex(ValueError, 'history deleted'):
            self.validate(restored)
        snapshot = cache._cache.get(cache._context(self.store, 'document'))
        self.assertEqual(snapshot['chain'][-1][0], restored)
        self.assertEqual(snapshot['documents'], [])
        self.publish(self.head)
        with self.assertRaisesRegex(ValueError, 'rewound or rewritten'):
            self.validate()

    def test_single_row_semantic_denial_still_remembers_authenticated_lineage(self):
        newer = self.commit(canonical(self.document), self.head)
        self.publish(newer)
        changed = copy.deepcopy(self.rows['task-one'])
        changed['task']['goal'] = 'substituted current row'
        with self.assertRaisesRegex(ValueError, 'serialized disposition differs'):
            native.validate_prelaunch_disposition(self.store, 'task-one', changed)
        snapshot = cache._cache.get(cache._context(self.store, 'document'))
        self.assertEqual(snapshot['chain'][-1][0], newer)
        self.publish(self.head)
        with self.assertRaisesRegex(ValueError, 'rewound or rewritten'):
            native._history(self.store)

    def test_semantic_failure_does_not_skip_later_canonical_document_checks(self):
        rearmed = copy.deepcopy(self.document)
        rearmed['tasks']['task-one'] = copy.deepcopy(self.fixture.row)
        bad_semantics = self.commit(canonical(rearmed), self.head)
        bad_json = self.commit('{"duplicate":1,"duplicate":2}\n', bad_semantics)
        restored = self.commit(canonical(self.document), bad_json)
        self.publish(restored)
        with self.assertRaisesRegex(ValueError, 'duplicate coordination JSON key'):
            self.validate(restored)
        # Incomplete object authentication must not publish that graph.
        snapshot = cache._cache.get(cache._context(self.store, 'document'))
        self.assertNotEqual(snapshot['chain'][-1][0], restored)

    def test_shallow_or_changed_endpoint_cannot_use_stream_lineage(self):
        self.validate()
        shallow = self.store.repo / '.git' / 'shallow'
        shallow.write_text(self.fixture.rev + '\n')
        try:
            with self.assertRaises(ValueError):
                self.validate()
        finally:
            shallow.unlink()
        other = self.fixture.root / 'other.git'
        self.fixture.git('init', '--bare', str(other))
        self.fixture.git('remote', 'set-url', 'origin', str(other))
        with self.assertRaises(ValueError):
            self.validate()

    def test_many_large_documents_have_bounded_peak_not_history_sized_cache_encoding(self):
        document = copy.deepcopy(self.document)
        document['padding'] = 'x' * (1536 * 1024)
        head = self.head
        peaks = []
        for count in [32, 128]:
            for number in range(0 if count == 32 else 32, count):
                document['generation'] = number
                head = self.commit(canonical(document), head)
            self.publish(head)
            gc.collect()
            tracemalloc.start()
            try:
                with patch.object(native, '_history', side_effect=AssertionError('full history materialized')):
                    result = self.validate(head)
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:
                tracemalloc.stop()
            self.assertEqual(result['task-one'], self.rows['task-one']['result']['administrative_disposition'])
            snapshot = cache._cache.get(cache._context(self.store, 'document'))
            self.assertEqual(snapshot['documents'], [])
        # Transport retains at most one fixed 16-blob batch; adding 96 full
        # 1.5 MiB generations must not add ~144 MiB of retained JSON strings.
        self.assertLess(peaks[1], peaks[0] + 24 * 1024 * 1024)
        self.assertLess(peaks[1], 160 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
