#!/usr/bin/env python3
"""CDC 2.10.1 branch-finishing evidence gate before CDC terminal/release handling."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
SCHEMA="branch-finish/v1";SHA=re.compile(r"^[0-9a-f]{40}$")

def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")
def validate(d):
    if isinstance(d,dict) and d.get('schema')=='branch-finish/v2':
        from quality_levels import fields
        expected={'schema','branch','candidate_sha','observed_head','validation_fresh','diff_spec_reconciled',
                  'candidate_bound','clean_worktree','unresolved_findings','required_checks',
                  'review_pipeline','review_candidate_sha','reused_checks'}
        fields(d,expected,'branch finish v2')
        base=_legacy_base(d);validate(base)
        if not isinstance(d['review_candidate_sha'],str) or not SHA.fullmatch(d['review_candidate_sha']):
            raise ValueError('review_candidate_sha invalid')
        from review_pipeline import validate as validate_review
        if not isinstance(d['review_pipeline'],dict) or d['review_pipeline'].get('schema')!='review-pipeline/v2':
            raise ValueError('v2 finishing requires review pipeline v2')
        validate_review(d['review_pipeline'])
        if not isinstance(d['reused_checks'],list):raise ValueError('reused_checks must be list')
        from evidence_reuse import validate as validate_reuse
        ids=[c['id'] for c in d['required_checks']]
        for record in d['reused_checks']:validate_reuse(record);ids.append(record['check_id'])
        if len(ids)!=len(set(ids)):raise ValueError('duplicate check ids')
        return d
    fields={"schema","branch","candidate_sha","observed_head","validation_fresh","diff_spec_reconciled",
            "spec_compliance_green","code_quality_green","candidate_bound","clean_worktree",
            "unresolved_findings","required_checks"}
    if not isinstance(d,dict) or set(d)!=fields or d.get("schema")!=SCHEMA: raise ValueError("branch finish fields/schema mismatch")
    _text(d["branch"],"branch")
    for n in ("candidate_sha","observed_head"):
        if not isinstance(d[n],str) or not SHA.fullmatch(d[n]): raise ValueError(f"{n} must be full SHA")
    for n in ("validation_fresh","diff_spec_reconciled","spec_compliance_green","code_quality_green","candidate_bound","clean_worktree"):
        if type(d[n]) is not bool: raise ValueError(f"{n} must be boolean")
    if not isinstance(d["unresolved_findings"],list) or any(not isinstance(x,str) or not x.strip() for x in d["unresolved_findings"]):
        raise ValueError("unresolved_findings invalid")
    if not isinstance(d["required_checks"],list): raise ValueError("required_checks must be list")
    for i,c in enumerate(d["required_checks"]):
        if not isinstance(c,dict) or set(c)!={"id","state","candidate_sha","evidence_ref"}: raise ValueError("required check fields mismatch")
        _text(c["id"],f"check[{i}].id");_text(c["evidence_ref"],f"check[{i}].evidence_ref")
        if c["state"] not in {"success","failed","not_run"}: raise ValueError("check state invalid")
        if not isinstance(c["candidate_sha"],str) or not SHA.fullmatch(c["candidate_sha"]): raise ValueError("check candidate_sha invalid")
    return d

def evaluate(d):
    if isinstance(d,dict) and d.get('schema')=='branch-finish/v2':
        validate(d);result=evaluate(_legacy_base(d))
        from review_pipeline import evaluate as evaluate_review
        from evidence_reuse import evaluate as evaluate_reuse
        review=evaluate_review(d['review_pipeline'])
        if not review['review_green']:result['blockers'].extend('review:'+b for b in review['blockers'])
        if d['review_candidate_sha']!=d['candidate_sha']:result['blockers'].append('review_wrong_candidate')
        ids={c['id'] for c in d['required_checks']}
        for record in d['reused_checks']:
            ids.add(record['check_id']);r=evaluate_reuse(record)
            result['blockers'].extend('reuse:'+record['check_id']+':'+b for b in r['blockers'])
            if record['target_candidate_sha']!=d['candidate_sha']:result['blockers'].append('reuse_wrong_candidate')
        for check_id in d['review_pipeline']['assessment']['mandatory_check_ids']:
            if check_id not in ids:result['blockers'].append('mandatory_check_missing:'+check_id)
        result.update(schema='branch-finish-result/v2',ready=not result['blockers'],review=review,
                      action='READY_FOR_CDC_TERMINAL' if not result['blockers'] else 'CONTINUE')
        return result
    validate(d);b=[];sha=d["candidate_sha"]
    if d["observed_head"]!=sha:b.append("candidate_head_mismatch")
    if not d["validation_fresh"]:b.append("validation_stale")
    if not d["diff_spec_reconciled"]:b.append("diff_spec_not_reconciled")
    if not d["spec_compliance_green"]:b.append("spec_compliance_not_green")
    if not d["code_quality_green"]:b.append("code_quality_not_green")
    if not d["candidate_bound"]:b.append("candidate_not_bound")
    if not d["clean_worktree"]:b.append("dirty_worktree")
    if d["unresolved_findings"]:b.append("unresolved_review_findings")
    for c in d["required_checks"]:
        if c["state"]!="success":b.append("required_check_not_green:"+c["id"])
        elif c["candidate_sha"]!=sha:b.append("required_check_wrong_sha:"+c["id"])
    ready=not b
    return {"schema":"branch-finish-result/v1","action":"READY_FOR_CDC_TERMINAL" if ready else "CONTINUE",
            "ready":ready,"blockers":b,"authorizes_merge":False,"authorizes_release":False,
            "authorizes_product_write":False,"authorizes_scope_expansion":False}

def _legacy_base(d):
    base={k:v for k,v in d.items() if k not in ('review_pipeline','review_candidate_sha','reused_checks')}
    base.update(schema=SCHEMA,spec_compliance_green=True,code_quality_green=True)
    return base

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=evaluate(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["ready"] else 1
if __name__=="__main__": raise SystemExit(main())
