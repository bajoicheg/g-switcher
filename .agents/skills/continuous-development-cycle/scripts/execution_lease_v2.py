#!/usr/bin/env python3
"""CDC 2.4 invocation-bound cooperative lease with transactional finalization."""
from __future__ import annotations

import argparse
import copy
from datetime import timedelta
import json
import sys
import uuid

import operation_intent as op
import execution_lease as legacy

V1_FIELDS = set(legacy.FIELDS)
FIELDS = V1_FIELDS | {"invocation", "finalization", "legacy_migration"}
SURFACES = {"chat", "watchdog", "work", "codex", "api", "unknown"}
FINALIZATION_STATES = {"active", "draining", "checkpointed", "reconciled", "ready", "failed"}
RECONCILIATION_STATES = {"pending", "none", "terminal_reconciled", "unknown_preserved"}
QUIESCENCE_EFFECTS = {"none", "reconciled", "preserved_unknown"}
LEGACY_DUMMY_OWNER = "00000000-0000-4000-8000-000000000000"

def _uuid(value, name="owner_id"):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError(f"{name} must be a canonical UUID")

def _generation(value):
    if type(value) is not int or value < 0:
        raise ValueError("generation must be a nonnegative integer")

def _nullable_text(value, name):
    if value is not None:
        op._text(value, name)

def _validate_invocation(value):
    op._object(value, {"invocation_id", "automation_id", "conversation_id",
                       "execution_surface", "started_at_utc"}, "invocation")
    op._text(value["invocation_id"], "invocation_id")
    _nullable_text(value["automation_id"], "automation_id")
    _nullable_text(value["conversation_id"], "conversation_id")
    if value["execution_surface"] not in SURFACES:
        raise ValueError("unsupported execution_surface")
    op._timestamp(value["started_at_utc"], "invocation start")
    return value

def _validate_finalization(value):
    op._object(value, {"state", "pending_shared_writes", "checkpoint_ref",
                       "external_reconciliation", "completion_reason", "updated_at_utc", "failure"}, "finalization")
    if value["state"] not in FINALIZATION_STATES:
        raise ValueError("unsupported finalization state")
    if type(value["pending_shared_writes"]) is not bool:
        raise ValueError("pending_shared_writes must be boolean")
    _nullable_text(value["checkpoint_ref"], "checkpoint_ref")
    if value["external_reconciliation"] not in RECONCILIATION_STATES:
        raise ValueError("unsupported external_reconciliation state")
    op._timestamp(value["updated_at_utc"], "finalization update")
    _nullable_text(value["completion_reason"], "completion_reason")
    _nullable_text(value["failure"], "finalization failure")
    if value["state"] == "failed":
        if value["failure"] is None:
            raise ValueError("failed finalization requires failure")
    elif value["failure"] is not None:
        raise ValueError("non-failed finalization cannot contain failure")
    if value["state"] in {"reconciled", "ready"} and value["pending_shared_writes"]:
        raise ValueError("reconciled/ready finalization cannot retain shared writes")
    if value["state"] in {"checkpointed", "reconciled", "ready"} and value["checkpoint_ref"] is None:
        raise ValueError("checkpointed/finalized state requires checkpoint_ref")
    if value["state"] == "ready" and value["external_reconciliation"] == "pending":
        raise ValueError("ready finalization requires external reconciliation")
    if value["state"] == "ready" and value["completion_reason"] is None:
        raise ValueError("ready finalization requires an allowed completion boundary")
    if value["state"] != "ready" and value["completion_reason"] is not None:
        raise ValueError("completion_reason is recorded only at ready boundary")
    return value

def _validate_release(value, generation):
    op._object(value, {"owner_id", "generation", "invocation_id", "at_utc",
                       "checkpoint_ref", "external_reconciliation", "completion_reason"}, "last_release")
    _uuid(value["owner_id"])
    _generation(value["generation"])
    _nullable_text(value["invocation_id"], "released invocation_id")
    op._timestamp(value["at_utc"], "release time")
    _nullable_text(value["checkpoint_ref"], "released checkpoint_ref")
    if value["external_reconciliation"] not in RECONCILIATION_STATES | {"legacy"}:
        raise ValueError("invalid release external_reconciliation")
    _nullable_text(value["completion_reason"], "released completion_reason")
    if value["generation"] > generation:
        raise ValueError("release generation exceeds persistent generation")

