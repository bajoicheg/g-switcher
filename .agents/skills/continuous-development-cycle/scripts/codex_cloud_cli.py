"""Supported Codex Cloud CLI transport; callers retain lease/intent/budget authority.

READY only means waiting_report. No credential files, private API or diff apply.
The live launch_authorized callback must recheck the caller's durable one-use
grant, exact guard, reserved budget and source HEAD immediately before exec.
Journal recovery never recreates this callback or authorizes another dispatch.
"""
from __future__ import annotations
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

KEY=re.compile(r'^sha256:[0-9a-f]{64}$')
TASK=re.compile(r'^task_[A-Za-z0-9_]+$')
HEX=re.compile(r'^[0-9a-f]{40}$')
REQUEST_FIELDS={'schema','operation_key','attempt_id','repository','candidate_sha','environment_id','environment_label','source_branch','checks'}

def _text(value):
    if not isinstance(value,str) or not value or value!=value.strip() or '\0' in value:
        raise ValueError('Cloud binding must be nonempty trimmed text')
    return value

def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def _digest(value):return hashlib.sha256(_canonical(value).encode()).hexdigest()
def _utc():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def validate_request(request):
    if not isinstance(request,dict) or set(request)!=REQUEST_FIELDS or request['schema']!='codex-cloud-cli-request/v1':
        raise ValueError('Cloud request fields/schema mismatch')
    if not KEY.fullmatch(request['operation_key']) or not HEX.fullmatch(request['candidate_sha']):
        raise ValueError('Cloud operation/source binding invalid')
    for field in ('environment_id','environment_label','attempt_id','repository','source_branch'):_text(request[field])
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',request['repository']):raise ValueError('Cloud repository binding invalid')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',request['source_branch']) or '..' in request['source_branch']:
        raise ValueError('Cloud branch binding invalid')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',request['attempt_id']):raise ValueError('Cloud attempt binding invalid')
    checks=request['checks']
    if not isinstance(checks,list) or not checks:raise ValueError('Cloud checks required')
    ids=[]
    for check in checks:
        if not isinstance(check,dict) or set(check)!={'id','argv','minimum_test_count'}:raise ValueError('Cloud check fields invalid')
        ids.append(_text(check['id']))
        if not isinstance(check['argv'],list) or not check['argv']:raise ValueError('Cloud command array required')
        for arg in check['argv']:_text(arg)
        count=check['minimum_test_count']
        if count is not None and (type(count) is not int or count<1):raise ValueError('Cloud minimum test count invalid')
    if len(ids)!=len(set(ids)):raise ValueError('Cloud check IDs must be unique')
    return request

def prompt(request):
    validate_request(request)
    return ('CDC '+request['operation_key']+' '+request['attempt_id']+'\n'
            'Use this first line as the task title, including the exact operation and attempt.\n'
            'COMPUTE_ONLY: execute this exact read-only check plan once.\n'+_canonical(request)+'\n'
            'The submitting host independently verifies the canonical repository/environment association and source branch SHA. '
            'Provider checkouts may omit Git remotes; absent origin alone is not an identity mismatch. '
            'Verify any available repository identity without editing Git configuration; reject a conflicting configured remote. '
            'Report whether identity is independently observed or host-bound; never describe a supplied expected value as observed. '
            'Verify exact candidate_sha and clean checkout before running. '
            'Stop on mismatch; return typed observed SHA/cleanliness and checks: [] for NOT_RUN, without invented exit codes or logs. '
            'Run only the supplied argv arrays, separately, capturing stdout/stderr outside '
            'the repository, exit codes, actual unittest counts and SHA256 of each complete log. '
            'Do not edit, fix, commit, push, apply diffs, delegate, acquire a lease, install dependencies or launch CI. '
            'After checks verify unchanged exact HEAD and clean checkout. Platform gates are NOT_RUN. '
            'Return JSON schema codex-cloud-cli-report/v1 with actual task_id (if unavailable, explicitly report '
            'that; the observing host binds the task ID from CLI), operation_key, attempt_id, repository, '
            'environment_id, environment_label, head_before, head_after, clean_before, clean_after, and checks. '
            'Each check includes id, exact argv, exit_code, test_count (null for non-test commands), and log_sha256. '
            'Use observed facts; never infer PASS from provider READY. Include output tails separately.')

