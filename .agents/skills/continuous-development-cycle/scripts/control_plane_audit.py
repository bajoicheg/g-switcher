#!/usr/bin/env python3
"""CDC 2.6 append-only hash-chained control-plane audit log."""
from __future__ import annotations
import argparse,copy,hashlib,json,re,sys
from pathlib import Path
DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")
EVENTS={"lease_acquire","lease_release","guard_set","guard_reconcile","policy_adopt","scheduler_drift","recovery","fleet_assessment","slo_state_change","version_convergence","continuation_event"}

def _text(v,n,nullable=False):
    if v is None and nullable:return
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be text")
def _canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def _hash(v):return "sha256:"+hashlib.sha256(_canon(v)).hexdigest()
def validate(log):
    if not isinstance(log,dict) or set(log)!={"schema","repository","source_ref","entries"} or log["schema"]!="control-plane-audit-log/v1":raise ValueError("invalid audit log")
    _text(log["repository"],"repository");_text(log["source_ref"],"source_ref")
    if not log["source_ref"].startswith("refs/heads/"):raise ValueError("source_ref invalid")
    if not isinstance(log["entries"],list):raise ValueError("entries must be list")
    prev=None
    fields={"sequence","occurred_at_utc","actor_invocation_id","event_type","object_ref","outcome","details_digest","previous_hash","event_hash"}
    for idx,e in enumerate(log["entries"],1):
        if not isinstance(e,dict) or set(e)!=fields:raise ValueError("audit entry fields mismatch")
        if e["sequence"]!=idx:raise ValueError("audit sequence mismatch")
        _text(e["occurred_at_utc"],"occurred_at_utc");_text(e["actor_invocation_id"],"actor_invocation_id",True)
        if e["event_type"] not in EVENTS:raise ValueError("unsupported audit event_type")
        _text(e["object_ref"],"object_ref");_text(e["outcome"],"outcome")
        if not isinstance(e["details_digest"],str) or not DIGEST.fullmatch(e["details_digest"]):raise ValueError("details_digest invalid")
        if e["previous_hash"]!=prev:raise ValueError("audit previous_hash mismatch")
        body={k:e[k] for k in fields if k!="event_hash"}
        if e["event_hash"]!=_hash(body):raise ValueError("audit event_hash mismatch")
        prev=e["event_hash"]
    return log
def append(log,*,occurred_at_utc,actor_invocation_id,event_type,object_ref,outcome,details_digest):
    validate(log)
    if event_type not in EVENTS:raise ValueError("unsupported audit event_type")
    if not isinstance(details_digest,str) or not DIGEST.fullmatch(details_digest):raise ValueError("details_digest invalid")
    prev=log["entries"][-1]["event_hash"] if log["entries"] else None
    e={"sequence":len(log["entries"])+1,"occurred_at_utc":occurred_at_utc,"actor_invocation_id":actor_invocation_id,
       "event_type":event_type,"object_ref":object_ref,"outcome":outcome,"details_digest":details_digest,"previous_hash":prev}
    e["event_hash"]=_hash(e)
    r=copy.deepcopy(log);r["entries"].append(e);return validate(r),copy.deepcopy(e)
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("log");a=p.parse_args(argv)
    try:validate(json.loads(Path(a.log).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print("PASS: control-plane audit log");return 0
if __name__=="__main__":raise SystemExit(main())