def _legacy_projection(record, *, sanitize_migrated=False):
    projected = {name: copy.deepcopy(record[name]) for name in V1_FIELDS}
    projected["schema"] = "execution-lease/v1"
    release = projected.get("last_release")
    if isinstance(release, dict) and "invocation_id" in release:
        projected["last_release"] = {key: release[key] for key in ("owner_id", "generation", "at_utc")}
    marker = record.get("legacy_migration")
    if sanitize_migrated and marker is not None:
        allowed = set(marker["noncanonical_claim_digests"])
        for claim in projected["submission_claims"]:
            if op._hash(claim) in allowed:
                claim["owner_id"] = LEGACY_DUMMY_OWNER
    return projected

def _noncanonical_claim_digests(record):
    result = []
    for claim in record.get("submission_claims", []):
        try:
            _uuid(claim.get("owner_id"), "claim owner_id")
        except (ValueError, AttributeError):
            op._text(claim.get("owner_id"), "legacy claim owner_id")
            result.append(op._hash(claim))
    return result

def _validate_legacy_migration(record):
    marker = record["legacy_migration"]
    op._object(marker, {"from_schema", "migrated_at_utc", "migrated_generation",
                        "source_digest", "noncanonical_claim_digests",
                        "legacy_takeover_evidence_digest"}, "legacy_migration")
    if marker["from_schema"] != "execution-lease/v1":
        raise ValueError("legacy migration source schema mismatch")
    op._timestamp(marker["migrated_at_utc"], "migration time")
    _generation(marker["migrated_generation"])
    if marker["migrated_generation"] > record["generation"]:
        raise ValueError("migration generation exceeds lease generation")
    op._digest(marker["source_digest"], "legacy source digest")
    if not isinstance(marker["noncanonical_claim_digests"], list):
        raise ValueError("noncanonical_claim_digests must be a list")
    for value in marker["noncanonical_claim_digests"]:
        op._digest(value, "legacy claim digest")
    if len(set(marker["noncanonical_claim_digests"])) != len(marker["noncanonical_claim_digests"]):
        raise ValueError("duplicate legacy claim digest")
    if marker["legacy_takeover_evidence_digest"] is not None:
        op._digest(marker["legacy_takeover_evidence_digest"], "legacy takeover evidence digest")
    observed = _noncanonical_claim_digests(record)
    if set(observed) != set(marker["noncanonical_claim_digests"]):
        raise ValueError("legacy noncanonical claim set changed after migration")
    projected = _legacy_projection(record, sanitize_migrated=True)
    legacy.validate(projected)
    if record["generation"] == marker["migrated_generation"]:
        if op._hash(_legacy_projection(record)) != marker["source_digest"]:
            raise ValueError("migrated v1 source digest changed before first v2 acquisition")
        takeover = record["takeover_evidence"]
        expected = marker["legacy_takeover_evidence_digest"]
        actual = op._hash(takeover) if takeover is not None else None
        if actual != expected:
            raise ValueError("legacy takeover evidence changed during migration")
    return marker

def validate(record):
    if not isinstance(record, dict):
        raise ValueError("lease must be an object")
    if record.get("schema") == "execution-lease/v1":
        return legacy.validate(record)
    op._object(record, FIELDS, "lease")
    if record["schema"] != "execution-lease/v2":
        raise ValueError("unsupported lease schema")
    if record["legacy_migration"] is None:
        legacy.validate(_legacy_projection(record))
    else:
        _validate_legacy_migration(record)
    if record["owner_id"] is None:
        if record["invocation"] is not None or record["finalization"] is not None:
            raise ValueError("released v2 lease cannot retain live invocation/finalization")
    else:
        _uuid(record["owner_id"])
        _validate_invocation(record["invocation"])
        _validate_finalization(record["finalization"])
        if op._timestamp(record["invocation"]["started_at_utc"], "invocation start") > op._timestamp(
                record["acquired_at_utc"], "acquired"):
            raise ValueError("invocation cannot start after lease acquisition")
    if record["last_release"] is not None:
        _validate_release(record["last_release"], record["generation"])
    takeover = record["takeover_evidence"]
    if takeover is not None:
        v2_fields = {"owner_id", "generation", "repository", "source_ref",
                     "invocation_id", "kind", "reference",
                     "pending_shared_writes", "external_effects_state"}
        legacy_fields = {"owner_id", "generation", "repository", "source_ref", "kind", "reference"}
        if set(takeover) == v2_fields:
            _uuid(takeover["owner_id"])
            _generation(takeover["generation"])
            for name in ("repository", "source_ref", "invocation_id", "reference"):
                op._text(takeover[name], name)
            if takeover["kind"] != "executor_stopped":
                raise ValueError("quiescence evidence must establish prior executor stopped")
            if takeover["pending_shared_writes"] is not False:
                raise ValueError("takeover requires no pending shared writes")
            if takeover["external_effects_state"] not in QUIESCENCE_EFFECTS:
                raise ValueError("invalid external effects state")
        elif set(takeover) == legacy_fields and record["legacy_migration"] is not None:
            for name in ("owner_id", "repository", "source_ref", "kind", "reference"):
                op._text(takeover[name], "legacy takeover " + name)
            _generation(takeover["generation"])
            if takeover["generation"] > record["legacy_migration"]["migrated_generation"]:
                raise ValueError("legacy takeover evidence exceeds migration generation")
            if op._hash(takeover) != record["legacy_migration"]["legacy_takeover_evidence_digest"]:
                raise ValueError("legacy takeover evidence digest mismatch")
        else:
            raise ValueError("unsupported takeover_evidence shape")
    return record

