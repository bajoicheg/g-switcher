#!/usr/bin/env python3
"""Reconcile provider-terminal guarded operations without implicit takeover."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
SCHEMA="provider-terminal-observation/v1";OUT="provider-terminal-reconciliation/v1"
PROVIDER={"queued","setup","running","success","failure","cancelled","timed_out","unknown"};TERMINAL={"success","failure","cancelled","timed_out"};GUARD={"none","running","terminal_unreconciled","unknown"};EFFECTS={"none","reconciled","unknown"}
def validate(o):
    fields={"schema","operation_key","provider_status","provider_evidence_ref","guard","owner","external_effects_state","lease_expired"}
    if not isinstance(o,dict) or set(o)!=fields or o.get("schema")!=SCHEMA:raise ValueError("invalid provider terminal observation")
    for name in ("operation_key","provider_evidence_ref"):
        if not isinstance(o[name],str) or not o[name].strip():raise ValueError(f"{name} invalid")
    if o["provider_status"] not in PROVIDER:raise ValueError("provider_status invalid")
    g=o["guard"]
    if not isinstance(g,dict) or set(g)!={"present","state","operation_key"} or type(g["present"]) is not bool:raise ValueError("guard invalid")
    if g["state"] not in GUARD:raise ValueError("guard state invalid")
    if g["present"]:
        if g["state"]=="none" or g["operation_key"]!=o["operation_key"]:raise ValueError("present guard must bind exact operation key")
    elif g["state"]!="none" or g["operation_key"] is not None:raise ValueError("absent guard must be none")
    owner=o["owner"]
    if not isinstance(owner,dict) or set(owner)!={"active","executor_stopped_proven","pending_shared_writes"}:raise ValueError("owner invalid")
    if any(type(owner[name]) is not bool for name in owner):raise ValueError("owner fields must be boolean")
    if owner["active"] and owner["executor_stopped_proven"]:raise ValueError("active owner cannot simultaneously be proven stopped")
    if o["external_effects_state"] not in EFFECTS:raise ValueError("external_effects_state invalid")
    if type(o["lease_expired"]) is not bool:raise ValueError("lease_expired must be boolean")
    return o
def reconcile(o):
    validate(o);terminal=o["provider_status"] in TERMINAL;g=o["guard"];owner=o["owner"]
    candidate=terminal and owner["executor_stopped_proven"] and not owner["pending_shared_writes"] and o["external_effects_state"] in {"none","reconciled"}
    if not terminal:action,wake,reason="OBSERVE_PROVIDER",False,"provider_not_terminal"
    elif g["present"]:action,wake,reason="REENTER_RECONCILIATION",True,"provider_terminal_guard_unreconciled"
    else:action,wake,reason="TERMINAL_ALREADY_RECONCILED",False,"provider_terminal_no_guard"
    return {"schema":OUT,"operation_key":o["operation_key"],"action":action,"wake_required":wake,"provider_terminal":terminal,"recovery_takeover_candidate":candidate,"lease_expiry_is_takeover_evidence":False,"provider_terminal_is_takeover_evidence":False,"authorizes_takeover":False,"authorizes_product_write":False,"authorizes_external_start":False,"reason":reason}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("observation");a=p.parse_args(argv)
    try:r=reconcile(json.loads(Path(a.observation).read_text(encoding="utf-8")))
    except (OSError,ValueError,json.JSONDecodeError) as exc:print(f"FAIL: {exc}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
