#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from terminal_state_v2 import evaluate as evaluate_terminal
SCHEMA="continuation-cycle/v1"
MILESTONES={"status","commit","test_subset","validation_stage","pr","artifact","migration_batch","other"}
def validate(d):
    current=isinstance(d,dict) and d.get('schema')=='continuation-cycle/v2'
    fields={"schema","milestone_kind","progress_update_emitted","terminal_state"}
    if current:fields.add('reporting_context')
    if not isinstance(d,dict) or set(d)!=fields or d.get("schema") not in (SCHEMA,'continuation-cycle/v2'):raise ValueError("invalid continuation cycle input")
    if d["milestone_kind"] not in MILESTONES or type(d["progress_update_emitted"]) is not bool or not isinstance(d["terminal_state"],dict):raise ValueError("continuation cycle fields invalid")
    return d
def decide(d,*,reporting_authority=None,now_utc=None):
    validate(d);t=evaluate_terminal(d["terminal_state"])
    reporting=None
    if d['schema']=='continuation-cycle/v2':
        from reporting_contract import check
        reporting=check(d['reporting_context'],reporting_authority,now_utc=now_utc)
        if d['reporting_context']['invocation_id']!=d['terminal_state']['invocation_id']:
            raise ValueError('continuation reporting invocation substituted')
    action="TERMINAL_RESPONSE_ALLOWED" if t["final_response_allowed"] else ("CONTINUE_NOW" if t.get("next_action") else "RECONCILE_TERMINAL_STATE")
    if t['final_response_allowed']:action='VERIFY_NATIVE_CLOSEOUT'
    return {"schema":"continuation-cycle-decision/v2","action":action,"terminal_decision":t["decision"],"terminal_reason":t["reason"],"next_action":t.get("next_action"),"progress_update_emitted":reporting is not None,"historical_contract":d['schema']==SCHEMA,"reporting":reporting,"progress_is_terminal":False,"final_response_allowed":False,"requires_native_closeout":t['final_response_allowed'],"authorizes_scope_expansion":False,"authorizes_side_effects":False}
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("input")
    for option in ('repo','remote','coordination-ref'):p.add_argument('--'+option)
    a=p.parse_args(argv)
    try:
        d=json.loads(Path(a.input).read_text());authority=None
        if d.get('schema')=='continuation-cycle/v2':
            from git_lease_store import GitLeaseStore
            from reporting_contract import authenticate
            if any(getattr(a,key) is None for key in ('repo','remote','coordination_ref')):raise ValueError('native continuation reporting route required')
            context=d['reporting_context'];authority=authenticate(GitLeaseStore(a.repo,a.remote,a.coordination_ref),context['reporting_binding'],context['invocation_id'],context['checkpoint_ref'])
        r=decide(d,reporting_authority=authority)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
