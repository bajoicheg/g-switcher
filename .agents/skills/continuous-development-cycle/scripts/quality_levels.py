#!/usr/bin/env python3
"""Risk-based validation policy; evidence only, never execution authority."""
from __future__ import annotations
import argparse
import json
import sys
import math
from pathlib import Path

LEVELS = {'FAST': 0, 'MEDIUM': 1, 'FULL': 2}
RISK_FLOORS = {c: 'FULL' for c in ('cdc_core', 'executor_authority',
    'authentication', 'ad_write', 'dangerous_migration')}
RISK_FLOORS.update(ordinary_feature='MEDIUM', local_reversible='FAST',
                   documentation='FAST', presentation='FAST')

def fields(data, expected, name):
    if not isinstance(data, dict) or set(data) != set(expected):
        raise ValueError(name + ' fields mismatch')

def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be nonempty text')

def texts(value, name, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(name + ' must be a list')
    for item in value: text(item, name)
    if len(value) != len(set(value)): raise ValueError(name + ' contains duplicates')

def level(value):
    if not isinstance(value, str) or value not in LEVELS: raise ValueError('invalid quality level')

def validate_policy(data: dict) -> dict:
    fields(data, ('default_level', 'max_validation_cycles'), 'quality policy')
    level(data['default_level'])
    if type(data['max_validation_cycles']) is not int or data['max_validation_cycles'] < 1:
        raise ValueError('max_validation_cycles must be positive integer')
    return data

def evaluate(data: dict) -> dict:
    fields(data, ('schema', 'project_level', 'risk_level', 'risk_categories',
                  'risk_reason', 'mandatory_check_ids'), 'quality assessment')
    if data['schema'] != 'quality-assessment/v1': raise ValueError('quality assessment schema mismatch')
    level(data['project_level']); level(data['risk_level'])
    texts(data['risk_categories'], 'risk_categories')
    if any(c not in RISK_FLOORS for c in data['risk_categories']): raise ValueError('unknown risk category')
    texts(data['mandatory_check_ids'], 'mandatory_check_ids', allow_empty=True)
    if not isinstance(data['risk_reason'], str): raise ValueError('risk_reason must be text')
    effective = max([data['project_level'], data['risk_level']] +
                    [RISK_FLOORS[c] for c in data['risk_categories']], key=LEVELS.get)
    raised = LEVELS[effective] > LEVELS[data['project_level']]
    if raised: text(data['risk_reason'], 'risk_reason for escalation')
    return {'schema': 'quality-assessment-result/v1', 'effective_level': effective,
            'escalated': raised, 'risk_reason': data['risk_reason'],
            'mandatory_check_ids': list(data['mandatory_check_ids']),
            'authorizes_product_write': False, 'authorizes_release': False,
            'authorizes_external_start': False}

def evaluate_cycle(data: dict) -> dict:
    fields(data,('schema','cycle_number','max_validation_cycles','changed_inputs','risk_reason',
                 'prior_evidence_insufficient_reason','strategy_revision_ref','budget_observation'),'validation cycle')
    if data['schema']!='validation-cycle/v1':raise ValueError('validation cycle schema mismatch')
    for key in ('cycle_number','max_validation_cycles'):
        if type(data[key]) is not int or data[key]<1:raise ValueError(key+' must be positive integer')
    texts(data['changed_inputs'],'changed_inputs',allow_empty=True)
    for key in ('risk_reason','prior_evidence_insufficient_reason'):
        if not isinstance(data[key],str):raise ValueError(key+' must be text')
    if data['strategy_revision_ref'] is not None:text(data['strategy_revision_ref'],'strategy_revision_ref')
    budget=data['budget_observation']
    fields(budget,('time_seconds','tokens','external_starts','time_limit_seconds','token_limit',
                   'external_start_limit','unknown_reason'),'budget observation')
    for key,value in budget.items():
        if key=='unknown_reason':continue
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
            raise ValueError(key+' must be finite nonnegative number or null')
        if key in ('tokens','external_starts','token_limit','external_start_limit') and value is not None and type(value) is not int:
            raise ValueError(key+' must be integer or null')
    if not isinstance(budget['unknown_reason'],str):raise ValueError('unknown_reason must be text')
    if any(budget[k] is None for k in ('time_seconds','tokens','external_starts')):text(budget['unknown_reason'],'unknown_reason')
    blockers=[]
    if data['cycle_number']>1:
        if not data['changed_inputs']:blockers.append('unchanged_repeat')
        if not data['risk_reason'].strip():blockers.append('repeat_risk_missing')
        if not data['prior_evidence_insufficient_reason'].strip():blockers.append('prior_evidence_not_invalidated')
    if data['cycle_number']>data['max_validation_cycles'] and data['strategy_revision_ref'] is None:
        blockers.append('strategy_revision_required')
    # Local validation does not consume an external start. External admission
    # remains independently guarded; retain its observed quota without granting it.
    for used,limit in (('time_seconds','time_limit_seconds'),('tokens','token_limit')):
        if budget[used] is not None and budget[limit] is not None and budget[used]>=budget[limit]:
            blockers.append('budget_exhausted:'+used)
    return {'schema':'validation-cycle-result/v1','validation_recommended':not blockers,
            'action':'VALIDATE' if not blockers else 'REPLAN_REQUIRED','blockers':blockers,
            'budget_observation':dict(budget),'authorizes_external_start':False,
            'authorizes_product_write':False,'authorizes_release':False}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('input')
    args=parser.parse_args(argv)
    try:
        data=json.loads(Path(args.input).read_text())
        result=evaluate_cycle(data) if isinstance(data,dict) and data.get('schema')=='validation-cycle/v1' else evaluate(data)
    except (OSError,ValueError) as exc:
        print('FAIL: '+str(exc),file=sys.stderr); return 2
    print(json.dumps(result,sort_keys=True)); return 0 if result.get('validation_recommended',True) else 1

if __name__=='__main__':raise SystemExit(main())
