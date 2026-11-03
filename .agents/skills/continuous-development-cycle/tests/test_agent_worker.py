"""Real native Git/process boundary tests; provider executables are synthetic fixtures."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import test_managed_executor_runtime as native_fixture
from project_budget_store import GitProjectBudgetStore, ledger_digest
import budget


def contract(base, task='a', provider='codex'):
    return {'schema':'cdc-agent-task/v1','task_id':task,'project_id':'synthetic',
        'repository':'fixture/project','base_sha':base,'branch':'worker-'+task,
        'worktree':'worktrees/'+task,'objective':'Create a synthetic fixture result.',
        'acceptance_criteria':['Synthetic output exists.'],'allowed_files':['src/'+task],
        'allowed_operations':['read','edit'],'provider':provider,'model':'fixture-model',
        'role':'developer','execution_profile':'workspace-write','security_classification':'synthetic',
        'budget':{'agent_starts':1,'tokens':None,'cost_units':1},
        'limits':{'timeout_seconds':10,'retry_limit':0},'dependencies':[],
        'required_tests':[['python3','-c',"from pathlib import Path; assert Path('src/"+task+"/fixture').read_text() == 'synthetic only'"]],
        'review':{'required':True,'provider':'gemini' if provider=='codex' else 'codex','max_iterations':1},
        'artifacts':{'directory':'artifacts/'+task},'review_of':None}


class AgentWorkerTests(unittest.TestCase):
    # Reuse only the existing real Git/process fixture, not its historical suite.
    git=native_fixture.RuntimeTests.git
    task=native_fixture.RuntimeTests.task
    make_runtime=native_fixture.RuntimeTests.make_runtime
    cleanup_workers=native_fixture.RuntimeTests.cleanup_workers
    wait=native_fixture.RuntimeTests.wait
    configure_fresh_pool=native_fixture.RuntimeTests.configure_fresh_pool

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('agent_worker'), 'native provider facade missing')
        global worker
        import agent_worker as worker
        native_fixture.RuntimeTests.setUp(self)
        self.contract=contract(self.base)
        self.cli=self.root/'fixture-provider'
        self.cli.write_text('''#!/usr/bin/python3
import json,sys,time,pathlib
task=json.loads(sys.argv[-1].split('\\n',1)[1])
p=pathlib.Path('src')/task['task_id'];p.mkdir(parents=True,exist_ok=True)
(p/'fixture').write_text('synthetic only')
barrier=pathlib.Path(__file__).with_name('parallel-barrier')
if barrier.exists():
 barrier.with_name('ready-'+task['task_id']).touch()
 while not all(barrier.with_name('ready-'+x).exists() for x in ('a','b')):time.sleep(.01)
started=time.monotonic()
time.sleep(.1)
(p/'interval.json').write_text(json.dumps([started,time.monotonic()]))
if task['provider']=='kimi':
 print(json.dumps({'role':'meta','type':'system.version','version':'2.2.0'}))
 print(json.dumps({'role':'assistant','content':'done'}))
 print(json.dumps({'role':'meta','type':'session.resume_hint','session_id':'fixture-kimi','command':'kimi -r fixture-kimi','content':'To resume this session: kimi -r fixture-kimi'}))
elif '--output-format' in sys.argv:
 print(json.dumps({'type':'init','session_id':'fixture-gemini'}))
 print(json.dumps({'type':'message','role':'assistant','content':'done','delta':True}))
 print(json.dumps({'type':'result','status':'success'}))
else:
 print(json.dumps({'type':'thread.started','thread_id':'fixture-codex'}))
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'done'}}))
 print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':1}}))
''');self.cli.chmod(0o700)
        # Separate registered original budget branch; never mutate source/index.
        self.brepo=self.root/'budget-client';self.brepo.mkdir()
        import subprocess
        def bg(*a):
            return subprocess.check_output(['git','-C',str(self.brepo),*a],stderr=subprocess.PIPE,text=True).strip()
        self.bg=bg
        for args in [('init','-q','-b','budget'),('config','user.name','Fixture'),('config','user.email','fixture@example.invalid'),('remote','add','origin',str(self.remote))]: bg(*args)
        policy={'task_limits':{'agent_starts':4},'wake_limits':{'agent_starts':4},'max_parallel_agents':2,
            'checkpoint_reserve':{'tokens':0,'tool_calls':0},'provider_max_age_seconds':60,'actions_budget':'normal'}
        ledger=budget.new_ledger('modernization','phase1',policy)
        (self.brepo/'budget.json').write_text(json.dumps(ledger))
        bg('add','budget.json');bg('commit','-qm','Original synthetic model budget')
        anchor=bg('rev-parse','HEAD');ref='refs/heads/cdc/fixture-agent-budget'
        bg('push','origin','HEAD:'+ref)
        self.bs=GitProjectBudgetStore(self.brepo,'origin',{
            'schema':'project-budget-binding/v1','repository':'fixture/project','source_ref':'refs/heads/integration',
            'coordination_ref':ref,'coordination_store_id':self.plan['coordination_store_id'],
            'ledger_path':'budget.json','budget_field':None,'task_id':'modernization',
            'anchor_revision':anchor,'anchor_ledger_digest':ledger_digest(ledger),'wake_authorizations':{}})

    def facade(self, value=None):
        return worker.AgentWorker(self.rt,value or self.contract,str(self.cli),project_id='synthetic',repository='fixture/project',model_budget_binding=self.bs.binding)

    def reserve(self, facade, attempt='a1'):
        event={'type':'reserve','event_id':'model-'+attempt,'task_id':'modernization','wake_id':'phase1',
            'at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'operation_key':facade.operation_key(attempt),
            'attempt_id':attempt,'kind':'agent_start','scope':'agent-task:'+facade.contract_digest,
            'recovery_ref':None,'cost':{'tool_calls':1,'tokens':None,'elapsed_seconds':facade.contract['limits']['timeout_seconds']}}
        rev,_=self.bs.read();self.bs.append_event(rev,event);return event

    def start(self, facade=None,attempt='a1'):
        facade=facade or self.facade();event=self.reserve(facade,attempt)
        rev,_=self.store.read()
        facade.start(rev,attempt,reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        return facade

    def test_rejects_native_scope_budget_and_base_substitution_before_launch(self):
        for field,value in [('base_sha','0'*40),('branch','worker-substitute'),('allowed_files',['src/b']),('project_id','other')]:
            changed=copy.deepcopy(self.contract);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.facade(changed)
        changed=copy.deepcopy(self.contract);changed['limits']['timeout_seconds']=11
        with self.assertRaises(ValueError):self.facade(changed)
        self.assertFalse(list((self.root/'journal').glob('*/request.json')))

    def test_original_model_charge_required_and_cannot_be_substituted(self):
        facade=self.facade();event=self.reserve(facade)
        event['operation_key']='sha256:'+'0'*64
        rev,_=self.store.read()
        with self.assertRaises(ValueError):facade.start(rev,'a1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        self.assertFalse(list((self.root/'journal').glob('*/request.json')))

    def test_codex_result_and_restart_observation_never_relaunch(self):
        facade=self.start();self.wait()
        observed=facade.collect_result('a1')
        self.assertEqual(observed['status'],'succeeded');self.assertEqual(observed['exit_code'],0)
        self.assertEqual(observed['usage'],{'input_tokens':3,'output_tokens':1})
        restarted=self.facade();self.assertEqual(restarted.collect_result('a1'),observed)
        rev,_=self.store.read();event=self.bs.read()[1]['events'][0]
        with self.assertRaises(ValueError):restarted.start(rev,'a1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        self.assertEqual(len(list((self.root/'journal').glob('*/launch.lock'))),1)

    def test_fresh_controller_recovers_in_flight_original_provider_without_relaunch(self):
        # Catch loss of durable launch ownership when every controller-side
        # runtime/store/facade object is reconstructed while the provider lives.
        self.cli.write_text('''#!/usr/bin/python3
import json,pathlib,time
control=pathlib.Path(__file__).parent
with (control/'provider-starts').open('a') as starts: starts.write('start\\n')
(control/'provider-started').touch()
while not (control/'provider-release').exists(): time.sleep(.01)
output=pathlib.Path('src/a');output.mkdir(parents=True,exist_ok=True)
(output/'fixture').write_text('synthetic only')
print(json.dumps({'type':'thread.started','thread_id':'original-in-flight-provider'}))
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'done'}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':1}}))
''')
        original=self.start()
        release=self.root/'provider-release'
        self.addCleanup(release.touch)
        native_fixture.RuntimeTests.wait_file(self,self.root/'provider-started')
        running=original.get_status('a1')
        ready_deadline=time.monotonic()+4
        while running['status']=='starting' and time.monotonic()<ready_deadline:
            time.sleep(.01)
            running=original.get_status('a1')
        self.assertEqual(running['status'],'running')
        self.assertFalse(running['quiescent'])
        request=original.runtime._request('a','a1')
        journal=Path(request['journal_directory'])
        request_bytes=(journal/'request.json').read_bytes()
        budget_before=self.bs.read()

        plan=copy.deepcopy(self.plan)
        self.store=worker.GitManagedExecutorStore(self.repo,'origin',plan['coordination_ref'],plan,
                                                protected_refs=['refs/heads/integration'])
        self.rt=worker.ManagedExecutorRuntime(plan,self.store,self.repo,
                    worker.LocalCommandBackend(self.root/'journal'),journal_root=self.root/'journal')
        recovered=self.facade()
        self.assertIsNot(recovered.runtime,original.runtime)
        self.assertIsNot(recovered.runtime.store,original.runtime.store)
        self.assertIsNot(recovered.runtime.backend,original.runtime.backend)
        observed=recovered.get_status('a1')
        self.assertEqual(observed['status'],'running')
        self.assertFalse(observed['quiescent'])
        self.assertEqual(observed['launch_id'],running['launch_id'])
        self.assertEqual(recovered.runtime._request('a','a1'),request)
        revision,_=self.store.read();event=budget_before[1]['events'][0]
        with self.assertRaises(ValueError):
            recovered.start(revision,'a1',reservation_token=event['event_id'],
                            model_budget_store=self.bs,reservation_event=event)

        release.touch()
        terminal=self.wait()
        self.assertEqual(terminal['status'],'succeeded')
        self.assertEqual(terminal['launch_id'],running['launch_id'])
        result=recovered.collect_result('a1')
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['attempt_id'],'a1')
        self.assertEqual(result['session_id'],'original-in-flight-provider')
        self.assertEqual(result['started_at'],running['started_at_utc'])
        self.assertEqual(result['test_evidence'][0]['exit_code'],0)
        self.assertEqual(result['checkpoint']['journal_directory'],str(journal))
        self.assertEqual((journal/'request.json').read_bytes(),request_bytes)
        self.assertEqual((self.root/'provider-starts').read_text(),'start\n')
        self.assertEqual(len(list((self.root/'journal').glob('*/request.json'))),1)
        self.assertEqual(len(list((self.root/'journal').glob('*/launch.lock'))),1)
        self.assertEqual(self.store.read()[1]['tasks'][0]['attempt_ids'],['a1'])
        self.assertEqual(self.bs.read(),budget_before)

    def test_gemini_result_preserves_unknown_usage(self):
        self.contract['provider']='gemini';self.contract['review']['provider']='codex'
        facade=self.start();self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['provider'],'gemini')
        self.assertIsNone(result['usage'])

    def test_deterministic_checks_failure_overrides_provider_success(self):
        self.contract['required_tests']=[[sys.executable,'-c',"print('real deterministic failure');raise SystemExit(7)"]]
        facade=self.start();self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['status'],'failed');self.assertEqual(result['exit_code'],7)
        self.assertEqual(result['test_evidence'][0]['exit_code'],7)
        self.assertEqual(result['test_evidence'][0]['argv'],self.contract['required_tests'][0])

    def test_deterministic_pass_records_actual_command_exit_and_logs(self):
        facade=self.start();self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['test_evidence'][0]['exit_code'],0)
        self.assertEqual(result['test_evidence'][0]['argv'],['python3','-c',"from pathlib import Path; assert Path('src/a/fixture').read_text() == 'synthetic only'"])
        self.assertTrue(Path(result['test_evidence'][0]['stderr']).is_file())

    def configure_review(self, dirty=False):
        (self.repo/'proposal.txt').write_text('synthetic proposal')
        self.git('add','proposal.txt');self.git('commit','-qm','Synthetic proposal')
        head=self.git('rev-parse','HEAD');old=self.base
        self.plan['base_sha']=head
        self.plan['tasks'][0].update(role='read_only',branch=None,worktree=None,write_paths=[])
        self.configure_fresh_pool()
        self.contract.update(base_sha=head,branch=None,worktree=None,role='reviewer',
            allowed_files=[],allowed_operations=['read'],execution_profile='read-only',
            required_tests=[],
            review_of={'base_sha':old,'head_sha':head,'developer_provider':'gemini','test_evidence':['synthetic test evidence']})
        lines=['#!/usr/bin/python3','import json,pathlib']
        if dirty:lines.append("pathlib.Path('injected').write_text('unexpected mutation')")
        lines += ["print(json.dumps({'type':'thread.started','thread_id':'fixture-review'}))",
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'verdict':'approved','findings':[]})}}))",
            "print(json.dumps({'type':'turn.completed'}))"]
        self.cli.write_text('\n'.join(lines)+'\n')

    def test_independent_review_binds_real_diff_and_clean_snapshot(self):
        self.configure_review();facade=self.start();self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['review'],{'verdict':'approved','findings':[]})
        request=self.rt._request('a','a1')
        self.assertIn('+synthetic proposal',request['argv'][-1])
        self.assertEqual(self.git('status','--porcelain'),'')

    def _exercise_developer_to_opposite_default_reviewer(self, provider, reviewer_provider=None):
        # Real Git, original native starts, checks, scoped host commit and exact
        # handoff; only the external coding CLIs are synthetic executables.
        import subprocess
        developer = self.contract
        developer['provider'] = provider
        reviewer_provider = reviewer_provider or ('gemini' if provider == 'codex' else 'codex')
        developer['review']['provider'] = reviewer_provider
        facade = self.start()
        terminal = self.wait()
        result = facade.collect_result('a1')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['test_evidence'][0]['exit_code'], 0)
        cwd = Path(self.rt._request('a', 'a1')['cwd'])
        def workgit(*args):
            return subprocess.check_output(['git', '-C', str(cwd), *args], text=True).strip()
        workgit('add', '--', 'src/a')
        workgit('commit', '-qm', 'Host records checked synthetic developer result')
        head = workgit('rev-parse', 'HEAD')
        self.assertNotEqual(head, self.base)
        check_refs = [result['test_evidence'][0][stream] for stream in ('stdout', 'stderr')]
        self.rt.accept('a', 'a1', result_commit=head, output_refs=['out:a'],
                       evidence_refs=['test:a', *check_refs], cost_units=1)
        developer_pool = self.store
        original_charge = self.bs.read()[1]['events'][0]
        rev, _ = self.bs.read()
        self.bs.append_event(rev, {'type':'outcome', 'event_id':'outcome-developer',
            'task_id':'modernization', 'wake_id':'phase1', 'at_utc':terminal['finished_at_utc'],
            'reservation_id':original_charge['event_id'], 'status':'succeeded',
            'usage':{'tokens':None, 'elapsed_seconds':terminal['runtime_seconds']}, 'failure':None})

        self.plan = copy.deepcopy(self.plan)
        self.plan['base_sha'] = head
        self.plan['tasks'][1].update(role='read_only', branch=None, worktree=None, write_paths=[])
        self.configure_fresh_pool()
        self.contract = copy.deepcopy(developer)
        self.contract.update(task_id='b', base_sha=head, branch=None, worktree=None, role='reviewer',
            provider=reviewer_provider, allowed_files=[], allowed_operations=['read'],
            execution_profile='read-only', required_tests=[],
            review={'required':True, 'provider':provider, 'max_iterations':1},
            review_of={'base_sha':self.base, 'head_sha':head,
                       'developer_provider':provider, 'test_evidence':check_refs})
        self.cli.write_text("""#!/usr/bin/python3
