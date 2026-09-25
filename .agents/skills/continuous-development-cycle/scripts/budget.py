#!/usr/bin/env python3
"""Small append-only local budget ledger. Never submits work or grants launch permission.

Writes require the existing single-writer lease or durable store CAS protocol.
The local expected-record check and rename are not distributed compare-and-swap.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

SCHEMA = 'budget-ledger/v1'
METRICS = {'compute_starts','ci_starts','agent_starts','status_polls','tool_calls','tokens','elapsed_seconds'}
COUNTERS = {'compute_start':'compute_starts','ci_start':'ci_starts','agent_start':'agent_starts','status_poll':'status_polls'}
EXPENSIVE = {'compute_start','ci_start','agent_start'}
KINDS = set(COUNTERS) | {'tool_call','checkpoint'}
BASE = {'type','event_id','task_id','wake_id','at_utc'}
FIELDS = {
    'reserve': {'operation_key','attempt_id','kind','scope','recovery_ref','cost'},
    'outcome': {'reservation_id','status','usage','failure'},
    'provider': {'metric','remaining','source'},
    'remedy': {'scope','signature','reference','kind','detail'},
}
POLICY_FIELDS = {'task_limits','wake_limits','max_parallel_agents','checkpoint_reserve','provider_max_age_seconds','actions_budget'}


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'{label} must contain exactly {sorted(fields)}')


def _text(value, label):
    if not isinstance(value,str) or not value.strip() or value != value.strip() or any(ord(c)<32 for c in value):
        raise ValueError(f'{label} must be nonempty text without whitespace padding or controls')


def _number(value, label, nullable=False, integer=False):
    if nullable and value is None: return
    if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{label} must be a nonnegative {"integer" if integer else "finite number"}')


def _time(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z',value):
        raise ValueError('at_utc must be a UTC timestamp ending in Z')
    return datetime.fromisoformat(value[:-1]+'+00:00')


def _digest(value):
    raw = json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return 'sha256:'+hashlib.sha256(raw).hexdigest()


def validate_policy(policy):
    """Validate configured local limits, never infer any provider quota."""
    _object(policy,POLICY_FIELDS,'policy')
    for field in ('task_limits','wake_limits'):
        limits = policy[field]
        if not isinstance(limits,dict) or set(limits)-METRICS:
            raise ValueError(f'{field} has unsupported metrics')
        for metric,limit in limits.items():
            _number(limit,field+'.'+metric,nullable=True,integer=metric!='elapsed_seconds')
    _number(policy['max_parallel_agents'],'max_parallel_agents',integer=True)
    _number(policy['provider_max_age_seconds'],'provider_max_age_seconds',integer=True)
    _object(policy['checkpoint_reserve'],{'tokens','tool_calls'},'checkpoint_reserve')
    for name,value in policy['checkpoint_reserve'].items(): _number(value,name,integer=True)
    if policy['actions_budget'] not in ('normal','conserve','exhausted'):
        raise ValueError('invalid actions_budget')


def new_ledger(task_id, wake_id, policy):
    _text(task_id,'task_id'); _text(wake_id,'wake_id'); validate_policy(policy)
    return dict(schema=SCHEMA,task_id=task_id,wake_ids=[wake_id],policy=copy.deepcopy(policy),
                policy_digest=_digest(policy),events=[])


def _validate_event(event):
    if not isinstance(event,dict) or not isinstance(event.get('type'),str) or event['type'] not in FIELDS:
        raise ValueError('invalid event type')
    _object(event,BASE|FIELDS[event['type']],'event')
    for field in ('event_id','task_id','wake_id'): _text(event[field],field)
    _time(event['at_utc'])
    kind = event['type']
    if kind == 'reserve':
        for field in ('operation_key','attempt_id','scope'): _text(event[field],field)
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',event['operation_key']):
            raise ValueError('operation_key must be a sha256 digest')
        if event['kind'] not in KINDS: raise ValueError('invalid reservation kind')
        if event['recovery_ref'] is not None: _text(event['recovery_ref'],'recovery_ref')
        _object(event['cost'],{'tool_calls','tokens','elapsed_seconds'},'cost')
        for metric,value in event['cost'].items():
            _number(value,metric,nullable=metric!='tool_calls',integer=metric!='elapsed_seconds')
        if event['kind'] in ('tool_call','status_poll') and event['cost']['tool_calls'] < 1:
            raise ValueError('tool calls and status polls must charge at least one tool call')
    elif kind == 'outcome':
        _text(event['reservation_id'],'reservation_id')
        if event['status'] not in ('unknown','succeeded','failed','setup_failed','cancelled','timed_out'):
            raise ValueError('invalid outcome status')
        _object(event['usage'],{'tokens','elapsed_seconds'},'usage')
        for metric,value in event['usage'].items(): _number(value,metric,nullable=True,integer=metric=='tokens')
        if event['status'] in ('failed','setup_failed','timed_out'):
            _object(event['failure'],{'signature','category'},'failure')
            _text(event['failure']['signature'],'signature')
            if event['failure']['category'] not in ('code','configuration','infrastructure'):
                raise ValueError('invalid failure category')
        elif event['failure'] is not None: raise ValueError('non-failure outcome must have null failure')
    elif kind == 'provider':
        if event['metric'] not in METRICS: raise ValueError('unsupported provider metric')
        _number(event['remaining'],'remaining',nullable=True,integer=event['metric']!='elapsed_seconds')
        _text(event['source'],'source')
    else:
        for field in ('scope','signature','reference','detail'): _text(event[field],field)
        if event['kind'] not in ('code_correction','configuration_correction','service_recovery'):
            raise ValueError('invalid remedy kind')


def _state(ledger):
    reservations = {}; outcomes = {}; failures = {}; remedies = {}; used = set()
    remedied_failures = {}
    for event in ledger['events']:
        kind = event['type']
        if kind == 'reserve':
            reservations[event['event_id']] = event
            if event['recovery_ref'] is not None:
                used.add(event['recovery_ref'])
                failure = failures.get(event['scope'])
                if failure is not None:
                    remedied_failures[event['event_id']] = failure['event_id']
        elif kind == 'outcome':
            outcomes[event['reservation_id']] = event
            if event['failure']:
                scope = reservations[event['reservation_id']]['scope']
                failures[scope] = event
            elif event['status'] == 'succeeded':
                scope = reservations[event['reservation_id']]['scope']
                failure = failures.get(scope)
                if failure is not None and failure['event_id'] == remedied_failures.get(event['reservation_id']):
                    del failures[scope]
        elif kind == 'remedy': remedies[event['reference']] = event
    return reservations,outcomes,failures,remedies,used


def _totals(ledger, wake=None):
    reservations,outcomes,_,_,_ = _state(ledger)
    known = dict.fromkeys(METRICS,0); unknown = dict.fromkeys(METRICS,0)
    observed = {'tokens':0,'elapsed_seconds':0}; observed_unknown = dict.fromkeys(observed,0)
    for event_id,event in reservations.items():
        if wake is not None and event['wake_id'] != wake: continue
        if event['kind'] in COUNTERS: known[COUNTERS[event['kind']]] += 1
        known['tool_calls'] += event['cost']['tool_calls']
        for metric in observed:
            reserved = event['cost'][metric]
            actual = outcomes.get(event_id,{}).get('usage',{}).get(metric)
            if actual is None: observed_unknown[metric] += 1
            else: observed[metric] += actual
            amounts = [v for v in (reserved,actual) if v is not None]
            if amounts: known[metric] += max(amounts)
            else: unknown[metric] += 1
    totals = {k: None if unknown[k] else known[k] for k in METRICS}
    return totals,known,unknown,{k:None if observed_unknown[k] else observed[k] for k in observed}


def summarize(ledger, *, _checked=False):
    if not _checked: validate_ledger(ledger)
    totals,known,unknown,observed = _totals(ledger)
    reservations,outcomes,_,_,_ = _state(ledger)
    active = sum(e['kind']=='agent_start' and outcomes.get(i,{}).get('status','unknown')=='unknown'
                 for i,e in reservations.items())
    return dict(task_id=ledger['task_id'],wake_id=ledger['wake_ids'][-1],task=totals,
                wake=_totals(ledger,ledger['wake_ids'][-1])[0],known=known,unknown=unknown,
                observed=observed,active_agents=active)


def _provider(ledger, at):
    result = {}
    for index,event in enumerate(ledger['events']):
        if event['type'] != 'provider': continue
        metric = event['metric']; remaining = event['remaining']
        spent = 0; uncertain = False
        reservations,outcomes,_,_,_ = _state(ledger)
        baseline_ledger = dict(ledger,events=ledger['events'][:index])
        baseline_reservations,baseline_outcomes,_,_,_ = _state(baseline_ledger)
        for event_id,reservation in reservations.items():
            if metric in ('tokens','elapsed_seconds'):
                amounts = [v for v in (reservation['cost'][metric],outcomes.get(event_id,{}).get('usage',{}).get(metric)) if v is not None]
                if not amounts:
                    if event_id not in baseline_reservations: uncertain = True
                    continue
                baseline = 0
                if event_id in baseline_reservations:
                    old = [v for v in (reservation['cost'][metric],baseline_outcomes.get(event_id,{}).get('usage',{}).get(metric)) if v is not None]
                    baseline = max(old) if old else 0
                spent += max(amounts)-baseline
            elif event_id not in baseline_reservations:
                spent += 1 if COUNTERS.get(reservation['kind']) == metric else reservation['cost'].get(metric,0)
        net = None if remaining is None or uncertain else max(0,remaining-spent)
        stale = (_time(at)-_time(event['at_utc'])).total_seconds() > ledger['policy']['provider_max_age_seconds']
        # A stale/null snapshot cannot establish restoration of previously exhausted capacity.
        prior_exhausted = result.get(metric,{}).get('exhausted',False)
        exhausted = (net == 0) or (prior_exhausted and (stale or net is None))
        result[metric] = dict(remaining=None if stale else net,status='stale' if stale else ('unknown' if net is None else 'known'),
                              source=event['source'],observed_at_utc=event['at_utc'],exhausted=exhausted)
    return result


def decide(ledger, reservation, *, _checked=False):
    """Budget admission only. An existing reservation must NEVER launch a second effect."""
    if not _checked: validate_ledger(ledger)
    _validate_event(reservation)
    if reservation['type'] != 'reserve': raise ValueError('decide requires a reservation')
    _scope(ledger,reservation)
    summary = summarize(ledger,_checked=True)
    provider = _provider(ledger,reservation['at_utc'])
    reasons = []
    for old in ledger['events']:
        if old['event_id'] == reservation['event_id']:
            if old != reservation: raise ValueError('event_id payload conflict')
            return dict(allow_reservation=True,allow_launch=False,already_recorded=True,reasons=['Existing charge; reconcile the original effect, never resubmit.'],provider=provider)
    kind = reservation['kind']; expensive = kind in EXPENSIVE; policy = ledger['policy']
    cost = dict.fromkeys(METRICS,0); cost.update(reservation['cost'])
    if kind in COUNTERS: cost[COUNTERS[kind]] = 1
    if kind == 'ci_start' and policy['actions_budget'] == 'exhausted': reasons.append('Actions budget exhausted')
    if kind == 'agent_start' and summary['active_agents'] >= policy['max_parallel_agents']:
        reasons.append('maximum parallel agents reached')
    for scope in ('task','wake'):
        for metric,limit in policy[scope+'_limits'].items():
            if limit is None: continue
            current = summary[scope][metric]; amount = cost[metric]
            reserve = policy['checkpoint_reserve'].get(metric,0) if expensive else 0
            if current is None or amount is None:
                # Unknown token/time accounting cannot prove room under a configured cap.
                reasons.append(f'{scope} {metric} usage unknown under configured limit')
            elif current+amount+reserve > limit: reasons.append(f'{scope} {metric} limit/reserve exceeded')
    for metric,quota in provider.items():
        amount = cost[metric]
        if amount == 0: continue
        reserve = policy['checkpoint_reserve'].get(metric,0) if expensive else 0
        if quota['exhausted']: reasons.append(f'provider {metric} exhausted; observed restoration required')
        elif quota['remaining'] is not None and (amount is None or amount+reserve > quota['remaining']):
            reasons.append(f'provider {metric} remaining/reserve insufficient')
    reservations,outcomes,failures,remedies,used = _state(ledger)
    binding = tuple(reservation[k] for k in ('operation_key','attempt_id','kind'))
    if any(tuple(e[k] for k in ('operation_key','attempt_id','kind'))==binding for e in reservations.values()):
        raise ValueError('operation_key + attempt_id + kind already reserved under another event_id')
    failure = failures.get(reservation['scope']) if expensive else None
    ref = reservation['recovery_ref']
    if failure:
        remedy = remedies.get(ref)
        valid = (remedy is not None and ref not in used and remedy['scope']==reservation['scope']
                 and remedy['signature']==failure['failure']['signature']
                 and _time(remedy['at_utc'])>=_time(failure['at_utc']))
        if valid and failure['failure']['category']=='infrastructure':
            valid = remedy['kind'] in ('configuration_correction','service_recovery')
        if not valid: reasons.append('failure circuit open: fresh concrete correction/recovery evidence required')
    elif ref is not None: reasons.append('recovery_ref has no matching failure circuit')
    return dict(allow_reservation=not reasons,allow_launch=False,already_recorded=False,reasons=reasons,provider=provider)


def _scope(ledger,event):
    if event['task_id'] != ledger['task_id'] or event['wake_id'] != ledger['wake_ids'][-1]:
        raise ValueError('event task/wake does not match active ledger')
    if ledger['events'] and _time(event['at_utc']) < _time(ledger['events'][-1]['at_utc']):
        raise ValueError('event timestamp regresses')


def _append(ledger,event):
    _validate_event(event)
    # Exact replay is idempotent even after a later wake; it never grants a new launch.
    for old in ledger['events']:
        if old['event_id'] == event['event_id']:
            if old != event: raise ValueError('event_id payload conflict')
            return copy.deepcopy(ledger)
    _scope(ledger,event)
    reservations,outcomes,failures,remedies,used = _state(ledger)
    if event['type'] == 'reserve':
        admission = decide(ledger,event,_checked=True)
        if not admission['allow_reservation']: raise ValueError('; '.join(admission['reasons']))
    elif event['type'] == 'outcome':
        reservation = reservations.get(event['reservation_id'])
        if reservation is None: raise ValueError('outcome has no matching reservation')
        previous = outcomes.get(event['reservation_id'])
        if previous and previous['status'] != 'unknown': raise ValueError('terminal outcome cannot be replaced')
        if previous:
            for metric,value in previous['usage'].items():
                if value is not None and (event['usage'][metric] is None or event['usage'][metric] < value):
                    raise ValueError('observed cumulative usage cannot regress')
    elif event['type'] == 'provider':
        for old in ledger['events']:
            if old['type'] == 'provider' and old['metric'] == event['metric'] and _time(event['at_utc']) <= _time(old['at_utc']):
                raise ValueError('provider observations must advance their timestamp; replay cannot restore capacity')
    elif event['type'] == 'remedy':
        if event['reference'] in remedies or event['reference'] in used:
            raise ValueError('remedy reference already recorded/consumed')
        failure = failures.get(event['scope'])
        if failure is None or event['signature'] != failure['failure']['signature']:
            raise ValueError('remedy must reference the current recorded failure')
    result = copy.deepcopy(ledger); result['events'].append(copy.deepcopy(event))
    return result


def validate_ledger(ledger):
    _object(ledger,{'schema','task_id','wake_ids','policy','policy_digest','events'},'ledger')
    if ledger['schema'] != SCHEMA: raise ValueError('unsupported ledger schema')
    _text(ledger['task_id'],'task_id'); validate_policy(ledger['policy'])
    if ledger['policy_digest'] != _digest(ledger['policy']): raise ValueError('policy digest mismatch')
    wakes = ledger['wake_ids']
    if not isinstance(wakes,list) or not wakes: raise ValueError('wake_ids must be nonempty')
    for wake in wakes: _text(wake,'wake_id')
    if len(set(wakes)) != len(wakes): raise ValueError('wake_id cannot be reused')
    if not isinstance(ledger['events'],list): raise ValueError('events must be a list')
    replay = new_ledger(ledger['task_id'],wakes[0],ledger['policy'])
    position = 0
    for event in ledger['events']:
        _validate_event(event)
        if event['wake_id'] not in wakes: raise ValueError('unknown event wake')
        index = wakes.index(event['wake_id'])
        if index < position: raise ValueError('event belongs to an earlier wake')
        replay['wake_ids'] = wakes[:index+1]; position = index
        length = len(replay['events']); replay = _append(replay,event)
        if len(replay['events']) == length: raise ValueError('duplicate event in stored ledger')


def apply_event(ledger,event):
    validate_ledger(ledger)
    return _append(ledger,event)


def begin_wake(ledger,wake_id):
    validate_ledger(ledger); _text(wake_id,'wake_id')
    if wake_id == ledger['wake_ids'][-1]: return copy.deepcopy(ledger)
    if wake_id in ledger['wake_ids']: raise ValueError('cannot reopen a previous wake')
    result = copy.deepcopy(ledger); result['wake_ids'].append(wake_id)
    return result


def _unique(pairs):
    result = {}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate JSON field: '+key)
        result[key] = value
    return result


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=_unique)


def write_ledger(path,ledger,*,expected=None):
    """Local durable replace under the caller's existing single-writer/CAS discipline."""
    validate_ledger(ledger); path = Path(path)
    if path.is_symlink(): raise ValueError('refusing ledger symlink')
    if expected is None:
        if path.exists(): raise ValueError('ledger already exists')
    else:
        validate_ledger(expected)
        if not path.exists() or _load(path) != expected: raise ValueError('stale expected ledger')
        for key in ('schema','task_id','policy','policy_digest'):
            if expected[key] != ledger[key]: raise ValueError('cannot replace ledger identity/policy')
        if ledger['events'][:len(expected['events'])] != expected['events'] or ledger['wake_ids'][:len(expected['wake_ids'])] != expected['wake_ids']:
            raise ValueError('ledger updates must be append-only')
        closed_wakes = set(expected['wake_ids'][:-1])
        if any(event['wake_id'] in closed_wakes for event in ledger['events'][len(expected['events']):]):
            raise ValueError('cannot append events to a closed wake')
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(ledger,stream,sort_keys=True,indent=2,allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        if expected is None:
            try: os.link(temporary,path)
            except FileExistsError as exc: raise ValueError('ledger already exists') from exc
        else:
            if path.is_symlink() or _load(path) != expected: raise ValueError('stale expected ledger')
            os.replace(temporary,path)
        directory = os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        if _load(path) != ledger: raise ValueError('ledger local readback mismatch')
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    for name in ('init','wake','apply','decide','summary','validate'):
        command = sub.add_parser(name); command.add_argument('--ledger',required=True)
        if name == 'init':
            for flag in ('task-id','wake-id','policy'): command.add_argument('--'+flag,required=True)
        elif name == 'wake': command.add_argument('--wake-id',required=True)
        elif name in ('apply','decide'): command.add_argument('--event',required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            result = new_ledger(args.task_id,args.wake_id,_load(args.policy)); write_ledger(args.ledger,result)
        else:
            ledger = _load(args.ledger); validate_ledger(ledger)
            if args.command == 'wake': result = begin_wake(ledger,args.wake_id); write_ledger(args.ledger,result,expected=ledger)
            elif args.command == 'apply': result = apply_event(ledger,_load(args.event)); write_ledger(args.ledger,result,expected=ledger)
            elif args.command == 'decide': result = decide(ledger,_load(args.event))
            elif args.command == 'summary': result = summarize(ledger)
            else: result = {'valid':True,'task_id':ledger['task_id']}
        print(json.dumps(result,sort_keys=True,indent=2)); return 0
    except (ValueError,TypeError,OSError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr); return 2

if __name__ == '__main__': sys.exit(main())
