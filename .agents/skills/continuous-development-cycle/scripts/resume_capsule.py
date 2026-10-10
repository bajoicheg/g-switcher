#!/usr/bin/env python3
"""CDC 2.4 durable resume capsule validation and fast-resume assessment."""
from __future__ import annotations
from datetime import datetime
import argparse, json, re, sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
HEALTH = {"HEALTHY", "DEGRADED", "STALLED", "BLOCKED", "RECOVERY_REQUIRED", "UNKNOWN"}

def _text(v, name, nullable=False):
    if v is None and nullable: return
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} must be nonempty text")

def _time(v, name):
    if not isinstance(v, str) or not v.endswith("Z"):
        raise ValueError(f"{name} must be UTC Z timestamp")
    try: return datetime.fromisoformat(v[:-1] + "+00:00")
    except ValueError as e: raise ValueError(f"{name} invalid timestamp") from e

def validate(c):
    keys={"schema","updated_at_utc","repository","source_ref","head_sha","policy_version",
          "policy_revision","policy_digest","checkpoint_ref","checkpoint_digest","task","ownership","external","validation",
          "health","budget","recovery"}
    if not isinstance(c,dict) or set(c)!=keys: raise ValueError("resume capsule fields mismatch")
    if c["schema"]!="resume-capsule/v1": raise ValueError("unsupported capsule schema")
    _time(c["updated_at_utc"],"updated_at_utc")
    for n in ("repository","source_ref","policy_version","policy_revision","checkpoint_ref"): _text(c[n],n)
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", c["policy_version"]): raise ValueError("policy_version must be stable semver")
    if not DIGEST.fullmatch(c["policy_digest"]): raise ValueError("policy_digest invalid")
    if not c["source_ref"].startswith("refs/heads/"): raise ValueError("source_ref must be refs/heads/*")
    if not SHA.fullmatch(c["head_sha"]): raise ValueError("head_sha invalid")
    if not DIGEST.fullmatch(c["checkpoint_digest"]): raise ValueError("checkpoint_digest invalid")
    task=c["task"]
    if not isinstance(task,dict) or set(task)!={"phase","current_task","next_action","blocker"}: raise ValueError("task fields mismatch")
    for n in ("phase","current_task","next_action"): _text(task[n],f"task.{n}")
    _text(task["blocker"],"task.blocker",True)
    own=c["ownership"]
    if not isinstance(own,dict) or set(own)!={"lease_schema","owner_id","invocation_id","generation","revision"}: raise ValueError("ownership fields mismatch")
    _text(own["lease_schema"],"ownership.lease_schema")
    _text(own["owner_id"],"ownership.owner_id",True); _text(own["invocation_id"],"ownership.invocation_id",True)
    if type(own["generation"]) is not int or own["generation"]<0: raise ValueError("ownership.generation invalid")
    _text(own["revision"],"ownership.revision",True)
    ext=c["external"]
    if ext is not None:
        if not isinstance(ext,dict) or set(ext)!={"kind","id","sha","operation_key","state"}: raise ValueError("external fields mismatch")
        for n in ("kind","id","operation_key","state"): _text(ext[n],f"external.{n}")
        if not SHA.fullmatch(ext["sha"]): raise ValueError("external.sha invalid")
    val=c["validation"]
    if not isinstance(val,dict) or set(val)!={"candidate_sha","last_green_sha","last_green_evidence","missing_gates"}: raise ValueError("validation fields mismatch")
    for n in ("candidate_sha","last_green_sha"):
        if val[n] and not SHA.fullmatch(val[n]): raise ValueError(f"validation.{n} invalid")
    _text(val["last_green_evidence"],"validation.last_green_evidence",True)
    if not isinstance(val["missing_gates"],list) or any(not isinstance(x,str) or not x.strip() for x in val["missing_gates"]): raise ValueError("missing_gates invalid")
    health=c["health"]
    if not isinstance(health,dict) or set(health)!={"state","fingerprint"}: raise ValueError("health fields mismatch")
    if health["state"] not in HEALTH: raise ValueError("health.state invalid")
    _text(health["fingerprint"],"health.fingerprint",True)
    budget=c["budget"]
    if not isinstance(budget,dict) or set(budget)!={"ref","summary"}: raise ValueError("budget fields mismatch")
    _text(budget["ref"],"budget.ref",True); _text(budget["summary"],"budget.summary")
    rec=c["recovery"]
    if not isinstance(rec,dict) or set(rec)!={"recommended_action","reason"}: raise ValueError("recovery fields mismatch")
    _text(rec["recommended_action"],"recovery.recommended_action"); _text(rec["reason"],"recovery.reason")
    return c

def assess(capsule, probe, max_age_seconds=7200):
    validate(capsule)
    keys={"schema","observed_at_utc","complete","repository","source_ref","head_sha",
          "policy_version","policy_revision","policy_digest","checkpoint_digest","lease_revision"}
    if not isinstance(probe,dict) or set(probe)!=keys or probe["schema"]!="resume-probe/v1":
        raise ValueError("invalid resume probe")
    now=_time(probe["observed_at_utc"],"probe.observed_at_utc")
    if type(probe["complete"]) is not bool: raise ValueError("probe.complete must be boolean")
    if type(max_age_seconds) is not int or max_age_seconds<=0: raise ValueError("max_age_seconds invalid")
    reasons=[]
    if not probe["complete"]: reasons.append("probe_incomplete")
    for field in ("repository","source_ref","head_sha","policy_version","policy_revision","policy_digest","checkpoint_digest"):
        if probe[field]!=capsule[field]: reasons.append(f"{field}_changed")
    if probe["lease_revision"] != capsule["ownership"]["revision"]: reasons.append("lease_revision_changed")
    age=(now-_time(capsule["updated_at_utc"],"capsule.updated_at_utc")).total_seconds()
    if age < 0: reasons.append("capsule_from_future")
    elif age > max_age_seconds: reasons.append("capsule_stale")
    return {"fast_resume": not reasons,
            "action": "resume_next_action" if not reasons else "reconcile",
            "reasons": reasons, "next_action": capsule["task"]["next_action"]}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    v=sub.add_parser("validate"); v.add_argument("capsule")
    a=sub.add_parser("assess"); a.add_argument("capsule"); a.add_argument("probe"); a.add_argument("--max-age-seconds",type=int,default=7200)
    args=p.parse_args(argv)
    try:
        cap=json.loads(Path(args.capsule).read_text(encoding="utf-8"))
        if args.command=="validate":
            validate(cap); out={"valid":True}
        else:
            probe=json.loads(Path(args.probe).read_text(encoding="utf-8"))
            out=assess(cap,probe,args.max_age_seconds)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}",file=sys.stderr); return 2
    print(json.dumps(out,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
