"""Isolated official Cloud development transport; no apply or publication authority.

The caller owns live lease, guard, budget and one-use grant verification. READY
is only waiting_result. Exported bytes remain untrusted until parent validation.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from codex_cloud_cli import CodexCloudCLI, KEY, HEX, TASK, _text, _digest, _utc, validate_request
from parallel_task_planner import portable_path_key

class ContractError(ValueError):
    pass

FIELDS={'schema','operation_key','attempt_id','repository','environment_id','environment_label','source_branch','base_sha','allowed_paths','acceptance_criteria','checks','budget_ref'}

def validate_development_request(request):
    try:
        if not isinstance(request,dict) or set(request)!=FIELDS or request['schema']!='codex-cloud-development-request/v1':
            raise ValueError('development request fields/schema mismatch')
        binding={k:request[k] for k in ('operation_key','attempt_id','repository','environment_id','environment_label','source_branch','checks')}
        binding.update(schema='codex-cloud-cli-request/v1',candidate_sha=request['base_sha'])
        validate_request(binding)
        _text(request['budget_ref'])
        paths=request['allowed_paths'];criteria=request['acceptance_criteria']
        if not isinstance(paths,list) or not paths or not isinstance(criteria,list) or not criteria:
            raise ValueError('nonempty development scope and acceptance criteria required')
        keys=[]
        for path in paths:
            _text(path);keys.append(portable_path_key(path))
        if len(keys)!=len(set(keys)):raise ValueError('duplicate portable scope path')
        for criterion in criteria:_text(criterion)
        # Return a detached value so mutable caller state cannot alter a binding.
        return copy.deepcopy(request)
    except (ValueError,TypeError,KeyError) as exc:
        raise ContractError(str(exc)) from exc

def prompt(request):
    validate_development_request(request)
    return ('CDC '+request['operation_key']+' '+request['attempt_id']+'\n'
        'Use that exact first line as the task title. DEVELOPMENT_ONLY, one attempt.\n'+json.dumps(request,sort_keys=True)+'\n'
        'Observe clean exact base_sha before changes. Reject conflicting repository identity or base; '
        'absent remote alone is not a mismatch. Never claim host-supplied identity as independently observed. '
        'Edit ONLY allowed_paths to satisfy acceptance_criteria. Do not edit other paths, commit, push, '
        'apply, open PR, run CI, install, change auth/network/settings, delegate, or acquire leases. '
        'Run only checks argv separately; capture complete logs outside repository and hash actual bytes. '
        'Return observed JSON schema codex-cloud-development-report/v1 with task_id, provider_attempt=1, '
        'operation_key, attempt_id, repository, environment_id, base_sha, head_before, '
        'changed_paths, checks and evidence_refs. Each check: id, argv, exit_code, test_count, log_sha256. '
        'Report unavailable observations explicitly; never invent commands, logs or PASS. '
        'Do not alter HEAD. Platform gates NOT_RUN. Provider READY is not validation.')

class CodexCloudDevelopment(CodexCloudCLI):
    """Shares durable filesystem/official inventory primitives, not compute policy."""
    def _load(self,path):
        state=json.loads(path.read_text())
        if not isinstance(state,dict) or state.get('schema')!='codex-cloud-development-journal/v1':raise ContractError('development journal schema invalid')
        r=validate_development_request(state.get('request'))
        if state.get('request_digest')!=_digest(r) or self._path(r['operation_key'])!=path:raise ContractError('development journal binding changed')
        if state.get('state') not in {'prepared','submitting','unknown','running','waiting_result','result_exported','failed'}:raise ContractError('development state invalid')
        task=state.get('task_id')
        if task is not None and (not isinstance(task,str) or not TASK.fullmatch(task)):raise ContractError('development task invalid')
        if state['state'] in {'running','waiting_result','result_exported'} and task is None:raise ContractError('development task missing')
        if state.get('dispatch') not in {'pre_dispatch','started','denied'}:raise ContractError('development dispatch state invalid')
        return state
    def submit(self,request,*,launch_authorized):
        request=validate_development_request(request)
        with self._locked(request['operation_key']) as path:
            if path.exists():
                state=self._load(path)
                if state['request']!=request:raise ContractError('immutable development context conflict')
                return copy.deepcopy(state)
            if not callable(launch_authorized):raise ContractError('live authority callback required')
            state={'schema':'codex-cloud-development-journal/v1','request':request,'request_digest':_digest(request),'state':'submitting','dispatch':'pre_dispatch','task_id':None,'attempted_at_utc':_utc()}
            self._save(path,state)
            try:launch_authorized()
            except Exception:
                state.update(state='failed',dispatch='denied',reason='gate_rejected_before_send');self._save(path,state);return copy.deepcopy(state)
            state.update(dispatch='started',dispatch_at_utc=_utc());self._save(path,state)
            try:
                result=self._run(['exec','--env',request['environment_id'],'--branch',request['source_branch'],'--attempts','1',prompt(request)],120)
                matches=set(re.findall(r'https://chatgpt\.com/codex/tasks/(task_[A-Za-z0-9_]+)',result.stdout))
                if result.returncode!=0 or len(matches)!=1:raise ContractError('unconfirmed development dispatch')
                state.update(state='running',task_id=matches.pop())
            except Exception:state.update(state='unknown',reason='dispatch_reply_unconfirmed')
            self._save(path,state);return copy.deepcopy(state)
    def observe(self,operation_key):
        with self._locked(operation_key) as path:
            state=self._load(path);r=state['request']
            if state['state'] in {'failed','result_exported'}:return copy.deepcopy(state)
            try:
                if state['task_id'] is None:
                    rows=self._inventory(r);exact=[]
                    for task in rows:
                        title=task.get('title','')
                        if not isinstance(title,str) or not all(re.search(r'(?<!\S)'+re.escape(v)+r'(?!\S)',title) for v in (operation_key,r['attempt_id'])):continue
                        env=task.get('environment_id');label=task.get('environment_label')
                        if env is None:
                            _text(label);same=label==r['environment_label']
                        else:
                            _text(env);same=env==r['environment_id']
                        if same:exact.append(task)
                    if len(exact)!=1:raise ContractError('one exact task/environment required')
                    state['task_id']=exact[0]['id']
                result=self._run(['status',state['task_id']]);status=re.match(r'^\[(READY|PENDING|ERROR)\]',result.stdout.strip())
                if status is None or result.returncode!=(0 if status[1]=='READY' else 1):raise ContractError('status unavailable')
                state.update(provider_status=status[1],observed_at_utc=_utc())
                if status[1]=='READY':state['state']='waiting_result'
                elif status[1]=='PENDING':state['state']='running'
                else:state.update(state='failed',reason='provider_error')
            except (OSError,ValueError,KeyError,subprocess.SubprocessError):state.update(state='unknown',reason='observation_incomplete')
            self._save(path,state);return copy.deepcopy(state)
    def export_diff(self,operation_key,*,evidence_root):
        with self._locked(operation_key) as path:
            state=self._load(path)
            if state['state']=='result_exported':
                exported=state['exported'];artifact=exported['artifact_ref'];data=Path(artifact['path']).read_bytes()
                if hashlib.sha256(data).hexdigest()!=artifact['sha256']:raise ContractError('exported evidence changed')
                return copy.deepcopy(exported)
            if state['state']!='waiting_result':raise ContractError('diff requires observed exact-task READY')
            result=self.runner([self.executable,'cloud','diff',state['task_id'],'--attempt','1'],cwd=self.root,capture_output=True,text=False,timeout=60)
            if result.returncode!=0 or not isinstance(result.stdout,bytes) or not result.stdout:raise ContractError('official diff unavailable')
            data=result.stdout;digest=hashlib.sha256(data).hexdigest();root=Path(evidence_root).resolve();root.mkdir(parents=True,exist_ok=True)
            target=root/(operation_key.removeprefix('sha256:')+'-attempt1-'+digest+'.diff')
            # Publish only a complete fsynced inode. A crash leaves at most an
            # orphan temp file, never a partial digest-named final artifact.
            fd,temp=tempfile.mkstemp(prefix='.diff-',suffix='.tmp',dir=root)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                try:os.link(temp,target,follow_symlinks=False)
                except FileExistsError:
                    if target.is_symlink() or target.read_bytes()!=data:raise ContractError('diff evidence collision')
                directory_fd=os.open(root,os.O_DIRECTORY)
                try:os.fsync(directory_fd)
                finally:os.close(directory_fd)
            finally:
                os.unlink(temp)
            exported={'task_id':state['task_id'],'provider_attempt':1,'base_sha':state['request']['base_sha'],'artifact_ref':{'path':str(target),'sha256':digest,'format':'unified_diff'}}
            state.update(state='result_exported',exported=exported);self._save(path,state);return copy.deepcopy(exported)