def initialize(repository, source_ref):
    record = legacy.initialize(repository, source_ref)
    record["schema"] = "execution-lease/v2"
    record["invocation"] = None
    record["finalization"] = None
    record["legacy_migration"] = None
    return validate(record)

def migrate_v1(record, at):
    if not isinstance(record, dict) or record.get("schema") != "execution-lease/v1":
        raise ValueError("migration requires execution-lease/v1")
    op._timestamp(at, "migration time")
    if record.get("owner_id") is not None:
        raise ValueError("owned v1 lease cannot migrate; release/recover the legacy owner first")
    noncanonical = _noncanonical_claim_digests(record)
    sanitized = copy.deepcopy(record)
    allowed = set(noncanonical)
    for claim in sanitized.get("submission_claims", []):
        if op._hash(claim) in allowed:
            claim["owner_id"] = LEGACY_DUMMY_OWNER
    legacy.validate(sanitized)
    result = copy.deepcopy(record)
    result["schema"] = "execution-lease/v2"
    result["invocation"] = None
    result["finalization"] = None
    result["legacy_migration"] = {
        "from_schema": "execution-lease/v1",
        "migrated_at_utc": at,
        "migrated_generation": record["generation"],
        "source_digest": op._hash(record),
        "noncanonical_claim_digests": noncanonical,
        "legacy_takeover_evidence_digest": op._hash(record["takeover_evidence"]) if record["takeover_evidence"] is not None else None,
    }
    if result["last_release"] is not None:
        release = result["last_release"]
        result["last_release"] = dict(release, invocation_id=None, checkpoint_ref=None,
                                      external_reconciliation="legacy", completion_reason="legacy")
    return validate(result)

