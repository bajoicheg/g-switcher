#!/usr/bin/env python3
"""CDC 2.8 safe reconciliation when another writer advances the source ref."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
SHA=re.compile(r"^[0-9a-f]{40}$")
RELATIONS={"equal","fast_forward","diverged","unknown"}
def validate(s):
    f={"schema","expected_head","observed_head","relation","local_changed_paths","remote_changed_paths","pending_external_guard"}
    if not isinstance(s,dict) or set(s)!=f or s.get("schema")!="writer-reconciliation/v1":raise ValueError("invalid writer reconciliation state")
    for k in ("expected_head","observed_head"):
        if not SHA.fullmatch(s[k]):raise ValueError(f"{k} invalid")
    if s["relation"] not in RELATIONS:raise ValueError("relation invalid")
    for k in ("local_changed_paths","remote_changed_paths"):
        if not isinstance(s[k],list) or any(not isinstance(x,str) or not x.strip() for x in s[k]):raise ValueError(f"{k} invalid")
        if len(set(s[k]))!=len(s[k]):raise ValueError(f"{k} duplicated")
    if type(s["pending_external_guard"]) is not bool:raise ValueError("pending_external_guard must be bool")
    return s
def reconcile(s):
    validate(s)
    common={"schema":"writer-reconciliation-result/v1","force_push_allowed":False,"authorizes_takeover":False,"authorizes_product_write":False}
    if s["pending_external_guard"]:
        return {**common,"action":"RECONCILE_REQUIRED","reason":"external_guard_present","base_head":s["observed_head"],"overlap":[]}
    if s["relation"]=="equal":
        return {**common,"action":"PROCEED","reason":"head_unchanged","base_head":s["observed_head"],"overlap":[]}
    overlap=sorted(set(s["local_changed_paths"])&set(s["remote_changed_paths"]))
    if s["relation"]=="fast_forward" and not overlap:
        return {**common,"action":"REPLAY_ON_FRESH_HEAD","reason":"non_overlapping_concurrent_progress","base_head":s["observed_head"],"overlap":[]}
    if s["relation"]=="fast_forward":
        return {**common,"action":"RECONCILE_REQUIRED","reason":"path_overlap","base_head":s["observed_head"],"overlap":overlap}
    return {**common,"action":"RECONCILE_REQUIRED","reason":"history_not_safe_for_automatic_replay","base_head":s["observed_head"],"overlap":overlap}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("state");a=p.parse_args(argv)
    try:r=reconcile(json.loads(Path(a.state).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"] in {"PROCEED","REPLAY_ON_FRESH_HEAD"} else 1
if __name__=="__main__":raise SystemExit(main())
