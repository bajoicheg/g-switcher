#!/usr/bin/env python3
"""CDC 2.5 deterministic capability-based backend router; recommendation only."""
from __future__ import annotations
from datetime import datetime
import argparse, json, re, sys
from pathlib import Path
SHA=re.compile(r"^[0-9a-f]{40}$");DIGEST=re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
KINDS={"codex_compute","local","other_compute","github_actions"};STATES={"ready","degraded","unavailable","unknown"}
def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")
def _time(v,n):
    if not isinstance(v,str) or not v.endswith("Z"): raise ValueError(f"{n} must be UTC Z timestamp")
    try:return datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError as e:raise ValueError(f"{n} invalid timestamp") from e
def _tokens(v,n):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(f"{n} must be a list of nonempty strings")
    if len(set(v))!=len(v):raise ValueError(f"{n} contains duplicates")
    return v
def validate_registry(r):
    if not isinstance(r,dict) or set(r)!={"schema","observed_at_utc","backends"} or r["schema"]!="backend-capability-registry/v1":raise ValueError("backend registry fields/schema mismatch")
    _time(r["observed_at_utc"],"registry.observed_at_utc")
    if not isinstance(r["backends"],list):raise ValueError("backends must be a list")
    ids=set();fields={"backend_id","kind","enabled","state","rank","capabilities","configuration_digest","last_verified_at_utc","evidence_refs"}
    for b in r["backends"]:
        if not isinstance(b,dict) or set(b)!=fields:raise ValueError("backend fields mismatch")
        _text(b["backend_id"],"backend_id")
        if b["backend_id"] in ids:raise ValueError("duplicate backend_id")
        ids.add(b["backend_id"])
        if b["kind"] not in KINDS or b["state"] not in STATES:raise ValueError("unsupported backend kind/state")
        if type(b["enabled"]) is not bool or type(b["rank"]) is not int or b["rank"]<0:raise ValueError("backend enabled/rank invalid")
        _tokens(b["capabilities"],"backend.capabilities")
        if not DIGEST.fullmatch(b["configuration_digest"]):raise ValueError("configuration_digest invalid")
        _time(b["last_verified_at_utc"],"last_verified_at_utc");_tokens(b["evidence_refs"],"backend.evidence_refs")
        if not b["evidence_refs"]:raise ValueError("backend requires evidence_refs")
    return r
def validate_request(q):
    f={"schema","task_id","candidate_sha","required_capabilities","preferred_kinds","forbidden_backend_ids","required_backend_id","max_registry_age_seconds"}
    if not isinstance(q,dict) or set(q)!=f or q["schema"]!="capability-request/v1":raise ValueError("capability request fields/schema mismatch")
    _text(q["task_id"],"task_id")
    if not SHA.fullmatch(q["candidate_sha"]):raise ValueError("candidate_sha must be a full 40-char SHA")
    _tokens(q["required_capabilities"],"required_capabilities");_tokens(q["preferred_kinds"],"preferred_kinds")
    if any(k not in KINDS for k in q["preferred_kinds"]):raise ValueError("preferred_kinds contains unsupported kind")
    _tokens(q["forbidden_backend_ids"],"forbidden_backend_ids")
    if q["required_backend_id"] is not None:_text(q["required_backend_id"],"required_backend_id")
    if type(q["max_registry_age_seconds"]) is not int or q["max_registry_age_seconds"]<=0:raise ValueError("max_registry_age_seconds must be positive integer")
    return q
def route(r,q,now_utc):
    validate_registry(r);validate_request(q);now=_time(now_utc,"now_utc");observed=_time(r["observed_at_utc"],"registry.observed_at_utc");age=(now-observed).total_seconds()
    if age<0:return {"action":"blocked","reason":"registry_from_future","backend_id":None,"missing_by_backend":{},"authorizes_external_start":False}
    if age>q["max_registry_age_seconds"]:return {"action":"blocked","reason":"registry_stale","backend_id":None,"missing_by_backend":{},"authorizes_external_start":False}
    required=set(q["required_capabilities"]);forbidden=set(q["forbidden_backend_ids"]);preference={k:i for i,k in enumerate(q["preferred_kinds"])};missing={};candidates=[]
    for b in r["backends"]:
        if q["required_backend_id"] is not None and b["backend_id"]!=q["required_backend_id"]:continue
        absent=sorted(required-set(b["capabilities"]))
        if absent:missing[b["backend_id"]]=absent
        if b["backend_id"] in forbidden or not b["enabled"] or b["state"]!="ready" or absent:continue
        candidates.append(b)
    if not candidates:return {"action":"waiting_external","reason":"no_compatible_ready_backend","backend_id":None,"missing_by_backend":missing,"authorizes_external_start":False}
    candidates.sort(key=lambda b:(preference.get(b["kind"],len(preference)),b["rank"],b["backend_id"]));b=candidates[0]
    return {"action":"route","reason":"compatible_backend_selected","backend_id":b["backend_id"],"backend_kind":b["kind"],"configuration_digest":b["configuration_digest"],"evidence_refs":b["evidence_refs"],"missing_by_backend":missing,"authorizes_external_start":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("registry");p.add_argument("request");p.add_argument("--now",required=True);a=p.parse_args(argv)
    try:r=route(json.loads(Path(a.registry).read_text()),json.loads(Path(a.request).read_text()),a.now)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"]=="route" else 1
if __name__=="__main__":raise SystemExit(main())
