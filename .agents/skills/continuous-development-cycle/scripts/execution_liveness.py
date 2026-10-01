#!/usr/bin/env python3
"""Classify execution liveness from independent runtime evidence, never lease presence alone."""
from __future__ import annotations
from datetime import datetime, timezone
import argparse, json, sys
from pathlib import Path
from execution_lease_v2 import validate as validate_lease

SCHEMA="runtime-observation/v1"
STATES={"running","stopped","unknown"}

def _time(v,name):
    if not isinstance(v,str) or not v.endswith("Z"): raise ValueError(name+" must be UTC Z timestamp")
    try:return datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError as e:raise ValueError(name+" invalid timestamp") from e

def validate_runtime(r):
    if r is None:return None
    if not isinstance(r,dict) or set(r)!={"schema","invocation_id","state","observed_at_utc","evidence_ref"} or r.get("schema")!=SCHEMA:
        raise ValueError("runtime observation invalid")
    if not isinstance(r["invocation_id"],str) or not r["invocation_id"].strip():raise ValueError("runtime invocation_id invalid")
    if r["state"] not in STATES:raise ValueError("runtime state invalid")
    _time(r["observed_at_utc"],"runtime observed_at_utc")
    if not isinstance(r["evidence_ref"],str) or not r["evidence_ref"].strip():raise ValueError("runtime evidence_ref invalid")
    return r

def classify(lease,runtime,now_utc,heartbeat_freshness_seconds=600,runtime_max_age_seconds=300):
    validate_lease(lease);validate_runtime(runtime)
    if type(heartbeat_freshness_seconds) is not int or heartbeat_freshness_seconds<=0:raise ValueError("heartbeat freshness invalid")
    if type(runtime_max_age_seconds) is not int or runtime_max_age_seconds<=0:raise ValueError("runtime max age invalid")
    now=_time(now_utc,"now")
    common={"schema":"execution-liveness-assessment/v1","authorizes_takeover":False,"authorizes_product_write":False}
    if lease["owner_id"] is None:
        return {**common,"state":"released","reason":"lease_released","quiescence_candidate":False,"runtime_evidence_ref":None}
    inv=lease["invocation"]["invocation_id"]
    if runtime is None or runtime["invocation_id"]!=inv or runtime["state"]=="unknown":
        return {**common,"state":"unknown","reason":"exact_runtime_state_not_proven","quiescence_candidate":False,
                "runtime_evidence_ref":None if runtime is None else runtime["evidence_ref"]}
    if runtime["state"]=="running":
        observed=_time(runtime["observed_at_utc"],"runtime observed_at_utc")
        if observed>now or (now-observed).total_seconds()>runtime_max_age_seconds:
            return {**common,"state":"unknown","reason":"runtime_running_observation_stale","quiescence_candidate":False,
                    "runtime_evidence_ref":runtime["evidence_ref"]}
        heartbeat=_time(lease["heartbeat_at_utc"],"heartbeat")
        expiry=_time(lease["expires_at_utc"],"expiry")
        if now>=expiry or (now-heartbeat).total_seconds()>=heartbeat_freshness_seconds:
            return {**common,"state":"unknown","reason":"runtime_running_but_lease_freshness_not_proven","quiescence_candidate":False,
                    "runtime_evidence_ref":runtime["evidence_ref"]}
        return {**common,"state":"active","reason":"exact_runtime_running_and_lease_fresh","quiescence_candidate":False,
                "runtime_evidence_ref":runtime["evidence_ref"]}
    resolved={x.get("grant_id") for x in lease.get("submission_resolutions",[])}
    current_claims=[c for c in lease.get("submission_claims",[])
                    if c.get("generation")==lease["generation"] and c.get("grant_id") not in resolved]
    finalization=lease["finalization"]
    pending=bool(finalization and finalization.get("pending_shared_writes"))
    if pending or lease["external_guard"] is not None or current_claims:
        return {**common,"state":"blocked_unknown_effects","reason":"executor_stopped_but_pending_effects_require_reconciliation",
                "quiescence_candidate":False,"runtime_evidence_ref":runtime["evidence_ref"]}
    return {**common,"state":"orphaned_recoverable","reason":"exact_executor_stopped_no_pending_effects",
            "quiescence_candidate":True,"runtime_evidence_ref":runtime["evidence_ref"]}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("lease");p.add_argument("runtime");p.add_argument("--now",required=True);a=p.parse_args(argv)
    try:
        lease=json.loads(Path(a.lease).read_text(encoding="utf-8"))
        runtime=json.loads(Path(a.runtime).read_text(encoding="utf-8"))
        r=classify(lease,runtime,a.now)
    except (OSError,ValueError,json.JSONDecodeError) as e:print("FAIL:",e,file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