import json,sys
assert 'synthetic only' in sys.argv[-1]
assert 'check-0.stdout.log' in sys.argv[-1]
assert 'check-0.stderr.log' in sys.argv[-1]
verdict=json.dumps({'verdict':'approved','findings':[]})
if '--agent-file' in sys.argv:
 print(json.dumps({'role':'meta','type':'system.version','version':'2.2.0'}))
 print(json.dumps({'role':'assistant','content':verdict}))
 print(json.dumps({'role':'meta','type':'session.resume_hint','session_id':'fixture-kimi-review','command':'kimi -r fixture-kimi-review','content':'To resume this session: kimi -r fixture-kimi-review'}))
elif '--output-format' in sys.argv:
 print(json.dumps({'type':'init','session_id':'fixture-gemini-review'}))
 print(json.dumps({'type':'message','role':'assistant','content':verdict,'delta':True}))
 print(json.dumps({'type':'result','status':'success'}))
else:
 print(json.dumps({'type':'thread.started','thread_id':'fixture-codex-review'}))
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':verdict}}))
 print(json.dumps({'type':'turn.completed'}))
""")
        review = self.start(attempt='b1')
        self.wait('b')
        observed = review.collect_result('b1')
        self.assertEqual(observed['status'], 'succeeded')
        self.assertEqual(observed['review'], {'verdict':'approved','findings':[]})
        self.assertEqual(observed['review_of']['test_evidence'], check_refs)
        self.assertEqual(observed['observed_head_sha'], head)
        self.assertEqual(observed['test_evidence'], [])
        self.assertFalse(observed['accepted'])
        self.assertIsNone(observed['cli_variant'])
        self.assertEqual(developer_pool.read()[1]['tasks'][0]['status'], 'succeeded')
        self.assertEqual(facade.collect_result('a1')['commit_sha'], head)
        self.assertEqual(workgit('status', '--porcelain'), '')
        self.assertEqual([e['type'] for e in self.bs.read()[1]['events']],
                         ['reserve', 'outcome', 'reserve'])

    def test_codex_developer_to_default_gemini_reviewer_with_actual_check_evidence(self):
        self._exercise_developer_to_opposite_default_reviewer('codex')

    def test_gemini_developer_to_codex_reviewer_with_actual_check_evidence(self):
        self._exercise_developer_to_opposite_default_reviewer('gemini')

    def test_codex_developer_to_kimi_reviewer_with_actual_check_evidence(self):
        self._exercise_developer_to_opposite_default_reviewer('codex', 'kimi')

    def test_kimi_developer_to_codex_reviewer_with_actual_check_evidence(self):
        self._exercise_developer_to_opposite_default_reviewer('kimi', 'codex')

    def test_kimi_agent_definition_change_rejects_original_binding_before_start(self):
        import agent_cli_adapters
        from unittest import mock
        self.contract['provider'] = 'kimi'
        self.contract['review']['provider'] = 'codex'
        profiles = self.root / 'isolated-kimi-package' / 'templates'
        profiles.mkdir(parents=True)
        for role in ('developer', 'reviewer'):
            (profiles / ('kimi-' + role + '-v220.yaml')).write_text('original profile')
        module = profiles.parent / 'scripts' / 'agent_cli_adapters.py'
        with mock.patch.object(agent_cli_adapters, '__file__', str(module)):
            facade = self.facade()
            original_key = facade.operation_key('a1')
            (profiles / 'kimi-reviewer-v220.yaml').write_text('changed tool policy')
            with self.assertRaisesRegex(ValueError, 'immutable provider CLI configuration'):
                facade.operation_key('a1')
            replacement = self.facade()
            self.assertNotEqual(replacement.operation_key('a1'), original_key)
        self.assertEqual(self.bs.read()[1]['events'], [])
        self.assertFalse(list((self.root / 'journal').glob('*/request.json')))

    def test_reconstructed_kimi_cannot_collect_after_inactive_role_file_changes(self):
        import agent_cli_adapters
        from unittest import mock
        self.contract['provider'] = 'kimi'
        self.contract['review']['provider'] = 'codex'
        profiles = self.root / 'isolated-kimi-recovery' / 'templates'
        profiles.mkdir(parents=True)
        for role in ('developer', 'reviewer'):
            (profiles / ('kimi-' + role + '-v220.yaml')).write_text('original profile')
        module = profiles.parent / 'scripts' / 'agent_cli_adapters.py'
        with mock.patch.object(agent_cli_adapters, '__file__', str(module)):
            original = self.start()
            self.wait()
            self.assertEqual(original.collect_result('a1')['status'], 'succeeded')
            (profiles / 'kimi-reviewer-v220.yaml').write_text('changed inactive role')
            reconstructed = self.facade()
            for observe in (reconstructed.get_status, reconstructed.collect_result):
                with self.assertRaisesRegex(ValueError, 'original launch contract/provider/prompt substituted'):
                    observe('a1')
        self.assertEqual(len(self.bs.read()[1]['events']), 1)

    def test_lost_check_receipt_cannot_retain_review_approval(self):
        self.configure_review();facade=self.start();self.wait()
        result=facade.collect_result('a1')
        self.assertEqual(result['review']['verdict'],'approved')
        (Path(result['checkpoint']['journal_directory'])/'checks.json').unlink()
        result=facade.collect_result('a1')
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['review']['verdict'],'blocked')

    def test_substituted_model_budget_registration_is_rejected(self):
        facade=self.facade();event=self.reserve(facade)
        self.bs.binding['task_id']='other-authority'
        rev,_=self.store.read()
        with self.assertRaises(ValueError):facade.start(rev,'a1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)

    def test_hidden_tracked_reviewer_mutation_cannot_approve(self):
        self.configure_review()
        code=self.cli.read_text().replace('import json,pathlib','import json,pathlib,subprocess')
        code=code.replace("print(json.dumps({'type':'thread.started'", "subprocess.run(['git','update-index','--assume-unchanged','seed'],check=True)\npathlib.Path('seed').write_text('hidden mutation')\nprint(json.dumps({'type':'thread.started'",1)
        self.cli.write_text(code)
        facade=self.start();self.wait()
        self.assertEqual(facade.collect_result('a1')['review']['verdict'],'blocked')

    def test_reviewer_mutation_cannot_approve(self):
        self.configure_review(dirty=True);facade=self.start();self.wait()
        self.assertEqual(facade.collect_result('a1')['review']['verdict'],'blocked')

    def test_native_timeout_preserves_original_attempt(self):
        self.plan['tasks'][0]['max_runtime_seconds']=1;self.configure_fresh_pool()
        self.contract['limits']['timeout_seconds']=1
        self.cli.write_text('#!/usr/bin/python3\nimport time\ntime.sleep(20)\n')
        facade=self.start();self.assertEqual(self.wait()['status'],'timed_out')
        self.assertEqual(facade.collect_result('a1')['status'],'timed_out')
        self.assertEqual(self.store.read()[1]['tasks'][0]['attempt_ids'],['a1'])

    def test_parallel_providers_use_distinct_worktrees_and_overlapping_intervals(self):
        (self.root/'parallel-barrier').touch()
        left=self.start()
        right_contract=contract(self.base,'b','gemini');right=self.facade(right_contract)
        self.start(right,'b1');self.wait('a');self.wait('b')
        l=json.loads((self.root/'worktrees/a/src/a/interval.json').read_text())
        r=json.loads((self.root/'worktrees/b/src/b/interval.json').read_text())
        self.assertLess(max(l[0],r[0]),min(l[1],r[1]))
        self.assertFalse((self.root/'worktrees/a/src/b').exists())
        self.assertFalse((self.repo/'src').exists())
        self.assertEqual(right.collect_result('b1')['provider'],'gemini')

    def test_conflicting_native_write_ownership_blocks_second_provider(self):
        self.plan['tasks'][1]['write_paths']=['src/a'];self.configure_fresh_pool()
        self.start()
        second=contract(self.base,'b','gemini');second['allowed_files']=['src/a']
        facade=self.facade(second);event=self.reserve(facade,'b1');rev,_=self.store.read()
        with self.assertRaises(ValueError):facade.start(rev,'b1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        self.assertEqual(len(list((self.root/'journal').glob('*/request.json'))),1)

    def test_malformed_or_duplicate_check_metadata_cannot_succeed(self):
        facade=self.start();self.wait();result=facade.collect_result('a1')
        path=Path(result['checkpoint']['journal_directory'])/'checks.json'
        original=path.read_text();value=json.loads(original)
        value['checks'][0]['started_at']=True;value['checks'][0]['completed_at']=['not-a-timestamp']
        path.write_text(json.dumps(value));self.assertEqual(facade.collect_result('a1')['status'],'unknown')
        path.write_text('{"schema":"bad",'+original[1:])
        self.assertEqual(facade.collect_result('a1')['status'],'unknown')

    def test_zero_exit_without_provider_terminal_is_unknown(self):
        self.contract['required_tests']=[['python3','-c','assert 2+2 == 4']]
        self.cli.write_text('#!/usr/bin/python3\nprint("{\\"type\\":\\"turn.started\\"}")\n')
        facade=self.start();self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['exit_code'],0)

    def test_missing_executable_reports_real_failure(self):
        self.cli.unlink();facade=self.start();self.wait()
        result=facade.collect_result('a1');self.assertEqual(result['status'],'failed')
        self.assertIsNotNone(result['errors'])

    def test_contract_substitution_on_restart_cannot_read_another_result(self):
        facade=self.start();self.wait()
        altered=copy.deepcopy(self.contract);altered['objective']='Substituted instruction'
        with self.assertRaises(ValueError):self.facade(altered).collect_result('a1')

    def test_cancel_retains_original_status_and_no_replay(self):
        self.cli.write_text('#!/usr/bin/python3\nimport time\ntime.sleep(20)\n')
        facade=self.start()
        end=time.monotonic()+5
        while time.monotonic()<end and facade.get_status('a1')['status']=='starting':time.sleep(.02)
        facade.cancel_execution('a1');receipt=self.wait()
        self.assertEqual(receipt['status'],'cancelled')
        self.assertEqual(facade.collect_result('a1')['status'],'cancelled')


    def antigravity_facade(self):
        try:
            return worker.AgentWorker(self.rt,self.contract,str(self.cli),project_id='synthetic',
                repository='fixture/project',model_budget_binding=self.bs.binding,cli_variant='antigravity-cli')
        except TypeError as error:
            self.fail('explicit immutable native CLI variant is unavailable: '+str(error))

    def test_antigravity_original_reservation_restart_and_variant_substitution(self):
        self.contract['provider']='gemini';self.contract['review']['provider']='codex'
        default=self.facade();old_key=default.operation_key('a1')
        legacy_binding={'contract':default.contract_digest,'native_plan':default.plan_digest,
            'model_budget_binding':default.model_budget_binding_digest,'attempt_id':'a1'}
        legacy_key='sha256:'+hashlib.sha256(json.dumps(legacy_binding,sort_keys=True,
            separators=(',',':'),allow_nan=False).encode()).hexdigest()
        self.assertEqual(old_key,legacy_key)
        facade=self.antigravity_facade()
        self.assertNotEqual(facade.operation_key('a1'),old_key)
        explicit_default=worker.AgentWorker(self.rt,self.contract,str(self.cli),project_id='synthetic',
            repository='fixture/project',model_budget_binding=self.bs.binding,cli_variant=None)
        self.assertEqual(explicit_default.operation_key('a1'),old_key)
        self.cli.write_text("""#!/usr/bin/python3
