#!/usr/bin/env python3
"""Owner disposition of UNKNOWN isolated create-only Git effects; never replay.

The controller must authenticate and persist/read back the referenced owner,
caller and physical-runtime evidence before calling. Parsing is not authority.
This administrative transition supplies no provider outcome or launch authority.
"""
from __future__ import annotations
import copy
import re
import operation_intent as op
import execution_lease_v2 as lease
from submission_recovery import _reference, _fresh, SHA

PILOT = re.compile(r'^refs/heads/pilot/[A-Za-z0-9][A-Za-z0-9._/-]*$')

def _validate_proof(proof, guard, repository, source_ref, release, at):
    op._object(proof, {'schema','lease_revision','lease_digest','guard_digest','repository',
        'source_ref','observed_at_utc','owner_decision','effect','runtime'}, 'retirement proof')
    if proof['schema'] != 'unknown-submission-retirement/v1':
        raise ValueError('unsupported retirement proof')
    if not isinstance(proof['lease_revision'],str) or not SHA.fullmatch(proof['lease_revision']):
        raise ValueError('immutable current lease revision required')
    op._digest(proof['lease_digest'],'retirement lease digest')
    if (proof['guard_digest'] != op._hash(guard) or proof['repository'] != repository
            or proof['source_ref'] != source_ref):
        raise ValueError('retirement must bind exact guard and repository/source')
    claim=guard['submission_claim']; intent=guard['intent']
    if (claim is None or intent['state'] not in {'submitting','unknown'} or intent['task'] is not None
            or release is None or release['owner_id'] != claim['owner_id']
            or release['generation'] != claim['generation'] or not release['invocation_id']
            or release['external_reconciliation'] != 'unknown_preserved'):
        raise ValueError('exact released UNKNOWN claim required; accepted/taskful operations unsupported')
    released=op._timestamp(release['at_utc'],'release time')
    claimed=op._timestamp(claim['claimed_at_utc'],'claim time')
    if claimed > released:
        raise ValueError('release cannot precede original claim')
    _fresh(proof['observed_at_utc'],at,released)
    decision=proof['owner_decision']
    op._object(decision,{'action','reference'},'owner decision')
    if decision['action'] != 'retire_unknown_without_replay':
        raise ValueError('explicit owner UNKNOWN retirement decision required')
    _reference(decision['reference'])
    effect=proof['effect']
    op._object(effect,{'backend','target_ref','candidate_sha','expected_target','receive_pack_calls',
        'subprocess_returned','caller_reference','caller_digest','observation_reference'},'original effect')
    target=effect['target_ref']
    if (effect['backend'] != 'git-conditional-create' or intent['binding']['backend'] != effect['backend']
            or effect['candidate_sha'] != intent['binding']['candidate_sha']
            or not isinstance(target,str) or not PILOT.fullmatch(target)
            or any(x in target for x in ('..','//','@{')) or target.endswith(('/','.','.lock'))
            or any(x.endswith('.lock') or x.startswith('.') for x in target.split('/'))
            or target == source_ref or effect['expected_target'] is not None
            or type(effect['receive_pack_calls']) is not int or effect['receive_pack_calls'] != 1
            or effect['subprocess_returned'] is not True):
        raise ValueError('only original returned single create-only isolated pilot Git push supported')
    for name in ('caller_reference','observation_reference'): _reference(effect[name])
    op._digest(effect['caller_digest'],'original caller digest')
    runtime=proof['runtime']
    op._object(runtime,{'invocation_id','owner_id','generation','status','quiescent',
        'pending_shared_writes','observed_at_utc','reference'},'stopped original runtime')
    if (runtime['invocation_id'] != release['invocation_id'] or runtime['owner_id'] != claim['owner_id']
            or type(runtime['generation']) is not int or runtime['generation'] != claim['generation']
            or runtime['status'] != 'stopped' or runtime['quiescent'] is not True
            or runtime['pending_shared_writes'] is not False):
        raise ValueError('exact original physically stopped/quiescent runtime required')
    _fresh(runtime['observed_at_utc'],at,released); _reference(runtime['reference'])

def validate_retirement(entry, record):
    """Validate immutable history independently of the current generation/clock."""
    if isinstance(entry,dict) and entry.get('schema')=='source-publication-quarantine/v1':
        from source_publication_quarantine import validate_source_quarantine
        return validate_source_quarantine(entry,record)
    if isinstance(entry,dict) and entry.get('schema')=='actions-submission-retirement/v1':
        return _validate_actions_retirement(entry,record)
    op._object(entry,{'schema','outcome','replay_forbidden','guard','original_release','proof',
        'evidence_reference','retired_at_utc'},'submission retirement')
    if (entry['schema'] != 'submission-retirement/v1' or entry['outcome'] != 'UNKNOWN'
            or entry['replay_forbidden'] is not True):
        raise ValueError('retirement must preserve UNKNOWN and permanent no replay')
    at=entry['retired_at_utc']; op._timestamp(at,'retirement time'); _reference(entry['evidence_reference'])
    # Reuse the original strict legacy guard validator without recursing into v2.
    projected=lease._legacy_projection(record,sanitize_migrated=True)
    projected['external_guard']=copy.deepcopy(entry['guard'])
    lease.legacy.validate(projected)
    lease._validate_release(entry['original_release'],record['generation'])
    _validate_proof(entry['proof'],entry['guard'],record['repository'],record['source_ref'],entry['original_release'],at)
    return entry

