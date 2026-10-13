import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import codex_cloud_cli as cloud

KEY='sha256:'+'a'*64
TASK='task_e_'+'b'*32
REQUEST={'schema':'codex-cloud-cli-request/v1','operation_key':KEY,'attempt_id':'compute-a1','repository':'test/project','candidate_sha':'c'*40,'environment_id':'d'*32,'environment_label':'test-env','source_branch':'cdc/candidate','checks':[{'id':'suite','argv':['python','-B','-m','unittest','discover'],'minimum_test_count':4}]}

class Runner:
    def __init__(self):self.calls=[];self.exec_error=False;self.pages=[{'tasks':[],'cursor':None}]
    def __call__(self,argv,**kwargs):
        self.calls.append(argv)
        if argv[2]=='exec':
            if self.exec_error:raise subprocess.TimeoutExpired(argv,1)
            return subprocess.CompletedProcess(argv,0,'https://chatgpt.com/codex/tasks/'+TASK,'')
        if argv[2]=='status':return subprocess.CompletedProcess(argv,0,'[READY] Task','')
        return subprocess.CompletedProcess(argv,0,json.dumps(self.pages.pop(0)),'')

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.runner=Runner();self.adapter=cloud.CodexCloudCLI(self.tmp.name,runner=self.runner)
    def submit(self):return self.adapter.submit(copy.deepcopy(REQUEST),launch_authorized=lambda:None)
    def report(self):
        return {'schema':'codex-cloud-cli-report/v1','task_id':TASK,**{k:REQUEST[k] for k in ('operation_key','attempt_id','repository','environment_id','environment_label')},'head_before':REQUEST['candidate_sha'],'head_after':REQUEST['candidate_sha'],'clean_before':True,'clean_after':True,'checks':[{'id':'suite','argv':REQUEST['checks'][0]['argv'],'exit_code':0,'test_count':4,'log_sha256':'e'*64}]}
    def task(self,**overrides):
        return {'id':TASK,'title':'CDC '+KEY+' compute-a1','environment_id':None,'environment_label':'test-env','status':'ready',**overrides}
    def test_submit_once_across_reconnect(self):
        self.submit();cloud.CodexCloudCLI(self.tmp.name,runner=self.runner).submit(REQUEST,launch_authorized=lambda:self.fail('repeated authorization'))
        self.assertEqual(sum(a[2]=='exec' for a in self.runner.calls),1)
        self.assertEqual(self.runner.calls[0][1:9],['cloud','exec','--env',REQUEST['environment_id'],'--branch','cdc/candidate','--attempts','1'])
    def test_gate_exception_persists_before_send_cancellation_without_cli_call(self):
        def gate():raise AssertionError('saved environment became stale')
        try:
            state=self.adapter.submit(REQUEST,launch_authorized=gate)
        except AssertionError:
            self.fail('pre-dispatch gate escaped without recording cancellation')
        self.assertEqual(state['state'],'not_submitted')
        self.assertEqual(state['dispatch']['state'],'cancelled_before_send')
        self.assertFalse(state['validation_passed'])
        self.assertIsNone(state['task_id'])
        self.assertFalse(self.runner.calls)
        recovered=cloud.CodexCloudCLI(self.tmp.name,runner=self.runner)
        self.assertEqual(recovered.observe(KEY),state)
        self.assertEqual(recovered.submit(REQUEST,launch_authorized=lambda:self.fail('replayed gate')),state)
        self.assertFalse(self.runner.calls)
    def test_provider_boundary_is_durable_before_runner_and_lost_reply_is_not_cancelled(self):
        def runner(argv,**kwargs):
            state=json.loads(self.adapter._path(KEY).read_text())
            self.assertEqual(state.get('dispatch',{}).get('state'),'started')
            raise subprocess.TimeoutExpired(argv,1)
        self.adapter.runner=runner
        state=self.submit()
        self.assertEqual(state['state'],'unknown')
        self.assertEqual(state['dispatch']['state'],'started')
    def test_cancelled_journal_cannot_hide_a_started_dispatch_or_task(self):
        def gate():raise ValueError('ownership lost')
        state=self.adapter.submit(REQUEST,launch_authorized=gate)
        self.assertEqual(state['state'],'not_submitted')
        for change in ({'task_id':TASK},{'dispatch':{'state':'started'}},{'validation_passed':True}):
            bad=copy.deepcopy(state);bad.update(change)
            self.adapter._path(KEY).write_text(json.dumps(bad))
            with self.subTest(change=change),self.assertRaises(ValueError):self.adapter.observe(KEY)
    def test_cli_diagnostics_stay_outside_candidate_checkout(self):
        candidate=Path(self.tmp.name)/'candidate';candidate.mkdir()
        executable=Path(self.tmp.name)/'diagnostic-cli'
        executable.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nPath("error.log").write_text("CLI diagnostic")\nprint("https://chatgpt.com/codex/tasks/task_e_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" if sys.argv[2]=="exec" else "[READY] Task")\n')
        executable.chmod(0o755)
        def ambient_runner(argv,**kwargs):
            kwargs.setdefault('cwd',candidate)
            return subprocess.run(argv,**kwargs)
        adapter=cloud.CodexCloudCLI(Path(self.tmp.name)/'journal',executable=str(executable),runner=ambient_runner)
        adapter.submit(REQUEST,launch_authorized=lambda:None)
        self.assertEqual(adapter.observe(KEY)['state'],'waiting_report')
        self.assertFalse((candidate/'error.log').exists())
        self.assertTrue((adapter.root/'error.log').exists())
    def test_missing_live_callback_never_dispatches(self):
        with self.assertRaises(ValueError):self.adapter.submit(REQUEST,launch_authorized=True)
        self.assertFalse(self.runner.calls)
    def test_conflicting_attempt_context_rejected(self):
        self.submit();other=copy.deepcopy(REQUEST);other['candidate_sha']='f'*40
        with self.assertRaises(ValueError):self.adapter.submit(other,launch_authorized=lambda:None)
    def test_lost_reply_remains_unknown_and_never_restarts(self):
        self.runner.exec_error=True;self.assertEqual(self.submit()['state'],'unknown')
        self.runner.pages=[{'tasks':[],'cursor':None}]
        self.adapter.observe(KEY);self.adapter.submit(REQUEST,launch_authorized=lambda:self.fail('repeat'))
        self.assertEqual(sum(a[2]=='exec' for a in self.runner.calls),1)
    def test_pagination_locally_filters_environment_and_recovers_exact_marker(self):
        self.runner.exec_error=True;self.submit()
        self.runner.pages=[{'tasks':[self.task(id='task_e_'+'9'*32,environment_label='other')],'cursor':'page2'},{'tasks':[self.task()],'cursor':None}]
        observed=self.adapter.observe(KEY)
        self.assertEqual(observed['task_id'],TASK);self.assertEqual(observed['state'],'waiting_report')
        self.assertIn('--cursor',self.runner.calls[-2])
    def test_repeated_cursor_stays_unknown(self):
        self.runner.exec_error=True;self.submit()
        self.runner.pages=[{'tasks':[self.task()],'cursor':'loop'},{'tasks':[],'cursor':'loop'}]
        self.assertEqual(self.adapter.observe(KEY)['state'],'unknown')
    def test_ambiguous_marker_stays_unknown(self):
        self.runner.exec_error=True;self.submit();self.runner.pages=[{'tasks':[self.task(),self.task(id='task_e_'+'f'*32)],'cursor':None}]
        self.assertEqual(self.adapter.observe(KEY)['state'],'unknown')
    def test_unidentified_matching_marker_keeps_recovery_unknown(self):
        for identity in ({}, {'environment_id': None, 'environment_label': None},
                         {'environment_id': None, 'environment_label': ''},
                         {'environment_id': 7, 'environment_label': 'test-env'}):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as directory:
                runner=Runner();runner.exec_error=True
                adapter=cloud.CodexCloudCLI(directory,runner=runner)
                adapter.submit(REQUEST,launch_authorized=lambda:None)
                unidentified={'id':'task_e_'+'f'*32,'title':'CDC '+KEY+' compute-a1',**identity}
                runner.pages=[{'tasks':[self.task()], 'cursor':'page2'},
                              {'tasks':[unidentified], 'cursor':None}]
                observed=adapter.observe(KEY)
                self.assertEqual(observed['state'],'unknown')
                self.assertIsNone(observed['task_id'])
                self.assertFalse(any(call[2]=='status' for call in runner.calls))
                adapter.submit(REQUEST,launch_authorized=lambda:self.fail('repeated launch'))
                self.assertEqual(sum(call[2]=='exec' for call in runner.calls),1)
    def test_ready_without_report_is_not_pass(self):
        self.submit();observed=self.adapter.observe(KEY)
        self.assertEqual(observed['state'],'waiting_report');self.assertFalse(observed['validation_passed'])
    def test_corrupt_journal_cannot_claim_success_without_report(self):
        self.submit();path=self.adapter._path(KEY);state=json.loads(path.read_text())
        state.update(state='succeeded',validation_passed=True);path.write_text(json.dumps(state))
        with self.assertRaises(ValueError):self.adapter.observe(KEY)
        self.assertEqual(sum(a[2]=='exec' for a in self.runner.calls),1)
    def test_corrupt_persisted_report_cannot_pass_after_reconnect(self):
        self.submit();self.adapter.observe(KEY);self.adapter.ingest_report(KEY,self.report(),'provider:report/1')
        path=self.adapter._path(KEY);original=json.loads(path.read_text())
        for update_digest in (False,True):
            state=copy.deepcopy(original);state['report']['head_after']='f'*40
            if update_digest:state['report_digest']=cloud._digest(state['report'])
            path.write_text(json.dumps(state))
            with self.assertRaises(ValueError):cloud.CodexCloudCLI(self.tmp.name,runner=self.runner).observe(KEY)
    def test_exact_report_proves_success(self):
        self.submit();self.adapter.observe(KEY)
        result=self.adapter.ingest_report(KEY,self.report(),'provider:report/1')
        self.assertEqual(result['state'],'succeeded');self.assertTrue(result['validation_passed'])
    def test_failed_check_report_proves_failure(self):
        self.submit();self.adapter.observe(KEY);report=self.report();report['checks'][0]['exit_code']=1
        self.assertEqual(self.adapter.ingest_report(KEY,report,'provider:report/1')['state'],'failed')
    def test_bound_source_or_cleanliness_failure_is_durable_and_immutable(self):
        for field,value in [('head_before','f'*40),('head_after','f'*40),('clean_before',False),('clean_after',False)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as directory:
                adapter=cloud.CodexCloudCLI(directory,runner=self.runner)
                adapter.submit(REQUEST,launch_authorized=lambda:None);adapter.observe(KEY)
                report=self.report();report[field]=value
                result=adapter.ingest_report(KEY,report,'provider:report/1')
                self.assertEqual(result['state'],'failed');self.assertFalse(result['validation_passed'])
                recovered=cloud.CodexCloudCLI(directory,runner=self.runner).observe(KEY)
                self.assertEqual(recovered['report'],report)
                with self.assertRaises(ValueError):adapter.ingest_report(KEY,self.report(),'provider:report/2')
    def test_bound_insufficient_test_coverage_is_recorded_failed(self):
        self.submit();self.adapter.observe(KEY);report=self.report();report['checks'][0]['test_count']=3
        result=self.adapter.ingest_report(KEY,report,'provider:report/1')
        self.assertEqual(result['state'],'failed');self.assertFalse(result['validation_passed'])
        self.assertEqual(self.adapter.observe(KEY)['report'],report)
    def test_bound_preflight_failure_can_report_checks_not_run(self):
        self.submit();self.adapter.observe(KEY);report=self.report()
        report.update(head_before='f'*40,head_after='f'*40,checks=[])
        result=self.adapter.ingest_report(KEY,report,'provider:report/1')
        self.assertEqual(result['state'],'failed');self.assertEqual(result['report']['checks'],[])
        self.assertFalse(cloud.CodexCloudCLI(self.tmp.name,runner=self.runner).observe(KEY)['validation_passed'])
    def test_identity_preflight_not_run_is_durable_with_matching_clean_source(self):
        self.submit();self.adapter.observe(KEY);report=self.report()
        report.update(result='NOT_RUN',checks=[],repository_identity_status='MISMATCH',
                      repository_identity_detail="error: No such remote 'origin'")
        result=self.adapter.ingest_report(KEY,report,'provider:actual-notrun/1')
        self.assertEqual(result['state'],'failed');self.assertFalse(result['validation_passed'])
        recovered=cloud.CodexCloudCLI(self.tmp.name,runner=self.runner).observe(KEY)
        self.assertEqual(recovered['report'],report)
        self.assertEqual(recovered['state'],'failed')
        with self.assertRaises(ValueError):
            self.adapter.ingest_report(KEY,self.report(),'provider:report/2')
    def test_not_run_cannot_include_successful_command_evidence(self):
        self.submit();self.adapter.observe(KEY);report=self.report();report['result']='NOT_RUN'
        with self.assertRaises(ValueError):
            self.adapter.ingest_report(KEY,report,'provider:contradictory-notrun/1')
        self.assertEqual(self.adapter.observe(KEY)['state'],'waiting_report')
    def test_explicit_identity_mismatch_cannot_pass_matching_checks(self):
        self.submit();self.adapter.observe(KEY);report=self.report()
        report['repository_identity_status']='MISMATCH'
        result=self.adapter.ingest_report(KEY,report,'provider:identity-failed/1')
        self.assertEqual(result['state'],'failed');self.assertFalse(result['validation_passed'])
    def test_report_mismatches_never_pass(self):
        self.submit();self.adapter.observe(KEY)
        changes=[('head_after','malformed'),('task_id','task_e_'+'f'*32),('environment_id','f'*32),('clean_after',1),('attempt_id','other'),('repository','other/repo')]
        for field,value in changes:
            with self.subTest(field=field):
                report=self.report();report[field]=value
                with self.assertRaises(ValueError):self.adapter.ingest_report(KEY,report,'provider:report/1')
        for change in ({'argv':['echo','pass']},{'log_sha256':'bad'},{'test_count':False},{'exit_code':False}):
            report=self.report();report['checks'][0].update(change)
            with self.assertRaises(ValueError):self.adapter.ingest_report(KEY,report,'provider:report/1')
    def test_report_requires_observed_provider_ready(self):
        self.submit()
        with self.assertRaises(ValueError):self.adapter.ingest_report(KEY,self.report(),'provider:report/1')
    def test_exact_report_replay_is_idempotent_but_changed_report_rejected(self):
        self.submit();self.adapter.observe(KEY);report=self.report();self.adapter.ingest_report(KEY,report,'provider:report/1')
        self.adapter.ingest_report(KEY,report,'provider:report/1');report['checks'][0]['exit_code']=1
        with self.assertRaises(ValueError):self.adapter.ingest_report(KEY,report,'provider:report/2')

if __name__=='__main__':unittest.main()
