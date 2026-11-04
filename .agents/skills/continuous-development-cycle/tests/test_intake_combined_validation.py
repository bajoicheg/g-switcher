"""Offline mixed-disposition folds over real local immutable Git documents."""
import copy
import gc
import pathlib
import sys
import tracemalloc
import unittest
import weakref
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import budget
import immutable_history_cache as cache
import unknown_recovery as native
from git_document_store import canonical


class CombinedValidationTests(unittest.TestCase):
    def setUp(self):
        # Keep imported TestCase classes local: discovery must not run them.
        from test_native_unknown_recovery import IntakeTests
        self.fixture = IntakeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.originals = {}
        for name in ['post-one', 'post-two', 'queue-one', 'queue-two', 'queue-three']:
            row = copy.deepcopy(self.fixture.row)
            row['task']['id'] = name
            if name.startswith('post'):
                row['operation']['start_request']['task_id'] = name
                row['operation']['start_request_digest'] = native.native_digest(row['operation']['start_request'])
                row['operation']['handle_id'] = 'original-' + name
            else:
                row.update(state='queued', operation=None, result=None)
                row['budget'] = budget.new_ledger(name, 'wake-one', row['budget']['policy'])
            self.originals[name] = row
        # Object fixtures bypass CAS only to construct historical negative cases.
        self.base_document = {'schema': native.INTAKE_SCHEMA, 'tasks': self.originals}
        self.anchor = self.commit(self.base_document, self.fixture.rev)
        self.document = copy.deepcopy(self.base_document)
        for name, row in self.document['tasks'].items():
            original = self.originals[name]
            if name.startswith('post'):
                pins = {'original_revision': self.anchor, 'row_digest': native.op._hash(original)}
                entry = dict(schema=native.POSTLAUNCH_SCHEMA, task_id=name,
                    contract_digest=native._contract(original), original_effect='UNKNOWN',
                    actual_wait=None, replay_forbidden=True, original_revision=self.anchor,
                    original_row=copy.deepcopy(original), trusted_contract=pins,
                    retired_at_utc='2026-10-13T12:00:00Z')
                row.update(state='retired_unknown', result={'administrative_disposition': entry})
            else:
                entry = dict(schema=native.QUEUED_SCHEMA, task_id=name, original_revision=self.anchor,
                    original_row=copy.deepcopy(original), original_row_digest=native.op._hash(original),
                    reason='cancelled', owner_decision_reference='fixture-owner',
                    at_utc='2026-10-13T12:00:00Z', no_send=True)
                row.update(state='cancelled', result={'unstarted_cancellation': entry})
        self.head = self.commit(self.document, self.anchor)
        self.publish(self.head)
        self.retired = {k:v for k,v in self.document['tasks'].items() if k.startswith('post')}
        self.cancelled = {k:v for k,v in self.document['tasks'].items() if k.startswith('queue')}

    def commit(self, document, parent):
        payload = canonical(document) if isinstance(document, dict) else document
        blob = self.store._git('hash-object', '-w', '--stdin', input_text=payload)
        tree = self.store._git('mktree', input_text=f'100644 blob {blob}\tdocument.json\n')
        return self.store._git('commit-tree', tree, '-p', parent, input_text='fixture\n')

    def publish(self, head):
        self.fixture.git('push', '--force', 'origin', head + ':' + self.store.ref)

    def validate(self, head=None, retired=None, cancelled=None):
        return native.validate_intake_dispositions(self.store, head or self.head,
            self.retired if retired is None else retired, self.cancelled if cancelled is None else cancelled)

    def test_mixed_single_stream_receipts_budgets_unknown_and_detached_results(self):
        read = self.store._read_document_objects
        calls = []
        def counted(revisions):
            if len(revisions) > 1:calls.append(tuple(revisions))
            yield from read(revisions)
        with patch.object(self.store, '_read_document_objects', side_effect=counted):
            result = self.validate()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 2)
        history = native._history(self.store)
        for name, row in self.retired.items():
            expected = native._disposition_from_history(self.store, name, row, history, dict(history))
            self.assertEqual(result[name], expected)
            self.assertEqual(result[name]['original_effect'], 'UNKNOWN')
            self.assertEqual(result[name]['original_row']['budget'], self.originals[name]['budget'])
            self.assertEqual(native._postlaunch_history(self.store, name, expected['trusted_contract'], retired=True),
                (self.head, self.originals[name], native._recorded_births(self.originals[name]['operation']), self.head))
        self.assertTrue(native.validate_queued_cancellations(self.store, self.head, self.cancelled))
        # Measure the former call sequence: 1 prelaunch + 2 postlaunch + 3 queued.
        calls.clear()
        with patch.object(self.store, '_read_document_objects', side_effect=counted):
            native.validate_prelaunch_dispositions(self.store, self.head, self.retired)
            for name, row in self.retired.items():
                native._postlaunch_history(self.store, name, row['result']['administrative_disposition']['trusted_contract'], retired=True)
            native.validate_queued_cancellations(self.store, self.head, self.cancelled)
        self.assertEqual(len(calls), 6)
        print('\nSmall mixed fixture historical streams: legacy sequence=6, combined=1', flush=True)
        result['post-one']['original_row']['task']['goal'] = 'caller mutation'
        self.assertNotEqual(self.validate()['post-one'], result['post-one'])
        self.assertEqual(cache._cache.get(cache._context(self.store, 'document'))['documents'], [])

    def test_stale_head_substitution_and_final_head_checks(self):
        with self.assertRaises(ValueError):self.validate(self.anchor)
        for kind in ['retired', 'queued']:
            rows = copy.deepcopy(self.retired if kind == 'retired' else self.cancelled)
            rows[next(iter(rows))]['task']['goal'] = 'substitution'
            with self.assertRaises(ValueError):
                self.validate(retired=rows) if kind == 'retired' else self.validate(cancelled=rows)
        read = self.store.read
        for moved_at in [2, 3, 4]:
            calls = []
            def moving():
                calls.append(True)
                head, document = read()
                return ('0'*40 if len(calls) == moved_at else head), document
            with patch.object(self.store, 'read', side_effect=moving):
                with self.assertRaises(ValueError):self.validate()

    def test_deleted_rearmed_and_changed_queued_history(self):
        for name in ['post-one', 'queue-one']:
            for change in ['delete', 'rearm', 'changed']:
                with self.subTest(name=name, change=change), patch.object(cache, '_cache', cache._HistoryCache()):
                    document = copy.deepcopy(self.document)
                    if change == 'delete':del document['tasks'][name]
                    elif change == 'rearm':document['tasks'][name] = self.originals[name]
                    else:document['tasks'][name]['task']['goal'] = 'rewritten'
                    bad = self.commit(document, self.head)
                    restored = self.commit(self.document, bad)
                    self.publish(restored)
                    with self.assertRaises(ValueError):self.validate(restored)
                    snapshot = cache._cache.get(cache._context(self.store, 'document'))
                    self.assertEqual(snapshot['documents'], [])
                    self.assertEqual(snapshot['chain'][-1][0], restored)
                    self.publish(self.head)
                    with self.assertRaisesRegex(ValueError, 'rewound or rewritten'):self.validate()

    def test_postlaunch_preanchor_budget_prefix_is_not_erased(self):
        # All individual ledgers validate, but earlier events may not disappear.
        previous = copy.deepcopy(self.base_document)
        previous['tasks']['post-one']['budget']['events'][0]['cost']['tool_calls'] = 8
        budget.validate_ledger(previous['tasks']['post-one']['budget'])
        before = self.commit(previous, self.fixture.rev)
        anchor = self.commit(self.base_document, before)
        document = copy.deepcopy(self.document)
        for row in document['tasks'].values():
            entry = next(iter(row['result'].values()))
            entry['original_revision'] = anchor
            if row['state'] == 'retired_unknown':entry['trusted_contract']['original_revision'] = anchor
        head = self.commit(document, anchor)
        self.publish(head)
        retired = {k:v for k,v in document['tasks'].items() if k.startswith('post')}
        cancelled = {k:v for k,v in document['tasks'].items() if k.startswith('queue')}
        with self.assertRaisesRegex(ValueError, 'budget ancestry erased'):
            self.validate(head, retired, cancelled)

    def test_postlaunch_preanchor_native_immutability_predicates(self):
        for kind, message in [('wakes', 'wake ancestry'), ('policy', 'policy or identity'),
                ('controllers', 'controller ancestry'), ('handle', 'admission/handle'),
                ('task', 'immutable task'), ('disappearance', 'ancestry deleted')]:
            with self.subTest(kind=kind), patch.object(cache, '_cache', cache._HistoryCache()):
                previous = copy.deepcopy(self.base_document)
                row = previous['tasks']['post-one']
                if kind == 'wakes':row['budget']['wake_ids'].append('old-wake')
                elif kind == 'policy':
                    row['budget']['policy']['task_limits']['tool_calls'] = 41
                    row['budget']['policy_digest'] = budget._digest(row['budget']['policy'])
                elif kind == 'controllers':row['operation']['controllers'] = [{'pid':123, 'birth':'4', 'boot_id':'old'}]
                elif kind == 'handle':row['operation']['handle_id'] = 'old-handle'
                elif kind == 'task':row['task']['goal'] = 'old goal'
                before = self.commit(previous, self.fixture.rev)
                if kind == 'disappearance':
                    missing = copy.deepcopy(previous)
                    del missing['tasks']['post-one']
                    before = self.commit(missing, before)
                anchor = self.commit(self.base_document, before)
                document = copy.deepcopy(self.document)
                for row in document['tasks'].values():
                    entry = next(iter(row['result'].values()))
                    entry['original_revision'] = anchor
                    if row['state'] == 'retired_unknown':entry['trusted_contract']['original_revision'] = anchor
                head = self.commit(document, anchor)
                self.publish(head)
                retired = {k:v for k,v in document['tasks'].items() if k.startswith('post')}
                cancelled = {k:v for k,v in document['tasks'].items() if k.startswith('queue')}
                with self.assertRaisesRegex(ValueError, message):self.validate(head, retired, cancelled)

    def test_actual_head_move_during_historical_stream(self):
        newer = self.commit(self.document, self.head)
        read = self.store._read_document_objects
        def moving(revisions):
            for document in read(revisions):
                # Fresh current-head reads use a singleton, not this history.
                if len(revisions) > 1:self.publish(newer)
                yield document
        with patch.object(self.store, '_read_document_objects', side_effect=moving):
            with self.assertRaisesRegex(ValueError, 'history moved during authentication'):self.validate()

    def test_malformed_middle_even_empty_selection_or_prior_semantic_denial(self):
        for empty in [True, False]:
            with self.subTest(empty=empty), patch.object(cache, '_cache', cache._HistoryCache()):
                rearmed = copy.deepcopy(self.base_document)
                semantic = self.commit(rearmed, self.head)
                malformed = self.commit('{"duplicate":1,"duplicate":2}\n', semantic)
                restored = self.commit(self.document, malformed)
                self.publish(restored)
                with self.assertRaisesRegex(ValueError, 'duplicate coordination JSON key'):
                    self.validate(restored, {} if empty else self.retired, {} if empty else self.cancelled)
                self.assertIsNone(cache._cache.get(cache._context(self.store, 'document')))

    def test_nonobject_selected_row_cannot_hide_later_malformed_document(self):
        document = copy.deepcopy(self.document)
        document['tasks']['queue-one'] = 123
        semantic = self.commit(document, self.head)
        malformed = self.commit('{"duplicate":1,"duplicate":2}\n', semantic)
        restored = self.commit(self.document, malformed)
        self.publish(restored)
        with self.assertRaisesRegex(ValueError, 'duplicate coordination JSON key'):
            self.validate(restored)

    def test_full_documents_are_released_between_generations(self):
        class Document(dict):pass
        head_refs = []; historical_refs = []
        read = self.store.read
        objects = self.store._read_document_objects
        def fresh():
            revision, document = read()
            document = Document(document)
            head_refs.append(weakref.ref(document))
            return revision, document
        def streamed(revisions):
            for document in objects(revisions):
                if len(revisions) > 1:
                    self.assertFalse(any(ref() is not None for ref in head_refs))
                    self.assertFalse(any(ref() is not None for ref in historical_refs))
                    document = Document(document)
                    historical_refs.append(weakref.ref(document))
                yield document
                document = None
        with patch.object(self.store, 'read', side_effect=fresh), patch.object(
                self.store, '_read_document_objects', side_effect=streamed):
            self.validate()
        self.assertFalse(any(ref() is not None for ref in head_refs + historical_refs))

    def test_many_unrelated_padded_generations_keep_only_chain_and_selected_facts(self):
        document = copy.deepcopy(self.document)
        document['unrelated'] = {'padding': 'x' * (512 * 1024)}
        head = self.head
        peaks = []
        for count in [24, 72]:
            for generation in range(0 if count == 24 else 24, count):
                document['generation'] = generation
                head = self.commit(document, head)
            self.publish(head)
            gc.collect()
            tracemalloc.start()
            try:
                with patch.object(native, '_history', side_effect=AssertionError('full history retained')):
                    result = self.validate(head)
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:tracemalloc.stop()
            self.assertEqual(result['post-one']['original_row'], self.originals['post-one'])
            snapshot = cache._cache.get(cache._context(self.store, 'document'))
            self.assertEqual(snapshot['documents'], [])
            self.assertEqual(len(snapshot['chain']), count + 3)
        print('\nMixed fixture peak bytes (24, 72 padded generations):', peaks, flush=True)
        self.assertLess(peaks[1], peaks[0] + 12 * 1024 * 1024)
        self.assertLess(peaks[1], 48 * 1024 * 1024)


if __name__ == '__main__':unittest.main()
