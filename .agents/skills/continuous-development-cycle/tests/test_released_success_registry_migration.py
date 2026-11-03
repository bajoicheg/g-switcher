"""One original same-boot success may migrate pins before metadata completion."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import managed_host_bridge as bridge
import managed_executor_runtime as runtime
import operation_intent as operation
import unknown_recovery as recovery
from git_document_store import GitDocumentStore


class ReleasedSuccessRegistryMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_managed_host_bridge import ManagedHostBridgeTests
        cls.fixture = ManagedHostBridgeTests()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        fixture = cls.fixture
        request = fixture.start_request()
        (fixture.root / 'start.json').write_text(json.dumps(request))
        code = '''import json,sys,time
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[2]]
import managed_host_bridge as bridge
from reporting_fixtures import binding
request=json.loads(Path(sys.argv[3]).read_text())
handle=bridge.start(request)
end=time.monotonic()+12
while time.monotonic()<end:
 if bridge.observe({'schema':'managed-host-observe/v1','handle_root':request['handle_root'],'handle_id':handle['handle_id']})['runtime_status']=='awaiting_release':break
 time.sleep(.01)
session=bridge._load_session(request['handle_root'],handle['handle_id'])
checkpoint='original-success:checkpoint'
finished=bridge.finish({'schema':'managed-host-finish/v2','handle_root':request['handle_root'],'handle_id':handle['handle_id'],'output_refs':['out:closure'],'evidence_refs':['test:closure'],'checkpoint_ref':checkpoint,'reporting_binding':binding(bridge._lease_store(session),handle['invocation_id'],checkpoint)})
Path(sys.argv[4]).write_text(json.dumps({'handle':handle,'finished':finished}))
'''
        output = fixture.root / 'finished.json'
        completed = subprocess.run([sys.executable, '-B', '-c', code,
            str(ROOT / 'scripts'), str(ROOT / 'tests'),
            str(fixture.root / 'start.json'), str(output)], capture_output=True, timeout=30)
        if completed.returncode:
            raise AssertionError(completed.stderr.decode())
        result = json.loads(output.read_text())
        cls.finished = result['finished']
        cls.session = bridge._load_session(request['handle_root'], result['handle']['handle_id'])
        cls.native = bridge._runtime(cls.session)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            try:
                cls.native.verify_terminal('closure', 'closure-a1', include_controller=True,
                    lease_store=fixture.lease_store, release_receipt=cls.session['release_receipt'])
                break
            except ValueError as error:
                if 'physical PID still present' not in str(error):
                    raise
                time.sleep(.02)
        else:
            raise AssertionError('original real success controller was not physically reaped')

    def setUp(self):
        start = json.loads((self.fixture.root / 'start.json').read_text())
        self.store = GitDocumentStore(self.fixture.repo, 'origin',
            'refs/heads/cdc/success-registry-' + uuid.uuid4().hex,
            self.fixture.store_id, task_shards=True)
        self.document = {'schema': 'cdc-vps-control/v1', 'registry_digest': 'sha256:' + 'a' * 64,
            'tasks': {'closure': {'state': 'terminal_pending',
                'task': {'id': 'closure', 'schema': 'cdc-vps-task/v2',
                    'source_sha': self.session['plan']['base_sha'], 'role': 'writer',
                    'budget': {'ci_starts': 0}},
                'budget': {'spent': 17, 'outcome': 'UNKNOWN', 'reservations': ['original']},
                'operation': {'handle_id': self.session['handle_id'],
                    'attempt_id': self.session['attempt_id'], 'start_request': start,
                    'start_request_digest': operation._hash(start),
                    'finish_result': copy.deepcopy(self.finished)}, 'result': None}},
            'queue': {'items': [{'original_id': 'queued-original', 'state': 'acked'}]}}
        self.revision = self.store.compare_and_swap(None, self.document)
        self.old = self.document['registry_digest']
        self.new = 'sha256:' + 'b' * 64

    def proof(self):
        return self.native.verify_terminal('closure', 'closure-a1', include_controller=True,
            lease_store=self.fixture.lease_store, release_receipt=self.session['release_receipt'])

    def migrate(self, proofs):
        return recovery.migrate_intake_registry_cas(self.store, self.revision,
            self.old, self.new, terminal_reconciliations=proofs)

    def test_real_original_same_boot_success_changes_only_registry_and_storage(self):
        source = self.fixture.remote_head()
        pool = self.native.store.read()
        lease = self.fixture.lease_store.read()
        proof = self.proof()
        self.assertNotIn('boot_reconciliation', proof)
        actual = self.migrate({'closure': proof})
        expected = copy.deepcopy(self.document)
        expected['registry_digest'] = self.new
        self.assertEqual(actual['document'], expected)
        self.assertEqual(self.store.read(), (actual['revision'], expected))
        self.assertEqual(actual['document']['tasks']['closure']['state'], 'terminal_pending')
        self.assertEqual(self.store._git('ls-tree', '--name-only', actual['revision']).splitlines(),
                         ['document.json', 'tasks'])
        self.assertEqual(self.fixture.remote_head(), source)
        self.assertEqual(self.native.store.read(), pool)
        self.assertEqual(self.fixture.lease_store.read(), lease)

    def test_missing_serialized_foreign_or_boot_relabelled_proof_is_denied(self):
        with self.assertRaises(ValueError):
            recovery.migrate_intake_registry_cas(self.store, self.revision, self.old, self.new)
        proof = self.proof()
        for value in (dict(proof), {}):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.migrate({'closure': value})
        for key, value in (('boot_reconciliation', {'status': 'forged'}),
                           ('status', 'failed'), ('boot_id', str(uuid.uuid4())),
                           ('request_ref', 'sha256:' + '0' * 64)):
            proof = self.proof()
            proof[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.migrate({'closure': proof})
        self.assertEqual(self.store.read(), (self.revision, self.document))

    def test_original_row_source_attempt_release_and_finish_substitution_is_denied(self):
        proof = self.proof()
        mutations = [
            ('task', 'role', 'read_only'), ('task', 'source_sha', '0' * 40),
            ('operation', 'handle_id', str(uuid.uuid4())),
            ('operation', 'attempt_id', 'closure-a2'),
            ('finish', 'worker_status', 'failed'), ('finish', 'scope_complete', False),
            ('finish', 'managed_finish_allowed', False),
            ('finish', 'published_commit', '0' * 40), ('finish', 'release_receipt', {}),
            ('row', 'state', 'unknown'), ('row', 'result', {'made_up': True}),
        ]
        for target, key, value in mutations:
            bad = copy.deepcopy(self.document)
            row = bad['tasks']['closure']
            container = row if target == 'row' else row['operation']['finish_result'] if target == 'finish' else row[target]
            container[key] = value
            revision = self.store.compare_and_swap(self.revision, bad)
            with self.subTest(target=target, key=key), self.assertRaises(ValueError):
                recovery.migrate_intake_registry_cas(self.store, revision, self.old, self.new,
                    terminal_reconciliations={'closure': proof})
            self.assertEqual(self.store.read(), (revision, bad))
            self.revision = self.store.compare_and_swap(revision, self.document)
        bad = copy.deepcopy(self.document)
        bad['tasks']['closure']['task']['budget']['ci_starts'] = 1
        revision = self.store.compare_and_swap(self.revision, bad)
        with self.assertRaises(ValueError):
            recovery.migrate_intake_registry_cas(self.store, revision, self.old, self.new,
                terminal_reconciliations={'closure': proof})

    def test_changed_original_launch_custody_is_denied(self):
        proof = self.proof()
        for key, value in (('argv', ['unrelated-command']), ('journal_root', '/unrelated'),
                           ('lease_repository', 'other/project'), ('lease_coordination_ref', 'refs/heads/cdc/other')):
            bad = copy.deepcopy(self.document)
            start = bad['tasks']['closure']['operation']['start_request']
            start[key] = value
            bad['tasks']['closure']['operation']['start_request_digest'] = operation._hash(start)
            revision = self.store.compare_and_swap(self.revision, bad)
            with self.subTest(key=key), self.assertRaises(ValueError):
                recovery.migrate_intake_registry_cas(self.store, revision, self.old, self.new,
                    terminal_reconciliations={'closure': proof})
            self.revision = self.store.compare_and_swap(revision, self.document)

    def test_session_owner_generation_publication_and_start_custody_is_denied(self):
        proof = self.proof()
        for key, value in (('owner_id', str(uuid.uuid4())), ('generation', self.session['generation'] + 1),
                           ('lease_source_ref', 'refs/heads/other'), ('result_commit', '0' * 40)):
            bad = copy.deepcopy(self.session)
            bad[key] = value
            with self.subTest(key=key), patch.object(bridge, '_load_session', return_value=bad):
                with self.assertRaises(ValueError):
                    self.migrate({'closure': proof})
        bad = copy.deepcopy(self.session)
        bad['publication']['conditional_update'] = False
        with patch.object(bridge, '_load_session', return_value=bad), self.assertRaises(ValueError):
            self.migrate({'closure': proof})
        self.assertEqual(self.store.read(), (self.revision, self.document))

    def test_original_process_presence_and_foreign_boot_deny_fresh_capability(self):
        proof = self.proof()
        pid = proof['processes'][0]['pid']
        real = runtime._process
        with patch.object(runtime, '_process', side_effect=lambda item: {'birth': '1'} if item == pid else real(item)):
            with self.assertRaises(ValueError):
                self.migrate({'closure': proof})
        with patch.object(runtime, '_boot', return_value=str(uuid.uuid4())), self.assertRaises(ValueError):
            self.migrate({'closure': proof})
        self.assertEqual(self.store.read(), (self.revision, self.document))

    def test_native_cas_revalidates_success_and_cannot_change_budget(self):
        proof = self.proof()
        original = self.store.compare_and_swap
        def inject(revision, document, **options):
            bad = copy.deepcopy(document)
            bad['tasks']['closure']['budget']['spent'] = 18
            return original(revision, bad, **options)
        with patch.object(self.store, 'compare_and_swap', side_effect=inject), self.assertRaises(ValueError):
            self.migrate({'closure': proof})
        self.assertEqual(self.store.read(), (self.revision, self.document))
        read = self.store.read
        actual_boot = runtime._boot()
        calls = []
        def fresh_read():
            calls.append(1)
            return read()
        with patch.object(self.store, 'read', side_effect=fresh_read), \
             patch.object(runtime, '_boot', side_effect=lambda: str(uuid.uuid4()) if len(calls) >= 2 else actual_boot):
            with self.assertRaises(ValueError):
                self.migrate({'closure': self.proof()})
        self.assertEqual(self.store.read(), (self.revision, self.document))


if __name__ == '__main__':
    unittest.main()
