"""Real Git custody faults for retained task budgets; all endpoints are local."""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import budget
from git_remote_identity import remote_identity

REF = 'refs/heads/cdc/coordination'
SOURCE = 'refs/heads/work/task'
NOW = '2026-10-13T10:00:00Z'


def ledger_digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class ProjectBudgetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.remote = self.root / 'remote.git'; self.repo = self.root / 'client'
        self.git(self.root, 'init', '--bare', str(self.remote))
        self.git(self.root, 'init', str(self.repo))
        self.git(self.repo, 'config', 'user.name', 'Fixture')
        self.git(self.repo, 'config', 'user.email', 'fixture@example.invalid')
        self.git(self.repo, 'remote', 'add', 'coordination', str(self.remote))
        self.policy = {'task_limits': {'compute_starts': 3, 'ci_starts': 0, 'agent_starts': 0},
                       'wake_limits': {'compute_starts': 2}, 'max_parallel_agents': 0,
                       'checkpoint_reserve': {'tokens': 0, 'tool_calls': 0},
                       'provider_max_age_seconds': 60, 'actions_budget': 'conserve'}
        self.ledger = budget.new_ledger('retained-task', 'old-wake', self.policy)
        self.path = 'budget.json'; self.field = None
        self.seed()

    def git(self, repo, *args, input_bytes=None):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        result = subprocess.run(['git', '-C', str(repo), *args], input=input_bytes,
                                capture_output=True, env=env, check=True)
        return result.stdout

    def seed(self, *, field=False, payload=None):
        if field:
            self.path = 'document.json'; self.field = 'budget'
            payload = (b'{\n  "note" : "keep \\u0061 and spaces", "number":1.00,\n "budget" : '
                       + json.dumps(self.ledger, indent=2).encode() + b',\n "tail" : [true, null] \n}\n') if payload is None else payload
        else:
            payload = json.dumps(self.ledger, indent=2).encode() + b'\n' if payload is None else payload
        (self.repo / self.path).write_bytes(payload)
        (self.repo / 'lease.json').write_bytes(b'{ "owner": null, "generation": 19 }\n')
        (self.repo / 'odd\nname').write_bytes(b'neighbor\x00raw')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '-m', 'Seed retained control')
        self.anchor = self.git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        self.git(self.repo, 'push', 'coordination', 'HEAD:' + REF)

    def binding(self, **changes):
        value = {'schema': 'project-budget-binding/v1', 'repository': 'fixture/project',
                 'source_ref': SOURCE, 'coordination_ref': REF,
                 'coordination_store_id': remote_identity(self.repo, 'coordination'),
                 'ledger_path': self.path, 'budget_field': self.field, 'task_id': 'retained-task',
                 'anchor_revision': self.anchor, 'anchor_ledger_digest': ledger_digest(self.ledger),
                 'wake_authorizations': {'adoption-wake': 'owner:explicit-new-adoption-wake'}}
        value.update(changes); return value

    def store(self, **changes):
        try:
            native = importlib.import_module('project_budget_store')
        except ModuleNotFoundError:
            self.fail('native retained-project budget CAS implementation is missing')
        return native.GitProjectBudgetStore(self.repo, 'coordination', self.binding(**changes), protected_refs=[SOURCE])

    def event(self, name='check-1', **changes):
        value = {'type': 'reserve', 'event_id': name, 'task_id': 'retained-task', 'wake_id': 'old-wake',
                 'at_utc': NOW, 'operation_key': 'sha256:' + hashlib.sha256(name.encode()).hexdigest(),
                 'attempt_id': name + '-a1', 'kind': 'compute_start', 'scope': 'fixed-linux-checks',
                 'recovery_ref': None, 'cost': {'tool_calls': 1, 'tokens': None, 'elapsed_seconds': None}}
        value.update(changes); return value

    def remote_head(self):
        return self.git(self.remote, 'rev-parse', REF).decode().strip()

    def publish_ledger(self, value, *, extra=None):
        self.git(self.repo, 'fetch', 'coordination', REF)
        self.git(self.repo, 'reset', '--hard', 'FETCH_HEAD')
        (self.repo / self.path).write_text(json.dumps(value) + '\n')
        if extra: (self.repo / extra[0]).write_bytes(extra[1])
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '-m', 'External fixture update')
        self.git(self.repo, 'push', 'coordination', 'HEAD:' + REF)
        return self.remote_head()

    def test_parallel_bound_appends_through_original_registered_cas(self):
        self.policy.update(task_limits={}, wake_limits={}, max_parallel_agents=3)
        self.ledger = budget.new_ledger('retained-task', 'old-wake', self.policy)
        self.seed()
        store = self.store()
        for name in ('a', 'b', 'c'):
            revision, _ = store.read()
            store.append_event(revision, self.event(name, kind='agent_start'))
        def finish(name):
            revision, _ = store.read()
            store.append_event(revision, {'type':'outcome', 'event_id':'outcome-'+name,
                'task_id':'retained-task', 'wake_id':'old-wake', 'at_utc':NOW,
                'reservation_id':name, 'status':'succeeded',
                'usage':{'tokens':None, 'elapsed_seconds':None}, 'failure':None})
        finish('a')
        before, prior = store.read()
        prior_tree = self.git(self.remote, 'ls-tree', '-z', before)
        event = {'type':'parallel_limit', 'event_id':'narrow-current',
            'task_id':'retained-task', 'wake_id':'old-wake', 'at_utc':NOW,
            'max_parallel_agents':2, 'reference':'fixture:old ceiling unchanged'}
        receipt = store.append_event(before, event)
        after, value = store.read()
        self.assertFalse(receipt['authorizes_launch'])
        self.assertEqual(value['events'], prior['events']+[event])
        self.assertEqual(value['policy'], prior['policy'])
        self.assertEqual(value['policy_digest'], prior['policy_digest'])
        self.assertEqual(budget.summarize(value)['task']['agent_starts'], 3)
        self.assertEqual(store.read_revision(before), prior)
        for entry in prior_tree.split(b'\0'):
            if entry and entry.split(b'\t', 1)[1] != b'budget.json':
                self.assertIn(entry, self.git(self.remote, 'ls-tree', '-z', after).split(b'\0'))
        with self.assertRaisesRegex(ValueError, 'maximum parallel agents'):
            store.append_event(after, self.event('d', kind='agent_start'))
        self.assertEqual(self.remote_head(), after)
        finish('b')
        revision, _ = store.read()
        store.append_event(revision, self.event('d', kind='agent_start'))
        final = store.read()[1]
        self.assertEqual(budget.summarize(final)['task']['agent_starts'], 4)
        self.assertEqual(final['events'][:len(value['events'])], value['events'])

    def test_whole_file_append_preserves_neighbors_and_retained_identity(self):
        store = self.store(); before, old = store.read()
        prior_tree = self.git(self.remote, 'ls-tree', '-z', before)
        receipt = store.append_event(before, self.event())
        after, value = store.read()
        self.assertEqual(after, receipt['revision'])
        self.assertEqual(value['task_id'], 'retained-task')
        self.assertEqual(value['wake_ids'], ['old-wake'])
        self.assertEqual(budget.summarize(value)['task']['compute_starts'], 1)
        self.assertFalse(receipt['authorizes_launch'])
        for entry in prior_tree.split(b'\0'):
            if entry and entry.split(b'\t', 1)[1] != b'budget.json':
                self.assertIn(entry, self.git(self.remote, 'ls-tree', '-z', after).split(b'\0'))
        self.assertEqual(store.read_revision(before), old)

    def test_document_field_keeps_nonbudget_bytes_exact(self):
        self.seed(field=True); original = self.git(self.remote, 'show', REF + ':document.json')
        store = self.store(); revision, _ = store.read(); store.append_event(revision, self.event())
        changed = self.git(self.remote, 'show', REF + ':document.json')
        self.assertTrue(changed.startswith(b'{\n  "note" : "keep \\u0061 and spaces", "number":1.00,\n "budget" : '))
        self.assertTrue(changed.endswith(b',\n "tail" : [true, null] \n}\n'))
        self.assertNotEqual(changed, original)
        self.assertEqual(json.loads(changed)['budget']['events'][0]['event_id'], 'check-1')

    def test_duplicate_and_lost_push_reply_are_observed_without_second_push(self):
        store = self.store(); revision, _ = store.read(); real = store._git
        def lost(*args, **kwargs):
            value = real(*args, **kwargs)
            if 'push' in args: raise ValueError('simulated lost push reply')
            return value
        with patch.object(store, '_git', side_effect=lost):
            with self.assertRaises(ValueError): store.append_event(revision, self.event())
        committed = self.remote_head()
        observed = store.observe_event(self.event())
        self.assertTrue(observed['already_recorded']); self.assertFalse(observed['authorizes_launch'])
        duplicate = store.append_event(committed, self.event())
        self.assertTrue(duplicate['already_recorded']); self.assertEqual(self.remote_head(), committed)
        self.assertEqual(len(store.read()[1]['events']), 1)
        with self.assertRaises(ValueError): store.append_event(revision, self.event('another'))

    def test_two_actual_sibling_proposals_have_one_winner(self):
        # Removing exact-parent non-force CAS would allow both distinct effects.
        stores = [self.store(), self.store()]; revision, _ = stores[0].read()
        barrier = threading.Barrier(2); results = []
        def append(index):
            store = stores[index]; real = store._git
            def racing(*args, **kwargs):
                if 'push' in args: barrier.wait(timeout=20)
                return real(*args, **kwargs)
            try:
                with patch.object(store, '_git', side_effect=racing): store.append_event(revision, self.event('check-' + str(index)))
                results.append('won')
            except ValueError: results.append('lost')
        threads = [threading.Thread(target=append, args=(i,)) for i in range(2)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=35)
        self.assertEqual(sorted(results), ['lost', 'won'])
        self.assertEqual(len(stores[0].read()[1]['events']), 1)

    def test_scope_endpoint_anchor_and_task_substitution_denied(self):
        for change in [{'coordination_store_id': 'sha256:' + '0' * 64}, {'task_id': 'replacement-task'},
                       {'ledger_path': 'lease.json'}, {'ledger_path': '../budget.json'},
                       {'ledger_path': 'nested/budget.json'}, {'coordination_ref': SOURCE},
                       {'anchor_ledger_digest': 'sha256:' + '0' * 64}, {'proof': {'allowed': True}}]:
            with self.subTest(change=change), self.assertRaises(ValueError): self.store(**change)

    def test_duplicate_json_keys_and_ambiguous_field_denied(self):
        for payload in [b'{"budget":{},"budget":{}}', b'{"meta":{"x":1,"x":2},"budget":{}}',
                        b'{"budget":{},"Budget":{}}', b'{"budget":{},"x":NaN}']:
            with self.subTest(payload=payload):
                self.seed(field=True, payload=payload)
                with self.assertRaises(ValueError): self.store()

    def test_counter_history_policy_and_identity_rewrites_fail_even_when_restored(self):
        for mutation in ['truncate', 'policy', 'task', 'event', 'wakes']:
            with self.subTest(mutation=mutation):
                # Fresh endpoint per mutation avoids reusing poisoned history.
                self.setUp()
                store = self.store(); revision, _ = store.read(); store.append_event(revision, self.event())
                _, good = store.read(); bad = copy.deepcopy(good)
                if mutation == 'truncate': bad['events'] = []
                elif mutation == 'policy': bad['policy']['task_limits']['compute_starts'] = 9; bad['policy_digest'] = budget._digest(bad['policy'])
                elif mutation == 'task': bad = budget.new_ledger('replacement-task', 'old-wake', self.policy)
                elif mutation == 'event': bad['events'][0]['cost']['tool_calls'] = 2
                else: bad['wake_ids'] = ['replacement-wake']; bad['events'][0]['wake_id'] = 'replacement-wake'
                self.publish_ledger(bad); self.publish_ledger(good)
                with self.assertRaises(ValueError): store.read()

    def test_registration_anchor_cannot_be_rewound_or_unrelated(self):
        store = self.store(); revision, _ = store.read(); store.append_event(revision, self.event())
        current = self.remote_head()
        self.git(self.remote, 'update-ref', REF, self.anchor)
        with self.assertRaises(ValueError): store.read_revision(current)
        with self.assertRaises(ValueError):
            self.store(anchor_revision=current, anchor_ledger_digest=ledger_digest(budget.apply_event(self.ledger, self.event())))

    def test_budget_denial_and_operation_alias_do_not_write(self):
        store = self.store(); revision, _ = store.read()
        with self.assertRaises(ValueError): store.append_event(revision, self.event(kind='ci_start'))
        self.assertEqual(self.remote_head(), revision)
        store.append_event(revision, self.event()); revision, _ = store.read()
        with self.assertRaises(ValueError): store.append_event(revision, self.event(event_id='alias'))
        self.assertEqual(len(store.read()[1]['events']), 1)

    def test_new_wake_requires_registered_owner_reference_and_preserves_old_charges(self):
        store = self.store(); revision, _ = store.read(); store.append_event(revision, self.event())
        revision, _ = store.read()
        with self.assertRaises(ValueError): store.begin_wake(revision, 'invented-wake', 'owner:fake')
        receipt = store.begin_wake(revision, 'adoption-wake', 'owner:explicit-new-adoption-wake')
        revision, value = store.read()
        self.assertEqual(receipt['revision'], revision)
        self.assertEqual(value['wake_ids'], ['old-wake', 'adoption-wake'])
        self.assertEqual(budget.summarize(value)['task']['compute_starts'], 1)
        self.assertEqual(budget.summarize(value)['wake']['compute_starts'], 0)
        with self.assertRaises(ValueError): store.begin_wake(revision, 'old-wake', 'owner:fake')

    def test_external_lease_neighbor_change_is_preserved_but_budget_drift_blocks(self):
        store = self.store(); revision, _ = store.read()
        changed = self.publish_ledger(self.ledger, extra=('lease.json', b'{"owner":null,"generation":20}\n'))
        self.assertEqual(store.read()[0], changed)
        with self.assertRaises(ValueError): store.append_event(revision, self.event())
        store.append_event(changed, self.event())
        self.assertEqual(self.git(self.remote, 'show', REF + ':lease.json'), b'{"owner":null,"generation":20}\n')

    def test_malformed_registration_is_rejected_as_contract_error(self):
        for change in [{'ledger_path': []}, {'budget_field': {}}, {'task_id': None},
                       {'wake_authorizations': {'new': True}}, {'repository': None}]:
            with self.subTest(change=change), self.assertRaises(ValueError): self.store(**change)

    def test_wake_preserves_unknown_agent_liability_and_task_cap(self):
        self.policy['task_limits']['compute_starts'] = 1
        self.policy['task_limits']['agent_starts'] = 1; self.policy['max_parallel_agents'] = 1
        self.ledger = budget.new_ledger('retained-task', 'old-wake', self.policy)
        self.ledger = budget.apply_event(self.ledger, self.event('old-agent', kind='agent_start'))
        self.ledger = budget.apply_event(self.ledger, self.event('old-compute'))
        self.seed()
        store = self.store(); revision, _ = store.read()
        store.begin_wake(revision, 'adoption-wake')
        revision, value = store.read()
        self.assertEqual(budget.summarize(value)['active_agents'], 1)
        self.assertEqual(budget.summarize(value)['task']['compute_starts'], 1)
        with self.assertRaises(ValueError):
            store.append_event(revision, self.event('new-compute', wake_id='adoption-wake'))
        self.assertEqual(len(store.read()[1]['events']), 2)


if __name__ == '__main__': unittest.main()
