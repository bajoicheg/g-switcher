#!/usr/bin/env python3
"""CDC 2.8.1 durable blocker proof validator."""
from __future__ import annotations
from datetime import datetime
import argparse,json,sys
from pathlib import Path
def _time(v):
    if not isinstance(v,str) or not v.endswith("Z"):raise ValueError("UTC timestamp required")
    return datetime.fromisoformat(v[:-1]+"+00:00")
def validate(p,now_utc=None):
    f={"schema","dependency_id","category","observed_at_utc","max_age_seconds","evidence_refs","next_action","recheck_trigger","same_invocation_work_exhausted"}
    if not isinstance(p,dict) or set(p)!=f or p.get("schema")!="blocked-state-proof/v1":raise ValueError("blocker proof invalid")
    for n in ("dependency_id","category","next_action","recheck_trigger"):
        if not isinstance(p[n],str) or not p[n].strip():raise ValueError(f"{n} invalid")
    observed=_time(p["observed_at_utc"])
    if type(p["max_age_seconds"]) is not int or p["max_age_seconds"]<=0:raise ValueError("max_age_seconds invalid")
    if not isinstance(p["evidence_refs"],list) or not p["evidence_refs"] or any(not isinstance(x,str) or not x.strip() for x in p["evidence_refs"]):raise ValueError("evidence_refs invalid")
    if type(p["same_invocation_work_exhausted"]) is not bool or not p["same_invocation_work_exhausted"]:raise ValueError("same_invocation_work_exhausted must be true")
    if now_utc is not None:
        now=_time(now_utc);age=(now-observed).total_seconds()
        if age<0:raise ValueError("blocker proof from future")
        if age>p["max_age_seconds"]:raise ValueError("blocker proof stale")
    return p
def assess(p,now_utc):
    validate(p,now_utc)
    return {"schema":"blocked-state-assessment/v1","state":"BLOCKED","dependency_id":p["dependency_id"],"next_action":p["next_action"],"recheck_trigger":p["recheck_trigger"],"terminal_boundary_valid":True,"authorizes_scope_expansion":False}
def main(argv=None):
    q=argparse.ArgumentParser(description=__doc__);q.add_argument("proof");q.add_argument("--now",required=True);a=q.parse_args(argv)
    try:r=assess(json.loads(Path(a.proof).read_text()),a.now)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