def _forbids_intent(entry,intent):
    old=entry['guard']['intent']; binding=intent['binding']; old_binding=old['binding']
    # Changing attempt, mode, environment, key or backend cannot disguise the
    # same retired candidate. Distinct source upgrade candidates remain eligible.
    return (intent['operation_key']==old['operation_key']
            or (binding['repository']==old_binding['repository']
                and binding['candidate_sha']==old_binding['candidate_sha']))

def retire_unknown_guard(record, proof, evidence_reference, at):
    """Pure transition; no ownership, provider terminal fact or budget refund."""
    lease.validate(record); _reference(evidence_reference)
    if (record.get('schema') != 'execution-lease/v2' or record['owner_id'] is not None
            or record['invocation'] is not None or record['finalization'] is not None
            or record['external_guard'] is None):
        raise ValueError('retirement requires a released v2 guarded lease')
    guard=record['external_guard']; claim=guard['submission_claim']
    if claim is None or claim['generation'] != record['generation']:
        raise ValueError('retirement must bind original released generation')
    if claim['grant_id'] in lease._resolved_grant_ids(record):
        raise ValueError('terminal-resolved claims cannot be retired')
    if proof.get('lease_digest') != op._hash(record):
        raise ValueError('retirement proof must bind exact current lease digest')
    _validate_proof(proof,guard,record['repository'],record['source_ref'],record['last_release'],at)
    result=copy.deepcopy(record)
    result['external_guard']=None
    result.setdefault('submission_retirements',[]).append(dict(schema='submission-retirement/v1',
        outcome='UNKNOWN',replay_forbidden=True,guard=copy.deepcopy(guard),
        original_release=copy.deepcopy(record['last_release']),proof=copy.deepcopy(proof),
        evidence_reference=evidence_reference,retired_at_utc=at))
    return lease.validate(result)

def retire_unknown_cas(store, expected_revision, proof, evidence_reference, at):
    """One conditional coordination write and independent readback; no replay."""
    revision,previous=store.read()
    if revision != expected_revision or proof.get('lease_revision') != expected_revision:
        raise ValueError('stale retirement revision; re-observe without replay')
    result=retire_unknown_guard(previous,proof,evidence_reference,at)
    revision=store.compare_and_swap(expected_revision,result)
    observed_revision,observed=store.read()
    if observed_revision != revision or observed != result:
        raise ValueError('retirement readback changed; re-observe without replay')
    return dict(revision=revision,record=result,outcome='UNKNOWN',authorizes_submission=False,
        authorizes_takeover=False,authorizes_merge=False,authorizes_release=False)


# Actions UNKNOWN quarantine is deliberately separate from positive cancellation
# and create-only Git retirement. It supplies neither a transport result nor a send.
_ACTIONS_EVIDENCE_TOKEN=object()
_ACTIONS_ARTIFACTS={'scope','owner_decision','original_ui','runtime','provider_observation','physical_stop','provider_lookup','workflow_definition'}


def _actions_artifacts(proof):
    fields=set(_ACTIONS_ARTIFACTS)
    if isinstance(proof.get('physical_stop'),dict) and proof['physical_stop'].get('schema')=='original-registry-stopped/v1':fields.add('original_registry')
    if 'workflow_mapping' in proof:fields.add('workflow_mapping')
    return fields

def _workflow_target(proof,binding,repository):
    """Filename or numeric provider ID must bind the original environment exactly."""
    scope=proof['scope'];match=re.fullmatch(r'github-actions/workflow/([^/]+)/[A-Za-z0-9._-]+',binding['environment_id'])
    if match is None:raise ValueError('original workflow environment binding required')
    target=match.group(1)
    if target.isdecimal():
        mapping=proof.get('workflow_mapping')
        if (not isinstance(mapping,dict) or type(mapping.get('workflow_id')) is not int or mapping['workflow_id']<=0
                or str(mapping['workflow_id'])!=target or type(mapping.get('id')) is not int or mapping['id']<=0
                or mapping.get('path')!='.github/workflows/'+scope['workflow']
                or mapping.get('head_sha')!=binding['candidate_sha']
                or not isinstance(mapping.get('repository'),dict) or mapping['repository'].get('full_name')!=repository
                or mapping.get('event') not in {'push','pull_request','workflow_dispatch'}):
            raise ValueError('authenticated original numeric workflow ID/file/repository/candidate mapping required')
    elif target!=scope['workflow'] or 'workflow_mapping' in proof:
        raise ValueError('filename scope must match exact original environment; unrelated mapping forbidden')
    return target

def _original_ui(proof):
    raw=proof['original_ui']
    if isinstance(raw,dict) and 'observed_at_utc' in raw:
        required={'observed_at_utc','submitted','form_closed','evidence_ref'}
        if not required<=raw.keys() or raw['submitted'] is not False or raw['form_closed'] is not True:
            raise ValueError('original legacy Close-without-Run record required')
        op._text(raw['evidence_ref'],'original UI observation reference')
        if proof['evidence'].get('original_ui',{}).get('normalization')!='legacy-ui/v1':
            raise ValueError('explicit pinned original UI normalization required')
        # Administrative intake only. Keep raw extras and bytes in the proof.
        # Neither submitted:false nor this normalization is a transport barrier.
        return {'closed_without_run':None,'final_run_clicked':None,'original_ci_submitted':False,'at_utc':raw['observed_at_utc']} # Legacy raw keys do not assert an unrecorded click fact.
    op._object(raw,{'closed_without_run','final_run_clicked','original_ci_submitted','at_utc'},'original UI evidence')
    return raw

