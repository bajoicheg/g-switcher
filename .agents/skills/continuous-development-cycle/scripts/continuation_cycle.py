#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from terminal_state_v2 import evaluate as evaluate_terminal
SCHEMA="continuation-cycle/v1"
MILESTONES={"status","commit","test_subset","validation_stage","pr","artifact","migration_batch","other"}
def validate(d):
    if not isinstance(d,dict) or set(d)!={"schema","milestone_kind","progress_update_emitted","terminal_state"} or d.get("schema")!=SCHEMA:raise ValueError("invalid continuation cycle input")
    if d["milestone_kind"] not in MILESTONES or type(d["progress_update_emitted"]) is not bool or not isinstance(d["terminal_state"],dict):raise ValueError("continuation cycle fields invalid")
    return d
def decide(d):
    validate(d);t=evaluate_terminal(d["terminal_state"])
    action="TERMINAL_RESPONSE_ALLOWED" if t["final_response_allowed"] else ("CONTINUE_NOW" if t.get("next_action") else "RECONCILE_TERMINAL_STATE")
    return {"schema":"continuation-cycle-decision/v1","action":action,"terminal_decision":t["decision"],"terminal_reason":t["reason"],"next_action":t.get("next_action"),"progress_update_emitted":d["progress_update_emitted"],"progress_is_terminal":False,"final_response_allowed":t["final_response_allowed"],"authorizes_scope_expansion":False,"authorizes_side_effects":False}
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("input");a=p.parse_args(argv)
    try:r=decide(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