def _expiry(at, ttl):
    if type(ttl) is not int or ttl <= 0:
        raise ValueError("ttl must be positive integer seconds")
    return (op._timestamp(at, "at") + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z")

def _owner(record, owner_id, generation, invocation_id, at):
    validate(record)
    if record["schema"] != "execution-lease/v2":
        raise ValueError("v2 mutation requires execution-lease/v2")
    _uuid(owner_id)
    _generation(generation)
    op._text(invocation_id, "invocation_id")
    if owner_id != record["owner_id"] or generation != record["generation"]:
        raise ValueError("stale or non-owner executor")
    if record["invocation"] is None or invocation_id != record["invocation"]["invocation_id"]:
        raise ValueError("invocation binding mismatch")
    if op._timestamp(at, "at") < op._timestamp(record["heartbeat_at_utc"], "heartbeat"):
        raise ValueError("ownership action cannot move backwards in time")

def acquire(record, owner_id, at, *, invocation, ttl=1200, quiescence=None):
    validate(record)
    if record["schema"] != "execution-lease/v2":
        raise ValueError("migrate v1 lease before v2 acquisition")
    _uuid(owner_id)
    inv = copy.deepcopy(_validate_invocation(invocation))
    at_dt = op._timestamp(at, "at")
    if op._timestamp(inv["started_at_utc"], "invocation start") > at_dt:
        raise ValueError("invocation start cannot be after acquisition")
    last_release = record["last_release"]
    if last_release is not None:
        if owner_id == last_release["owner_id"]:
            raise ValueError("released executor UUID cannot be reused")
        if at_dt < op._timestamp(last_release["at_utc"], "release time"):
            raise ValueError("acquisition predates explicit release")
    if owner_id == record["owner_id"]:
        raise ValueError("each acquisition needs a fresh executor UUID")
    if record["owner_id"] is not None:
        op._object(quiescence, {"owner_id", "generation", "repository", "source_ref",
                                "invocation_id", "kind", "reference",
                                "pending_shared_writes", "external_effects_state"}, "quiescence evidence")
        expected = {"owner_id": record["owner_id"], "generation": record["generation"],
                    "repository": record["repository"], "source_ref": record["source_ref"],
                    "invocation_id": record["invocation"]["invocation_id"]}
        for field, value in expected.items():
            if quiescence[field] != value:
                raise ValueError("quiescence evidence must match prior owner/invocation/generation")
        if quiescence["kind"] != "executor_stopped" or quiescence["pending_shared_writes"] is not False:
            raise ValueError("quiescence must prove stopped executor and no pending shared writes")
        if quiescence["external_effects_state"] not in QUIESCENCE_EFFECTS:
            raise ValueError("quiescence must classify external effects")
        op._text(quiescence["reference"], "quiescence reference")
        if at_dt < op._timestamp(record["heartbeat_at_utc"], "heartbeat"):
            raise ValueError("acquisition predates prior heartbeat")
    elif quiescence is not None:
        raise ValueError("quiescence supplied without a prior owner")
    result = copy.deepcopy(record)
    result.update(owner_id=owner_id, generation=record["generation"] + 1,
                  acquired_at_utc=at, heartbeat_at_utc=at, expires_at_utc=_expiry(at, ttl),
                  activity_refs=[], takeover_evidence=copy.deepcopy(quiescence),
                  invocation=inv,
                  finalization={"state": "active", "pending_shared_writes": False,
                                "checkpoint_ref": None, "external_reconciliation": "pending",
                                "completion_reason": None, "updated_at_utc": at, "failure": None})
    return validate(result)

def renew(record, owner_id, generation, invocation_id, at, *, activity_ref, ttl=1200):
    _owner(record, owner_id, generation, invocation_id, at)
    op._text(activity_ref, "activity_ref")
    if activity_ref in record["activity_refs"]:
        raise ValueError("heartbeat requires unique observable activity")
    result = copy.deepcopy(record)
    result["activity_refs"].append(activity_ref)
    result.update(heartbeat_at_utc=at, expires_at_utc=_expiry(at, ttl))
    return validate(result)

def begin_finalization(record, owner_id, generation, invocation_id, at, *, pending_shared_writes):
    _owner(record, owner_id, generation, invocation_id, at)
    if type(pending_shared_writes) is not bool:
        raise ValueError("pending_shared_writes must be boolean")
    if record["finalization"]["state"] not in {"active", "failed"}:
        raise ValueError("finalization can begin only from active or failed")
    result = copy.deepcopy(record)
    result["finalization"].update(state="draining", pending_shared_writes=pending_shared_writes,
                                  checkpoint_ref=None, external_reconciliation="pending",
                                  completion_reason=None, updated_at_utc=at, failure=None)
    return validate(result)

def record_checkpoint(record, owner_id, generation, invocation_id, at, *,
                      checkpoint_ref, pending_shared_writes):
    _owner(record, owner_id, generation, invocation_id, at)
    op._text(checkpoint_ref, "checkpoint_ref")
    if pending_shared_writes is not False:
        raise ValueError("checkpoint boundary requires no pending shared writes")
    if record["finalization"]["state"] != "draining":
        raise ValueError("checkpoint finalization requires draining state")
    result = copy.deepcopy(record)
    result["finalization"].update(state="checkpointed", pending_shared_writes=False,
                                  checkpoint_ref=checkpoint_ref, updated_at_utc=at)
    return validate(result)

def reconcile_finalization(record, owner_id, generation, invocation_id, at, *, external_reconciliation):
    _owner(record, owner_id, generation, invocation_id, at)
    if record["finalization"]["state"] != "checkpointed":
        raise ValueError("external reconciliation requires checkpointed state")
    if external_reconciliation not in {"none", "terminal_reconciled", "unknown_preserved"}:
        raise ValueError("invalid external_reconciliation")
    if record["external_guard"] is None and external_reconciliation == "unknown_preserved":
        raise ValueError("unknown_preserved requires an unresolved external guard")
    if record["external_guard"] is not None and external_reconciliation != "unknown_preserved":
        raise ValueError("unresolved external guard must be preserved_unknown before release")
    result = copy.deepcopy(record)
    result["finalization"].update(state="reconciled", external_reconciliation=external_reconciliation,
                                  updated_at_utc=at)
    return validate(result)

def mark_ready(record, owner_id, generation, invocation_id, at, *, continuity_state):
    _owner(record, owner_id, generation, invocation_id, at)
    if record["finalization"]["state"] != "reconciled":
        raise ValueError("ready requires reconciled state")
    from execution_continuity import evaluate
    if not isinstance(continuity_state, dict) or continuity_state.get("invocation_id") != invocation_id:
        raise ValueError("continuity state must bind the exact invocation")
    if continuity_state.get("lease_release_required") is not False or continuity_state.get("lease_released") is not False:
        raise ValueError("pre-release continuity state must describe an owned, not-yet-released lease")
    decision = evaluate(continuity_state)
    if not decision["allowed"] or continuity_state.get("requested_terminal_outcome") == "continue":
        raise ValueError("hard execution-continuity gate rejected finalization")
    result = copy.deepcopy(record)
    result["finalization"].update(state="ready", completion_reason=decision["reason"], updated_at_utc=at)
    return validate(result)

def fail_finalization(record, owner_id, generation, invocation_id, at, *, failure):
    _owner(record, owner_id, generation, invocation_id, at)
    op._text(failure, "finalization failure")
    result = copy.deepcopy(record)
    result["finalization"].update(state="failed", failure=failure, updated_at_utc=at)
    return validate(result)

def release(record, owner_id, generation, invocation_id, at):
    _owner(record, owner_id, generation, invocation_id, at)
    finalization = record["finalization"]
    if finalization["state"] != "ready":
        raise ValueError("release requires completed transactional finalization")
    result = copy.deepcopy(record)
    result["last_release"] = {"owner_id": owner_id, "generation": generation,
                              "invocation_id": invocation_id, "at_utc": at,
                              "checkpoint_ref": finalization["checkpoint_ref"],
                              "external_reconciliation": finalization["external_reconciliation"],
                              "completion_reason": finalization["completion_reason"]}
    result.update(owner_id=None, acquired_at_utc=None, heartbeat_at_utc=None,
                  expires_at_utc=None, invocation=None, finalization=None)
    return validate(result)

def set_guard(record, owner_id, generation, invocation_id, at, intent, intent_reference):
    _owner(record, owner_id, generation, invocation_id, at)
    if record["finalization"]["state"] != "active":
        raise ValueError("cannot start/update external work after finalization begins")
    projected = legacy.set_guard(_legacy_projection(record, sanitize_migrated=True), owner_id, generation, at, intent, intent_reference)
    result = copy.deepcopy(record)
    result["external_guard"] = projected["external_guard"]
    return validate(result)

def clear_guard(record, owner_id, generation, invocation_id, at, observation, evidence_reference):
    _owner(record, owner_id, generation, invocation_id, at)
    projected = legacy.clear_guard(_legacy_projection(record, sanitize_migrated=True), owner_id, generation, at,
                                   observation, evidence_reference)
    result = copy.deepcopy(record)
    result["external_guard"] = projected["external_guard"]
    result["last_terminal"] = projected["last_terminal"]
    return validate(result)

def check_record(record, owner_id, generation, invocation_id, at, *,
                 action, intent_digest=None, heartbeat_freshness=600):
    _owner(record, owner_id, generation, invocation_id, at)
    if action not in {"product_write", "external_start", "observe"}:
        raise ValueError("unknown ownership action")
    if action == "observe":
        return {"action": action, "generation": generation, "owner_id": owner_id,
                "invocation_id": invocation_id}
    if record["finalization"]["state"] != "active":
        raise ValueError("writes/starts are forbidden after finalization begins")
    now = op._timestamp(at, "at")
    if type(heartbeat_freshness) is not int or heartbeat_freshness <= 0:
        raise ValueError("heartbeat_freshness must be positive seconds")
    if (now >= op._timestamp(record["expires_at_utc"], "expiry") or
            now - op._timestamp(record["heartbeat_at_utc"], "heartbeat") >= timedelta(seconds=heartbeat_freshness)):
        raise ValueError("ownership is not fresh; observable owner activity required")
    guard = record["external_guard"]
    if action == "product_write" and guard is not None:
        raise ValueError("unresolved external guard blocks product writes")
    if action == "external_start" and (
            guard is None or guard["submission_claim"] is not None
            or guard["intent"]["state"] != "submitting"
            or guard["intent_digest"] != intent_digest):
        raise ValueError("external start requires exact durably guarded submitting intent")
    return {"action": action, "generation": generation, "owner_id": owner_id,
            "invocation_id": invocation_id}

def check(store, expected_revision, repository, source_ref, owner_id, generation,
          invocation_id, at, **kwargs):
    revision, record = store.read()
    if revision != expected_revision or record is None:
        raise ValueError("stale coordination store revision")
    if record["repository"] != repository or record["source_ref"] != source_ref:
        raise ValueError("exact repository/source-ref binding mismatch")
    result = check_record(record, owner_id, generation, invocation_id, at, **kwargs)
    return dict(result, revision=revision, repository=repository, source_ref=source_ref)

def claim_submission(store, expected_revision, repository, source_ref, owner_id,
                     generation, invocation_id, at, *, intent_digest, heartbeat_freshness=600):
    revision, record = store.read()
    if revision != expected_revision or record is None:
        raise ValueError("stale coordination store revision")
    if record["repository"] != repository or record["source_ref"] != source_ref:
        raise ValueError("exact repository/source-ref binding mismatch")
    check_record(record, owner_id, generation, invocation_id, at, action="external_start",
                 intent_digest=intent_digest, heartbeat_freshness=heartbeat_freshness)
    guard = record["external_guard"]
    grant = {"grant_id": str(uuid.uuid4()), "owner_id": owner_id, "generation": generation,
             "operation_key": guard["operation_key"], "attempt_id": guard["intent"]["attempt_id"],
             "intent_digest": intent_digest, "claimed_at_utc": at}
    record = copy.deepcopy(record)
    record["external_guard"]["submission_claim"] = grant
    record["submission_claims"].append(copy.deepcopy(grant))
    validate(record)
    new_revision = store.compare_and_swap(expected_revision, record)
    return {"revision": new_revision, "grant": copy.deepcopy(grant)}

def _mutate(store, expected, repository, source_ref, command, request):
    revision, record = store.read()
    if revision != expected:
        raise ValueError("stale expected revision")
    if command == "init":
        if record is not None or request:
            raise ValueError("initialization requires absent store and no extra arguments")
        result = initialize(repository, source_ref)
    elif command == "migrate-v2":
        if record is None or request:
            raise ValueError("migration requires existing record and no extra arguments")
        if record["repository"] != repository or record["source_ref"] != source_ref:
            raise ValueError("exact repository/source-ref binding mismatch")
        result = migrate_v1(record, request.pop("at"))
    else:
        if record is None or record["repository"] != repository or record["source_ref"] != source_ref:
            raise ValueError("exact repository/source-ref binding mismatch")
        if command == "acquire":
            if "owner_id" in request:
                raise ValueError("CLI acquisition generates a new executor UUID")
            request["owner_id"] = str(uuid.uuid4())
        command_name = {
            "finalize-begin": "begin_finalization",
            "finalize-checkpoint": "record_checkpoint",
            "finalize-reconcile": "reconcile_finalization",
            "finalize-ready": "mark_ready",
            "finalize-fail": "fail_finalization",
        }.get(command, command)
        if command_name == "guard":
            command_name = "clear_guard" if "observation" in request else "set_guard"
        result = globals()[command_name](record, **request)
    new_revision = store.compare_and_swap(expected, result)
    return new_revision, result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[
        "read", "init", "migrate-v2", "acquire", "renew", "release", "guard",
        "check", "claim-submission", "finalize-begin", "finalize-checkpoint",
        "finalize-reconcile", "finalize-ready", "finalize-fail"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--coordination-ref", required=True)
    parser.add_argument("--request", help="JSON command arguments; expected_revision required for mutations/check")
    args = parser.parse_args(argv)
    try:
        from git_lease_store import GitLeaseStore
        store = GitLeaseStore(args.repo, args.remote, args.coordination_ref)
        request = op._load(args.request) if args.request else {}
        if args.command == "read":
            revision, record = store.read()
            if record is not None:
                validate(record)
        else:
            expected = request.pop("expected_revision")
            repository, source_ref = request.pop("repository"), request.pop("source_ref")
            if args.command in {"check", "claim-submission"}:
                fn = check if args.command == "check" else claim_submission
                print(json.dumps(fn(store, expected, repository, source_ref, **request), sort_keys=True))
                return 0
            revision, record = _mutate(store, expected, repository, source_ref, args.command, request)
        print(json.dumps({"revision": revision, "record": record}, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"execution lease v2: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