def _legacy_capability_descriptor(proof,registry):
    """Hash-matched historical descriptor, never a newly issued sealed capability."""
    import managed_terminal_capability as terminal
    descriptor=registry['capability_descriptor']
    op._object(descriptor,{'schema','provenance','payload'},'original capability descriptor')
    if descriptor['schema']!='historical-managed-capability-descriptor/v1' or descriptor['provenance']!='hash_matching_reconstruction':
        raise ValueError('explicit historical hash-matching descriptor required, never minted capability')
    payload=descriptor['payload']
    fields={'schema','invocation_id','execution_surface','managed_store_ref','managed_store_id','managed_store_revision','managed_state_revision','pool_id','task_id','attempt_id','request_ref','launch_id','lease_repository','lease_source_ref','observed_at_utc','started_at_utc'}
    if payload.get('schema')=='managed-terminal-capability/v2':
        fields.update(('controller_proc_pid','controller_birth','boot_id','runtime_processes'))
    op._object(payload,fields,'original managed capability descriptor payload')
    request=registry['request'];receipt=registry['receipt'];owned=registry['owned'];hold=registry['intent']
    identity=request['identity'];claim=request['claim']
    op._object(hold,{'schema','capability_ref','invocation_id','lease_repository','lease_source_ref','armed_at_utc','controller_proc_pid','controller_birth'},'original terminal hold intent')
    derived='managed-terminal:'+terminal._digest(terminal.invocation_identity(payload)).split(':',1)[1]
    if payload['schema']=='managed-terminal-capability/v2' and any(payload[k]!=hold[k] for k in ('controller_proc_pid','controller_birth')):
        raise ValueError('original controller canonical birth binding mismatch')
    if payload['schema']=='managed-terminal-capability/v2':
        processes=payload['runtime_processes']
        if (payload['boot_id']!=receipt.get('boot_id') or not isinstance(processes,list) or len(processes)!=2 or
            {p.get('role') for p in processes}!={'worker','supervisor'} or
            any(p.get('pid')!=receipt.get('worker_pid' if p['role']=='worker' else 'supervisor_proc_pid') or
                not any((p.get('pid'),p.get('birth'),p.get('role'))==(row.get('pid'),row.get('birth'),row.get('role')) for row in receipt.get('process_births',[])) for p in processes)):
            raise ValueError('original canonical runtime process binding mismatch')
    request_digest=op._hash(request)
    if (payload['schema'] not in ('managed-terminal-capability/v1','managed-terminal-capability/v2') or payload['execution_surface']!='managed'
            or terminal._digest(payload)!=owned['capability_ref'] or hold['capability_ref']!=owned['capability_ref']
            or hold['schema']!='managed-terminal-lease-intent/v1' or payload['invocation_id']!=derived
            or any(x!=derived for x in [owned['invocation_id'],hold['invocation_id'],proof['physical_stop']['invocation_id']])
            or any(payload[k]!=identity.get(k) for k in ['pool_id','task_id','attempt_id'])
            or any(payload[k]!=claim.get(k) for k in ['task_id','attempt_id']) or claim.get('launch_allowed') is not True
            or payload['request_ref']!=request_digest or payload['launch_id']!=request_digest
            or receipt.get('launch_id')!=request_digest or receipt['request_ref']!=request_digest
            or payload['lease_repository']!=proof['repository'] or payload['lease_source_ref']!=proof['source_ref']
            or any(hold[k]!=payload[k] for k in ['invocation_id','lease_repository','lease_source_ref'])
            or payload['started_at_utc']!=receipt.get('created_at_utc')):
        raise ValueError('original ownership-to-launch capability/hold registry binding mismatch')
    for key in ['managed_store_id','request_ref','launch_id']:op._digest(payload[key],'original '+key)
    for value in [payload['managed_store_revision'],claim.get('store_revision')]:
        if not isinstance(value,str) or not SHA.fullmatch(value):raise ValueError('original immutable pool revision required')
    if type(payload['managed_state_revision']) is not int or payload['managed_state_revision']<0:raise ValueError('original pool state revision required')
    for key in ['observed_at_utc','started_at_utc']:op._timestamp(payload[key],'original capability '+key)
    if op._timestamp(payload['started_at_utc'],'start')>op._timestamp(payload['observed_at_utc'],'observation'):raise ValueError('original capability time order mismatch')
    if type(hold['controller_proc_pid']) is not int or hold['controller_proc_pid']<=0 or not isinstance(hold['controller_birth'],str) or not re.fullmatch(r'[0-9]+',hold['controller_birth']):raise ValueError('original recorded hold controller identity required')
    return payload

