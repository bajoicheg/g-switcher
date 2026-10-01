#!/usr/bin/env python3
"""CDC 2.5 deterministic recovery-recipe selection; never grants side-effect authority."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ACTIONS={"reconcile_live_state","inspect_exact_invocation","verify_pending_writes","reconcile_external","preserve_external_guard","migrate_released_lease","reconcile_scheduler","repair_scheduler_if_authorized","verify_delivery","reconcile_chat_binding","restore_chat_if_authorized","refresh_capability_registry","route_backend","wait_retry_after","record_blocker","resume_next_action","reload_policy","validate_policy","reconcile_checkpoint","diagnose_progress","execute_or_block","escalate_owner"}
OUTCOMES={"continue","waiting_external","blocked","reconcile"}
def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be nonempty text")
def _tokens(v,n):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(f"{n} invalid")
    if len(set(v))!=len(v):raise ValueError(f"{n} contains duplicates")
    return v
def validate_catalog(c):
    if not isinstance(c,dict) or set(c)!={"schema","recipes"} or c["schema"]!="recovery-recipe-catalog/v1":raise ValueError("invalid recovery catalog")
    if not isinstance(c["recipes"],list) or not c["recipes"]:raise ValueError("recipes must be nonempty list")
    ids=set();fields={"id","diagnosis_code","priority","requires_all","forbids","actions","outcome"}
    for r in c["recipes"]:
        if not isinstance(r,dict) or set(r)!=fields:raise ValueError("recipe fields mismatch")
        _text(r["id"],"recipe.id");_text(r["diagnosis_code"],"diagnosis_code")
        if r["id"] in ids:raise ValueError("duplicate recipe id")
        ids.add(r["id"])
        if type(r["priority"]) is not int or r["priority"]<0:raise ValueError("priority invalid")
        _tokens(r["requires_all"],"requires_all");_tokens(r["forbids"],"forbids");_tokens(r["actions"],"actions")
        if set(r["actions"])-ACTIONS:raise ValueError("recipe contains non-allowlisted action")
        if r["outcome"] not in OUTCOMES:raise ValueError("unsupported outcome")
    return c
def validate_diagnosis(d):
    if not isinstance(d,dict) or set(d)!={"schema","code","facts","reference"} or d["schema"]!="recovery-diagnosis/v1":raise ValueError("invalid recovery diagnosis")
    _text(d["code"],"diagnosis.code");_tokens(d["facts"],"diagnosis.facts");_text(d["reference"],"diagnosis.reference");return d
def select(c,d):
    validate_catalog(c);validate_diagnosis(d);facts=set(d["facts"]);matches=[r for r in c["recipes"] if r["diagnosis_code"]==d["code"] and set(r["requires_all"])<=facts and not(set(r["forbids"])&facts)]
    if not matches:return {"action":"blocked","reason":"no_deterministic_recipe","recipe_id":None,"steps":["escalate_owner"],"outcome":"blocked","authorizes_takeover":False,"authorizes_product_write":False,"authorizes_external_start":False,"authorizes_scheduler_mutation":False}
    matches.sort(key=lambda r:(r["priority"],r["id"]));r=matches[0]
    return {"action":"apply_recipe","reason":"deterministic_recipe_selected","recipe_id":r["id"],"steps":r["actions"],"outcome":r["outcome"],"authorizes_takeover":False,"authorizes_product_write":False,"authorizes_external_start":False,"authorizes_scheduler_mutation":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("catalog");p.add_argument("diagnosis");a=p.parse_args(argv)
    try:r=select(json.loads(Path(a.catalog).read_text()),json.loads(Path(a.diagnosis).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"]=="apply_recipe" else 1
if __name__=="__main__":raise SystemExit(main())
