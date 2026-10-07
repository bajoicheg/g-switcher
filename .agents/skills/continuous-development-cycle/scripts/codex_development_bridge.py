"""Parent-owned admission evidence and Cloud report adapter to existing handoff.

Pure validation does not grant a submission, clear a guard, refund a budget,
publish an artifact, or replace the live caller authority callback.
"""
from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import re
import subprocess
import budget
import execution_lease_v2 as lease
import managed_executor_pool as pool
from managed_executor_handoff import validate_handoff, resolve_artifact, publication_plan
from codex_cloud_development import ContractError, validate_development_request
from parallel_task_planner import portable_path_key
from git_object_integrity import git_object_environment

CHECKS={'git_native','coordination_cas','submit','observe','diff_export','validation_report','provider_quiescence'}
ADMISSION={'lease_record','owner_id','generation','invocation_id','at_utc','ledger','reservation','pool_plan','pool_state','task_id','evidence_refs'}
REPORT={'schema','task_id','provider_attempt','operation_key','attempt_id','repository','environment_id','base_sha','head_before','changed_paths','checks','evidence_refs'}
CONTEXT={'pool_id','change_id','task_id','attempt_id','parent_invocation_id','executor_id','assigned_branch','publication_repository','publication_remote_id'}

def _refs(refs):
    if not isinstance(refs,list) or not refs or any(not isinstance(r,str) or not r.strip() for r in refs) or len(refs)!=len(set(refs)):raise ContractError('nonempty unique evidence references required')

def admit_development(request,*,capability_receipt,admission):
    """Validate trusted parent snapshots; caller must still refresh them live.

A worker boolean is not accepted. The parent reads these actual snapshots via
existing runtime/store APIs and supplies their durable evidence references.
"""
    r=validate_development_request(request)
    try:
        cap=capability_receipt
        if not isinstance(cap,dict) or cap.get('schema')!='cdc-codex-controller-capabilities/v1' or cap.get('qualified') is not True or set(cap.get('checks',{}))!=CHECKS:raise ContractError('qualified capability receipt required')
        if cap.get('verdict')!='qualified' or cap.get('cli_version')!='0.160.0':raise ContractError('qualified supported CLI receipt required')
        for field in ('repository','environment_id','environment_label'):
            if cap.get(field)!=r[field]:raise ContractError('capability identity mismatch: '+field)
        for check in cap['checks'].values():
            if check.get('status')!='passed':raise ContractError('capability check not passed')
            _refs(check.get('evidence_refs'))
        if not isinstance(admission,dict) or set(admission)!=ADMISSION:raise ContractError('existing-runtime admission evidence required')
        a=admission;_refs(a['evidence_refs'])
        if r['budget_ref'] not in a['evidence_refs']:raise ContractError('budget revision evidence missing')
        lr=a['lease_record'];lease.validate(lr)
        if lr['repository']!=r['repository'] or lr['source_ref']!='refs/heads/main':raise ContractError('lease source/repository mismatch')
        lease.check_record(lr,a['owner_id'],a['generation'],a['invocation_id'],a['at_utc'],action='product_write')
        event=a['reservation'];decision=budget.decide(a['ledger'],event)
        if not decision['allow_reservation'] or not decision['already_recorded']:raise ContractError('durably accepted budget reservation required')
        if event['operation_key']!=r['operation_key'] or event['attempt_id']!=r['attempt_id'] or event['kind']!='compute_start':raise ContractError('reservation binding mismatch')
        # Terminal/unknown outcomes never restore the same submission authority.
        outcomes=[e for e in a['ledger']['events'] if e['type']=='outcome' and e['reservation_id']==event['event_id']]
        if outcomes:raise ContractError('reservation has observed outcome; reconcile only')
        plan=a['pool_plan'];state=a['pool_state'];pool.validate_state(plan,state)
        tasks=[t for t in plan['tasks'] if t['id']==a['task_id']]
        rows=[t for t in state['tasks'] if t['id']==a['task_id']]
        if len(tasks)!=1 or len(rows)!=1 or tasks[0]['role']!='writer' or rows[0]['status']!='planned' or a['task_id'] not in pool.ready_task_ids(plan,state):raise ContractError('free ready writer slot required')
        if plan['base_sha']!=r['base_sha'] or tasks[0]['branch']!=r['source_branch']:raise ContractError('writer base/branch mismatch')
        if not set(map(portable_path_key,r['allowed_paths'])).issubset(set(map(portable_path_key,tasks[0]['write_paths']))):raise ContractError('writer scope mismatch')
        return r
    except (ValueError,TypeError,KeyError) as exc:raise ContractError(str(exc)) from exc

