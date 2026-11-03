"""Real Git acceptance distinguishes final changes from scoped historical touches."""
import sys
import unittest
import test_managed_executor_pool as pool_fixture
import test_managed_host_bridge as host_fixture

pool = pool_fixture.m
bridge = host_fixture.bridge


class PoolScopedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.f = pool_fixture.T(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.git('switch', '-q', 'worker-a')

    def transient(self, revert=False):
        temporary = self.f.repo / 'src/a/temporary.txt'
        temporary.write_text('scoped intermediate content')
        self.f.git('add', 'src/a/temporary.txt')
        self.f.git('commit', '-q', '-m', 'scoped intermediate')
        if revert:
            commit = self.f.git('rev-parse', 'HEAD')
            self.f.git('revert', '--no-edit', commit)
        else:
            temporary.unlink()
            self.f.git('add', '-A')
            self.f.git('commit', '-q', '-m', 'remove scoped intermediate')
        return self.f.git('rev-parse', 'HEAD')

    def running(self):
        plan = pool_fixture.plan(self.f.base)
        state = pool.initial_state(plan, parallel_capable=True)
        state = self.f._queue(plan, state, 'a', 'a1')
        state = self.f._run(plan, state, 'a', 'a1')
        return plan, state

    def accept(self, result):
        plan, state = self.running()
        preview = pool.preview_writer_result(plan['tasks'][0], self.f.base, result, self.f.repo)
        self.assertEqual(preview['candidate_commit'], result)
        self.assertEqual(preview['final_paths'], ['src/a/result.txt'])
        self.assertEqual(set(preview['touched_paths']), {'src/a/result.txt', 'src/a/temporary.txt'})
        accepted = self.f._accept(plan, state, 'a', 'a1', ['src/a/result.txt'], ['out:a'], ['test:a'], result_commit=result)
        row = self.f._task_state(accepted, 'a')
        self.assertEqual(row['status'], 'succeeded')
        self.assertFalse(row['integrated'])
        self.assertEqual(self.f.git('rev-parse', 'worker-a'), result)
        self.assertEqual(row['runtime_seconds'], 10)
        self.assertEqual(row['attempt_ids'], ['a1'])

    def test_scoped_added_then_removed_path_is_allowed(self):
        self.accept(self.transient())

    def test_scoped_reverted_intermediate_path_is_allowed(self):
        self.accept(self.transient(revert=True))

    def test_reported_paths_still_match_exact_final_diff(self):
        result = self.transient()
        plan, state = self.running()
        with self.assertRaisesRegex(ValueError, 'exact Git diff'):
            self.f._accept(plan, state, 'a', 'a1', ['src/a/result.txt', 'src/a/temporary.txt'], ['out:a'], ['test:a'], result_commit=result)
        self.assertEqual(self.f._task_state(state, 'a')['status'], 'running')


@unittest.skipUnless(sys.platform == 'linux', 'existing managed process proof needs Linux')
class BridgeScopedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.f = host_fixture.ManagedHostBridgeTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.plan['tasks'][0]['max_runtime_seconds'] = 30
        self.f.plan['total_runtime_budget_seconds'] = 60

    def start(self, temporary):
        code = self.f.worker()[-1] + '''
p=Path(%r)
p.write_text('temporary')
subprocess.run(['git','add',str(p)],check=True)
subprocess.run(['git','commit','-qm','temporary history'],check=True)
p.unlink()
subprocess.run(['git','add','-A'],check=True)
subprocess.run(['git','commit','-qm','remove temporary history'],check=True)
''' % temporary
        request = self.f.start_request()
        request['argv'] = [sys.executable, '-c', code]
        handle = bridge.start(request)
        self.f.wait_for(handle, 'awaiting_release')
        session = bridge._load_session(request['handle_root'], handle['handle_id'])
        runtime = bridge._runtime(session)
        original = runtime._request(session['task_id'], session['attempt_id'])
        result_commit = runtime_module_git(original['cwd'], 'rev-parse', 'HEAD')
        return handle, runtime, result_commit

    def test_scoped_intermediate_history_publishes_exact_candidate_and_closes(self):
        handle, runtime, result_commit = self.start('docs/temporary.txt')
        result = bridge.finish(self.f.finish_request(handle))
        self.assertEqual(result['published_commit'], result_commit)
        self.assertEqual(self.f.remote_head(), result_commit)
        self.assertTrue(result['scope_complete'])
        row = runtime.store.read()[1]['tasks'][0]
        self.assertEqual(row['status'], 'succeeded')
        self.assertTrue(row['integrated'])
        self.assertIsNone(self.f.lease_store.read()[1]['owner_id'])
        self.assertTrue(runtime.verify_terminal('closure', 'closure-a1')['fresh_physical_absence'])

    def test_out_of_scope_transient_history_still_denied_before_publication(self):
        handle, runtime, result_commit = self.start('ESCAPED')
        request = self.f.finish_request(handle)
        with self.assertRaisesRegex(ValueError, 'history touched paths'):
            bridge.finish(request)
        self.assertEqual(self.f.remote_head(), self.f.base)
        self.assertIsNotNone(self.f.lease_store.read()[1]['owner_id'])
        rejection = {key: value for key, value in request.items() if key not in {'output_refs', 'evidence_refs'}}
        rejection.update(schema='managed-host-reject-preparation/v1', review_ref='review:out-of-scope-history')
        self.assertFalse(bridge.reject_preparation(rejection)['scope_complete'])
        self.assertEqual(self.f.remote_head(), self.f.base)


def runtime_module_git(cwd, *args):
    import subprocess
    return subprocess.check_output(['git', '-C', str(cwd), *args], text=True).strip()
