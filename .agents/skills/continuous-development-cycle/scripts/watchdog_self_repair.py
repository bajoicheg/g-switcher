#!/usr/bin/env python3
"""CDC 2.8.1 watchdog self-repair planner; planning only, never mutation authority."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
SCHEMA="watchdog-repair-state/v1"
def validate(s):
    f={"schema","desired_enabled","scheduler_state","chat_state","backend_state","scheduler_fallback_configured","repair_attempts","max_repair_attempts","evidence_refs"}
    if not isinstance(s,dict) or set(s)!=f or s.get("schema")!=SCHEMA:raise ValueError("watchdog repair state invalid")
    for n in ("desired_enabled","scheduler_fallback_configured"):
        if type(s[n]) is not bool:raise ValueError(f"{n} must be bool")
    if s["scheduler_state"] not in {"ok","disabled","missing","overdue","error","unknown"}:raise ValueError("scheduler_state invalid")
    if s["chat_state"] not in {"active","archived","missing","unknown"}:raise ValueError("chat_state invalid")
    if s["backend_state"] not in {"ready","degraded","unavailable","unknown"}:raise ValueError("backend_state invalid")
    for n in ("repair_attempts","max_repair_attempts"):
        if type(s[n]) is not int or s[n]<0:raise ValueError(f"{n} invalid")
    if s["max_repair_attempts"]<1:raise ValueError("max_repair_attempts must be positive")
    if not isinstance(s["evidence_refs"],list) or any(not isinstance(x,str) or not x.strip() for x in s["evidence_refs"]):raise ValueError("evidence_refs invalid")
    return s
def plan(s):
    validate(s)
    base={"schema":"watchdog-repair-plan/v1","authorizes_scheduler_mutation":False,"authorizes_chat_mutation":False,"authorizes_external_start":False}
    if not s["desired_enabled"]:return {**base,"action":"NOOP","reason":"watchdog_intentionally_disabled","next_action":None}
    if s["repair_attempts"]>=s["max_repair_attempts"]:
        return {**base,"action":"BLOCKED","reason":"repair_budget_exhausted","next_action":"persist blocker with scheduler/chat/backend evidence"}
    if s["chat_state"] in {"archived","missing"}:
        return {**base,"action":"REBIND_CHAT","reason":"chat_dependency_unavailable","next_action":"bind watchdog to a live durable conversation or chat-independent trigger"}
    if s["scheduler_state"] in {"disabled","missing","error"}:
        return {**base,"action":"REPAIR_SCHEDULER","reason":"scheduler_not_delivering","next_action":"restore desired recurring schedule and read it back"}
    if s["scheduler_state"]=="overdue":
        return {**base,"action":"REPAIR_SCHEDULER","reason":"scheduler_overdue","next_action":"verify delivery then repair scheduler/fallback trigger"}
    if s["backend_state"]=="unavailable" and s["scheduler_fallback_configured"]:
        return {**base,"action":"USE_FALLBACK","reason":"primary_backend_unavailable","next_action":"deliver recovery through configured scheduler fallback"}
    if s["backend_state"] in {"unavailable","unknown"}:
        return {**base,"action":"BLOCKED","reason":"no_verified_execution_backend","next_action":"refresh capability registry and establish a durable fallback"}
    if s["scheduler_state"]=="unknown" or s["chat_state"]=="unknown":
        return {**base,"action":"PROBE","reason":"health_state_incomplete","next_action":"refresh scheduler and chat dependency evidence"}
    return {**base,"action":"HEALTHY","reason":"watchdog_delivery_path_healthy","next_action":None}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("state");a=p.parse_args(argv)
    try:r=plan(json.loads(Path(a.state).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"] in {"HEALTHY","NOOP","USE_FALLBACK","REPAIR_SCHEDULER","REBIND_CHAT","PROBE"} else 1
if __name__=="__main__":raise SystemExit(main())
