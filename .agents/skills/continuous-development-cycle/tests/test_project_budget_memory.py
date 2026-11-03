"""Focused local Git regressions for project budget history memory."""
import copy
import gc
import unittest
import weakref
from unittest.mock import patch

import test_project_budget_store as fixture_module
import budget
import project_budget_store as native
import immutable_history_cache as history_cache


class ProjectBudgetMemoryTests(unittest.TestCase):
    def fixture(self):
        f = fixture_module.ProjectBudgetStoreTests('runTest')
        self.addCleanup(f.doCleanups)
        f.setUp()
        return f

    def isolated_cache(self):
        replacement = history_cache._HistoryCache()
        manager = patch.object(history_cache, '_cache', replacement)
        manager.start()
        self.addCleanup(manager.stop)
        return replacement

    def test_cold_walk_does_not_retain_all_full_ledgers(self):
        self.isolated_cache()
        f = self.fixture()
        store = f.store()
        revisions = [f.anchor]
        for i in range(20):
            revisions.append(f.publish_ledger(f.ledger, extra=('lease.json', str(i).encode())))
        # Empty the cache without changing its production limits or implementation.
        with patch.object(history_cache, '_cache', history_cache._HistoryCache()):
            original = store._object
            live = []
            counts = []
            seen = []
            class Tracked(dict):
                pass
            def tracked(revision):
                ledger, *rest = original(revision)
                result = Tracked(ledger)
                live.append(weakref.ref(result))
                seen.append(revision)
                gc.collect()
                counts.append(sum(item() is not None for item in live))
                return (result, *rest)
            with patch.object(store, '_object', side_effect=tracked):
                self.assertEqual(store.read(), (revisions[-1], f.ledger))
            self.assertEqual(seen, revisions)
            self.assertLessEqual(max(counts), 6)

    def test_warm_reads_decode_only_new_tip_and_return_detached_data(self):
        self.isolated_cache()
        f = self.fixture()
        store = f.store()
        expected = store.read()
        with patch.object(store, '_object', wraps=store._object) as objects:
            actual = store.read()
            self.assertEqual(actual, expected)
            self.assertEqual(objects.call_count, 0)
            actual[1]['policy']['task_limits'].clear()
            self.assertEqual(store.read(), expected)
            value = budget.apply_event(f.ledger, f.event())
            revision = f.publish_ledger(value)
            self.assertEqual(store.read(), (revision, value))
            self.assertEqual([call.args[0] for call in objects.call_args_list], [revision])

    def test_historical_selection_tip_detachment_anchor_and_rewind(self):
        self.isolated_cache()
        f = self.fixture()
        store = f.store()
        first = budget.apply_event(f.ledger, f.event())
        selected = f.publish_ledger(first)
        second = budget.apply_event(first, f.event('second'))
        tip = f.publish_ledger(second)
        store.read()
        with patch.object(store, '_object', wraps=store._object) as objects:
            result = store.read_revision(selected)
            self.assertEqual(result, first)
            self.assertEqual([call.args[0] for call in objects.call_args_list], [selected])
            result['events'][0]['cost']['tool_calls'] = 999
            objects.reset_mock()
            self.assertEqual(store.read_revision(tip), second)
            self.assertEqual(objects.call_count, 0)
        self.assertEqual(store.read_revision(selected), first)
        self.assertEqual(store._last_observed, tip)
        later_anchor_store = f.store(anchor_revision=selected, anchor_ledger_digest=native.ledger_digest(first))
        with self.assertRaises(ValueError):
            later_anchor_store.read_revision(f.anchor)
        self.assertEqual(later_anchor_store._last_observed, tip)
        f.git(f.remote, 'update-ref', fixture_module.REF, selected)
        with self.assertRaises(ValueError):
            store.read_revision(selected)
        self.assertEqual(store._last_observed, tip)

    def test_restored_intermediate_drift_denied_cold_and_warm(self):
        for mutation in ('policy', 'events', 'wake'):
            for warm in (False, True):
                with self.subTest(mutation=mutation, warm=warm):
                    f = self.fixture()
                    with patch.object(history_cache, '_cache', history_cache._HistoryCache()):
                        store = f.store()
                        good = budget.apply_event(f.ledger, f.event())
                        f.publish_ledger(good)
                        store.read()
                        bad = copy.deepcopy(good)
                        if mutation == 'policy':
                            bad['policy']['task_limits']['compute_starts'] = 9
                            bad['policy_digest'] = budget._digest(bad['policy'])
                        elif mutation == 'events':
                            bad['events'][0]['cost']['tool_calls'] = 2
                        else:
                            bad['wake_ids'].append('unregistered-wake')
                        budget.validate_ledger(bad)
                        f.publish_ledger(bad)
                        f.publish_ledger(good)
                        if warm:
                            with self.assertRaises(ValueError):
                                store.read()
                        else:
                            with patch.object(history_cache, '_cache', history_cache._HistoryCache()):
                                with self.assertRaises(ValueError):
                                    f.store()

    def test_oversized_regular_blob_denied_before_body_read(self):
        self.isolated_cache()
        f = self.fixture()
        store = f.store()
        (f.repo / f.path).write_bytes(b' ' * (native.MAX_BYTES + 1))
        f.git(f.repo, 'add', f.path)
        f.git(f.repo, 'commit', '-m', 'Oversized genuine blob')
        f.git(f.repo, 'push', 'coordination', 'HEAD:' + fixture_module.REF)
        real = store._git
        sizes = []
        def guarded(*args, **kwargs):
            if args[:2] == ('cat-file', 'blob'):
                raise AssertionError('oversized blob body requested')
            result = real(*args, **kwargs)
            if args[:2] == ('cat-file', '-s'):
                sizes.append(result)
            return result
        with patch.object(store, '_git', side_effect=guarded):
            with self.assertRaisesRegex(ValueError, 'exceeds 4 MiB'):
                store.read()
        self.assertEqual(len(sizes), 1)
        self.assertEqual(int(sizes[0]), native.MAX_BYTES + 1)

    def test_real_cas_parallel_event_preserves_neighbors_unknown_charge_and_replay(self):
        self.isolated_cache()
        f = self.fixture()
        store = f.store()
        before, _ = store.read()
        store.append_event(before, f.event())
        before, prior = store.read()
        tree = f.git(f.remote, 'ls-tree', '-z', before).split(b'\0')
        event = dict(type='parallel_limit', event_id='operational-bound',
                     task_id=prior['task_id'], wake_id=prior['wake_ids'][-1],
                     at_utc=fixture_module.NOW, max_parallel_agents=0,
                     reference='fixture:original-policy-bound')
        receipt = store.append_event(before, event)
        after, value = store.read()
        native._extends(prior, value)
        self.assertEqual(value['events'], prior['events'] + [event])
        self.assertEqual(budget.summarize(value), budget.summarize(prior))
        self.assertIsNone(budget.summarize(value)['task']['tokens'])
        self.assertFalse(receipt['authorizes_launch'])
        self.assertFalse(receipt['authorizes_product_write'])
        new_tree = f.git(f.remote, 'ls-tree', '-z', after).split(b'\0')
        for entry in tree:
            if entry and entry.split(b'\t', 1)[1] != f.path.encode():
                self.assertIn(entry, new_tree)
        replay = store.append_event(after, event)
        self.assertTrue(replay['already_recorded'])
        self.assertEqual(f.remote_head(), after)
        self.assertEqual(store.read_revision(before), prior)


if __name__ == '__main__':
    unittest.main()
