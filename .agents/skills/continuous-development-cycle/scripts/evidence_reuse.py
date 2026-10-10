#!/usr/bin/env python3
"""Explicit dependency-bound reuse of an original test observation."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
from quality_levels import fields,text,texts

SHA=re.compile(r'^[0-9a-f]{40}$');DIGEST=re.compile(r'^[0-9a-f]{64}$')

def _hash(value,pattern,name):
    if not isinstance(value,str) or not pattern.fullmatch(value):raise ValueError(name+' invalid hash')

def _canonical(value):
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (TypeError,ValueError) as exc:raise ValueError('inputs must contain finite JSON values') from exc

def _inputs(data):
    fields(data,('dependency_fingerprints','argv','parameters','environment_fingerprint',
                 'check_definition_fingerprint'),'test inputs')
    deps=data['dependency_fingerprints']
    if not isinstance(deps,dict) or not deps:raise ValueError('dependency coverage must not be empty')
    for key,value in deps.items():text(key,'dependency id');_hash(value,DIGEST,'dependency fingerprint')
    if not isinstance(data['argv'],list) or not data['argv']:raise ValueError('argv required')
    for arg in data['argv']:
        if not isinstance(arg,str):raise ValueError('argv item must be string')
    if not isinstance(data['parameters'],dict):raise ValueError('parameters must be object')
    _hash(data['environment_fingerprint'],DIGEST,'environment_fingerprint')
    _hash(data['check_definition_fingerprint'],DIGEST,'check_definition_fingerprint')
    _canonical(data)

def validate(data:dict)->dict:
    fields(data,('schema','check_id','source_candidate_sha','target_candidate_sha',
                 'source_evidence_ref','source_state','original_inputs','current_inputs',
                 'coverage_refs','exact_candidate_required'),'evidence reuse')
    if data['schema']!='evidence-reuse/v1':raise ValueError('evidence reuse schema mismatch')
    text(data['check_id'],'check_id');text(data['source_evidence_ref'],'source_evidence_ref')
    for key in ('source_candidate_sha','target_candidate_sha'):_hash(data[key],SHA,key)
    if data['source_state'] not in ('success','failed','not_run'):raise ValueError('source_state invalid')
    if type(data['exact_candidate_required']) is not bool:raise ValueError('exact_candidate_required must be bool')
    texts(data['coverage_refs'],'coverage_refs')
    _inputs(data['original_inputs']);_inputs(data['current_inputs'])
    return data

def evaluate(data:dict)->dict:
    validate(data);blockers=[]
    if data['source_state']!='success':blockers.append('source_not_success')
    if data['exact_candidate_required'] and data['source_candidate_sha']!=data['target_candidate_sha']:
        blockers.append('exact_candidate_required')
    for key,value in data['original_inputs'].items():
        if _canonical(value)!=_canonical(data['current_inputs'][key]):blockers.append('inputs_changed:'+key)
    return {'schema':'evidence-reuse-result/v1','check_id':data['check_id'],
            'reusable':not blockers,'blockers':blockers,
            'source_candidate_sha':data['source_candidate_sha'],'target_candidate_sha':data['target_candidate_sha'],
            'source_evidence_ref':data['source_evidence_ref'],'coverage_refs':list(data['coverage_refs']),
            'authorizes_product_write':False,'authorizes_release':False,'authorizes_external_start':False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');a=p.parse_args(argv)
    try:r=evaluate(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError) as exc:print('FAIL: '+str(exc),file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r['reusable'] else 1

if __name__=='__main__':raise SystemExit(main())