import json,pathlib,sys
assert '--mode' in sys.argv and '--sandbox' in sys.argv
assert '--approval-mode' not in sys.argv
output=pathlib.Path('src/a');output.mkdir(parents=True,exist_ok=True)
(output/'fixture').write_text('synthetic only')
print(json.dumps({'event':'init','conversation_id':'agy-native-fixture'}))
print(json.dumps({'event':'result','result':{'conversation_id':'agy-native-fixture','status':'SUCCESS','response':'done','num_turns':1,'usage':{'input_tokens':4,'output_tokens':2}}}))
""")
        event=self.reserve(facade);rev,_=self.store.read()
        with self.assertRaises(ValueError):
            default.start(rev,'a1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        self.assertFalse(list((self.root/'journal').glob('*/request.json')))
        facade.start(rev,'a1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['cli_variant'],'antigravity-cli')
        self.assertEqual(result['session_id'],'agy-native-fixture')
        self.assertEqual(result['usage'],{'input_tokens':4,'output_tokens':2})
        self.assertEqual(result['test_evidence'][0]['exit_code'],0)
        with self.assertRaises(ValueError):default.collect_result('a1')
        facade.cli_variant=None
        with self.assertRaises(ValueError):facade.get_status('a1')
        restarted=self.antigravity_facade();self.assertEqual(restarted.collect_result('a1'),result)
        rev,_=self.store.read()
        with self.assertRaises(ValueError):
            restarted.start(rev,'a1',reservation_token=event['event_id'],model_budget_store=self.bs,reservation_event=event)
        self.assertEqual(len(list((self.root/'journal').glob('*/launch.lock'))),1)
        self.assertEqual(self.store.read()[1]['tasks'][0]['attempt_ids'],['a1'])

    def test_antigravity_independent_review_uses_terminal_response_and_clean_native_head(self):
        self.configure_review()
        self.contract['provider']='gemini';self.contract['review']['provider']='codex'
        self.contract['review_of']['developer_provider']='codex'
        self.cli.write_text("""#!/usr/bin/python3
