#!/usr/bin/env python3
"""Local intent records and read-only recovery decisions; never submits work.

An existing single-writer lease is required. Atomic local file replacement is
neither a distributed lock nor proof of durable remote persistence.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


SCHEMA = "operation-intent/v1"
SKILL_VERSION = "2.3.0"
SUPPORTED_PRODUCER_VERSIONS = {"2.2.0", "2.3.0"}
BINDING_FIELDS = {
    "repository", "candidate_sha", "backend", "mode", "environment_id",
    "check_suite_fingerprint", "environment_fingerprint", "check_plan_digest",
}
INTENT_FIELDS = {
    "schema", "skill_version", "operation_key", "attempt_id", "binding",
    "source_ref", "state", "created_at_utc", "updated_at_utc", "durable_intent", "task",
}
TASK_FIELDS = {
    "task_id", "task_url", "operation_key", "attempt_id", "binding", "state",
    "conclusion", "evidence_refs",
}
RECEIPT_FIELDS = {
    "schema", "operation_key", "attempt_id", "record_digest", "reference", "read_back_at_utc",
}
TRANSITIONS = {
    "prepared": {"submitting"},
    "submitting": {"accepted", "unknown", "terminal"},
    "unknown": {"accepted", "terminal"},
    "accepted": {"terminal"},
    "terminal": set(),
}
ACTIVE_TASK_STATES = {"accepted", "queued", "running"}
CONCLUSIONS = {"succeeded", "failed", "cancelled", "timed_out", "setup_failed"}


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} must be an object with exactly: {', '.join(sorted(fields))}")


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a nonempty string without surrounding whitespace or control characters")


def _timestamp(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise ValueError(f"{label} must be a UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid timestamp") from exc


def _digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be sha256: followed by 64 lowercase hex digits")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(value):
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _binding(value):
    _object(value, BINDING_FIELDS, "binding")
    for field in BINDING_FIELDS:
        _text(value[field], "binding." + field)
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value["candidate_sha"]):
        raise ValueError("binding.candidate_sha must be a full lowercase 40- or 64-character Git SHA")
    for field in ("check_suite_fingerprint", "environment_fingerprint", "check_plan_digest"):
        _digest(value[field], "binding." + field)


def operation_key(binding):
    """Hash the exact canonical execution contract; attempts and source refs are separate."""
    _binding(binding)
    return _hash({"schema": SCHEMA, "binding": binding})


def _task(task):
    _object(task, TASK_FIELDS, "task")
    for field in ("task_id", "task_url", "attempt_id"):
        _text(task[field], "task." + field)
    _digest(task["operation_key"], "task.operation_key")
    _binding(task["binding"])
    if not isinstance(task["state"], str) or task["state"] not in ACTIVE_TASK_STATES | {"terminal", "unknown"}:
        raise ValueError("task.state is not a supported provider state")
    if task["state"] == "terminal":
        if not isinstance(task["conclusion"], str) or task["conclusion"] not in CONCLUSIONS:
            raise ValueError("terminal task.conclusion is required and must be a supported outcome")
    elif task["conclusion"] is not None:
        raise ValueError("non-terminal task.conclusion must be null")
    if not isinstance(task["evidence_refs"], list):
        raise ValueError("task.evidence_refs must be a list")
    for ref in task["evidence_refs"]:
        _text(ref, "task.evidence_refs entry")


def _matches(intent, task):
    return all(task[field] == intent[field] for field in ("operation_key", "attempt_id", "binding"))


def _prepared_copy(intent):
    result = copy.deepcopy(intent)
    result.update(state="prepared", updated_at_utc=result["created_at_utc"], durable_intent=None, task=None)
    return result


def _receipt(receipt, intent):
    _object(receipt, RECEIPT_FIELDS, "durable readback receipt")
    if receipt["schema"] != "operation-intent-readback/v1":
        raise ValueError("invalid readback receipt schema")
    for field in ("operation_key", "attempt_id"):
        if receipt[field] != intent[field]:
            raise ValueError(f"readback receipt {field} does not match intent")
    _text(receipt["reference"], "readback receipt reference")
    _digest(receipt["record_digest"], "readback receipt record_digest")
    if receipt["record_digest"] != _hash(_prepared_copy(intent)):
        raise ValueError("readback receipt record_digest does not match the prepared intent")
    observed = _timestamp(receipt["read_back_at_utc"], "read_back_at_utc")
    if observed < _timestamp(intent["created_at_utc"], "created_at_utc"):
        raise ValueError("readback timestamp is earlier than intent creation")
    return observed


def validate_intent(intent):
    _object(intent, INTENT_FIELDS, "intent")
    if intent["schema"] != SCHEMA:
        raise ValueError("unsupported intent schema")
    if intent["skill_version"] not in SUPPORTED_PRODUCER_VERSIONS:
        raise ValueError("unsupported skill_version")
    _binding(intent["binding"])
    if intent["operation_key"] != operation_key(intent["binding"]):
        raise ValueError("operation_key does not match binding")
    _text(intent["attempt_id"], "attempt_id")
    _text(intent["source_ref"], "source_ref")
    state = intent["state"]
    if not isinstance(state, str) or state not in TRANSITIONS:
        raise ValueError("invalid intent state")
    created = _timestamp(intent["created_at_utc"], "created_at_utc")
    updated = _timestamp(intent["updated_at_utc"], "updated_at_utc")
    if updated < created:
        raise ValueError("updated_at_utc timestamp is earlier than created_at_utc")
    if state == "prepared":
        if intent["durable_intent"] is not None or intent["task"] is not None or updated != created:
            raise ValueError("prepared intent must have initial timestamps and null durable_intent/task")
    else:
        if _receipt(intent["durable_intent"], intent) > updated:
            raise ValueError("readback timestamp is later than updated_at_utc")
    if state in {"accepted", "terminal"}:
        _task(intent["task"])
        if not _matches(intent, intent["task"]):
            raise ValueError("task binding does not match intent")
        valid_states = ACTIVE_TASK_STATES if state == "accepted" else {"terminal"}
        if intent["task"]["state"] not in valid_states:
            raise ValueError("task state does not match intent state")
    elif intent["task"] is not None:
        raise ValueError("task must be null before accepted or terminal state")


def prepare(binding, attempt_id, source_ref, at):
    intent = {
        "schema": SCHEMA, "skill_version": SKILL_VERSION,
        "operation_key": operation_key(binding), "attempt_id": attempt_id,
        "binding": copy.deepcopy(binding), "source_ref": source_ref,
        "state": "prepared", "created_at_utc": at, "updated_at_utc": at,
        "durable_intent": None, "task": None,
    }
    validate_intent(intent)
    return intent


def verify_readback(intent, readback, reference, at):
    """Compare a caller-supplied durable-store readback; cannot authenticate its origin."""
    validate_intent(intent)
    validate_intent(readback)
    if _canonical(intent) != _canonical(readback):
        raise ValueError("durable readback does not match the complete intent")
    _text(reference, "readback reference")
    if _timestamp(at, "read_back_at_utc") < _timestamp(intent["updated_at_utc"], "updated_at_utc"):
        raise ValueError("readback timestamp is earlier than intent update")
    return {
        "schema": "operation-intent-readback/v1", "operation_key": intent["operation_key"],
        "attempt_id": intent["attempt_id"], "record_digest": _hash(intent),
        "reference": reference, "read_back_at_utc": at,
    }


def transition(intent, state, at, *, receipt=None, task=None):
    validate_intent(intent)
    if not isinstance(state, str) or state not in TRANSITIONS:
        raise ValueError("invalid transition target state")
    if _timestamp(at, "transition timestamp") < _timestamp(intent["updated_at_utc"], "updated_at_utc"):
        raise ValueError("transition timestamp is earlier than current intent")
    if state == intent["state"]:
        if (receipt is not None and receipt != intent["durable_intent"]) or (task is not None and task != intent["task"]):
            raise ValueError("repeated transition cannot change receipt or task")
        return copy.deepcopy(intent)
    if state not in TRANSITIONS[intent["state"]]:
        raise ValueError(f"invalid transition {intent['state']} -> {state}; reconcile before any new attempt")
    result = copy.deepcopy(intent)
    result.update(state=state, updated_at_utc=at)
    if state == "submitting":
        _receipt(receipt, intent)
        result["durable_intent"] = copy.deepcopy(receipt)
    elif receipt is not None:
        raise ValueError("readback receipt can only be supplied for the submitting transition")
    if state in {"accepted", "terminal"}:
        _task(task)
        if not _matches(intent, task):
            raise ValueError("task binding does not match intent")
        if intent["task"] is not None and intent["task"]["task_id"] != task["task_id"]:
            raise ValueError("cannot replace the known task_id")
        result["task"] = copy.deepcopy(task)
    elif task is not None:
        raise ValueError("task is only allowed for accepted or terminal transition")
    validate_intent(result)
    return result


def decide(intent, observation):
    """Read-only: uncertainty always keeps the external guard and never permits submit."""
    validate_intent(intent)
    _object(observation, {"schema", "operation_key", "lookup_complete", "observed_at_utc", "tasks"}, "observation")
    if observation["schema"] != "operation-observation/v1":
        raise ValueError("unsupported observation schema")
    if type(observation["lookup_complete"]) is not bool:
        raise ValueError("lookup_complete must be a boolean")
    if not isinstance(observation["tasks"], list):
        raise ValueError("observation.tasks must be a list")
    observed = _timestamp(observation["observed_at_utc"], "observed_at_utc")
    decision = {
        "action": "reconcile", "reason": "No confirmed task; preserve guard and reconcile provider facts.",
        "operation_key": intent["operation_key"], "attempt_id": intent["attempt_id"],
        "allow_submission": False, "external_guard": True, "completion_claim_allowed": False,
        "task_id": None, "terminal_outcome": None, "evidence_refs": [],
    }
    if observation["operation_key"] != intent["operation_key"] or observed < _timestamp(intent["updated_at_utc"], "updated_at_utc"):
        decision.update(action="blocked", reason="Observation scope or timestamp does not match the current intent.")
        return decision
    tasks = observation["tasks"]
    for task in tasks:
        _task(task)
    if len(tasks) > 1:
        decision.update(action="blocked", reason="Multiple candidate tasks require reconciliation; no task was selected.")
        return decision
    if tasks and not _matches(intent, tasks[0]):
        decision.update(action="blocked", reason="Task binding or attempt does not match the exact operation contract.")
        return decision
    if tasks and intent["task"] is not None and intent["task"]["task_id"] != tasks[0]["task_id"]:
        decision.update(action="blocked", reason="Observed task_id differs from the recorded task.")
        return decision
    if not observation["lookup_complete"]:
        decision["reason"] = "Provider lookup is incomplete or unavailable; preserve the external guard."
        return decision
    if not tasks:
        return decision
    task = tasks[0]
    decision["task_id"] = task["task_id"]
    if intent["state"] == "terminal" and task["state"] != "terminal":
        decision.update(action="blocked", reason="Provider state regressed from the recorded terminal result.")
    elif task["state"] in ACTIVE_TASK_STATES:
        decision.update(action="observe", reason="Observe the existing accepted or running task; retain its exact source SHA.")
    elif task["state"] == "terminal" and task["evidence_refs"]:
        if intent["state"] == "terminal" and intent["task"]["conclusion"] != task["conclusion"]:
            decision.update(action="blocked", reason="Provider terminal outcome conflicts with the recorded result.")
        else:
            decision.update(action="reuse_terminal", external_guard=False,
                            reason="Reuse this terminal outcome and evidence through normal evidence validation; it is not task completion.",
                            terminal_outcome=task["conclusion"], evidence_refs=copy.deepcopy(task["evidence_refs"]))
    else:
        decision["reason"] = "Task state or terminal evidence is incomplete; reconcile before proceeding."
    return decision


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _load(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_unique_object)


def write_intent(path, intent, *, expected=None):
    """Atomically publish locally, under the caller's existing single-writer lease."""
    validate_intent(intent)
    path = Path(path)
    if path.is_symlink():
        raise ValueError("refusing to overwrite an intent symlink")
    if expected is None:
        if path.exists():
            raise ValueError("intent output already exists; use transition on the existing record")
    else:
        validate_intent(expected)
        for field in INTENT_FIELDS - {"state", "updated_at_utc", "durable_intent", "task"}:
            if expected[field] != intent[field]:
                raise ValueError("cannot overwrite an unrelated intent or attempt")
        if not path.exists() or _load(path) != expected:
            raise ValueError("intent changed since read; stale expected record")
        allowed = transition(
            expected, intent["state"], intent["updated_at_utc"],
            receipt=intent["durable_intent"] if expected["state"] == "prepared" else None,
            task=intent["task"],
        )
        if allowed != intent:
            raise ValueError("intent update does not match an allowed transition")
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(intent, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if expected is None:
            # Atomic create-if-absent prevents accidentally replacing an unrelated file.
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ValueError("intent output already exists") from exc
        else:
            # A precondition check is not compare-and-swap; the external lease is required.
            if path.is_symlink() or _load(path) != expected:
                raise ValueError("intent changed since read; stale expected record")
            os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if _load(path) != intent:
            raise ValueError("local intent readback mismatch")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare", help="create a local intent; durable publication is a separate required step")
    for flag in ("binding", "attempt-id", "source-ref", "at", "output"):
        create.add_argument("--" + flag, required=True)
    for name in ("validate", "readback", "transition", "decide"):
        command = commands.add_parser(name)
        command.add_argument("--intent", required=True)
        if name == "readback":
            for flag in ("readback", "reference", "at"):
                command.add_argument("--" + flag, required=True)
        elif name == "transition":
            command.add_argument("--state", choices=sorted(TRANSITIONS), required=True)
            command.add_argument("--at", required=True)
            command.add_argument("--receipt")
            command.add_argument("--task")
        elif name == "decide":
            command.add_argument("--observation", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(_load(args.binding), args.attempt_id, args.source_ref, args.at)
            write_intent(args.output, result)
        else:
            intent = _load(args.intent)
            validate_intent(intent)
            if args.command == "validate":
                result = {"valid": True, "operation_key": intent["operation_key"]}
            elif args.command == "readback":
                result = verify_readback(intent, _load(args.readback), args.reference, args.at)
            elif args.command == "transition":
                result = transition(intent, args.state, args.at,
                                    receipt=_load(args.receipt) if args.receipt else None,
                                    task=_load(args.task) if args.task else None)
                write_intent(args.intent, result, expected=intent)
            else:
                result = decide(intent, _load(args.observation))
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
