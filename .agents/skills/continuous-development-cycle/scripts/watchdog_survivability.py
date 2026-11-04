#!/usr/bin/env python3
"""Desired-state watchdog survivability assessment and generation fencing.

Assessment is evidence only. Scheduler effects require a separate durable runtime
that claims an operation and re-reads this contract immediately before I/O.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

DESIRED_SCHEMA = "watchdog-desired-state/v1"
INVENTORY_SCHEMA = "watchdog-runtime-inventory/v1"
ASSESSMENT_SCHEMA = "watchdog-survivability-assessment/v1"
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})$")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}$")


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 16384:
        raise ValueError(f"{label} must be bounded non-empty text")
    return value


def _utc(value, label="timestamp"):
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise ValueError(f"{label} must be ISO UTC ending Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError(f"invalid {label}") from None


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _binding(value):
    if not isinstance(value, dict) or set(value) != {"project_id", "source_ref", "role"}:
        raise ValueError("watchdog binding must contain exact project/ref/role")
    for name, item in value.items():
        _text(item, "binding." + name)
    ref = value["source_ref"]
    if (not ref.startswith("refs/heads/") or ref.endswith(("/", ".")) or ".." in ref or "@{" in ref
            or "//" in ref or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", ref)):
        raise ValueError("binding.source_ref must be a canonical branch ref")
    return value


def validate_desired(value):
    expected = {"schema", "binding", "required", "desired_state", "generation", "canonical_object_id",
                "schedule", "template_digest", "owner_stop_evidence", "recovery_policy"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema") != DESIRED_SCHEMA:
        raise ValueError("invalid watchdog desired state")
    _binding(value["binding"])
    if type(value["required"]) is not bool or value["desired_state"] not in {"enabled", "paused"}:
        raise ValueError("invalid watchdog desired-state flags")
    if type(value["generation"]) is not int or value["generation"] < 1:
        raise ValueError("watchdog generation must be a positive integer")
    if value["canonical_object_id"] is not None:
        _text(value["canonical_object_id"], "canonical_object_id")
    _text(value["schedule"], "schedule")
    if not isinstance(value["template_digest"], str) or not DIGEST.fullmatch(value["template_digest"]):
        raise ValueError("template_digest must be sha256")
    if value["owner_stop_evidence"] is not None:
        _text(value["owner_stop_evidence"], "owner_stop_evidence")
    policy = value["recovery_policy"]
    if (not isinstance(policy, dict)
            or set(policy) != {"allowed", "owner_authorization", "overdue_after_seconds", "flap_threshold"}
            or type(policy["allowed"]) is not bool
            or type(policy["overdue_after_seconds"]) is not int or policy["overdue_after_seconds"] < 60
            or type(policy["flap_threshold"]) is not int or policy["flap_threshold"] < 1):
        raise ValueError("invalid watchdog recovery policy")
    if policy["owner_authorization"] is not None:
        _text(policy["owner_authorization"], "recovery_policy.owner_authorization")
    return value


def _validate_object(value):
    expected = {"object_id", "generation", "enabled", "schedule", "template_digest", "last_run_at_utc",
                "consecutive_failures", "execution_state", "quiescence_evidence"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid watchdog runtime object")
    _text(value["object_id"], "object_id")
    if type(value["generation"]) is not int or value["generation"] < 1 or type(value["enabled"]) is not bool:
        raise ValueError("invalid watchdog runtime generation/enabled")
    _text(value["schedule"], "object.schedule")
    if not isinstance(value["template_digest"], str) or not DIGEST.fullmatch(value["template_digest"]):
        raise ValueError("object.template_digest must be sha256")
    if value["last_run_at_utc"] is not None:
        _utc(value["last_run_at_utc"], "object.last_run_at_utc")
    if type(value["consecutive_failures"]) is not int or value["consecutive_failures"] < 0:
        raise ValueError("consecutive_failures must be nonnegative")
    if value["execution_state"] not in {"idle", "running", "failed", "unknown"}:
        raise ValueError("unsupported watchdog execution_state")
    proof = value["quiescence_evidence"]
    if proof is not None:
        if (not isinstance(proof, dict)
                or set(proof) != {"object_id", "generation", "quiescent", "evidence_ref"}
                or proof["object_id"] != value["object_id"]
                or proof["generation"] != value["generation"]
                or proof["quiescent"] is not True):
            raise ValueError("watchdog quiescence evidence must bind exact object/generation")
        _text(proof["evidence_ref"], "quiescence_evidence.evidence_ref")
    return value


def validate_inventory(value):
    expected = {"schema", "binding", "observed_at_utc", "project", "safety", "objects"}
    if not isinstance(value, dict) or set(value) != expected or value.get("schema") != INVENTORY_SCHEMA:
        raise ValueError("invalid watchdog runtime inventory")
    _binding(value["binding"])
    _utc(value["observed_at_utc"], "observed_at_utc")
    project = value["project"]
    if not isinstance(project, dict) or set(project) != {"state", "source_revision", "terminal_proof"}:
        raise ValueError("invalid project survivability state")
    if project["state"] not in {"runnable", "terminal", "unknown"} or not isinstance(project["source_revision"], str) or not SHA.fullmatch(project["source_revision"]):
        raise ValueError("invalid project state/revision")
    safety = value["safety"]
    if not isinstance(safety, dict) or set(safety) != {"owner", "guard", "external", "pause", "owner_pause_evidence", "observed_at_utc"}:
        raise ValueError("invalid survivability safety state")
    if safety["owner"] not in {"released", "active", "unknown"} or safety["guard"] not in {"released", "active", "unknown"}:
        raise ValueError("invalid owner/guard safety state")
    if safety["external"] not in {"none", "submitting", "queued", "running", "unknown", "terminal_unreconciled", "terminal_reconciled"}:
        raise ValueError("invalid external safety state")
    if safety["pause"] not in {"running", "paused", "unknown"}:
        raise ValueError("invalid pause state")
    if safety["owner_pause_evidence"] is not None:
        _text(safety["owner_pause_evidence"], "owner_pause_evidence")
    _utc(safety["observed_at_utc"], "safety.observed_at_utc")
    if not isinstance(value["objects"], list):
        raise ValueError("objects must be a list")
    ids = []
    for item in value["objects"]:
        _validate_object(item)
        ids.append(item["object_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate watchdog runtime object_id")
    return value


def _fresh(when, instant, max_age_seconds):
    age = (instant - _utc(when)).total_seconds()
    return 0 <= age <= max_age_seconds


def _terminal(desired, inventory, fresh):
    project = inventory["project"]
    proof = project["terminal_proof"]
    binding = desired["binding"]
    return (fresh and project["state"] == "terminal" and isinstance(proof, dict)
            and set(proof) == {"project_id", "source_ref", "source_revision", "evidence_ref"}
            and proof["project_id"] == binding["project_id"]
            and proof["source_ref"] == binding["source_ref"]
            and proof["source_revision"] == project["source_revision"]
            and isinstance(proof["evidence_ref"], str) and bool(proof["evidence_ref"].strip()))


def replacement_quiescence_proven(inventory):
    validate_inventory(inventory)
    return all(
        item["execution_state"] in {"idle", "failed"}
        and isinstance(item["quiescence_evidence"], dict)
        and item["quiescence_evidence"]["quiescent"] is True
        and item["quiescence_evidence"]["object_id"] == item["object_id"]
        and item["quiescence_evidence"]["generation"] == item["generation"]
        for item in inventory["objects"]
    )


def execution_is_current(desired, runtime_object):
    validate_desired(desired)
    _validate_object(runtime_object)
    return (desired["required"] and desired["desired_state"] == "enabled"
            and desired["owner_stop_evidence"] is None and runtime_object["enabled"]
            and desired["canonical_object_id"] == runtime_object["object_id"]
            and desired["generation"] == runtime_object["generation"]
            and desired["schedule"] == runtime_object["schedule"]
            and desired["template_digest"] == runtime_object["template_digest"])


def invocation_fence(desired, inventory, *, object_id, generation, now=None, max_age_seconds=120):
    validate_desired(desired)
    validate_inventory(inventory)
    if desired["binding"] != inventory["binding"]:
        raise ValueError("desired state and runtime inventory binding disagree")
    if type(max_age_seconds) is not int or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    instant = _utc(now or now_utc(), "now")
    fresh = (_fresh(inventory["observed_at_utc"], instant, max_age_seconds)
             and _fresh(inventory["safety"]["observed_at_utc"], instant, max_age_seconds))
    safety = inventory["safety"]
    allowed = (
        fresh
        and isinstance(object_id, str)
        and type(generation) is int
        and desired["canonical_object_id"] == object_id
        and desired["generation"] == generation
        and desired["required"]
        and desired["desired_state"] == "enabled"
        and desired["owner_stop_evidence"] is None
        and inventory["project"]["state"] == "runnable"
        and safety["owner"] == "released"
        and safety["guard"] == "released"
        and safety["external"] in {"none", "terminal_reconciled"}
        and safety["pause"] == "running"
        and safety["owner_pause_evidence"] is None
    )
    runtime_object = next((item for item in inventory["objects"]
                           if item["object_id"] == object_id), None)
    if (not allowed or runtime_object is None
            or runtime_object["generation"] != generation
            or runtime_object["execution_state"] != "running"
            or not execution_is_current(desired, runtime_object)):
        allowed = False
    return {
        "binding": dict(desired["binding"]),
        "object_id": object_id,
        "generation": generation,
        "may_enter_cdc": bool(allowed),
        "authorizes_product_write": False,
        "authorizes_external_start": False,
        "authorizes_lease_acquire": False,
    }


def _result(desired, overall, action, *, eligible=False, next_generation=None, canonical_object_id=None,
            stale_object_ids=(), reasons=()):
    return {
        "schema": ASSESSMENT_SCHEMA,
        "binding": dict(desired["binding"]),
        "overall": overall,
        "action": action,
        "next_generation": desired["generation"] if next_generation is None else next_generation,
        "canonical_object_id": canonical_object_id,
        "stale_object_ids": sorted(stale_object_ids),
        "recovery_eligible": bool(eligible),
        "reasons": list(reasons),
        "authorizes_scheduler_mutation": False,
    }


def assess(desired, inventory, *, now=None, max_age_seconds=120):
    validate_desired(desired)
    validate_inventory(inventory)
    if desired["binding"] != inventory["binding"]:
        raise ValueError("desired state and runtime inventory binding disagree")
    if type(max_age_seconds) is not int or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    instant = _utc(now or now_utc(), "now")
    fresh = (_fresh(inventory["observed_at_utc"], instant, max_age_seconds)
             and _fresh(inventory["safety"]["observed_at_utc"], instant, max_age_seconds))
    policy = desired["recovery_policy"]
    safety = inventory["safety"]
    safe = (fresh and desired["required"] and desired["desired_state"] == "enabled"
            and desired["owner_stop_evidence"] is None and policy["allowed"]
            and isinstance(policy["owner_authorization"], str) and bool(policy["owner_authorization"].strip())
            and inventory["project"]["state"] == "runnable"
            and safety["owner"] == "released" and safety["guard"] == "released"
            and safety["external"] in {"none", "terminal_reconciled"} and safety["pause"] == "running"
            and safety["owner_pause_evidence"] is None)

    if desired["desired_state"] == "paused" or desired["owner_stop_evidence"] is not None or not desired["required"]:
        return _result(desired, "OWNER_PAUSED", "NONE", reasons=["desired state intentionally suppresses watchdog recovery"])
    if fresh and (safety["pause"] == "paused" or safety["owner_pause_evidence"] is not None):
        return _result(desired, "OWNER_PAUSED", "NONE", reasons=["fresh owner pause suppresses watchdog recovery"])
    if _terminal(desired, inventory, fresh):
        return _result(desired, "PROJECT_TERMINAL", "NONE", reasons=["fresh exact terminal proof suppresses watchdog recovery"])
    if not safe:
        return _result(desired, "EXECUTION_BROKEN", "OBSERVE", reasons=["fresh recovery safety gates are not satisfied"])

    objects = inventory["objects"]
    canonical = next((item for item in objects if item["object_id"] == desired["canonical_object_id"]), None)
    matching = [item for item in objects if item["generation"] == desired["generation"]
                and item["schedule"] == desired["schedule"] and item["template_digest"] == desired["template_digest"]]
    if desired["canonical_object_id"] is None and len(matching) == 1:
        return _result(desired, "CONFIG_DRIFT", "ADOPT", eligible=True,
                       canonical_object_id=matching[0]["object_id"], reasons=["one exact unbound materialization can be adopted"])
    if desired["canonical_object_id"] is None and len(matching) > 1:
        return _result(desired, "DUPLICATE", "OBSERVE", reasons=["multiple current materializations prevent canonical adoption"])
    if canonical is None:
        if objects and not replacement_quiescence_proven(inventory):
            return _result(
                desired, "DUPLICATE", "OBSERVE",
                stale_object_ids=[item["object_id"] for item in objects],
                reasons=["canonical watchdog is missing but replacement lacks exact independently observed quiescence evidence"])
        return _result(desired, "MISSING", "RECREATE", eligible=True, next_generation=desired["generation"] + 1,
                       stale_object_ids=[item["object_id"] for item in objects], reasons=["required canonical watchdog object is missing"])
    extras = [item["object_id"] for item in objects
              if item["object_id"] != canonical["object_id"]
              and (item["enabled"] or item["execution_state"] in {"running", "unknown"})]
    if extras:
        return _result(desired, "DUPLICATE", "QUIESCE_DUPLICATES", eligible=True,
                       canonical_object_id=canonical["object_id"], stale_object_ids=extras,
                       reasons=["noncanonical watchdog materializations remain"])
    if canonical["execution_state"] == "unknown":
        return _result(desired, "EXECUTION_BROKEN", "OBSERVE", canonical_object_id=canonical["object_id"],
                       reasons=["watchdog execution outcome is unknown"])
    config_drift = (canonical["generation"] != desired["generation"]
                    or canonical["schedule"] != desired["schedule"]
                    or canonical["template_digest"] != desired["template_digest"])
    if canonical["execution_state"] == "running":
        if not canonical["enabled"]:
            return _result(desired, "DISABLED_DRIFT", "ENABLE", eligible=True,
                           canonical_object_id=canonical["object_id"],
                           reasons=["active watchdog schedule is disabled; enable without a second run"])
        if config_drift:
            return _result(desired, "CONFIG_DRIFT", "OBSERVE",
                           canonical_object_id=canonical["object_id"],
                           reasons=["active watchdog must become quiescent before destructive configuration replacement"])
        if canonical["consecutive_failures"] >= policy["flap_threshold"]:
            return _result(desired, "FLAPPING", "OBSERVE",
                           canonical_object_id=canonical["object_id"],
                           reasons=["active watchdog is not recreated until the running invocation is quiescent"])
        return _result(desired, "HEALTHY", "NONE", canonical_object_id=canonical["object_id"],
                       reasons=["watchdog invocation is already running; duplicate wake suppressed"])
    if config_drift:
        if not replacement_quiescence_proven(inventory):
            return _result(desired, "CONFIG_DRIFT", "OBSERVE",
                           canonical_object_id=canonical["object_id"],
                           reasons=["configuration replacement waits for exact independently observed quiescence evidence"])
        return _result(desired, "CONFIG_DRIFT", "RECREATE", eligible=True, next_generation=desired["generation"] + 1,
                       canonical_object_id=canonical["object_id"], reasons=["canonical watchdog configuration disagrees with desired state"])
    if canonical["consecutive_failures"] >= policy["flap_threshold"]:
        if not replacement_quiescence_proven(inventory):
            return _result(desired, "FLAPPING", "OBSERVE",
                           canonical_object_id=canonical["object_id"],
                           reasons=["flapping replacement waits for exact independently observed quiescence evidence"])
        return _result(desired, "FLAPPING", "RECREATE", eligible=True, next_generation=desired["generation"] + 1,
                       canonical_object_id=canonical["object_id"], reasons=["watchdog reached configured failure threshold"])
    if not canonical["enabled"]:
        return _result(desired, "DISABLED_DRIFT", "ENABLE", eligible=True,
                       canonical_object_id=canonical["object_id"], reasons=["required watchdog is disabled"])
    if canonical["execution_state"] == "failed":
        return _result(desired, "OVERDUE", "RUN", eligible=True,
                       canonical_object_id=canonical["object_id"], reasons=["last watchdog invocation failed; bounded retry requested"])
    if canonical["last_run_at_utc"] is None or (instant - _utc(canonical["last_run_at_utc"])).total_seconds() > policy["overdue_after_seconds"]:
        return _result(desired, "OVERDUE", "RUN", eligible=True,
                       canonical_object_id=canonical["object_id"], reasons=["watchdog wake is overdue"])
    return _result(desired, "HEALTHY", "NONE", canonical_object_id=canonical["object_id"], reasons=["desired and actual watchdog state agree"])
