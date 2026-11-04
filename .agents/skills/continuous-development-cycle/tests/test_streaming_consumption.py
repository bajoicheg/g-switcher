"""Changed-risk hosted checks for original consumption's immutable stream only.

Reuse the real native CAS fixture; no providers, processes or production refs.
"""
import copy
import gc
import weakref
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
if __package__:
    from . import test_start_consumption_reconciliation as acknowledgements
    from . import test_streaming_dispositions as dispositions
else:
    import test_start_consumption_reconciliation as acknowledgements
    import test_streaming_dispositions as dispositions
import immutable_history_cache as cache
import unknown_recovery as native
from git_document_store import canonical, MAX_BYTES
from managed_executor_runtime import _digest


class StreamingConsumptionTests(unittest.TestCase):
    commit = dispositions.StreamingDispositionTests.commit
    publish = dispositions.StreamingDispositionTests.publish

    def setUp(self):
        self.new_fixture()

    def new_fixture(self):
        self.fixture = acknowledgements.ConsumptionAcknowledgementTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.head, self.document = self.store.read()

    def unresolved(self):
        return self.fixture.unresolved()[1]

    def observe(self, failure):
        # The selected proposal must be joined against the streamed immutable
        # document, not loaded a second time or recovered from full history.
        with patch.object(native, '_history', side_effect=AssertionError('full history retained')), \
             patch.object(self.store, 'read_revision', side_effect=AssertionError('proposal reread')):
            return native.reconcile_intake_start_consumption(failure)

    def snapshot(self):
        return cache._cache.get(cache._context(self.store, 'document'))

    def test_all_four_original_outcomes_use_stream_and_preserve_evidence_and_charges(self):
        for state, retry in [('confirmed_original', False), ('unconsumed_before_effect', True),
                             ('unconsumed_after_head_advance', True), ('unresolved_original', False)]:
            with self.subTest(state=state):
                if state != 'confirmed_original':
                    self.new_fixture()
                f = self.fixture
                if state == 'confirmed_original':
                    original = self.store._git
                    def lost(*args, **kwargs):
                        result = original(*args, **kwargs)
                        if 'push' in args:
                            raise ValueError('lost original reply')
                        return result
                    with patch.object(self.store, '_git', side_effect=lost):
                        with self.assertRaises(native.IntakeStartConsumptionFailure) as caught:
                            native.consume_intake_start(self.store, f.rev, 'task-one',
                                start_request_digest=_digest(f.req), controller_identity=f.identity())
                    failure = caught.exception
                    later = copy.deepcopy(self.store.read()[1]); later['unrelated-later-head'] = True
                    self.store.compare_and_swap(failure._proposal, later)
                elif state == 'unconsumed_before_effect':
                    changed = copy.deepcopy(self.document); changed['sibling'] = True
                    self.store.compare_and_swap(f.rev, changed)
                    with self.assertRaises(native.IntakeStartConsumptionFailure) as caught:
                        native.consume_intake_start(self.store, f.rev, 'task-one',
                            start_request_digest=_digest(f.req), controller_identity=f.identity())
                    failure = caught.exception
                else:
                    failure = self.unresolved()
                    if state == 'unconsumed_after_head_advance':
                        changed = copy.deepcopy(self.document); changed['sibling'] = True
                        self.store.compare_and_swap(f.rev, changed)
                evidence = failure._evidence
                with patch.object(self.store, 'compare_and_swap', side_effect=AssertionError('second start')):
                    result = self.observe(failure)
                    self.assertEqual(result['state'], state)
                    self.assertEqual(result['retry_original_consumption'], retry)
                    self.assertEqual(result.revalidate_for(self.store, 'task-one', _digest(f.req), f.identity()), result)
                self.assertEqual(failure._evidence, evidence)
                self.assertEqual(failure._values(), evidence)
                self.assertEqual(self.store.read()[1]['tasks']['task-one']['budget'], f.row['budget'])
                self.assertEqual(result['new_attempts'], 0)
                self.assertEqual(result['new_budget_reservations'], 0)
                self.assertEqual(self.snapshot()['documents'], [])

    def test_valid_prefix_before_anchor_is_authenticated_without_semantic_projection(self):
        # Earlier documents need object authentication, not task/schema checks.
        prefix = self.commit(canonical({'unrelated': ['über']}), self.head)
        anchor = self.commit(canonical(self.document), prefix)
        self.publish(anchor); self.fixture.rev = anchor
        failure = self.unresolved()
        seen = []; read = self.store._read_document_objects
        def observe_objects(revisions):
            seen.extend(revisions)
            yield from read(revisions)
        with patch.object(self.store, '_read_document_objects', side_effect=observe_objects):
            self.assertEqual(self.observe(failure)['state'], 'unresolved_original')
        # Current-head reads now use the same decoder; the historical prefix
        # must still be authenticated exactly once without task projection.
        self.assertEqual([revision for revision in seen if revision != anchor], [self.head, prefix])
        self.assertEqual(seen.count(anchor), 3)
        self.assertEqual(self.snapshot()['documents'], [])
        # Existing detached full-history API still loads a chain-only entry.
        history = native._history(self.store)
        self.assertEqual(history[-1], (anchor, self.document))
        history[0][1]['tasks']['task-one']['task']['goal'] = 'caller mutation'
        self.assertEqual(self.observe(failure)['state'], 'unresolved_original')

    def test_invalid_tree_or_canonical_json_before_or_after_anchor_never_remembers_partial_graph(self):
        payloads = [('{"a":1,"a":1}\n', False), ('{ "a": 1 }\n', False),
                    ('[]\n', False), ('{"a":NaN}\n', False), ('not JSON\n', False),
                    ('{}\n', True), ('{"padding":"' + 'x' * MAX_BYTES + '"}\n', False)]
        for before_anchor in [True, False]:
            for payload, extra in payloads:
                with self.subTest(before_anchor=before_anchor, payload=payload[:20], extra=extra), \
                     patch.object(cache, '_cache', cache._HistoryCache()):
                    bad = self.commit(payload, self.head, extra=extra)
                    restored = self.commit(canonical(self.document), bad)
                    self.publish(restored)
                    self.fixture.rev = restored if before_anchor else self.head
                    failure = self.unresolved()
                    with self.assertRaises(ValueError):
                        self.observe(failure)
                    self.assertIsNone(self.snapshot())

    def test_semantic_rejection_authenticates_later_objects_without_remembering_invalid_history(self):
        failure = self.unresolved()
        changed = copy.deepcopy(self.document); changed['tasks']['task-one']['task']['goal'] = 'tampered'
        semantic = self.commit(canonical(changed), self.head)
        invalid = self.commit('{"duplicate":1,"duplicate":2}\n', semantic)
        restored = self.commit(canonical(self.document), invalid)
        self.publish(restored)
        with patch.object(cache, '_cache', cache._HistoryCache()):
            with self.assertRaisesRegex(ValueError, 'duplicate coordination JSON key'):
                self.observe(failure)
            self.assertIsNone(self.snapshot())

    def test_semantic_rejection_remembers_complete_lineage_and_denies_rewind(self):
        failure = self.unresolved()
        changed = copy.deepcopy(self.document); changed['tasks']['task-one']['task']['goal'] = 'tampered'
        semantic = self.commit(canonical(changed), self.head)
        restored = self.commit(canonical(self.document), semantic)
        self.publish(restored)
        with self.assertRaisesRegex(ValueError, 'original task, charged budget or consumption history changed'):
            self.observe(failure)
        self.assertEqual(self.snapshot()['chain'][-1][0], restored)
        self.assertEqual(self.snapshot()['documents'], [])
        self.publish(self.head)
        with self.assertRaisesRegex(ValueError, 'rewound or rewritten'):
            self.observe(failure)

    def test_missing_anchor_still_authenticates_all_objects_and_remembers_valid_lineage(self):
        # Build another valid branch after the same old head; failure's sealed
        # original anchor is real but no longer part of the current graph.
        original = self.commit(canonical(self.document), self.head)
        self.publish(original); self.fixture.rev = original
        failure = self.unresolved()
        other_document = copy.deepcopy(self.document); other_document['sibling'] = 'other'
        other = self.commit(canonical(other_document), self.head)
        self.publish(other)
        with self.assertRaisesRegex(ValueError, 'anchor is outside current history'):
            self.observe(failure)
        self.assertEqual(self.snapshot()['chain'][-1][0], other)
        bad = self.commit('{"a":1,"a":1}\n', other)
        restored = self.commit(canonical(other_document), bad)
        self.publish(restored)
        with self.assertRaisesRegex(ValueError, 'duplicate coordination JSON key'):
            self.observe(failure)
        self.assertEqual(self.snapshot()['chain'][-1][0], other)

    def test_streamed_intermediate_task_contract_budget_registry_and_consumption_edits_deny(self):
        failure = self.unresolved()
        for kind in ['task', 'contract', 'budget', 'registry', 'registry-presence', 'consumption', 'deleted']:
            with self.subTest(kind=kind), patch.object(cache, '_cache', cache._HistoryCache()):
                changed = copy.deepcopy(self.document); row = changed['tasks']['task-one']
                if kind == 'task': row['task']['goal'] = 'other'
                elif kind == 'contract': row['operation']['start_request']['argv'].append('other')
                elif kind == 'budget': row['budget']['other'] = 'charged differently'
                elif kind == 'registry': changed['registry_digest'] = 'sha256:' + 'b' * 64
                elif kind == 'registry-presence': changed['registry_digest'] = None
                elif kind == 'consumption': row['operation']['start_consumption'] = failure._document['tasks']['task-one']['operation']['start_consumption']
                else: changed['tasks'].clear()
                altered = self.commit(canonical(changed), self.head)
                restored = self.commit(canonical(self.document), altered)
                self.publish(restored)
                with self.assertRaises(ValueError): self.observe(failure)
                self.assertEqual(self.snapshot()['chain'][-1][0], restored)

    def test_stream_joins_exact_proposal_document_and_direct_original_parent(self):
        # Use the original issued proposal, then put it after an extra parent.
        # Rebinding local sealed evidence here isolates the graph join check;
        # ordinary evidence mutation is tested independently below.
        failure = self.unresolved()
        wrong_document = copy.deepcopy(failure._document); wrong_document['sibling'] = 'wrong proposal'
        wrong = self.commit(canonical(wrong_document), self.head)
        sibling = self.commit(canonical(self.document), self.head)
        wrong_parent = self.commit(canonical(failure._document), sibling)
        for proposal, message in [(wrong, 'proposal document changed'), (wrong_parent, 'proposal parent changed')]:
            with self.subTest(message=message), patch.object(cache, '_cache', cache._HistoryCache()):
                failure._proposal = proposal; failure._evidence = failure._values()
                self.publish(proposal)
                with self.assertRaisesRegex(ValueError, message): self.observe(failure)
                self.assertEqual(self.snapshot()['chain'][-1][0], proposal)

    def test_evidence_and_original_caller_checks_precede_snapshot(self):
        failure = self.unresolved()
        with patch.object(native, '_history_snapshot', side_effect=AssertionError('invalid caller reached history')):
            failure._task = 'other'
            with self.assertRaisesRegex(ValueError, 'unaltered SDK-issued'): self.observe(failure)
            failure._task = 'task-one'
            failure._identity['pid'] += 1; failure._evidence = failure._values()
            with self.assertRaisesRegex(ValueError, 'original live consumption caller'): self.observe(failure)
            failure._identity = self.fixture.identity(); failure._identity['birth'] += '0'
            failure._evidence = failure._values()
            with self.assertRaisesRegex(ValueError, 'exact current controller birth'): self.observe(failure)

    def test_both_final_heads_and_exact_full_head_equality_fail_closed(self):
        failure = self.unresolved(); read = self.store.read
        for moved_at, change_document in [(2, False), (3, False), (3, True)]:
            calls = []
            def moving():
                calls.append(True); revision, document = read()
                if len(calls) == moved_at:
                    if change_document: document['unrelated-head-content'] = 'substituted'
                    else: revision = '0' * 40
                return revision, document
            with self.subTest(moved_at=moved_at, change_document=change_document), \
                 patch.object(cache, '_cache', cache._HistoryCache()), \
                 patch.object(self.store, 'read', side_effect=moving):
                with self.assertRaises(ValueError): self.observe(failure)
                if moved_at == 2: self.assertIsNone(self.snapshot())
                else: self.assertEqual(self.snapshot()['chain'][-1][0], self.head)

    def test_old_generations_are_discarded_before_requesting_the_next_document(self):
        class Generation(dict):
            pass
        head = self.head; revisions = []
        document = copy.deepcopy(self.document); document['padding'] = 'x' * 16384
        for number in range(40):
            document['generation'] = number
            head = self.commit(canonical(document), head); revisions.append(head)
        self.publish(head); self.fixture.rev = revisions[20]
        failure = self.unresolved()
        read = self.store._read_document_objects; observed = []
        def tracked(revisions):
            revisions=tuple(revisions)
            if revisions == (head,):
                # A fresh current document must survive its read. Track only
                # historical generations, the subject of the retention bound.
                yield from read(revisions)
                return
            for document in read(revisions):
                generation = Generation(document)
                reference = weakref.ref(generation)
                yield generation
                del generation
                gc.collect()
                self.assertIsNone(reference(), 'reader retained a full old generation')
                observed.append(True)
        with patch.object(self.store, '_read_document_objects', side_effect=tracked):
            self.assertEqual(self.observe(failure)['state'], 'unconsumed_before_effect')
        self.assertGreater(len(observed), 32)
        self.assertEqual(self.snapshot()['documents'], [])

    def test_warm_full_history_cannot_hide_shallow_endpoint_or_non_linear_graph(self):
        failure = self.unresolved()
        native._history(self.store)
        shallow = self.store.repo / '.git' / 'shallow'; shallow.write_text(self.head + '\n')
        try:
            with self.assertRaises(ValueError): self.observe(failure)
        finally:
            shallow.unlink()
        other = self.fixture.root / 'other.git'
        self.fixture.git('init', '--bare', str(other))
        self.fixture.git('remote', 'set-url', 'origin', str(other))
        with self.assertRaises(ValueError): self.observe(failure)
        self.fixture.git('remote', 'set-url', 'origin', str(self.fixture.remote))
        sibling = self.commit(canonical(self.document), self.head)
        tree = self.store._git('rev-parse', self.head + '^{tree}')
        merge = self.store._git('commit-tree', tree, '-p', self.head, '-p', sibling, input_text='merge fixture\n')
        self.publish(merge)
        with self.assertRaisesRegex(ValueError, 'one complete parent chain'): self.observe(failure)


if __name__ == '__main__':
    unittest.main()
