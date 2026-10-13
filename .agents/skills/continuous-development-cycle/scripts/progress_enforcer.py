#!/usr/bin/env python3
"""CDC 2.8.1 maps progress SLO state to an executable continuation action."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
def enforce(s):
    f={"schema","progress_state","runnable_work","watchdog_enabled","external_wait","blocker_proven"}
    if not isinstance(s,dict) or set(s)!=f or s.get("schema")!="progress-enforcement/v1":raise ValueError("progress enforcement state invalid")
    if s["progress_state"] not in {"HEALTHY","DEGRADED","STALLED","BLOCKED","RECOVERY_REQUIRED"}:raise ValueError("progress_state invalid")
    for n in ("runnable_work","watchdog_enabled","external_wait","blocker_proven"):
        if type(s[n]) is not bool:raise ValueError(f"{n} invalid")
    if s["external_wait"] or s["blocker_proven"]:
        return {"schema":"progress-enforcement-plan/v1","action":"OBSERVE_BLOCKER","reason":"durable_wait_or_blocker","final_response_allowed":True,"authorizes_side_effects":False}
    if s["runnable_work"]:
        return {"schema":"progress-enforcement-plan/v1","action":"CONTINUE_NOW","reason":"no_idle_runnable_work","final_response_allowed":False,"authorizes_side_effects":False}
    if s["progress_state"]=="STALLED":
        return {"schema":"progress-enforcement-plan/v1","action":"KICK_WATCHDOG" if s["watchdog_enabled"] else "REPAIR_WATCHDOG","reason":"progress_slo_stalled","final_response_allowed":False,"authorizes_side_effects":False}
    if s["progress_state"]=="RECOVERY_REQUIRED":
        return {"schema":"progress-enforcement-plan/v1","action":"RECOVER","reason":"progress_evidence_inconsistent","final_response_allowed":False,"authorizes_side_effects":False}
    if s["progress_state"]=="DEGRADED":
        return {"schema":"progress-enforcement-plan/v1","action":"INSPECT_AND_CONTINUE","reason":"progress_aging","final_response_allowed":False,"authorizes_side_effects":False}
    return {"schema":"progress-enforcement-plan/v1","action":"NOOP","reason":"healthy_no_runnable_work","final_response_allowed":True,"authorizes_side_effects":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("state");a=p.parse_args(argv)
    try:r=enforce(json.loads(Path(a.state).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
