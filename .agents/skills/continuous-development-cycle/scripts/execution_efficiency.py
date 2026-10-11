"""Risk-scaled overhead decisions and compact terminal evidence composition."""
from __future__ import annotations
from datetime import datetime, timezone
import math

import quality_levels
import final_response_gate


def evaluate(request):
    quality_levels.fields(request,('schema','quality','change_kind','small_reversible',
        'independent_tasks','observation','unknown_effect','independent_work_available'), 'efficiency')
    if request['schema']!='execution-efficiency/v1':raise ValueError('efficiency schema mismatch')
    if request['change_kind'] not in ('feature','bugfix','refactor','text_layout'):
        raise ValueError('change kind invalid')
    for key in ('small_reversible','independent_work_available'):
        if type(request[key]) is not bool:raise ValueError(key+' must be bool')
    if type(request['independent_tasks']) is not int or request['independent_tasks']<0:
        raise ValueError('independent task count invalid')
    observation=request['observation']
    quality_levels.fields(observation,('unchanged_probes','probe_limit','new_information_ref',
        'parallel_benefit_ref'), 'overhead observation')
    for key in ('unchanged_probes','probe_limit'):
        if type(observation[key]) is not int or observation[key]<0:raise ValueError(key+' invalid')
    for key in ('new_information_ref','parallel_benefit_ref'):
        if observation[key] is not None:quality_levels.text(observation[key],key)
    q=quality_levels.evaluate(request['quality'])
    low=(request['small_reversible'] and request['change_kind']=='text_layout'
         and q['effective_level']=='FAST')
    parallel=(not low and request['independent_tasks']>1 and observation['parallel_benefit_ref'] is not None)
    effect=request['unknown_effect']
    if effect is not None:
        quality_levels.fields(effect,('operation_key','guard_ref'), 'unknown effect')
        for key in effect:quality_levels.text(effect[key],key)
    exhausted=(observation['unchanged_probes']>=observation['probe_limit']
               and observation['new_information_ref'] is None)
    action='CONTINUE_INDEPENDENT' if exhausted and request['independent_work_available'] else (
        'WAIT_FOR_NEW_INFORMATION' if exhausted else 'OBSERVE_BOUNDED')
    return {'schema':'execution-efficiency-result/v1','quality':q,
        'execution':'PARALLEL_RECOMMENDED' if parallel else 'SINGLE',
        'review':'ORDERED_INDEPENDENT' if q['effective_level']=='FULL' else ('SELF' if low else 'COMBINED'),
        'new_tests_required':not low,'new_runtime_release_required':not low,
        'repeat_probe_recommended':not exhausted,'observation_action':action,
        'preserved_unknown_effect':effect,'unknown_replay_allowed':False,
        'fresh_ownership_required':True,'mandatory_check_ids':q['mandatory_check_ids'],
        'authorizes_external_start':False,'authorizes_product_write':False,'authorizes_release':False}


def terminal_bundle(request, store, *, now_utc=None):
    quality_levels.fields(request,('schema','invocation_id','owned_lease','release_receipt',
        'continuity','runtime','pool','physical','remaining_queue'), 'terminal bundle')
    if request['schema']!='terminal-bundle/v1':raise ValueError('terminal bundle schema mismatch')
    now=now_utc or datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    revision,lease=store.read()
    record=store.read_revision(request['release_receipt']['lease_revision'])
    gate=final_response_gate.evaluate(request['invocation_id'],lease,request['continuity'],
        request['owned_lease'],request['release_receipt'],record,now)
    runtime=request['runtime'];pool=request['pool']
    quality_levels.fields(runtime,('status','quiescent','process_ids','evidence_ref'), 'terminal runtime')
    if (not isinstance(runtime['process_ids'],list) or not runtime['process_ids']
            or any(type(pid) is not int or pid<=0 for pid in runtime['process_ids'])
            or len(set(runtime['process_ids']))!=len(runtime['process_ids'])):
        raise ValueError('runtime needs exact distinct owned process IDs')
    quality_levels.fields(pool,('accepted','integrated','evidence_ref'), 'terminal pool')
    for item in (runtime,pool):quality_levels.text(item['evidence_ref'],'evidence_ref')
    blockers=[] if gate['allowed'] else [gate['reason']]
    if runtime['status'] not in ('succeeded','failed','cancelled') or runtime['quiescent'] is not True:
        blockers.append('runtime_not_terminal')
    if pool['accepted'] is not True or pool['integrated'] is not True:
        blockers.append('pool_not_accepted_integrated')
    physical=request['physical']
    if not isinstance(physical,list) or not physical:raise ValueError('physical observations required')
    seen=set()
    for item in physical:
        quality_levels.fields(item,('pid','absent','observed_at_utc','evidence_ref'), 'physical observation')
        if type(item['pid']) is not int or item['pid']<=0 or item['pid'] in seen:
            raise ValueError('distinct positive PID required')
        seen.add(item['pid'])
        quality_levels.text(item['evidence_ref'],'physical evidence_ref')
        if not isinstance(item['observed_at_utc'],str) or not item['observed_at_utc'].endswith('Z'):
            raise ValueError('physical timestamp must be UTC Z')
        age=(datetime.fromisoformat(now.replace('Z','+00:00'))-
             datetime.fromisoformat(item['observed_at_utc'].replace('Z','+00:00'))).total_seconds()
        if not math.isfinite(age) or not 0<=age<=90 or item['absent'] is not True:
            blockers.append('physical_absence_missing_or_stale:'+str(item['pid']))
    if seen!=set(runtime['process_ids']):blockers.append('owned_process_observation_set_mismatch')
    quality_levels.texts(request['remaining_queue'],'remaining queue',allow_empty=True)
    return {'schema':'terminal-bundle-result/v1','accepted':not blockers,'blockers':blockers,
        'current_lease_revision':revision,
        'invocation_id':request['invocation_id'],'release_receipt':request['release_receipt'],
        'physical':physical,'runtime':runtime,'pool':pool,'remaining_queue':request['remaining_queue'],
        'authorizes_external_start':False,'authorizes_product_write':False,'authorizes_release':False}
