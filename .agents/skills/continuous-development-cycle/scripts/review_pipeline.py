#!/usr/bin/env python3
"""CDC 2.10.1 ordered spec-compliance then code-quality review gate."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

SCHEMA="review-pipeline/v1"
STATES={"not_run","green","red"}
FINDING_STATES={"open","resolved","dispositioned"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")

def _finding(v,n):
    if not isinstance(v,dict) or set(v)!={"id","summary","state","resolution_ref"}:
        raise ValueError(f"{n} fields mismatch")
    _text(v["id"],f"{n}.id");_text(v["summary"],f"{n}.summary")
    if v["state"] not in FINDING_STATES: raise ValueError(f"{n}.state invalid")
    if v["state"]=="open":
        if v["resolution_ref"] is not None: raise ValueError(f"{n}.open resolution_ref must be null")
    else:
        _text(v["resolution_ref"],f"{n}.resolution_ref")
    return v

def _review(v,n):
    if not isinstance(v,dict) or set(v)!={"state","reviewer_ref","sequence","evidence_refs","findings"}:
        raise ValueError(f"{n} fields mismatch")
    if v["state"] not in STATES: raise ValueError(f"{n}.state invalid")
    if v["state"]=="not_run":
        if v["reviewer_ref"] is not None or v["sequence"] is not None or v["evidence_refs"] or v["findings"]:
            raise ValueError(f"{n} not_run must be empty")
    else:
        _text(v["reviewer_ref"],f"{n}.reviewer_ref")
        if type(v["sequence"]) is not int or v["sequence"]<1: raise ValueError(f"{n}.sequence invalid")
        if not isinstance(v["evidence_refs"],list) or not v["evidence_refs"] or any(not isinstance(x,str) or not x.strip() for x in v["evidence_refs"]):
            raise ValueError(f"{n}.evidence_refs invalid")
        if not isinstance(v["findings"],list): raise ValueError(f"{n}.findings invalid")
        ids=[]
        for i,f in enumerate(v["findings"]):
            _finding(f,f"{n}.findings[{i}]");ids.append(f["id"])
        if len(ids)!=len(set(ids)): raise ValueError(f"{n}.duplicate finding id")
    return v

def validate(data):
    if isinstance(data,dict) and data.get("schema")=="review-pipeline/v2":
        return validate_v2(data)
    if not isinstance(data,dict) or set(data)!={"schema","change_id","material_change","spec_compliance","code_quality"} or data.get("schema")!=SCHEMA:
        raise ValueError("review pipeline fields/schema mismatch")
    _text(data["change_id"],"change_id")
    if type(data["material_change"]) is not bool: raise ValueError("material_change must be boolean")
    _review(data["spec_compliance"],"spec_compliance");_review(data["code_quality"],"code_quality")
    return data

def evaluate(data):
    if isinstance(data,dict) and data.get("schema")=="review-pipeline/v2":
        return evaluate_v2(data)
    validate(data);s=data["spec_compliance"];q=data["code_quality"];b=[]
    if not data["material_change"] and s["state"]=="not_run" and q["state"]=="not_run":
        return {
          "schema":"review-pipeline-result/v1","change_id":data["change_id"],"action":"REVIEW_NOT_REQUIRED",
          "review_green":True,"blockers":[],
          "authorizes_product_write":False,"authorizes_merge":False,"authorizes_release":False,
          "authorizes_scope_expansion":False,
        }
    if data["material_change"] and s["state"]!="green":
        b.append("spec_compliance_not_green")
    if q["state"]!="not_run" and s["state"]!="green":
        b.append("quality_review_before_spec_green")
    if s["state"]!="not_run" and q["state"]!="not_run":
        if s["reviewer_ref"]==q["reviewer_ref"]: b.append("reviewers_not_independent")
        if s["sequence"]>=q["sequence"]: b.append("review_order_invalid")
    if any(f["state"]=="open" for f in s["findings"]): b.append("unresolved_spec_findings")
    if any(f["state"]=="open" for f in q["findings"]): b.append("unresolved_quality_findings")
    if s["state"]=="green" and q["state"]=="not_run": b.append("code_quality_review_required")
    if q["state"]=="red": b.append("code_quality_red")
    if s["state"]=="red": b.append("spec_compliance_red")
    green=(s["state"]=="green" and q["state"]=="green" and not b)
    action="REVIEW_GREEN" if green else ("SPEC_REVIEW_REQUIRED" if s["state"]!="green" else "CONTINUE_REVIEW")
    return {
      "schema":"review-pipeline-result/v1","change_id":data["change_id"],"action":action,
      "review_green":green,"blockers":b,
      "authorizes_product_write":False,"authorizes_merge":False,"authorizes_release":False,
      "authorizes_scope_expansion":False,
    }

def validate_v2(data):
    from quality_levels import fields,evaluate as assess,texts
    fields(data,{"schema","change_id","implementer_ref","assessment","self_review",
                 "combined_review","spec_compliance","code_quality"},"review pipeline v2")
    _text(data['change_id'],'change_id');_text(data['implementer_ref'],'implementer_ref')
    assess(data['assessment'])
    for name in ('self_review','spec_compliance','code_quality'):_review(data[name],name)
    combined=data['combined_review']
    if not isinstance(combined,dict) or 'covers' not in combined:raise ValueError('combined review fields mismatch')
    _review({k:v for k,v in combined.items() if k!='covers'},'combined_review')
    texts(combined['covers'],'covers',allow_empty=True)
    if not set(combined['covers']) <= {'requirements','quality'}:raise ValueError('unknown review coverage')
    if combined['state']=='not_run' and combined['covers']:raise ValueError('not_run review coverage must be empty')
    return data

def evaluate_v2(data):
    from quality_levels import evaluate as assess
    validate_v2(data);level=assess(data['assessment'])['effective_level'];b=[]
    required={'FAST':('self_review',),'MEDIUM':('combined_review',),
              'FULL':('spec_compliance','code_quality')}[level]
    for name in ('self_review','combined_review','spec_compliance','code_quality'):
        review=data[name]
        if name not in required:
            if review['state']!='not_run':b.append('unused_review_present:'+name)
            continue
        if review['state']!='green':b.append('required_review_not_green:'+name)
        if any(f['state']=='open' for f in review['findings']):b.append('open_findings:'+name)
        if name=='self_review':
            if review['reviewer_ref']!=data['implementer_ref']:b.append('self_review_wrong_executor')
        elif review['reviewer_ref']==data['implementer_ref']:b.append('reviewer_is_implementer:'+name)
    if level=='MEDIUM' and set(data['combined_review']['covers'])!={'requirements','quality'}:
        b.append('combined_review_incomplete')
    if level=='FULL':
        s=data['spec_compliance'];q=data['code_quality']
        if q['state']!='not_run' and s['state']!='green':b.append('quality_review_before_spec_green')
        if s['state']!='not_run' and q['state']!='not_run':
            if s['reviewer_ref']==q['reviewer_ref']:b.append('reviewers_not_independent')
            if s['sequence']>=q['sequence']:b.append('review_order_invalid')
    return {'schema':'review-pipeline-result/v2','change_id':data['change_id'],
            'effective_level':level,'review_green':not b,'blockers':b,
            'action':'REVIEW_GREEN' if not b else 'REVIEW_REQUIRED',
            'authorizes_product_write':False,'authorizes_merge':False,'authorizes_release':False,
            'authorizes_scope_expansion':False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=evaluate(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["review_green"] else 1
if __name__=="__main__": raise SystemExit(main())
