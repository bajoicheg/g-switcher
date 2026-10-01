#!/usr/bin/env python3
"""CDC 2.4 checkpoint validator: v4 enforcement with v3 read compatibility."""
from __future__ import annotations
import argparse, copy
from contracts import ContractError, check, load_yaml, nonempty, nullable_text
import validate_checkpoint as legacy

EXECUTION_CONTINUITY_SCHEMA = {
    "invocation_id": nullable_text,
    "runnable_next_action": bool,
    "meaningful_progress": bool,
    "primitive_steps_since_progress": lambda v: type(v) is int and v >= 0,
    "completion_gate": ("continue", "meaningful_progress", "durable_external_binding",
                        "resumable_blocker", "task_complete", "scope_complete"),
    "last_progress_ref": nullable_text,
}
V4_EXTRA = {"resume_capsule_ref": nonempty, "execution_continuity": EXECUTION_CONTINUITY_SCHEMA}

def validate_checkpoint_24(data, adapter):
    if not isinstance(data, dict):
        raise ContractError("checkpoint must be a mapping")
    if data.get("schema") == "development-work-status/v3":
        return legacy.validate_checkpoint(data, adapter)
    if data.get("schema") != "development-work-status/v4":
        raise ContractError("unsupported checkpoint schema")
    expected = set(legacy.SCHEMA) | set(V4_EXTRA)
    if "control" in data: expected.add("control")
    missing, unknown = expected - set(data), set(data) - expected
    if missing: raise ContractError("checkpoint: missing fields: " + ", ".join(sorted(missing)))
    if unknown: raise ContractError("checkpoint: unknown fields: " + ", ".join(sorted(unknown)))
    base = {k: copy.deepcopy(v) for k, v in data.items() if k not in V4_EXTRA}
    base["schema"] = "development-work-status/v3"
    binding = legacy.validate_checkpoint(base, adapter)
    check(data["execution_continuity"], EXECUTION_CONTINUITY_SCHEMA, "checkpoint.execution_continuity")
    ec = data["execution_continuity"]
    external = data["lease_state"] == "waiting_external" or data["phase"] == "waiting_external"
    blocked = data["blocker"].strip().lower() not in {"none", "no blocker", "n/a", "-"}
    released = data["lease_state"] == "released"
    if data["lease_state"] == "active" and not ec["invocation_id"]:
        raise ContractError("active v4 checkpoint requires execution_continuity.invocation_id")
    if ec["completion_gate"] == "meaningful_progress":
        if not ec["meaningful_progress"] or not ec["last_progress_ref"]:
            raise ContractError("meaningful_progress gate requires progress and durable reference")
    if ec["completion_gate"] == "durable_external_binding" and not external:
        raise ContractError("durable_external_binding gate requires external wait")
    if ec["completion_gate"] == "resumable_blocker" and (not blocked or not data["next_action"]):
        raise ContractError("resumable_blocker gate requires blocker and next_action")
    if ec["completion_gate"] in {"task_complete", "scope_complete"}:
        if data["phase"] != "complete" or ec["runnable_next_action"]:
            raise ContractError("complete gate requires complete phase and no runnable next action")
    if ec["completion_gate"] == "continue" and data["phase"] == "complete":
        raise ContractError("continue gate conflicts with complete phase")
    if released and ec["runnable_next_action"] and not external and not blocked and not ec["meaningful_progress"]:
        raise ContractError("released runnable checkpoint cannot be primitive-only")
    if released and ec["primitive_steps_since_progress"] > 1 and ec["runnable_next_action"] and not external and not blocked:
        raise ContractError("released runnable checkpoint exceeds primitive-step continuity budget")
    return binding

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint"); p.add_argument("--adapter",required=True)
    args=p.parse_args(argv)
    try:
        data=load_yaml(args.checkpoint,frontmatter=True)
        validate_checkpoint_24(data,load_yaml(args.adapter))
    except (ContractError,OSError,UnicodeError) as exc:
        print(f"FAIL: {exc}"); return 1
    version="v4" if data.get("schema")=="development-work-status/v4" else "v3-compat"
    print(f"PASS: CDC 2.4 checkpoint {version}; remote observations still required")
    return 0

if __name__=="__main__": raise SystemExit(main())
