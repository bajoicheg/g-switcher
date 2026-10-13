#!/usr/bin/env python3
"""CDC 2.6 meaningful-progress SLO classifier; primitive activity is never progress."""
from __future__ import annotations
from datetime import datetime
import argparse,json,sys
from pathlib import Path

STATES={"HEALTHY","DEGRADED","STALLED","BLOCKED","RECOVERY_REQUIRED"}

def _time(v,name,nullable=False):
    if v is None and nullable:return None
    if not isinstance(v,str) or not v.endswith("Z"):raise ValueError(f"{name} must be UTC Z timestamp")
    try:return datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError as e:raise ValueError(f"{name} invalid timestamp") from e

def validate_policy(p):
    fields={"schema","degraded_after_seconds","stalled_after_seconds","blocked_pauses_clock","waiting_external_pauses_clock","primitive_activity_is_progress"}
    if not isinstance(p,dict) or set(p)!=fields or p["schema"]!="progress-slo-policy/v1":raise ValueError("invalid progress SLO policy")
    for k in ("degraded_after_seconds","stalled_after_seconds"):
        if type(p[k]) is not int or p[k]<=0:raise ValueError(f"{k} must be positive integer")
    if p["stalled_after_seconds"]<=p["degraded_after_seconds"]:raise ValueError("stalled threshold must exceed degraded threshold")
    for k in ("blocked_pauses_clock","waiting_external_pauses_clock","primitive_activity_is_progress"):
        if type(p[k]) is not bool:raise ValueError(f"{k} must be boolean")
    if p["primitive_activity_is_progress"]:raise ValueError("CDC 2.6 forbids primitive activity counting as progress")
    return p

def validate_observation(o):
    fields={"schema","observed_at_utc","last_meaningful_progress_at_utc","last_activity_at_utc","primitive_steps_since_progress","blocker","waiting_external","phase","evidence_refs"}
    if not isinstance(o,dict) or set(o)!=fields or o["schema"]!="progress-observation/v1":raise ValueError("invalid progress observation")
    now=_time(o["observed_at_utc"],"observed_at_utc")
    progress=_time(o["last_meaningful_progress_at_utc"],"last_meaningful_progress_at_utc",True)
    activity=_time(o["last_activity_at_utc"],"last_activity_at_utc",True)
    if progress and progress>now:raise ValueError("meaningful progress cannot be from future")
    if activity and activity>now:raise ValueError("activity cannot be from future")
    if type(o["primitive_steps_since_progress"]) is not int or o["primitive_steps_since_progress"]<0:raise ValueError("primitive_steps_since_progress invalid")
    if type(o["blocker"]) is not bool or type(o["waiting_external"]) is not bool:raise ValueError("blocker/waiting_external must be boolean")
    if not isinstance(o["phase"],str) or not o["phase"].strip():raise ValueError("phase must be text")
    if not isinstance(o["evidence_refs"],list) or any(not isinstance(x,str) or not x.strip() for x in o["evidence_refs"]):raise ValueError("evidence_refs invalid")
    return o

def classify(policy,obs):
    validate_policy(policy);validate_observation(obs)
    if obs["blocker"] and policy["blocked_pauses_clock"]:
        return {"state":"BLOCKED","reason":"durable_blocker","meaningful_progress_age_seconds":None,"primitive_activity_ignored":True,"authorizes_recovery":False}
    if obs["waiting_external"] and policy["waiting_external_pauses_clock"]:
        return {"state":"BLOCKED","reason":"waiting_external","meaningful_progress_age_seconds":None,"primitive_activity_ignored":True,"authorizes_recovery":False}
    if obs["last_meaningful_progress_at_utc"] is None:
        return {"state":"RECOVERY_REQUIRED","reason":"meaningful_progress_time_unknown","meaningful_progress_age_seconds":None,"primitive_activity_ignored":True,"authorizes_recovery":False}
    now=_time(obs["observed_at_utc"],"observed_at_utc");last=_time(obs["last_meaningful_progress_at_utc"],"last_meaningful_progress_at_utc")
    age=int((now-last).total_seconds())
    if age>=policy["stalled_after_seconds"]:state,reason="STALLED","meaningful_progress_stale"
    elif age>=policy["degraded_after_seconds"]:state,reason="DEGRADED","meaningful_progress_aging"
    else:state,reason="HEALTHY","meaningful_progress_fresh"
    return {"state":state,"reason":reason,"meaningful_progress_age_seconds":age,"primitive_activity_ignored":True,"authorizes_recovery":False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("policy");p.add_argument("observation");a=p.parse_args(argv)
    try:r=classify(json.loads(Path(a.policy).read_text()),json.loads(Path(a.observation).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