def _authenticate_legacy_launch_history(store,proof):
    """Join the pinned raw launch chain to authoritative owned lease/pool history."""
    import json
    from git_remote_identity import isolated_remote_args
    import managed_executor_pool as pool
    registry=proof['original_registry'];cap=_legacy_capability_descriptor(proof,registry);owned=registry['owned']
    original=store.read_revision(owned['lease_revision'])
    if (store._git('merge-base',owned['lease_revision'],proof['original_lease_revision'])!=owned['lease_revision']
            or any(original[k]!=owned[k] for k in ['owner_id','generation'])
            or original['repository']!=cap['lease_repository'] or original['source_ref']!=cap['lease_source_ref']
            or original['invocation']!={'invocation_id':cap['invocation_id'],'automation_id':None,'conversation_id':None,'execution_surface':'managed','started_at_utc':cap['started_at_utc']}
            or original['acquired_at_utc']!=cap['observed_at_utc']):raise ValueError('original authoritative owned lease revision/launch mismatch')
    ref=cap['managed_store_ref']
    if not isinstance(ref,str) or not ref.startswith('refs/heads/') or ref in {store.ref,proof['source_ref']} or cap['managed_store_id']!=store.store_id:raise ValueError('original pool must use isolated ref on exact configured coordination endpoint')
    store._assert_remote_identity();store._git('check-ref-format',ref)
    rows=store._git('ls-remote','--refs',store.remote,ref).splitlines()
    if len(rows)!=1 or rows[0].split('\t')[1]!=ref:raise ValueError('original authoritative pool ref missing')
    config,remote=isolated_remote_args(store.repo,store.remote,store.store_id)
    store._git(*config,'fetch','--no-tags','--no-write-fetch-head','--refmap=',remote,ref)
    current=rows[0].split('\t')[0];claim=registry['request']['claim'];identity=registry['request']['identity']
    revisions=[(cap['managed_store_revision'],cap['managed_state_revision']),(claim['store_revision'],claim['state_revision'])]
    for revision,state_revision in revisions:
        if store._git('merge-base',revision,current)!=revision:raise ValueError('original pool revision lacks authoritative ancestry')
        rows=store._git('ls-tree','--full-tree','-z',revision,'--','pool-state.json',raw=True).split(b'\0');rows=[r for r in rows if r]
        if len(rows)!=1:raise ValueError('original pool state blob missing')
        metadata,path=rows[0].split(b'\t',1);mode,kind,_=metadata.split(b' ')
        if mode not in {b'100644',b'100755'} or kind!=b'blob' or path!=b'pool-state.json':raise ValueError('exact regular original pool blob required')
        state=json.loads(store._git('show',revision+':pool-state.json',raw=True),object_pairs_hook=op._unique_object)
        op._object(state,pool.STATE_FIELDS,'original pool state')
        task_rows=[t for t in state['tasks'] if t.get('id')==cap['task_id']]
        if len(task_rows)!=1:raise ValueError('exact original launch task missing in pool')
        task=task_rows[0];op._object(task,pool.TASK_STATE_FIELDS,'original pool task')
        if (state['schema']!=pool.STATE_SCHEMA or state['revision']!=state_revision or state['pool_id']!=cap['pool_id']
                or state['coordination_ref']!=ref or state['coordination_store_id']!=cap['managed_store_id']
                or state['plan_digest']!=identity.get('plan_ref')
                or any(state[k]!=identity.get(k) for k in ['change_id','parent_invocation_id','base_sha','integrator_id','coordination_ref','coordination_store_id'])
                or any(state[k] is not False for k in pool.AUTHORITY_FIELDS)
                or task['status']!='running' or task['active_attempt_id']!=cap['attempt_id'] or cap['attempt_id'] not in task['attempt_ids']
                or task['reservation_token']!=claim['reservation_token'] or task['accepted_result_ref'] is not None or task['integrated'] is not False):raise ValueError('original authenticated running pool launch/ownership chain mismatch')
        if revision==claim['store_revision'] and pool.canonical_state_ref(state)!=claim['state_ref']:raise ValueError('original launch claim pool digest mismatch')
    if store._git('merge-base',claim['store_revision'],cap['managed_store_revision'])!=claim['store_revision']:raise ValueError('capability pool revision predates original launch claim')
    store._assert_remote_identity()

