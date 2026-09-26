#!/usr/bin/env python3
"""CDC 2.8 terminal-state v2 and no-idle invariant."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

SCHEMA="terminal-state/v2"
DECISIONS={"CONTINUE","WAIT_EXTERNAL","BLOCKED","COMPLETE"}
SHA=re.compile(r"^[0-9a-f]{40}$")

def _text(v,n,nullable=False):
    if v is None and nullable:return
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be nonempty text")

def _refs(v,n):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(f"{n} must be list of nonempty strings")
    if len(v)!=len(set(v)):raise ValueError(f"{n} contains duplicates")

def validate(state):
    fields={"schema","invocation_id","scope_id","observed_head","decision","runnable_actions",
            "pending_external","blocker","meaningful_progress_refs","completion_evidence_refs",
            "checkpoint_ref","lease_released"}
    if not isinstance(state,dict) or set(state)!=fields or state.get("schema")!=SCHEMA:
        raise ValueError("terminal state fields/schema mismatch")
    _text(state["invocation_id"],"invocation_id");_text(state["scope_id"],"scope_id")
    if not SHA.fullmatch(state["observed_head"]):raise ValueError("observed_head must be full SHA")
    if state["decision"] not in DECISIONS:raise ValueError("unsupported terminal decision")
    if not isinstance(state["runnable_actions"],list):raise ValueError("runnable_actions must be list")
    for i,a in enumerate(state["runnable_actions"]):
        if not isinstance(a,dict) or set(a)!={"id","action","authority_ref"}:raise ValueError("runnable action fields mismatch")
        for k in ("id","action","authority_ref"):_text(a[k],f"runnable_actions[{i}].{k}")
    if len({a["id"] for a in state["runnable_actions"]})!=len(state["runnable_actions"]):raise ValueError("duplicate runnable action id")
    ext=state["pending_external"]
    if ext is not None:
        if not isinstance(ext,dict) or set(ext)!={"kind","id","operation_key","state","recheck_action"}:raise ValueError("pending_external fields mismatch")
        for k in ("kind","id","operation_key","recheck_action"):_text(ext[k],f"pending_external.{k}")
        if ext["state"] not in {"submitted","queued","running","unknown"}:raise ValueError("pending_external.state invalid")
    blocker=state["blocker"]
    if blocker is not None:
        if not isinstance(blocker,dict) or set(blocker)!={"code","evidence_refs","next_action","recheck_trigger"}:raise ValueError("blocker fields mismatch")
        _text(blocker["code"],"blocker.code");_text(blocker["next_action"],"blocker.next_action");_text(blocker["recheck_trigger"],"blocker.recheck_trigger")
        _refs(blocker["evidence_refs"],"blocker.evidence_refs")
        if not blocker["evidence_refs"]:raise ValueError("blocker requires evidence")
    _refs(state["meaningful_progress_refs"],"meaningful_progress_refs")
    _refs(state["completion_evidence_refs"],"completion_evidence_refs")
    _text(state["checkpoint_ref"],"checkpoint_ref")
    if type(state["lease_released"]) is not bool:raise ValueError("lease_released must be boolean")
    return state

def evaluate(state):
    validate(state)
    decision=state["decision"]; runnable=state["runnable_actions"]; ext=state["pending_external"]; blocker=state["blocker"]
    common={"schema":"terminal-state-assessment/v2","decision":decision,
            "authorizes_scope_expansion":False,"authorizes_destructive_action":False}
    if decision=="CONTINUE":
        if not runnable:return {**common,"allowed":False,"final_response_allowed":False,"reason":"continue_requires_runnable_action","next_action":None}
        return {**common,"allowed":True,"final_response_allowed":False,"reason":"no_idle_runnable_work","next_action":runnable[0]["action"]}
    if runnable:
        return {**common,"allowed":False,"final_response_allowed":False,"reason":"no_idle_invariant_runnable_work_exists","next_action":runnable[0]["action"]}
    if not state["lease_released"]:
        return {**common,"allowed":False,"final_response_allowed":False,"reason":"lease_must_be_released_before_terminal_response","next_action":"release invocation-bound lease"}
    if decision=="WAIT_EXTERNAL":
        if ext is None or blocker is not None:return {**common,"allowed":False,"final_response_allowed":False,"reason":"waiting_external_requires_single_durable_external_binding","next_action":None}
        return {**common,"allowed":True,"final_response_allowed":True,"reason":"durable_external_wait","next_action":ext["recheck_action"]}
    if decision=="BLOCKED":
        if blocker is None or ext is not None:return {**common,"allowed":False,"final_response_allowed":False,"reason":"blocked_requires_single_proven_blocker","next_action":None}
        return {**common,"allowed":True,"final_response_allowed":True,"reason":"proven_resumable_blocker","next_action":blocker["next_action"]}
    if decision=="COMPLETE":
        if ext is not None or blocker is not None:return {**common,"allowed":False,"final_response_allowed":False,"reason":"complete_conflicts_with_pending_state","next_action":None}
        if not state["completion_evidence_refs"]:return {**common,"allowed":False,"final_response_allowed":False,"reason":"complete_requires_evidence","next_action":"validate completion"}
        return {**common,"allowed":True,"final_response_allowed":True,"reason":"verified_scope_complete","next_action":None}
    raise AssertionError(decision)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("state");a=p.parse_args(argv)
    try:r=evaluate(json.loads(Path(a.state).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["allowed"] else 1
if __name__=="__main__":raise SystemExit(main())
