#!/usr/bin/env python3
"""Validate checkpoint state and its policy binding; never infer remote liveness."""
import argparse
import re
import uuid
from contracts import (ContractError, check, digest, load_yaml, nonempty, nullable_text, sha, utc)
from validate_adapter import validate_adapter

HASH = lambda v: isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) is not None
OPTIONAL_HASH = lambda v: v is None or HASH(v)
OPERATION_KEY = lambda v: v is None or (isinstance(v, str) and v.startswith("sha256:") and HASH(v[7:]))
OPTIONAL_TIME = lambda v: v is None or utc(v)
MAYBE_SHA = lambda v: v == "" or sha(v)
SCHEMA = {
    "schema": ("development-work-status/v3",), "repository": nonempty, "branch": str,
    "policy_revision": nonempty, "policy_digest": OPTIONAL_HASH,
    "observed_at_utc": lambda v: v == "" or utc(v),
    "orchestration_origin": ("chat", "work", "codex_orchestrator", "unknown"),
    "active_executor": nonempty, "lease_state": ("released", "active", "waiting_external"),
    "executor_heartbeat_at_utc": OPTIONAL_TIME, "execution_lease_until_utc": OPTIONAL_TIME,
    "waiting_external_kind": nullable_text, "waiting_external_id": nullable_text,
    "waiting_external_sha": lambda v: v is None or sha(v),
    "operation_intent_ref": nullable_text, "operation_key": OPERATION_KEY,
    "active_change": str, "current_task": str,
    "phase": ("recovery", "red", "implementation", "validation", "review", "final_gate",
              "waiting_external", "release", "complete", "blocked"),
    "implementation_sha": MAYBE_SHA, "candidate_sha": MAYBE_SHA, "last_green_sha": MAYBE_SHA,
    "last_green_evidence": str, "active_compute": str, "active_ci_run_id": str,
    "last_ci_run_id": str, "last_ci_status": str, "release_version": str,
    "release_candidate_sha": MAYBE_SHA, "release_state": ("not-started", "candidate", "validating", "released", "blocked"),
    "blocker": nonempty, "next_action": nonempty,
}

CONTROL_SCHEMA = {
    "execution_lease_ref": nullable_text,
    "execution_lease_revision": lambda v: v is None or sha(v),
    "executor_id": nullable_text,
    "lease_generation": lambda v: v is None or (type(v) is int and v >= 0),
    "budget_ref": nullable_text,
    "recovery_snapshot_ref": nullable_text,
    "external_wait_ref": nullable_text,
}


def validate_checkpoint(data, adapter):
    binding = validate_adapter(adapter)
    schema = dict(SCHEMA)
    if isinstance(data, dict) and "control" in data:
        schema["control"] = CONTROL_SCHEMA
    check(data, schema, "checkpoint")
    if "control" in data:
        if "orchestration" not in adapter:
            raise ContractError("checkpoint control pointers require adapter orchestration policy")
        control = data["control"]
        if control["executor_id"] is not None:
            try:
                if str(uuid.UUID(control["executor_id"])) != control["executor_id"]:
                    raise ValueError("non-canonical executor id")
            except ValueError as exc:
                raise ContractError("checkpoint executor_id must be a canonical UUID") from exc
        if control["execution_lease_revision"] is not None and (not control["execution_lease_ref"] or
                                                               control["lease_generation"] is None):
            raise ContractError("lease revision requires lease reference and generation")
    if data["repository"] != adapter["repository"]["remote"]:
        raise ContractError("checkpoint repository differs from adapter; reconcile identity")
    if data["policy_revision"] != binding["policy_revision"]:
        raise ContractError("checkpoint policy revision is stale; reconcile before updating binding")
    if data["policy_digest"] is None:
        if data["phase"] != "recovery":
            raise ContractError("unbound policy is allowed only in recovery")
    elif data["policy_digest"] != binding["policy_digest"]:
        raise ContractError("checkpoint policy digest is stale; reconcile before updating binding")
    if data["phase"] not in ("recovery", "blocked") and not all(
            data[name] for name in ("candidate_sha", "branch", "observed_at_utc")):
        raise ContractError("active phase requires candidate SHA, branch and observation timestamp")
    if data["lease_state"] == "active" and (data["active_executor"] == "none" or not all(
            data[name] for name in ("executor_heartbeat_at_utc", "execution_lease_until_utc"))):
        raise ContractError("active lease requires owner and timestamps")
    external = data["lease_state"] == "waiting_external" or data["phase"] == "waiting_external"
    if external and data["phase"] == "complete":
        raise ContractError("complete conflicts with an active external wait; reconcile it first")
    if external:
        if not all(data[name] for name in ("waiting_external_kind", "waiting_external_sha",
                                          "operation_intent_ref", "operation_key")):
            raise ContractError("external wait requires kind, exact SHA and durable operation intent/key")
        if data["waiting_external_sha"] != data["candidate_sha"]:
            raise ContractError("external task SHA differs from candidate; preserve original binding")
    if data["phase"] == "complete" and (not data["last_green_evidence"] or
                                           data["last_green_sha"] != data["candidate_sha"]):
        raise ContractError("complete requires GREEN evidence for the candidate; revalidate gates")
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("--adapter", required=True)
    args = parser.parse_args()
    try:
        validate_checkpoint(load_yaml(args.checkpoint, frontmatter=True), load_yaml(args.adapter))
    except (ContractError, OSError, UnicodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print("PASS: checkpoint v3 structure and policy binding; remote observations still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