def _validate_physical_stop(proof,claim,release,at,released):
    physical=proof['physical_stop'];legacy=isinstance(physical,dict) and physical.get('schema')=='original-registry-stopped/v1'
    fields={'boot_id','executor_pid','executor_birth','supervisor_pid','supervisor_birth','absent','invocation_id','owner_id','generation','observed_at_utc'}
    if legacy:fields|={'schema','supervisor_state','worker_pids','worker_absent','live_descendants','pending_shared_commands'}
    op._object(physical,fields,'original native physical stop')
    if (physical['invocation_id']!=release['invocation_id'] or physical['owner_id']!=claim['owner_id']
            or type(physical['generation']) is not int or physical['generation']!=claim['generation']):
        raise ValueError('exact original stopped ownership identity required')
    lease._uuid(physical['boot_id'],'original kernel boot identity')
    for prefix in ['executor','supervisor']:
        pid=physical[prefix+'_pid'];birth=physical[prefix+'_birth']
        if type(pid) is not int or pid<=0 or not (legacy and prefix=='executor' and birth is None) and (not isinstance(birth,str) or not re.fullmatch(r'[0-9]+',birth)):
            raise ValueError('recorded original native PID/birth required; missing executor birth stays null only in authenticated legacy registry')
    if physical['executor_pid']==physical['supervisor_pid']:raise ValueError('distinct original executor and supervisor required')
    if not legacy:
        if physical['absent'] is not True:raise ValueError('birth-bound original native PIDs must be absent')
    else:
        if (physical['absent'] is not False or physical['supervisor_state']!='Z' or physical['worker_absent'] is not True
                or type(physical['live_descendants']) is not int or physical['live_descendants']!=0
                or physical['pending_shared_commands'] is not False):raise ValueError('legacy zombie is stopped, never absent; no live original descendants/commands required')
        registry=proof['original_registry'];op._object(registry,{'schema','request','receipt','owned','intent','capability_descriptor','worker_pids','worker_births'},'original native registry chain')
        request=registry['request'];receipt=registry['receipt'];owned=registry['owned'];workers=registry['worker_pids']
        if (registry['schema']!='actions-original-registry/v2' or not isinstance(request,dict) or request.get('schema')!='managed-executor-start/v1'
                or not isinstance(receipt,dict) or receipt.get('schema')!='managed-executor-observation/v1'
                or not isinstance(owned,dict) or owned.get('schema')!='managed-terminal-lease-owned/v1'
                or receipt.get('request_ref')!=op._hash(request) or receipt.get('identity')!=request.get('identity')
                or receipt.get('claim')!=request.get('claim') or request.get('identity',{}).get('executor_id')!=claim['owner_id']
                or receipt.get('boot_id')!=physical['boot_id'] or receipt.get('supervisor_proc_pid')!=physical['supervisor_pid']
                or receipt.get('supervisor_birth')!=physical['supervisor_birth']
                or receipt.get('status') not in {'succeeded','failed','cancelled','timed_out'} or receipt.get('quiescent') is not True
                or type(receipt.get('exit_code')) is not int
                or any(owned.get(k)!=physical[k] for k in ['owner_id','generation','invocation_id'])
                or not isinstance(workers,list) or not workers or any(type(x) is not int or x<=0 for x in workers)
                or len(workers)!=len(set(workers)) or physical['supervisor_pid'] in workers
                or workers!=physical['worker_pids'] or physical['executor_pid'] not in workers or receipt.get('worker_pid') not in workers
                or not isinstance(registry['worker_births'],dict) or set(registry['worker_births'])!={str(x) for x in workers}
                or registry['worker_births'][str(physical['executor_pid'])]!=physical['executor_birth']):
            raise ValueError('immutable original request/receipt/ownership/worker registry chain mismatch')
        for birth in registry['worker_births'].values():
            if birth is not None and (not isinstance(birth,str) or not re.fullmatch(r'[0-9]+',birth)):raise ValueError('recorded worker births or truthful null required')
        op._digest(owned.get('capability_ref'),'original ownership capability reference')
        if not isinstance(owned.get('lease_revision'),str) or not SHA.fullmatch(owned['lease_revision']):raise ValueError('immutable original ownership revision required')
        _legacy_capability_descriptor(proof,registry)
    _fresh(physical['observed_at_utc'],at,released)

def _observe_physical_stop(physical):
    from pathlib import Path
    if physical.get('schema')!='original-registry-stopped/v1':
        for prefix in ['executor','supervisor']:
            if Path('/proc',str(physical[prefix+'_pid'])).exists():raise ValueError('original exact native PID must be absent, never infer stop from elapsed time')
        return
    # Check the original kernel zombie without calling it absent or executing.
    from managed_executor_runtime import _process,_descendants
    current=_process(physical['supervisor_pid'])
    if not current or current['birth']!=physical['supervisor_birth'] or current['state']!='Z':
        raise ValueError('exact original recorded supervisor must be a stopped zombie')
    if _descendants(physical['supervisor_pid']):raise ValueError('original supervisor has live descendants')
    for pid in physical['worker_pids']:
        if Path('/proc',str(pid)).exists():raise ValueError('original registry worker PID present; never invent an unrecorded birth')

def _actions_descriptor(value):
    fields={'revision','ref','path','pointer','sha256'}
    if 'normalization' in value:
        fields.add('normalization')
        if value['normalization']!='legacy-ui/v1':raise ValueError('unsupported original-byte normalization')
    if 'byte_range' in value or 'range_sha256' in value:
        fields.update({'byte_range','range_sha256'})
        span=value.get('byte_range')
        if not isinstance(span,list) or len(span)!=2 or any(type(x) is not int for x in span) or not 0<=span[0]<span[1]:raise ValueError('exact original byte range required')
        op._digest(value.get('range_sha256'),'original byte range digest')
    op._object(value,fields,'Actions evidence pin')
    if not isinstance(value['revision'],str) or not SHA.fullmatch(value['revision']):
        raise ValueError('immutable Actions evidence revision required')
    if (not isinstance(value['ref'],str) or not value['ref'].startswith('refs/heads/')
            or not isinstance(value['path'],str) or value['path'].startswith('/')
            or any(x in {'','..','.'} for x in value['path'].split('/'))
            or not isinstance(value['pointer'],str) or not value['pointer'].startswith('/')):
        raise ValueError('exact native evidence ref, relative path and JSON pointer required')
    op._digest(value['sha256'],'Actions evidence byte hash')