def _validate_report(request, task_id, report):
    if not isinstance(report,dict) or report.get('schema')!='codex-cloud-cli-report/v1':raise ValueError('Cloud report schema invalid')
    for key in ('operation_key','attempt_id','repository','environment_id','environment_label'):
        if report.get(key)!=request[key]:raise ValueError('Cloud report binding mismatch: '+key)
    if report.get('task_id')!=task_id:raise ValueError('Cloud report task mismatch')
    for key in ('head_before','head_after'):
        if not isinstance(report.get(key),str) or not HEX.fullmatch(report[key]):raise ValueError('Cloud report source SHA invalid')
    if any(type(report.get(key)) is not bool for key in ('clean_before','clean_after')):
        raise ValueError('Cloud report cleanliness observation invalid')
    passed=(all(report[key]==request['candidate_sha'] for key in ('head_before','head_after'))
            and report['clean_before'] and report['clean_after'])
    checks=report.get('checks')
    if report.get('result')=='NOT_RUN':
        if checks!=[]:raise ValueError('Cloud NOT_RUN contradicts command evidence')
        return False  # A bound setup/identity preflight may fail on an unchanged clean SHA.
    passed=passed and report.get('repository_identity_status')!='MISMATCH'
    if not passed and checks==[]:return False  # Exact-task preflight failed; commands NOT_RUN.
    if not isinstance(checks,list) or len(checks)!=len(request['checks']):raise ValueError('Cloud report checks incomplete')
    for planned,actual in zip(request['checks'],checks):
        if not isinstance(actual,dict) or actual.get('id')!=planned['id'] or actual.get('argv')!=planned['argv']:raise ValueError('Cloud report command mismatch')
        if type(actual.get('exit_code')) is not int:raise ValueError('Cloud report exit code missing/invalid')
        if not isinstance(actual.get('log_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',actual['log_sha256']):raise ValueError('Cloud report log digest invalid')
        count=actual.get('test_count');minimum=planned['minimum_test_count']
        if count is not None and (type(count) is not int or count<0):raise ValueError('Cloud report test count invalid')
        if minimum is not None and count is None:raise ValueError('Cloud report test count missing')
        passed=passed and actual['exit_code']==0 and (minimum is None or count>=minimum)
    return passed

class CodexCloudCLI:
    def __init__(self,journal_root,executable='codex',runner=None,max_pages=1000):
        self.root=Path(journal_root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.executable=_text(executable);self.runner=runner or subprocess.run
        if type(max_pages) is not int or max_pages<1:raise ValueError('Cloud page bound invalid')
        self.max_pages=max_pages
    def _path(self,key):
        if not isinstance(key,str) or not KEY.fullmatch(key):raise ValueError('Cloud operation key invalid')
        return self.root/(key.removeprefix('sha256:')+'.json')
    @contextmanager
    def _locked(self,key):
        path=self._path(key)
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);yield path
    def snapshot(self,operation_key):
        """Read the validated existing journal without a provider call.

        None means only this exact local journal is absent, not complete
        provider inventory or permission to submit. Corruption remains an error.
        Subclasses retain their own journal validator via self._load.
        """
        with self._locked(operation_key) as path:
            return copy.deepcopy(self._load(path)) if path.exists() else None

    def _save(self,path,state):
        tmp=path.with_suffix('.'+str(os.getpid())+'.tmp')
        with tmp.open('w') as stream:
            stream.write(_canonical(state)+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    def _load(self,path):
        state=json.loads(path.read_text())
        if not isinstance(state,dict) or state.get('schema')!='codex-cloud-cli-journal/v1':
            raise ValueError('Cloud journal schema invalid')
        validate_request(state.get('request'))
        if state.get('state') not in {'submitting','submitted','unknown','running','waiting_report','succeeded','failed','not_submitted'} or type(state.get('validation_passed')) is not bool:
            raise ValueError('Cloud journal state invalid')
        if state.get('request_digest')!=_digest(state['request']) or self._path(state['request']['operation_key'])!=path:
            raise ValueError('Cloud journal binding mismatch')
        task=state.get('task_id')
        if task is not None and (not isinstance(task,str) or not TASK.fullmatch(task)):
            raise ValueError('Cloud journal task invalid')
        if state['state'] in {'submitted','running','waiting_report','succeeded','failed'} and task is None:
            raise ValueError('Cloud journal state requires exact task')
        dispatch=state.get('dispatch')
        if dispatch is not None:
            if (not isinstance(dispatch,dict) or set(dispatch)!={'state','at_utc','request_digest'}
                    or dispatch['state'] not in {'pre_dispatch','started','cancelled_before_send'}
                    or dispatch['request_digest']!=state['request_digest']):
                raise ValueError('Cloud dispatch boundary binding invalid')
            stamp=dispatch['at_utc']
            if not isinstance(stamp,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z',stamp):
                raise ValueError('Cloud dispatch boundary timestamp invalid')
            if datetime.fromisoformat(stamp.replace('Z','+00:00')) < datetime.fromisoformat(state['attempted_at_utc'].replace('Z','+00:00')):
                raise ValueError('Cloud dispatch boundary predates attempt')
            if (dispatch['state']=='cancelled_before_send') != (state['state']=='not_submitted'):
                raise ValueError('Cloud cancellation contradicts dispatch state')
        if state['state']=='not_submitted' and (dispatch is None or task is not None
                or state.get('report') is not None or state['validation_passed']
                or state.get('reason')!='gate_rejected_before_send'):
            raise ValueError('Cloud cancellation requires durable taskless before-send barrier')
        report=state.get('report')
        if report is not None:
            _text(state.get('evidence_ref'))
            if state.get('report_digest')!=_digest(report) or state.get('provider_status')!='READY':
                raise ValueError('Cloud journal report evidence invalid')
            passed=_validate_report(state['request'],task,report)
            if state['state']!=('succeeded' if passed else 'failed') or state['validation_passed']!=passed:
                raise ValueError('Cloud journal conclusion differs from report')
        elif state['state']=='succeeded' or state['validation_passed']:
            raise ValueError('Cloud journal success requires validated report')
        elif state['state']=='failed' and (state.get('reason')!='provider_error' or state.get('provider_status')!='ERROR'):
            raise ValueError('Cloud journal failure requires report or provider error')
        return state
    def _run(self,args,timeout=60):
        return self.runner([self.executable,'cloud',*args],cwd=self.root,capture_output=True,text=True,timeout=timeout)
    def submit(self,request,*,launch_authorized):
        validate_request(request)
        with self._locked(request['operation_key']) as path:
            if path.exists():
                state=self._load(path)
                if state['request']!=request:raise ValueError('Cloud repeated operation has conflicting immutable context')
                return copy.deepcopy(state)
            if not callable(launch_authorized):raise ValueError('Cloud dispatch requires a live caller gate callback')
            state={'schema':'codex-cloud-cli-journal/v1','request':copy.deepcopy(request),'request_digest':_digest(request),
                   'state':'submitting','task_id':None,'validation_passed':False,'attempted_at_utc':_utc()}
            state['dispatch']={'state':'pre_dispatch','at_utc':state['attempted_at_utc'],'request_digest':state['request_digest']}
            self._save(path,state)
            try:
                launch_authorized()
            except Exception:
                # The host callback checks authority only. It must never dispatch
                # provider work itself. The runner boundary has not been entered.
                state.update(state='not_submitted',reason='gate_rejected_before_send')
                state['dispatch'].update(state='cancelled_before_send',at_utc=_utc())
                self._save(path,state)
                return copy.deepcopy(state)
            # Persist uncertainty before entering any caller-supplied runner: it
            # may send before raising, including from its own last-minute gate.
            state['dispatch'].update(state='started',at_utc=_utc())
            self._save(path,state)
            try:
                result=self._run(['exec','--env',request['environment_id'],'--branch',request['source_branch'],'--attempts','1',prompt(request)],120)
                matches=re.findall(r'https://chatgpt\.com/codex/tasks/(task_[A-Za-z0-9_]+)',result.stdout)
                if result.returncode!=0 or len(set(matches))!=1:raise ValueError('unconfirmed Cloud submission')
                state.update(state='submitted',task_id=matches[0])
            except Exception:
                state.update(state='unknown',reason='dispatch_reply_or_gate_unconfirmed')
            self._save(path,state);return copy.deepcopy(state)
    def _inventory(self,request):
        cursor=None;seen=set();tasks={}
        for _ in range(self.max_pages):
            args=['list','--json','--limit','20','--env',request['environment_id']]
            if cursor is not None:args+=['--cursor',cursor]
            result=self._run(args)
            if result.returncode!=0:raise ValueError('Cloud inventory unavailable')
            page=json.loads(result.stdout)
            if not isinstance(page,dict) or not isinstance(page.get('tasks'),list) or 'cursor' not in page:
                raise ValueError('Cloud inventory incomplete')
            for task in page['tasks']:
                if not isinstance(task,dict) or not isinstance(task.get('id'),str) or not TASK.fullmatch(task['id']):raise ValueError('Cloud task identity invalid')
                if task['id'] in tasks and tasks[task['id']]!=task:raise ValueError('Cloud inventory changed during pagination')
                tasks[task['id']]=task
            cursor=page['cursor']
            if cursor is None:return list(tasks.values())
            if not isinstance(cursor,str) or not cursor or cursor in seen:raise ValueError('Cloud inventory cursor invalid/repeated')
            seen.add(cursor)
        raise ValueError('Cloud inventory page bound exceeded; outcome remains unknown')
    def observe(self,operation_key):
        with self._locked(operation_key) as path:
            state=self._load(path);request=state['request']
            if state['state'] in {'succeeded','failed','not_submitted'}:return copy.deepcopy(state)
            try:
                if state['task_id'] is None:
                    rows=self._inventory(request)
                    exact=[]
                    for task in rows:
                        title=task.get('title','')
                        if not (isinstance(title,str)
                                and re.search(r'(?<!\S)'+re.escape(operation_key)+r'(?!\S)',title)
                                and re.search(r'(?<!\S)'+re.escape(request['attempt_id'])+r'(?!\S)',title)):
                            continue
                        env=task.get('environment_id')
                        if env is None:
                            label=task.get('environment_label')
                            _text(label)  # An unclassified marker could be a second task here.
                            same_environment=label==request['environment_label']
                        else:
                            _text(env)
                            same_environment=env==request['environment_id']
                        if same_environment:exact.append(task)
                    if len(exact)!=1:raise ValueError('Cloud recovery requires one exact provider task marker/environment')
                    state['task_id']=exact[0]['id']
                result=self._run(['status',state['task_id']])
                status=re.match(r'^\[(READY|PENDING|ERROR|APPLIED)\]',result.stdout.strip())
                if status is None:raise ValueError('Cloud status unrecognized')
                state.update(provider_status=status[1],observed_at_utc=_utc())
                if status[1]=='READY' and result.returncode==0:state['state']='waiting_report'
                elif status[1]=='PENDING':state['state']='running'
                elif status[1]=='ERROR':state.update(state='failed',reason='provider_error')
                else:raise ValueError('Cloud compute-only status is not usable')
            except (OSError,ValueError,KeyError,subprocess.SubprocessError):
                state.update(state='unknown',reason='provider_observation_incomplete')
            self._save(path,state);return copy.deepcopy(state)
    def ingest_report(self,operation_key,report,evidence_ref):
        _text(evidence_ref)
        with self._locked(operation_key) as path:
            state=self._load(path);request=state['request']
            if state.get('report') is not None:
                if state['report']!=report or state['evidence_ref']!=evidence_ref:raise ValueError('Cloud terminal report cannot be rewritten')
                return copy.deepcopy(state)
            if state['state']!='waiting_report':raise ValueError('Cloud report requires observed provider READY')
            passed=_validate_report(request,state['task_id'],report)
            state.update(state='succeeded' if passed else 'failed',validation_passed=passed,report=copy.deepcopy(report),evidence_ref=evidence_ref,report_digest=_digest(report))
            self._save(path,state);return copy.deepcopy(state)
