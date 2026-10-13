#!/usr/bin/env python3
"""CDC 2.10 systematic-debugging RCA pipeline feeding the bounded roadmap disposition."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path

SCHEMA="systematic-rca/v1"
CLASSES={"product","policy","execution_channel","stale_state","concurrent_writer","operator_tooling","other"}
KEY=re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")

def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")
def _refs(v,n):
    if not isinstance(v,list) or not v or any(not isinstance(x,str) or not x.strip() for x in v): raise ValueError(f"{n} invalid")
    if len(v)!=len(set(v)): raise ValueError(f"{n} contains duplicates")

def validate(data):
    fields={"schema","anomaly_id","material","anomaly_class","fix_key","problem","evidence_refs",
            "hypotheses","selected_hypothesis_id","correction","defense_in_depth","invariant",
            "existing_fix_keys","sensitive_context_detected"}
    if not isinstance(data,dict) or set(data)!=fields or data.get("schema")!=SCHEMA:
        raise ValueError("systematic RCA fields/schema mismatch")
    _text(data["anomaly_id"],"anomaly_id");_text(data["problem"],"problem")
    if type(data["material"]) is not bool or type(data["sensitive_context_detected"]) is not bool: raise ValueError("RCA booleans invalid")
    if data["anomaly_class"] not in CLASSES: raise ValueError("RCA anomaly_class invalid")
    if not isinstance(data["fix_key"],str) or not KEY.fullmatch(data["fix_key"]): raise ValueError("RCA fix_key invalid")
    _refs(data["evidence_refs"],"evidence_refs")
    if not isinstance(data["hypotheses"],list) or not data["hypotheses"]: raise ValueError("RCA requires hypotheses")
    ids=[];supported=[]
    for i,h in enumerate(data["hypotheses"]):
        if not isinstance(h,dict) or set(h)!={"id","statement","discriminating_test","observed_result","supported"}: raise ValueError("RCA hypothesis fields mismatch")
        for k in ("id","statement","discriminating_test","observed_result"): _text(h[k],f"hypothesis[{i}].{k}")
        if type(h["supported"]) is not bool: raise ValueError("hypothesis.supported must be boolean")
        ids.append(h["id"])
        if h["supported"]: supported.append(h["id"])
    if len(ids)!=len(set(ids)): raise ValueError("duplicate hypothesis id")
    _text(data["selected_hypothesis_id"],"selected_hypothesis_id")
    if data["selected_hypothesis_id"] not in ids: raise ValueError("selected hypothesis missing")
    if len(supported)!=1 or supported[0]!=data["selected_hypothesis_id"]:
        raise ValueError("RCA requires exactly one selected supported root-cause hypothesis")
    for n in ("correction","defense_in_depth","invariant"): _text(data[n],n)
    if not isinstance(data["existing_fix_keys"],list) or any(not isinstance(x,str) or not KEY.fullmatch(x) for x in data["existing_fix_keys"]):
        raise ValueError("existing_fix_keys invalid")
    return data

def analyze(data):
    validate(data)
    selected=next(h for h in data["hypotheses"] if h["id"]==data["selected_hypothesis_id"])
    feedback={
        "schema":"rca-feedback/v1","anomaly_id":data["anomaly_id"],"material":data["material"],
        "anomaly_class":data["anomaly_class"],"fix_key":data["fix_key"],"problem":data["problem"],
        "fix":data["correction"]+" Defense-in-depth: "+data["defense_in_depth"],
        "invariant":data["invariant"],"existing_fix_keys":data["existing_fix_keys"],
        "evidence_refs":data["evidence_refs"],"sensitive_context_detected":data["sensitive_context_detected"],
    }
    return {
        "schema":"systematic-rca-result/v1","anomaly_id":data["anomaly_id"],
        "root_cause_hypothesis_id":selected["id"],"root_cause":selected["statement"],
        "discriminating_test":selected["discriminating_test"],"observed_result":selected["observed_result"],
        "feedback":feedback,"ready_for_feedback_disposition":True,
        "authorizes_product_write":False,"authorizes_roadmap_write":False,"authorizes_takeover":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=analyze(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0

if __name__=="__main__":
    raise SystemExit(main())
