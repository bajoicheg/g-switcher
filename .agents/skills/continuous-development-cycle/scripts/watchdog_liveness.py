#!/usr/bin/env python3
"""Fresh, exact watchdog liveness facts; assessment is never mutation authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

SCHEMA = "watchdog-liveness-probe/v1"
BINDING_FIELDS = {"project_id", "source_ref", "watchdog_id", "incident_id"}
STATES = {
    "scheduler": {"enabled", "disabled", "overdue", "unknown"},
    "invocation": {"idle", "running", "completed", "unknown"},
    "work": {"runnable", "terminal", "unknown"},
    "owner": {"released", "active", "unknown"},
    "guard": {"released", "active", "unknown"},
    "external": {"none", "submitting", "queued", "running", "unknown", "terminal_unreconciled", "terminal_reconciled"},
    "progress": {"fresh", "stale", "unknown"},
    "pause": {"running", "paused", "unknown"},
}


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 16384:
        raise ValueError(f"{label} must be bounded non-empty text")
    return value


def utc(value):
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise ValueError("timestamp must be ISO UTC ending Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError("invalid UTC timestamp") from None


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_binding(binding, *, incident=True):
    fields = BINDING_FIELDS if incident else BINDING_FIELDS - {"incident_id"}
    if not isinstance(binding, dict) or set(binding) != fields:
        raise ValueError("binding must contain the exact project/ref/watchdog identity" + (" and incident" if incident else ""))
    for key, value in binding.items():
        text(value, key)
    ref = binding["source_ref"]
    if (not ref.startswith("refs/heads/") or ref.endswith(("/", ".")) or ".." in ref or "@{" in ref
            or "//" in ref or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", ref)
            or any(part.startswith(".") or part.endswith(".lock") for part in ref.split("/"))):
        raise ValueError("source_ref must be a canonical exact refs/heads/ ref")
    return binding


def binding_key(binding):
    validate_binding(binding, incident="incident_id" in binding)
    raw = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_probe(probe):
    if not isinstance(probe, dict) or set(probe) != {"schema", "binding", "signals"} or probe["schema"] != SCHEMA:
        raise ValueError("unsupported watchdog liveness probe")
    validate_binding(probe["binding"])
    signals = probe["signals"]
    if not isinstance(signals, dict) or set(signals) != set(STATES) | {"policy"}:
        raise ValueError("probe must contain every independent liveness signal")
    for name, signal in signals.items():
        if not isinstance(signal, dict):
            raise ValueError("liveness signal must be an object")
        utc(signal.get("observed_at_utc"))
        if name in STATES and signal.get("state") not in STATES[name]:
            raise ValueError(f"unsupported {name} state")
    for key in ["schedule", "prompt"]:
        text(signals["scheduler"].get(key), "scheduler." + key)
    policy = signals["policy"]
    if type(policy.get("recovery_allowed")) is not bool or type(policy.get("effects_remaining")) is not int or policy["effects_remaining"] < 0:
        raise ValueError("policy requires explicit authorization and a nonnegative effect budget")
    text(policy.get("revision"), "policy.revision")
    return probe


def assess(probe, *, now=None, max_age_seconds=120, expected_binding=None):
    validate_probe(probe)
    if expected_binding is not None and probe["binding"] != expected_binding:
        raise ValueError("liveness binding disagrees with expected project/ref/watchdog/incident")
    if type(max_age_seconds) is not int or max_age_seconds < 0:
        raise ValueError("freshness window must be nonnegative seconds")
    instant = utc(now or now_utc())
    signals = probe["signals"]
    stale = [name for name, signal in signals.items()
             if not 0 <= (instant - utc(signal["observed_at_utc"])).total_seconds() <= max_age_seconds]
    states = {name: signals[name]["state"] for name in STATES}
    reasons = ["stale_or_future:" + name for name in stale]
    pause = signals["pause"]
    explicit_pause = (states["pause"] == "paused" and "pause" not in stale
                      and isinstance(pause.get("owner_evidence"), str) and bool(pause["owner_evidence"].strip()))
    invocation_known = (states["invocation"] == "idle" and signals["invocation"].get("invocation_id") is None) or (
        states["invocation"] in {"running", "completed"}
        and isinstance(signals["invocation"].get("invocation_id"), str)
        and bool(signals["invocation"]["invocation_id"].strip()))
    proof = signals["work"].get("terminal_proof")
    source_revision = signals["work"].get("source_revision")
    terminal = (states["work"] == "terminal" and isinstance(proof, dict)
                and set(proof) == {"project_id", "source_ref", "source_revision", "evidence_ref"}
                and proof["project_id"] == probe["binding"]["project_id"]
                and proof["source_ref"] == probe["binding"]["source_ref"]
                and isinstance(source_revision, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source_revision) is not None
                and proof["source_revision"] == source_revision
                and isinstance(proof["evidence_ref"], str) and bool(proof["evidence_ref"].strip()) and not stale)
    critical = states["scheduler"] in {"disabled", "overdue"} or (
        states["invocation"] == "completed" and states["work"] == "runnable")
    safe = (not stale and states["pause"] == "running" and states["work"] == "runnable"
            and states["owner"] == "released" and states["guard"] == "released"
            and states["external"] in {"none", "terminal_reconciled"}
            and states["invocation"] in {"idle", "completed"} and invocation_known
            and states["scheduler"] != "unknown" and states["progress"] != "unknown"
            and isinstance(signals["policy"].get("owner_authorization"), str)
            and bool(signals["policy"]["owner_authorization"].strip())
            and signals["policy"]["recovery_allowed"] and signals["policy"]["effects_remaining"] > 0)
    if explicit_pause:
        overall = "PAUSED"
        reasons.append("current_explicit_owner_pause")
    elif terminal:
        overall = "COMPLETE"
        reasons.append("fresh_project_terminal_proof")
    elif critical:
        overall = "CRITICAL"
        reasons.append("scheduler_delivery_fault" if states["scheduler"] in {"disabled", "overdue"} else "invocation_completed_with_runnable_work")
    elif stale or any(state == "unknown" for state in states.values()) or not invocation_known or states["work"] == "terminal":
        overall = "UNKNOWN"
        reasons.append("incomplete_liveness_evidence")
    else:
        overall = "HEALTHY" if states["progress"] == "fresh" else "STALLED"
    if not safe and not explicit_pause and not terminal:
        reasons.append("fresh_recovery_gates_not_satisfied")
    return {
        "schema": "watchdog-liveness-assessment/v1", "binding": dict(probe["binding"]),
        "assessed_at_utc": instant.isoformat().replace("+00:00", "Z"), "overall": overall,
        "states": states, "reasons": reasons, "safe_to_recover": safe,
        "recovery_eligible": critical and safe and not explicit_pause,
        "authorizes_scheduler_mutation": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe")
    parser.add_argument("--now")
    parser.add_argument("--max-age-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        raw = Path(args.probe).read_text(encoding="utf-8")
        if len(raw) > 262144:
            raise ValueError("probe exceeds 256 KiB")
        print(json.dumps(assess(json.loads(raw), now=args.now, max_age_seconds=args.max_age_seconds), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