def _validate_actions_proof(proof,guard,repository,source_ref,release,at):
    op._object(proof,{'schema','lease_revision','lease_digest','original_lease_revision',
        'guard_digest','repository','source_ref','observed_at_utc','scope','owner_decision',
        'original_ui','transport','runtime','provider_observation','physical_stop','provider_lookup','workflow_definition','evidence'} | (_actions_artifacts(proof)-_ACTIONS_ARTIFACTS),'Actions retirement proof')
    if proof['schema']!='actions-unknown-retirement-proof/v1':
        raise ValueError('unsupported Actions administrative proof')
    for key in ['lease_revision','original_lease_revision']:
        if not isinstance(proof[key],str) or not SHA.fullmatch(proof[key]):raise ValueError('immutable original/current lease revision required')
    op._digest(proof['lease_digest'],'Actions lease digest')
    if (proof['guard_digest']!=op._hash(guard) or proof['repository']!=repository or proof['source_ref']!=source_ref):
        raise ValueError('exact Actions guard/repository/source binding required')
    claim=guard['submission_claim'];intent=guard['intent'];binding=intent['binding']
    if (claim is None or intent['state'] not in {'submitting','unknown'} or intent['task'] is not None
            or binding['backend']!='github-actions' or binding['mode']!='ordinary-unsigned-pilot'
            or release is None or release['owner_id']!=claim['owner_id'] or release['generation']!=claim['generation']
            or not release['invocation_id'] or release['external_reconciliation']!='unknown_preserved'):
        raise ValueError('only exact taskless released ordinary-unsigned-pilot/github-actions UNKNOWN supported')
    claimed=op._timestamp(claim['claimed_at_utc'],'claim time');released=op._timestamp(release['at_utc'],'release time')
    if claimed>released:raise ValueError('original claim must precede release')
    _fresh(proof['observed_at_utc'],at,released)
    scope=proof['scope']
    op._object(scope,{'backend','mode','method','workflow','target','candidate_sha','read_only'},'original Actions scope')
    if (scope['backend']!=binding['backend'] or scope['mode']!=binding['mode'] or scope['method']!='POST'
            or scope['candidate_sha']!=binding['candidate_sha'] or scope['read_only'] is not True
            or not isinstance(scope['workflow'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*\.ya?ml',scope['workflow'])
            or scope['target']!='repos/'+repository+'/actions/workflows/'+_workflow_target(proof,binding,repository)+'/dispatches'):
        raise ValueError('exact read-only ordinary unsigned pilot workflow-dispatch target required')
    decision=proof['owner_decision']
    op._object(decision,{'action','operation_key','grant_id','owner_id','generation','scope','at_utc'},'original owner decision')
    if (decision['action']!='retire_actions_unknown_without_replay' or decision['scope']!=scope
            or any(decision[k]!=claim[k] for k in ['operation_key','grant_id','owner_id','generation'])
            or type(decision['generation']) is not int):
        raise ValueError('explicit exact owner administrative UNKNOWN disposition required')
    if not released<=op._timestamp(decision['at_utc'],'owner decision time')<=op._timestamp(at,'retirement time'):
        raise ValueError('owner disposition must follow original release')
    ui=_original_ui(proof)
    legacy_ui='observed_at_utc' in proof['original_ui']
    if ((not legacy_ui and (ui['closed_without_run'] is not True or ui['final_run_clicked'] is not False)) or ui['original_ci_submitted'] is not False
            or not claimed<=op._timestamp(ui['at_utc'],'UI close time')<=released):
        raise ValueError('original pre-release Close-without-Run evidence required')
    if proof['transport']!={'outcome':'UNKNOWN','cancellation_barrier':None,'dispatcher_birth':None,'no_in_flight':None}:
        raise ValueError('missing transport proof remains NULL/UNKNOWN, never manufactured cancellation')
    runtime=proof['runtime']
    op._object(runtime,{'invocation_id','owner_id','generation','status','quiescent','pending_shared_writes','observed_at_utc','reference'},'original stopped runtime')
    if (runtime['invocation_id']!=release['invocation_id'] or runtime['owner_id']!=claim['owner_id']
            or type(runtime['generation']) is not int or runtime['generation']!=claim['generation']
            or runtime['status']!='stopped' or runtime['quiescent'] is not True or runtime['pending_shared_writes'] is not False):
        raise ValueError('exact original locally stopped/quiescent runtime required')
    _fresh(runtime['observed_at_utc'],at,released);_reference(runtime['reference'])
    observation=proof['provider_observation'];decision=op.decide(intent,observation)
    if (observation['lookup_complete'] is not True or observation['tasks']!=[] or decision['action']!='reconcile'
            or observation['operation_key']!=claim['operation_key']):
        raise ValueError('complete exact provider lookup must retain UNKNOWN without an invented terminal')
    _fresh(observation['observed_at_utc'],at,released)
    _validate_physical_stop(proof,claim,release,at,released)
    lookup=proof['provider_lookup']
    op._object(lookup,{'repository','workflow','candidate_sha','operation_key','grant_id','surfaces','pagination_complete','observed_at_utc','evidence_refs'},'complete original provider lookup')
    if (lookup['repository']!=repository or lookup['workflow']!=scope['workflow'] or lookup['candidate_sha']!=scope['candidate_sha']
            or lookup['operation_key']!=claim['operation_key'] or lookup['grant_id']!=claim['grant_id']
            or lookup['surfaces']!=['status','check_runs','actions'] or lookup['pagination_complete'] is not True
            or not isinstance(lookup['evidence_refs'],list) or len(lookup['evidence_refs'])<3):
        raise ValueError('complete status/check-runs/Actions original-window lookup required')
    for reference in lookup['evidence_refs']:_reference(reference)
    _fresh(lookup['observed_at_utc'],at,released);op._digest(proof['workflow_definition'],'original workflow byte hash')
    op._object(proof['evidence'],_actions_artifacts(proof),'authenticated original-channel artifact pins')
    for descriptor in proof['evidence'].values():_actions_descriptor(descriptor)
    workflow_pin=proof['evidence']['workflow_definition']
    if (workflow_pin['revision']!=scope['candidate_sha'] or workflow_pin['path']!='.github/workflows/'+scope['workflow']
            or workflow_pin['sha256']!=proof['workflow_definition'] or workflow_pin['pointer']!='/'):
        raise ValueError('original exact candidate workflow bytes must be pinned')

def _validate_actions_retirement(entry,record):
    op._object(entry,{'schema','outcome','replay_forbidden','guard','original_release','proof','evidence_reference','retired_at_utc'},'Actions retirement history')
    if entry['schema']!='actions-submission-retirement/v1' or entry['outcome']!='UNKNOWN' or entry['replay_forbidden'] is not True:
        raise ValueError('Actions retirement must retain UNKNOWN permanently')
    _reference(entry['evidence_reference']);op._timestamp(entry['retired_at_utc'],'retirement time')
    projected=lease._legacy_projection(record,sanitize_migrated=True);projected['external_guard']=copy.deepcopy(entry['guard']);lease.legacy.validate(projected)
    lease._validate_release(entry['original_release'],record['generation'])
    if entry['guard']['submission_claim'] not in record['submission_claims']:raise ValueError('original consumed claim must remain exact history')
    _validate_actions_proof(entry['proof'],entry['guard'],record['repository'],record['source_ref'],entry['original_release'],entry['retired_at_utc'])
    return entry

def retire_actions_unknown_guard(record,proof,evidence_reference,at):
    """Pure proposal/history validation only. Native CAS additionally needs authentication."""
    lease.validate(record);_reference(evidence_reference)
    if (record.get('schema')!='execution-lease/v2' or any(record[k] is not None for k in ['owner_id','invocation','finalization'])
            or record['external_guard'] is None):raise ValueError('released guarded v2 lease required')
    guard=record['external_guard'];claim=guard['submission_claim']
    if (claim is None or claim['generation']!=record['generation'] or claim['grant_id'] in lease._resolved_grant_ids(record)
            or proof.get('lease_digest')!=op._hash(record)):raise ValueError('exact unresolved original lease/claim required')
    _validate_actions_proof(proof,guard,record['repository'],record['source_ref'],record['last_release'],at)
    result=copy.deepcopy(record);result['external_guard']=None
    result.setdefault('submission_retirements',[]).append(dict(schema='actions-submission-retirement/v1',outcome='UNKNOWN',replay_forbidden=True,
        guard=copy.deepcopy(guard),original_release=copy.deepcopy(record['last_release']),proof=copy.deepcopy(proof),evidence_reference=evidence_reference,retired_at_utc=at))
    return lease.validate(result)

class ActionsRetirementEvidence:
    """Ephemeral exact native-Git evidence capability, never caller proof syntax."""
    def __init__(self,token,store,proof,pins,at):
        if token is not _ACTIONS_EVIDENCE_TOKEN:raise ValueError('verified native evidence capability required')
        self._store=store;self._proof=copy.deepcopy(proof);self._pins=copy.deepcopy(pins);self._at=at

    def revalidate(self,store,expected_revision,previous,entry):
        if (store is not self._store or expected_revision!=self._proof['lease_revision']
                or entry['proof']!=self._proof or entry['retired_at_utc']!=self._at):
            raise ValueError('verified evidence capability must bind exact native CAS and proposal')
        _authenticate_actions_artifacts(store,self._proof,self._pins,self._at)
        if previous['external_guard']!=entry['guard'] or previous['last_release']!=entry['original_release']:
            raise ValueError('original authoritative guard/release changed before CAS')

def _authenticate_actions_artifacts(store,proof,pins,at):
    """Use deployment-pinned original-channel bytes, not pins derived from untrusted proof.

    The original native caller independently obtains real provider pages and fresh
    birth-bound local absence and saves/readbacks their exact reports. This code
    authenticates their configured Git endpoint and bytes; it never contacts a
    provider, invents a transport barrier, or upgrades UNKNOWN to a terminal fact.
    """
    import hashlib,json
    from pathlib import Path
    from git_lease_store import GitLeaseStore
    from git_remote_identity import isolated_remote_args
    if type(store) is not GitLeaseStore:raise ValueError('actual configured native Git lease store required')
    revision,record=store.read()
    if revision!=proof.get('lease_revision'):raise ValueError('stale Actions lease; observe without replay')
    retire_actions_unknown_guard(record,proof,'sha256:'+'0'*64,at)
    op._object(pins,_actions_artifacts(proof),'trusted deployment evidence pins')
    if pins!=proof['evidence']:raise ValueError('proof must match independently trusted evidence pins')
    original=store.read_revision(proof['original_lease_revision'])
    if (original['external_guard']!=record['external_guard'] or original['last_release']!=record['last_release']
            or original['generation']!=record['generation'] or original['owner_id'] is not None):
        raise ValueError('exact immutable original released guard/claim required')
    physical=proof['physical_stop']
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=physical['boot_id']:
        raise ValueError('fresh original native kernel must verify stopped identity; boot change is not terminal proof')
    _observe_physical_stop(physical)
    fetched={};blobs={}
    for name,pin in pins.items():
        _actions_descriptor(pin);store._assert_remote_identity();store._git('check-ref-format',pin['ref'])
        if pin['ref'] not in fetched:
            rows=store._git('ls-remote','--refs',store.remote,pin['ref']).splitlines()
            if len(rows)!=1 or rows[0].split('\t')[1]!=pin['ref']:raise ValueError('missing authoritative evidence ref')
            current=rows[0].split('\t')[0]
            config,remote=isolated_remote_args(store.repo,store.remote,store.store_id)
            store._git(*config,'fetch','--no-tags','--no-write-fetch-head','--refmap=',remote,pin['ref']);fetched[pin['ref']]=current
        current=fetched[pin['ref']]
        if store._git('merge-base',pin['revision'],current)!=pin['revision']:raise ValueError('evidence revision lacks authoritative ancestry')
        blob_key=(pin['revision'],pin['path'])
        if blob_key not in blobs:
            rows=store._git('ls-tree','--full-tree','-z',pin['revision'],'--',pin['path'],raw=True).split(b'\0');rows=[r for r in rows if r]
            if len(rows)!=1:raise ValueError('authenticated evidence regular blob missing')
            metadata,path=rows[0].split(b'\t',1);mode,kind,_=metadata.split(b' ')
            if mode not in {b'100644',b'100755'} or kind!=b'blob' or path!=pin['path'].encode():raise ValueError('authenticated evidence must be an exact regular Git blob')
            blobs[blob_key]=store._git('show',pin['revision']+':'+pin['path'],raw=True)
        raw=blobs[blob_key]
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=pin['sha256']:raise ValueError('authenticated immutable evidence bytes mismatch')
        if name=='workflow_definition':
            import yaml
            definition=yaml.safe_load(raw)
            if not isinstance(definition,dict):raise ValueError('original read-only workflow definition required')
            permissions=definition.get('permissions')
            if (not isinstance(permissions,dict) or permissions.get('contents')!='read'
                    or any(p not in {'read','none'} for p in permissions.values())):
                raise ValueError('original workflow permissions must be read-only')
            trigger=definition.get('on',definition.get(True));jobs=definition.get('jobs')
            if (not isinstance(trigger,(dict,list)) or 'workflow_dispatch' not in trigger
                    or not isinstance(jobs,dict) or not jobs):raise ValueError('original read-only workflow-dispatch jobs required')
            for job in jobs.values():
                if not isinstance(job,dict):raise ValueError('original workflow job must be an object')
                job_permissions=job.get('permissions',permissions)
                if not isinstance(job_permissions,dict) or any(p not in {'read','none'} for p in job_permissions.values()):raise ValueError('job permissions exceed original read-only scope')
            continue
        if pin.get('normalization') is not None and name!='original_ui':raise ValueError('UI normalization cannot reinterpret other authority')
        selected=raw
        if 'byte_range' in pin:
            start,end=pin['byte_range']
            if end>len(raw):raise ValueError('original byte range exceeds pinned blob')
            selected=raw[start:end]
            if 'sha256:'+hashlib.sha256(selected).hexdigest()!=pin['range_sha256']:raise ValueError('original byte range digest mismatch')
        body=json.loads(selected,object_pairs_hook=op._unique_object)
        for segment in ([] if pin['pointer']=='/' else pin['pointer'].split('/')[1:]):
            segment=segment.replace('~1','/').replace('~0','~')
            if not isinstance(body,dict) or segment not in body:raise ValueError('original evidence pointer missing')
            body=body[segment]
        if body!=proof[name]:raise ValueError('caller facts disagree with authenticated original evidence')
        store._assert_remote_identity()
    if physical.get('schema')=='original-registry-stopped/v1':_authenticate_legacy_launch_history(store,proof)
    return record

def authenticate_actions_retirement(store,proof,trusted_evidence_pins,at):
    """Trusted original native channel only; inputs/refs alone are never authority."""
    _authenticate_actions_artifacts(store,proof,trusted_evidence_pins,at)
    return ActionsRetirementEvidence(_ACTIONS_EVIDENCE_TOKEN,store,proof,trusted_evidence_pins,at)

def retire_actions_unknown_cas(store,expected_revision,proof,evidence_reference,at,*,evidence_capability):
    revision,previous=store.read()
    if revision!=expected_revision or proof.get('lease_revision')!=expected_revision:raise ValueError('stale retirement revision; observe without replay')
    if type(evidence_capability) is not ActionsRetirementEvidence:raise ValueError('authenticated native evidence capability required')
    result=retire_actions_unknown_guard(previous,proof,evidence_reference,at)
    # The store revalidates the typed capability at its actual conditional write.
    # Do not repeat all native evidence fetches once more in this wrapper.
    revision=store.compare_and_swap(expected_revision,result,retirement_capability=evidence_capability)
    actual_revision,actual=store.read()
    if actual_revision!=revision or actual!=result:raise ValueError('retirement readback changed; observe without replay')
    return dict(revision=revision,record=result,outcome='UNKNOWN',authorizes_submission=False,authorizes_takeover=False,authorizes_merge=False,authorizes_release=False)

def observe_actions_retirement(store,proof,evidence_reference):
    """Read only recovery after lost reply; never another CAS or external send."""
    _reference(evidence_reference);revision,record=store.read()
    if record is None:raise ValueError('original authoritative lease absent; preserve UNKNOWN')
    matches=[e for e in record.get('submission_retirements',[]) if e['schema']=='actions-submission-retirement/v1' and e['proof']==proof and e['evidence_reference']==evidence_reference]
    if len(matches)!=1:raise ValueError('exact authoritative retirement not observed; preserve UNKNOWN')
    return dict(revision=revision,record=record,outcome='UNKNOWN',authorizes_submission=False,authorizes_takeover=False,authorizes_merge=False,authorizes_release=False)
