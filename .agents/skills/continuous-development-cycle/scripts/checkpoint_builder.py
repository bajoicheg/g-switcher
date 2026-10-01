#!/usr/bin/env python3
"""Build checkpoint v4 from explicitly typed control fields and validate before output."""
from __future__ import annotations
import argparse,copy,json,sys
from pathlib import Path
from contracts import load_yaml
from validate_checkpoint_24 import validate_checkpoint_24
SCHEMA="typed-checkpoint-build/v1"
UPDATE_FIELDS={"phase","lease_state","blocker","next_action","resume_capsule_ref"}
GATES={"continue","meaningful_progress","durable_external_binding","resumable_blocker","task_complete","scope_complete"}
def validate_request(request):
    if not isinstance(request,dict) or set(request)!={"schema","updates","execution_continuity"} or request.get("schema")!=SCHEMA: raise ValueError("invalid typed checkpoint build request")
    updates=request["updates"]
    if not isinstance(updates,dict) or set(updates)-UPDATE_FIELDS: raise ValueError("unsupported checkpoint update field")
    for name,value in updates.items():
        if not isinstance(value,str) or not value.strip(): raise ValueError(f"{name} must be nonempty text")
    ec=request["execution_continuity"]; fields={"invocation_id","runnable_next_action","meaningful_progress","primitive_steps_since_progress","completion_gate","last_progress_ref"}
    if not isinstance(ec,dict) or set(ec)!=fields: raise ValueError("execution_continuity fields mismatch")
    for name in ("runnable_next_action","meaningful_progress"):
        if type(ec[name]) is not bool: raise ValueError(f"{name} must be boolean, never display text")
    if type(ec["primitive_steps_since_progress"]) is not int or ec["primitive_steps_since_progress"]<0: raise ValueError("primitive_steps_since_progress must be nonnegative integer")
    if ec["completion_gate"] not in GATES: raise ValueError("completion_gate invalid")
    for name in ("invocation_id","last_progress_ref"):
        if ec[name] is not None and (not isinstance(ec[name],str) or not ec[name].strip()): raise ValueError(f"{name} must be null or nonempty text")
    return request
def build(base_checkpoint,request,adapter):
    if not isinstance(base_checkpoint,dict): raise ValueError("base checkpoint must be mapping")
    validate_request(request); result=copy.deepcopy(base_checkpoint)
    result.update(copy.deepcopy(request["updates"])); result["execution_continuity"]=copy.deepcopy(request["execution_continuity"])
    validate_checkpoint_24(result,adapter)
    return result
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("base_checkpoint");p.add_argument("request");p.add_argument("--adapter",required=True);a=p.parse_args(argv)
    try:r=build(load_yaml(a.base_checkpoint,frontmatter=True),json.loads(Path(a.request).read_text(encoding="utf-8")),load_yaml(a.adapter))
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:print(f"FAIL: {exc}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
