#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
SCHEMA="rca-feedback/v1";CLASSES={"product","policy","execution_channel","stale_state","concurrent_writer","operator_tooling","other"};KEY=re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
def validate(d):
    f={"schema","anomaly_id","material","anomaly_class","fix_key","problem","fix","invariant","existing_fix_keys","evidence_refs","sensitive_context_detected"}
    if not isinstance(d,dict) or set(d)!=f or d.get("schema")!=SCHEMA:raise ValueError("invalid RCA feedback input")
    if type(d["material"]) is not bool or type(d["sensitive_context_detected"]) is not bool or d["anomaly_class"] not in CLASSES or not KEY.fullmatch(d["fix_key"]):raise ValueError("RCA classification invalid")
    for n in ("anomaly_id","problem","fix","invariant"):
        if not isinstance(d[n],str) or not d[n].strip():raise ValueError(f"{n} invalid")
    return d
def disposition(d):
    validate(d);common={"schema":"rca-feedback-disposition/v1","anomaly_id":d["anomaly_id"],"fix_key":d["fix_key"],"authorizes_roadmap_write":False,"authorizes_product_write":False}
    if not d["material"]:return {**common,"action":"NO_ROADMAP_CHANGE","roadmap_payload":None}
    if d["sensitive_context_detected"]:return {**common,"action":"SANITIZE_BEFORE_DISPOSITION","roadmap_payload":None}
    action="REINFORCE_EXISTING" if d["fix_key"] in d["existing_fix_keys"] else "ADD_FIX_FORMULATION"
    return {**common,"action":action,"roadmap_payload":{"problem":d["problem"],"fix":d["fix"],"invariant":d["invariant"],"evidence_refs":d["evidence_refs"]}}
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("input");a=p.parse_args(argv)
    try:r=disposition(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
