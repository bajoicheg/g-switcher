"""Explicit terminal evidence for successful lifecycle tests."""
from datetime import datetime, timezone


def with_terminal_evidence(state, at=None):
    outcome = state["requested_terminal_outcome"]
    decision = {"waiting_external": "WAIT_EXTERNAL", "blocked": "BLOCKED",
                "task_complete": "COMPLETE", "scope_complete": "COMPLETE"}[outcome]
    terminal = dict(schema="terminal-state/v2", invocation_id=state["invocation_id"],
                    scope_id="authorized-test-scope", observed_head="a" * 40, decision=decision,
                    runnable_actions=[], pending_external=None, blocker=None,
                    meaningful_progress_refs=state["meaningful_progress_refs"],
                    completion_evidence_refs=[], checkpoint_ref=state["checkpoint_ref"],
                    lease_released=state["lease_released"])
    if decision == "COMPLETE":
        state["next_action"] = None
        terminal["completion_evidence_refs"] = ["scope:all-required-tasks-verified"]
    elif decision == "WAIT_EXTERNAL":
        terminal["pending_external"] = dict(state["external_binding"], state="running",
                                            recheck_action=state["next_action"])
    else:
        proof = dict(schema="blocked-state-proof/v1", dependency_id="required-credential",
                     category="access", observed_at_utc=at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                     max_age_seconds=300, evidence_refs=["provider:verified-access-failure"],
                     next_action=state["next_action"], recheck_trigger="credential-change",
                     same_invocation_work_exhausted=True)
        state["blocker_proof"] = proof
        terminal["blocker"] = dict(code=proof["dependency_id"], evidence_refs=proof["evidence_refs"],
                                  next_action=proof["next_action"], recheck_trigger=proof["recheck_trigger"])
    state["terminal_state"] = terminal
    return state
