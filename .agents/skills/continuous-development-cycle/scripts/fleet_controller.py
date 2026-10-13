#!/usr/bin/env python3
"""CDC 2.8.2 project-independent fleet continuation planner."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
STATES={"HEALTHY","DEGRADED","STALLED","BLOCKED","RECOVERY_REQUIRED"}
def plan(data):
    if not isinstance(data,dict) or set(data)!={"schema","projects"} or data.get("schema")!="fleet-control-input/v1":raise ValueError("fleet control input invalid")
    if not isinstance(data["projects"],list) or not data["projects"]:raise ValueError("projects must be nonempty")
    out=[]
    fields={"repository","source_ref","state","runnable_work","owner_active","guard_present","watchdog_enabled","next_action"}
    for p in data["projects"]:
        if not isinstance(p,dict) or set(p)!=fields or p["state"] not in STATES:raise ValueError("project record invalid")
        if not isinstance(p["repository"],str) or "/" not in p["repository"] or not p["source_ref"].startswith("refs/heads/"):raise ValueError("project identity invalid")
        for n in ("runnable_work","owner_active","guard_present","watchdog_enabled"):
            if type(p[n]) is not bool:raise ValueError(f"{n} invalid")
        if p["guard_present"]:action="OBSERVE_GUARD"
        elif p["owner_active"]:action="OBSERVE_OWNER"
        elif p["runnable_work"]:action="WAKE_PROJECT"
        elif p["state"]=="STALLED":action="KICK_WATCHDOG" if p["watchdog_enabled"] else "REPAIR_WATCHDOG"
        elif p["state"]=="RECOVERY_REQUIRED":action="RECOVER_PROJECT"
        elif p["state"]=="DEGRADED":action="REFRESH_PROJECT"
        elif p["state"]=="BLOCKED":action="OBSERVE_BLOCKER"
        else:action="NOOP"
        out.append({"repository":p["repository"],"source_ref":p["source_ref"],"action":action,"next_action":p["next_action"]})
    return {"schema":"fleet-control-plan/v1","projects":out,"authorizes_product_write":False,"authorizes_takeover":False,"authorizes_external_start":False,"project_specific_code_required":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=plan(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
