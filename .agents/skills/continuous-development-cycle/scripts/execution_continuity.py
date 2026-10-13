#!/usr/bin/env python3
"""CDC 2.4 hard execution-continuity completion gate."""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
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
    optional = {"terminal_state", "blocker_proof"}
    if not isinstance(state, dict) or not required <= set(state) or set(state) - required - optional:
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

def _terminal_evidence(state, now_utc):
    """Require the same terminal contract as the conversational final-response path."""
    from terminal_state_v2 import evaluate as terminal_evaluate
    from blocker_proof import assess
    terminal = state.get("terminal_state")
    if not isinstance(terminal, dict):
        return "terminal_state_evidence_required"
    expected = {"waiting_external": "WAIT_EXTERNAL", "blocked": "BLOCKED",
                "task_complete": "COMPLETE", "scope_complete": "COMPLETE"}
    if (terminal.get("decision") != expected[state["requested_terminal_outcome"]]
            or terminal.get("invocation_id") != state["invocation_id"]
            or terminal.get("checkpoint_ref") != state["checkpoint_ref"]
            or terminal.get("lease_released") != state["lease_released"]
            or bool(terminal.get("runnable_actions")) != state["runnable_next_action"]):
        return "terminal_state_binding_mismatch"
    # This pre-release assessment skips only release itself. mark_ready/release
    # still enforce the real owner and transaction; no record is rewritten here.
    result = terminal_evaluate(terminal, pre_release=not state["lease_release_required"])
    if not result["allowed"]:
        return result["reason"]
    if terminal["decision"] == "COMPLETE":
        if state["next_action"] is not None:
            return "completion_cannot_retain_next_action"
        if set(terminal["completion_evidence_refs"]) <= set(state["meaningful_progress_refs"]):
            return "distinct_scope_completion_evidence_required"
    elif terminal["decision"] == "WAIT_EXTERNAL":
        pending = terminal["pending_external"]
        if ({k: pending[k] for k in ("kind", "id", "operation_key")} != state["external_binding"]
                or pending["recheck_action"] != state["next_action"]):
            return "external_binding_or_next_action_mismatch"
    else:
        proof = state.get("blocker_proof")
        assess(proof, now_utc)
        blocker = terminal["blocker"]
        if (blocker["code"] != proof["dependency_id"]
                or blocker["evidence_refs"] != proof["evidence_refs"]
                or blocker["next_action"] != proof["next_action"]
                or blocker["recheck_trigger"] != proof["recheck_trigger"]
                or state["next_action"] != proof["next_action"]):
            return "blocker_proof_binding_mismatch"
    return None


def evaluate(state, *, now_utc=None):
    validate(state)
    outcome = state["requested_terminal_outcome"]
    progress = bool(state["meaningful_progress_refs"])
    external = state["external_binding"] is not None
    blocked = state["blocker"] is not None
    def result(allowed, reason, next_state, final=False):
        return {"allowed": allowed, "reason": reason, "next_state": next_state,
                "final_response_allowed": final}

    if outcome == "continue":
        return result(True, "continue_execution", "EXECUTE")
    # Progress is evidence of work, never evidence that the requested scope ended.
    # An unrelated wait/blocker must not hide another eligible local action.
    if state["runnable_next_action"]:
        return result(False, "runnable_work_requires_continuation", "EXECUTE")
    if outcome == "progress":
        return result(False, "progress_is_not_terminal", "CONTINUE")
    if state["lease_release_required"] and not state["lease_released"]:
        return result(False, "owned_lease_not_released", "CHECKPOINT")
    if state["checkpoint_ref"] is None:
        return result(False, "terminal_outcome_requires_checkpoint", "CHECKPOINT")
    if outcome == "waiting_external" and state["next_action"] is None:
        return result(False, "waiting_external_requires_next_action", "CHECKPOINT")
    now_utc = now_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        evidence_error = _terminal_evidence(state, now_utc)
    except (ValueError, KeyError, TypeError) as exc:
        evidence_error = "invalid_terminal_evidence: " + str(exc)
    if evidence_error:
        return result(False, evidence_error, "RECONCILE")
    if outcome == "waiting_external":
        if not external:
            return result(False, "waiting_external_requires_durable_binding", "CHECKPOINT")
        return result(True, "durable_external_binding", "WAIT_EXTERNAL", final=True)
    if outcome == "blocked":
        if not blocked or state["next_action"] is None:
            return result(False, "blocked_requires_blocker_and_next_action", "CHECKPOINT")
        return result(True, "resumable_blocker", "BLOCKED", final=True)
    if outcome in {"task_complete", "scope_complete"}:
        if state["runnable_next_action"] or external or blocked:
            return result(False, "complete_conflicts_with_runnable_or_waiting_work", "RECONCILE")
        if not progress:
            return result(False, "complete_requires_terminal_evidence", "VALIDATE")
        return result(True, outcome, "COMPLETE", final=True)
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
