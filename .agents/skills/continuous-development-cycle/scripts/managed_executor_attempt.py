#!/usr/bin/env python3
"""CDC 2.11.0 durable managed-executor attempt and result contract."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import re
import sys
from pathlib import Path

from parallel_task_planner import validate_write_path, portable_path_key

ATTEMPT_SCHEMA = "managed-executor-attempt/v1"
RESULT_SCHEMA = "managed-executor-result/v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
ROLES = {"writer", "read_only", "review"}
STATUSES = {"planned", "queued", "running", "succeeded", "failed", "cancelled", "stale"}
ACTIVE_STATUSES = {"planned", "queued", "running"}
TERMINAL_STATUSES = STATUSES - ACTIVE_STATUSES
AUTHORITY_FIELDS = (
    "authorizes_shared_branch_write",
    "authorizes_merge",
    "authorizes_release",
    "authorizes_scope_expansion",
    "authorizes_scheduler_mutation",
    "authorizes_user_approval",
)
ATTEMPT_FIELDS = {
    "schema", "pool_id", "change_id", "task_id", "attempt_id", "predecessor_attempt_id",
    "parent_invocation_id", "executor_id", "backend", "role", "base_sha", "branch",
    "worktree", "write_paths", "status", "created_at_utc", "started_at_utc",
    "heartbeat_at_utc", "finished_at_utc", "activity_refs", "failure",
}
RESULT_FIELDS = {
    "schema", "pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id",
    "role", "base_sha", "result_commit", "changed_paths", "evidence_refs",
    "completed_at_utc", "integrated", *AUTHORITY_FIELDS,
}


def _text(value, name, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _sha(value, name, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase SHA")


def _timestamp(value, name, nullable=False):
    if value is None and nullable:
        return None
    _text(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include timezone")
    return parsed.astimezone(timezone.utc)


def _refs(value, name, allow_empty=False):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{name} must be a list of nonempty strings")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} contains duplicates")
    return value


def _portable_unique(paths, name):
    if not isinstance(paths, list):
        raise ValueError(f"{name} must be a list")
    keys = []
    for path in paths:
        validate_write_path(path)
        keys.append(portable_path_key(path))
    if len(keys) != len(set(keys)):
        raise ValueError(f"{name} contains portable aliases")
    return paths


def _false_authority(record):
    for name in AUTHORITY_FIELDS:
        if type(record[name]) is not bool or record[name]:
            raise ValueError(f"{name} must be false")


def validate_attempt(attempt):
    if not isinstance(attempt, dict) or set(attempt) != ATTEMPT_FIELDS or attempt.get("schema") != ATTEMPT_SCHEMA:
        raise ValueError("managed executor attempt fields/schema mismatch")
    for name in ("pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id", "executor_id", "backend"):
        _text(attempt[name], name)
    _text(attempt["predecessor_attempt_id"], "predecessor_attempt_id", nullable=True)
    if attempt["predecessor_attempt_id"] == attempt["attempt_id"]:
        raise ValueError("attempt cannot be its own predecessor")
    if attempt["role"] not in ROLES:
        raise ValueError("unsupported executor role")
    _sha(attempt["base_sha"], "base_sha")
    if attempt["status"] not in STATUSES:
        raise ValueError("unsupported attempt status")
    _portable_unique(attempt["write_paths"], "write_paths")
    if attempt["role"] == "writer":
        _text(attempt["branch"], "branch")
        _text(attempt["worktree"], "worktree")
        if not attempt["write_paths"]:
            raise ValueError("writer attempt requires write_paths")
    else:
        if attempt["branch"] is not None or attempt["worktree"] is not None or attempt["write_paths"]:
            raise ValueError("read_only/review attempt cannot claim writer isolation or writes")
    created = _timestamp(attempt["created_at_utc"], "created_at_utc")
    started = _timestamp(attempt["started_at_utc"], "started_at_utc", nullable=True)
    heartbeat = _timestamp(attempt["heartbeat_at_utc"], "heartbeat_at_utc", nullable=True)
    finished = _timestamp(attempt["finished_at_utc"], "finished_at_utc", nullable=True)
    _refs(attempt["activity_refs"], "activity_refs", allow_empty=True)
    _text(attempt["failure"], "failure", nullable=True)
    if started is not None and started < created:
        raise ValueError("started_at_utc predates attempt creation")
    if heartbeat is not None and (started is None or heartbeat < started):
        raise ValueError("heartbeat requires a started attempt")
    if finished is not None and finished < (heartbeat or started or created):
        raise ValueError("finished_at_utc predates latest attempt activity")
    status = attempt["status"]
    if status in {"planned", "queued"}:
        if started is not None or heartbeat is not None or finished is not None or attempt["failure"] is not None:
            raise ValueError(f"{status} attempt cannot contain runtime/terminal fields")
    elif status == "running":
        if started is None or heartbeat is None or finished is not None or attempt["failure"] is not None:
            raise ValueError("running attempt requires start+heartbeat and no terminal fields")
        if not attempt["activity_refs"]:
            raise ValueError("running attempt requires observable activity")
    elif status == "succeeded":
        if started is None or heartbeat is None or finished is None or attempt["failure"] is not None:
            raise ValueError("succeeded attempt requires runtime timestamps and no failure")
    elif status == "failed":
        if finished is None or attempt["failure"] is None:
            raise ValueError("failed attempt requires finished_at_utc and failure")
    elif status == "stale":
        if finished is None or attempt["failure"] is None:
            raise ValueError("stale attempt requires finished_at_utc and reason")
    elif status == "cancelled":
        if finished is None:
            raise ValueError("cancelled attempt requires finished_at_utc")
    return attempt


def new_attempt(*, pool_id, change_id, task_id, attempt_id, parent_invocation_id,
                executor_id, backend, role, base_sha, at_utc, write_paths=None,
                branch=None, worktree=None, predecessor_attempt_id=None):
    record = {
        "schema": ATTEMPT_SCHEMA,
        "pool_id": pool_id,
        "change_id": change_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "predecessor_attempt_id": predecessor_attempt_id,
        "parent_invocation_id": parent_invocation_id,
        "executor_id": executor_id,
        "backend": backend,
        "role": role,
        "base_sha": base_sha,
        "branch": branch,
        "worktree": worktree,
        "write_paths": list(write_paths or []),
        "status": "planned",
        "created_at_utc": at_utc,
        "started_at_utc": None,
        "heartbeat_at_utc": None,
        "finished_at_utc": None,
        "activity_refs": [],
        "failure": None,
    }
    return validate_attempt(record)


def _move_time(record, at_utc):
    at = _timestamp(at_utc, "transition time")
    latest = _timestamp(record["heartbeat_at_utc"], "heartbeat_at_utc", nullable=True) or _timestamp(
        record["started_at_utc"], "started_at_utc", nullable=True) or _timestamp(record["created_at_utc"], "created_at_utc")
    if at < latest:
        raise ValueError("attempt transition cannot move backwards in time")
    return at


def transition(attempt, to_status, at_utc, *, activity_ref=None, failure=None):
    validate_attempt(attempt)
    allowed = {
        "planned": {"queued", "cancelled"},
        "queued": {"running", "failed", "cancelled", "stale"},
        "running": {"succeeded", "failed", "cancelled", "stale"},
    }
    current = attempt["status"]
    if current not in allowed or to_status not in allowed[current]:
        raise ValueError(f"illegal attempt transition {current}->{to_status}")
    _move_time(attempt, at_utc)
    result = copy.deepcopy(attempt)
    if activity_ref is not None:
        _text(activity_ref, "activity_ref")
        if activity_ref in result["activity_refs"]:
            raise ValueError("activity_ref must identify new observable activity")
        result["activity_refs"].append(activity_ref)
    if to_status == "running":
        if activity_ref is None:
            raise ValueError("running transition requires observable activity_ref")
        result["started_at_utc"] = at_utc
        result["heartbeat_at_utc"] = at_utc
    if to_status in TERMINAL_STATUSES:
        result["finished_at_utc"] = at_utc
        if to_status in {"failed", "stale"}:
            _text(failure, "failure")
            result["failure"] = failure
        elif failure is not None:
            _text(failure, "failure")
            result["failure"] = failure
    result["status"] = to_status
    return validate_attempt(result)


def heartbeat(attempt, at_utc, *, activity_ref):
    validate_attempt(attempt)
    if attempt["status"] != "running":
        raise ValueError("heartbeat requires running attempt")
    _move_time(attempt, at_utc)
    _text(activity_ref, "activity_ref")
    if activity_ref in attempt["activity_refs"]:
        raise ValueError("heartbeat requires unique observable activity")
    result = copy.deepcopy(attempt)
    result["heartbeat_at_utc"] = at_utc
    result["activity_refs"].append(activity_ref)
    return validate_attempt(result)


def retry(previous, *, attempt_id, executor_id, backend, at_utc, branch=None, worktree=None):
    validate_attempt(previous)
    if previous["status"] not in {"failed", "cancelled", "stale"}:
        raise ValueError("retry requires failed/cancelled/stale predecessor")
    if attempt_id == previous["attempt_id"]:
        raise ValueError("retry requires a new attempt_id")
    return new_attempt(
        pool_id=previous["pool_id"], change_id=previous["change_id"], task_id=previous["task_id"],
        attempt_id=attempt_id, predecessor_attempt_id=previous["attempt_id"],
        parent_invocation_id=previous["parent_invocation_id"], executor_id=executor_id,
        backend=backend, role=previous["role"], base_sha=previous["base_sha"], at_utc=at_utc,
        write_paths=previous["write_paths"],
        branch=branch if previous["role"] == "writer" else None,
        worktree=worktree if previous["role"] == "writer" else None,
    )


def assert_no_duplicate_active(attempts):
    seen = {}
    for attempt in attempts:
        validate_attempt(attempt)
        if attempt["status"] not in ACTIVE_STATUSES:
            continue
        key = (attempt["pool_id"], attempt["task_id"])
        if key in seen:
            raise ValueError(
                f"duplicate active launch for pool/task {key[0]}/{key[1]}: "
                f"{seen[key]} and {attempt['attempt_id']}"
            )
        seen[key] = attempt["attempt_id"]
    return True


def _changed_within_claim(changed, claim):
    changed_key = portable_path_key(changed)
    claim_key = portable_path_key(claim)
    return changed_key == claim_key or changed_key.startswith(claim_key + "/")


def validate_result(result, attempt):
    validate_attempt(attempt)
    if attempt["status"] != "succeeded":
        raise ValueError("result requires succeeded attempt")
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS or result.get("schema") != RESULT_SCHEMA:
        raise ValueError("managed executor result fields/schema mismatch")
    for field in ("pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id"):
        if result[field] != attempt[field]:
            raise ValueError(f"result {field} does not match attempt")
    if result["role"] != attempt["role"] or result["base_sha"] != attempt["base_sha"]:
        raise ValueError("result role/base does not match attempt")
    _timestamp(result["completed_at_utc"], "completed_at_utc")
    if _timestamp(result["completed_at_utc"], "completed_at_utc") < _timestamp(attempt["finished_at_utc"], "finished_at_utc"):
        raise ValueError("result completion predates attempt success")
    _refs(result["evidence_refs"], "evidence_refs")
    _portable_unique(result["changed_paths"], "changed_paths")
    if type(result["integrated"]) is not bool or result["integrated"]:
        raise ValueError("worker result must remain unintegrated")
    _false_authority(result)
    if attempt["role"] == "writer":
        _sha(result["result_commit"], "result_commit")
        if not result["changed_paths"]:
            raise ValueError("writer result requires changed_paths")
        for changed in result["changed_paths"]:
            if not any(_changed_within_claim(changed, claim) for claim in attempt["write_paths"]):
                raise ValueError(f"changed path escapes declared write set: {changed}")
    else:
        if result["result_commit"] is not None or result["changed_paths"]:
            raise ValueError("read_only/review result cannot claim repository changes")
    return result


def acceptance(result, attempt):
    validate_result(result, attempt)
    return {
        "schema": "managed-executor-result-acceptance/v1",
        "pool_id": result["pool_id"],
        "task_id": result["task_id"],
        "attempt_id": result["attempt_id"],
        "accepted": True,
        "integrated": False,
        "evidence_refs": list(result["evidence_refs"]),
        **{name: False for name in AUTHORITY_FIELDS},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempt")
    parser.add_argument("--result")
    args = parser.parse_args(argv)
    try:
        attempt = validate_attempt(json.loads(Path(args.attempt).read_text()))
        output = attempt if args.result is None else acceptance(json.loads(Path(args.result).read_text()), attempt)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