def build_development_handoff(request,exported,report,*,context,evidence_root):
    r=validate_development_request(request)
    try:
        if not isinstance(report,dict) or set(report)!=REPORT or report['schema']!='codex-cloud-development-report/v1':raise ContractError('observed report fields/schema mismatch')
        if not isinstance(context,dict) or set(context)!=CONTEXT:raise ContractError('managed identity context required')
        if set(exported)!={'task_id','provider_attempt','base_sha','artifact_ref'}:raise ContractError('official export fields mismatch')
        for key in ('task_id','provider_attempt','base_sha'):
            if report[key]!=exported[key]:raise ContractError('report/export mismatch: '+key)
        if type(report['provider_attempt']) is not int or report['provider_attempt']!=1:raise ContractError('exact provider attempt 1 required')
        for key in ('operation_key','attempt_id','repository','environment_id','base_sha'):
            if report[key]!=r[key]:raise ContractError('observed report binding mismatch: '+key)
        if report['head_before']!=r['base_sha']:raise ContractError('observed worker base mismatch')
        if context['attempt_id']!=r['attempt_id'] or context['assigned_branch']!=r['source_branch'] or context['publication_repository']!=r['repository']:raise ContractError('handoff identity mismatch')
        changed=report['changed_paths']
        if not isinstance(changed,list) or not changed:raise ContractError('observed changed paths required')
        allowed=set(map(portable_path_key,r['allowed_paths']));actual=list(map(portable_path_key,changed))
        if len(actual)!=len(set(actual)) or not set(actual).issubset(allowed):raise ContractError('report scope escape')
        checks=report['checks']
        if not isinstance(checks,list) or len(checks)!=len(r['checks']):raise ContractError('observed checks incomplete')
        for planned,observed in zip(r['checks'],checks):
            if not isinstance(observed,dict) or set(observed)!={'id','argv','exit_code','test_count','log_sha256'}:raise ContractError('complete command/log evidence required')
            if observed['id']!=planned['id'] or observed['argv']!=planned['argv']:raise ContractError('observed command mismatch')
            if type(observed['exit_code']) is not int or observed['exit_code']!=0:raise ContractError('check failed or NOT_RUN')
            if not isinstance(observed['log_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',observed['log_sha256']):raise ContractError('complete log digest required')
            count=observed['test_count'];minimum=planned['minimum_test_count']
            if count is not None and (type(count) is not int or count<0):raise ContractError('test count invalid')
            if minimum is not None and (count is None or count<minimum):raise ContractError('minimum test count not observed')
        _refs(report['evidence_refs'])
        artifact=exported['artifact_ref']
        if set(artifact)!={'path','sha256','format'} or artifact['format']!='unified_diff':raise ContractError('official unified diff artifact required')
        root=Path(evidence_root).resolve();target=Path(artifact['path'])
        if not target.is_absolute():target=root/target
        target=target.resolve();relative=target.relative_to(root).as_posix()
        digest=artifact['sha256']
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ContractError('export digest invalid')
        h={'schema':'managed-executor-handoff/v1',**copy.deepcopy(context),'base_sha':r['base_sha'],'transport':'content_artifact','source_result_commit':None,'direct_result_commit':None,'artifact_ref':{'path':relative,'sha256':'sha256:'+digest,'format':'unified_diff'},'changed_paths':copy.deepcopy(changed),'evidence_refs':copy.deepcopy(report['evidence_refs'])}
        validate_handoff(h);payload=resolve_artifact(h,root)
        # Git parses quoting, binary patches and renames. Both numstat paths and
        # raw-diff validation remain untrusted until existing integrator proof.
        parsed=subprocess.run(['git','apply','--numstat','-z','--recount','-'],env=git_object_environment(),input=payload,capture_output=True,timeout=15)
        if parsed.returncode:raise ContractError('invalid official diff')
        names=[]
        for record in parsed.stdout.split(b'\0'):
            if not record:continue
            fields=record.split(b'\t',2)
            if len(fields)!=3 or not fields[2]:raise ContractError('unsupported or ambiguous patch path')
            names.append(portable_path_key(fields[2].decode('utf8')))
        if not names or len(names)!=len(set(names)) or set(names)!=set(actual):raise ContractError('actual patch scope differs from observed report')
        publication_plan(h,root)
        return h
    except (ValueError,TypeError,KeyError,OSError,UnicodeError,subprocess.SubprocessError) as exc:raise ContractError(str(exc)) from exc
