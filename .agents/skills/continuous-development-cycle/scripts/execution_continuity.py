#!/usr/bin/env python3
"""CDC 2.4 hard execution-continuity completion gate."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

PRIMITIVE_STEPS = {
    "status_read", "health_check", "lease_check",
    "poll_without_transition", "report_only", "heartbeat", "lease_renewal",
}
STATES = {
    "BOOTSTRAP", "RECONCILE", "OWNERSHIP", "EXECUTE", "VALIDATE",
    "CHECKPOINT", "CONTINUE", "WAIT_EXTERNAL", "BLOCKED", "COMPLETE",
}
OUTCOMES = {
    "continue", "progress", "waiting_external", "blocked",
    "task_complete", "scope_complete",
}

def _text(value, name, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")

def validate(state):
    required = {
        "schema", "invocation_id", "current_state", "requested_terminal_outcome",
        "runnable_next_action", "meaningful_progress_refs", "primitive_steps",
        "external_binding", "blocker", "checkpoint_ref", "next_action",
        "lease_release_required", "lease_released",
    }
    if not isinstance(state, dict) or set(state) != required:
        raise ValueError("execution continuity state has missing/unknown fields")
    if state["schema"] != "execution-continuity/v1":
        raise ValueError("unsupported execution continuity schema")
    _text(state["invocation_id"], "invocation_id")
    if state["current_state"] not in STATES:
        raise ValueError("unknown current_state")
    if state["requested_terminal_outcome"] not in OUTCOMES:
        raise ValueError("unknown requested_terminal_outcome")
    for name in ("runnable_next_action", "lease_release_required", "lease_released"):
        if type(state[name]) is not bool:
            raise ValueError(f"{name} must be boolean")
    if not isinstance(state["meaningful_progress_refs"], list):
        raise ValueError("meaningful_progress_refs must be a list")
    for ref in state["meaningful_progress_refs"]:
        _text(ref, "meaningful progress reference")
    if len(set(state["meaningful_progress_refs"])) != len(state["meaningful_progress_refs"]):
        raise ValueError("duplicate meaningful progress reference")
    if not isinstance(state["primitive_steps"], list):
        raise ValueError("primitive_steps must be a list")
    for step in state["primitive_steps"]:
        if step not in PRIMITIVE_STEPS:
            raise ValueError(f"unknown primitive step: {step}")
    binding = state["external_binding"]
    if binding is not None:
        if not isinstance(binding, dict) or set(binding) != {"kind", "id", "operation_key"}:
            raise ValueError("external_binding requires kind/id/operation_key")
        for name in ("kind", "id", "operation_key"):
            _text(binding[name], f"external_binding.{name}")
    _text(state["blocker"], "blocker", nullable=True)
    _text(state["checkpoint_ref"], "checkpoint_ref", nullable=True)
    _text(state["next_action"], "next_action", nullable=True)
    return state

def evaluate(state):
    validate(state)
    outcome = state["requested_terminal_outcome"]
    progress = bool(state["meaningful_progress_refs"])
    external = state["external_binding"] is not None
    blocked = state["blocker"] is not None
    primitive_only = bool(state["primitive_steps"]) and not progress
    if outcome == "continue":
        return {"allowed": True, "reason": "continue_execution", "next_state": "EXECUTE"}
    if state["lease_release_required"] and not state["lease_released"]:
        return {"allowed": False, "reason": "owned_lease_not_released", "next_state": "CHECKPOINT"}
    if state["checkpoint_ref"] is None:
        return {"allowed": False, "reason": "terminal_outcome_requires_checkpoint", "next_state": "CHECKPOINT"}
    if state["runnable_next_action"] and not blocked and not external and not progress:
        return {"allowed": False, "reason": "primitive_only_completion", "next_state": "EXECUTE"}
    if primitive_only and outcome == "progress":
        return {"allowed": False, "reason": "progress_outcome_without_meaningful_progress", "next_state": "EXECUTE"}
    if outcome == "progress":
        if not progress:
            return {"allowed": False, "reason": "progress_outcome_requires_progress", "next_state": "EXECUTE"}
        return {"allowed": True, "reason": "meaningful_repository_progress", "next_state": "CONTINUE"}
    if outcome == "waiting_external":
        if not external:
            return {"allowed": False, "reason": "waiting_external_requires_durable_binding", "next_state": "CHECKPOINT"}
        return {"allowed": True, "reason": "durable_external_binding", "next_state": "WAIT_EXTERNAL"}
    if outcome == "blocked":
        if not blocked or state["next_action"] is None:
            return {"allowed": False, "reason": "blocked_requires_blocker_and_next_action", "next_state": "CHECKPOINT"}
        return {"allowed": True, "reason": "resumable_blocker", "next_state": "BLOCKED"}
    if outcome in {"task_complete", "scope_complete"}:
        if state["runnable_next_action"] or external or blocked:
            return {"allowed": False, "reason": "complete_conflicts_with_runnable_or_waiting_work", "next_state": "RECONCILE"}
        if not progress:
            return {"allowed": False, "reason": "complete_requires_terminal_evidence", "next_state": "VALIDATE"}
        return {"allowed": True, "reason": outcome, "next_state": "COMPLETE"}
    raise AssertionError(outcome)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("state")
    args = p.parse_args(argv)
    try:
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        result = evaluate(state)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