import json,sys
assert sys.argv[sys.argv.index('--mode')+1]=='plan'
assert 'synthetic proposal' in sys.argv[-1]
print(json.dumps({'event':'init','conversation_id':'agy-review-fixture'}))
print(json.dumps({'event':'step_update','step_update':{'conversation_id':'agy-review-fixture','text_delta':'Working'}}))
print(json.dumps({'event':'result','result':{'conversation_id':'agy-review-fixture','status':'SUCCESS','response':'{\"verdict\":\"approved\",\"findings\":[]}','num_turns':1}}))
""")
        facade=self.start(self.antigravity_facade());self.wait();result=facade.collect_result('a1')
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['review'],{'verdict':'approved','findings':[]})
        self.assertEqual(result['observed_head_sha'],self.contract['review_of']['head_sha'])
        self.assertEqual(result['test_evidence'],[])


class ReviewVerdictTests(unittest.TestCase):
    def test_duplicate_inner_verdict_cannot_approve(self):
        from agent_worker import _review_verdict
        value=_review_verdict('{"verdict":"changes_requested","verdict":"approved","findings":[]}')
        self.assertEqual(value['verdict'],'blocked')

    def test_deeply_nested_review_is_blocked_without_aborting_observation(self):
        from agent_worker import _review_verdict
        value=_review_verdict('['*10000+'0'+']'*10000)
        self.assertEqual(value['verdict'],'blocked')

if __name__=='__main__':unittest.main()
