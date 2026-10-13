#!/usr/bin/env python3
"""CDC 2.8.2 detects repeated non-progress loops."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
def detect(d):
    f={"schema","observations","repeat_threshold","head_stall_threshold"}
    if not isinstance(d,dict) or set(d)!=f or d.get("schema")!="stuck-state-input/v1":raise ValueError("stuck state input invalid")
    if type(d["repeat_threshold"]) is not int or d["repeat_threshold"]<2 or type(d["head_stall_threshold"]) is not int or d["head_stall_threshold"]<2:raise ValueError("threshold invalid")
    if not isinstance(d["observations"],list):raise ValueError("observations invalid")
    seen={};head_run=0;last_head=None;stuck_reason=None
    for o in d["observations"]:
        if not isinstance(o,dict) or set(o)!={"action_fingerprint","head","meaningful_progress","result_class"}:raise ValueError("observation invalid")
        key=(o["action_fingerprint"],o["result_class"]);seen[key]=seen.get(key,0)+1
        if seen[key]>=d["repeat_threshold"] and not o["meaningful_progress"]:stuck_reason="repeated_strategy_without_progress"
        if o["head"]==last_head and not o["meaningful_progress"]:head_run+=1
        else:head_run=1
        last_head=o["head"]
        if head_run>=d["head_stall_threshold"] and not o["meaningful_progress"]:stuck_reason=stuck_reason or "head_not_advancing"
    return {"schema":"stuck-state-assessment/v1","stuck":stuck_reason is not None,"reason":stuck_reason,"action":"CHANGE_STRATEGY" if stuck_reason else "CONTINUE","authorizes_side_effects":False}
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
 try:r=detect(json.loads(Path(a.input).read_text()))
 except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
 print(json.dumps(r,sort_keys=True));return 1 if r["stuck"] else 0
if __name__=="__main__":raise SystemExit(main())
