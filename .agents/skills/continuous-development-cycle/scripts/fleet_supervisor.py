#!/usr/bin/env python3
"""CDC 2.6 fleet supervisor assessment; read/control-plane only, never product authority."""
from __future__ import annotations
from datetime import datetime
import argparse,json,sys
from pathlib import Path
from progress_slo import classify as classify_progress, validate_policy as validate_slo_policy
from version_convergence import assess as assess_version, validate_target

OVERALL={"HEALTHY","DEGRADED","STALLED","BLOCKED","RECOVERY_REQUIRED"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be text")
def _time(v,n):
    if not isinstance(v,str) or not v.endswith("Z"):raise ValueError(f"{n} must be UTC Z timestamp")
    try:return datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError as e:raise ValueError(f"{n} invalid timestamp") from e
def validate_registry(r):
    f={"schema","target","slo_policy","assessment_max_age_seconds","projects"}
    if not isinstance(r,dict) or set(r)!=f or r["schema"]!="fleet-registry/v1":raise ValueError("invalid fleet registry")
    validate_target(r["target"]);validate_slo_policy(r["slo_policy"])
    if type(r["assessment_max_age_seconds"]) is not int or r["assessment_max_age_seconds"]<=0:raise ValueError("assessment_max_age_seconds invalid")
    if not isinstance(r["projects"],list) or not r["projects"]:raise ValueError("projects must be nonempty list")
    ids=set()
    for p in r["projects"]:
        if not isinstance(p,dict) or set(p)!={"repository","source_ref","watchdog_id","required"}:raise ValueError("fleet project fields mismatch")
        _text(p["repository"],"repository");_text(p["source_ref"],"source_ref");_text(p["watchdog_id"],"watchdog_id")
        if not p["source_ref"].startswith("refs/heads/") or type(p["required"]) is not bool:raise ValueError("fleet project binding invalid")
        key=(p["repository"],p["source_ref"])
        if key in ids:raise ValueError("duplicate fleet project")
        ids.add(key)
    return r
def validate_snapshot(s):
    f={"schema","repository","source_ref","observed_at_utc","product_head","cdc_version","package_fingerprint","checkpoint_schema","policy_revision","watchdog","coordination","progress"}
    if not isinstance(s,dict) or set(s)!=f or s["schema"]!="fleet-project-snapshot/v1":raise ValueError("invalid fleet project snapshot")
    for k in ("repository","source_ref","product_head","cdc_version","package_fingerprint","checkpoint_schema","policy_revision"):_text(s[k],k)
    _time(s["observed_at_utc"],"observed_at_utc")
    w=s["watchdog"]
    if not isinstance(w,dict) or set(w)!={"enabled","last_run_at_utc"} or type(w["enabled"]) is not bool:raise ValueError("watchdog snapshot invalid")
    if w["last_run_at_utc"] is not None:_time(w["last_run_at_utc"],"last_run_at_utc")
    c=s["coordination"]
    if not isinstance(c,dict) or set(c)!={"lease_schema","generation","owner_active","guard_present"}:raise ValueError("coordination snapshot invalid")
    _text(c["lease_schema"],"lease_schema")
    if type(c["generation"]) is not int or c["generation"]<0 or type(c["owner_active"]) is not bool or type(c["guard_present"]) is not bool:raise ValueError("coordination snapshot values invalid")
    return s
def assess_project(registry,snapshot,now_utc):
    validate_registry(registry);validate_snapshot(snapshot);now=_time(now_utc,"now_utc");obs=_time(snapshot["observed_at_utc"],"observed_at_utc")
    age=int((now-obs).total_seconds())
    if age<0 or age>registry["assessment_max_age_seconds"]:
        return {"overall":"RECOVERY_REQUIRED","reason":"snapshot_stale_or_future","snapshot_age_seconds":age,
                "recommended_actions":["refresh_project_snapshot"],"authorizes_product_write":False,"authorizes_takeover":False,"authorizes_merge":False,"authorizes_external_start":False}
    target={"schema":"version-convergence-target/v1",**registry["target"]}
    vs={"schema":"version-convergence-snapshot/v1","repository":snapshot["repository"],"source_ref":snapshot["source_ref"],"cdc_version":snapshot["cdc_version"],"package_fingerprint":snapshot["package_fingerprint"],"checkpoint_schema":snapshot["checkpoint_schema"],"owner_active":snapshot["coordination"]["owner_active"],"guard_present":snapshot["coordination"]["guard_present"],"policy_revision":snapshot["policy_revision"]}
    conv=assess_version(target,vs)
    prog=classify_progress(registry["slo_policy"],snapshot["progress"])
    actions=[]
    if not snapshot["watchdog"]["enabled"]:actions.append("reconcile_scheduler")
    if conv["state"]!="CONVERGED":actions.append(conv["recommended_action"])
    if prog["state"]=="STALLED":actions.append("kick_project_watchdog")
    elif prog["state"]=="DEGRADED":actions.append("inspect_progress")
    elif prog["state"]=="BLOCKED":actions.append("observe_blocker")
    if conv["state"] in {"INCOMPATIBLE","DRIFT"} or not snapshot["watchdog"]["enabled"]:overall="RECOVERY_REQUIRED"
    elif prog["state"]=="STALLED":overall="STALLED"
    elif prog["state"]=="BLOCKED":overall="BLOCKED"
    elif conv["state"]!="CONVERGED" or prog["state"]=="DEGRADED":overall="DEGRADED"
    else:overall="HEALTHY"
    return {"overall":overall,"reason":"fleet_project_assessed","snapshot_age_seconds":age,"version":conv,"progress":prog,
            "recommended_actions":actions,"authorizes_product_write":False,"authorizes_takeover":False,"authorizes_merge":False,"authorizes_external_start":False}
def assess_fleet(registry,snapshots,now_utc):
    validate_registry(registry)
    index={(s["repository"],s["source_ref"]):s for s in snapshots}
    results=[];rank={"RECOVERY_REQUIRED":5,"STALLED":4,"BLOCKED":3,"DEGRADED":2,"HEALTHY":1};worst="HEALTHY"
    for p in registry["projects"]:
        key=(p["repository"],p["source_ref"])
        if key not in index:
            r={"overall":"RECOVERY_REQUIRED","reason":"missing_snapshot","recommended_actions":["refresh_project_snapshot"],"authorizes_product_write":False,"authorizes_takeover":False,"authorizes_merge":False,"authorizes_external_start":False}
        else:r=assess_project(registry,index[key],now_utc)
        results.append({"repository":p["repository"],"source_ref":p["source_ref"],**r})
        if p["required"] and rank[r["overall"]]>rank[worst]:worst=r["overall"]
    return {"schema":"fleet-assessment/v1","overall":worst,"projects":results,"authorizes_product_write":False,"authorizes_takeover":False,"authorizes_merge":False,"authorizes_external_start":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("registry");p.add_argument("snapshots");p.add_argument("--now",required=True);a=p.parse_args(argv)
    try:r=assess_fleet(json.loads(Path(a.registry).read_text()),json.loads(Path(a.snapshots).read_text()),a.now)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
