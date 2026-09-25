#!/usr/bin/env python3
"""Validate and classify a six-signal watchdog health probe.

The assessment is diagnostic only. It never grants takeover, product-write,
external-start, scheduler-mutation, or budget authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "watchdog-health-probe/v1"
ASSESSMENT_SCHEMA = "watchdog-health-assessment/v1"

SIGNAL_STATES = {
    "scheduler": {"ok", "drift", "overdue", "unknown"},
    "chat": {"active", "archived", "missing", "unknown"},
    "invocation": {"idle", "running", "completed", "unknown"},
    "lease": {"released", "fresh", "stale", "expired", "unknown"},
    "external": {"none", "queued", "running", "unknown", "terminal_unreconciled", "terminal_reconciled"},
    "progress": {"fresh", "stale", "none", "unknown"},
}


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _utc(value):
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
        return True
    except ValueError:
        return False


def validate_probe(probe):
    if not isinstance(probe, dict):
        raise ValueError("health probe must be an object")
    expected = {"schema", "repository", "observed_at_utc", "signals"}
    if set(probe) != expected:
        raise ValueError(f"health probe must contain exactly {sorted(expected)}")
    if probe["schema"] != SCHEMA:
        raise ValueError("unsupported watchdog health probe schema")
    _text(probe["repository"], "repository")
    if not _utc(probe["observed_at_utc"]):
        raise ValueError("observed_at_utc must be an ISO UTC timestamp")
    signals = probe["signals"]
    if not isinstance(signals, dict) or set(signals) != set(SIGNAL_STATES):
        raise ValueError(f"signals must contain exactly {sorted(SIGNAL_STATES)}")
    for name, allowed in SIGNAL_STATES.items():
        value = signals[name]
        if not isinstance(value, dict) or not isinstance(value.get("state"), str):
            raise ValueError(f"signals.{name} must contain a state")
        if value["state"] not in allowed:
            raise ValueError(f"unsupported signals.{name}.state: {value['state']!r}")
    return probe


def _fingerprint(repository, states, overall, action):
    payload = {
        "repository": repository,
        "states": states,
        "overall": overall,
        "recovery_action": action,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def assess(probe):
    validate_probe(probe)
    states = {name: probe["signals"][name]["state"] for name in SIGNAL_STATES}
    reasons = []
    overall = "HEALTHY"
    action = "none"

    # Recovery faults take priority over transient waits. This ordering does not
    # grant permission to perform the proposed recovery.
    if states["scheduler"] == "drift":
        overall, action = "RECOVERY_REQUIRED", "repair_scheduler"
        reasons.append("desired and observed scheduler state differ")
    elif states["chat"] in {"archived", "missing"}:
        overall, action = "RECOVERY_REQUIRED", "restore_chat_dependency"
        reasons.append(f"watchdog chat dependency is {states['chat']}")
    elif states["invocation"] in {"idle", "completed"} and states["lease"] in {"fresh", "stale", "expired"}:
        overall, action = "RECOVERY_REQUIRED", "reconcile_orphan_lease"
        reasons.append("orphan lease: no live invocation is expected while ownership remains held")
    elif states["external"] in {"unknown", "terminal_unreconciled"}:
        overall, action = "BLOCKED", "reconcile_external"
        reasons.append(f"external operation is {states['external']}")
    elif states["external"] in {"queued", "running"}:
        overall, action = "BLOCKED", "observe_external"
        reasons.append(f"external operation is {states['external']}")
    elif states["scheduler"] == "overdue":
        overall, action = "STALLED", "diagnose_scheduler_delivery"
        reasons.append("scheduler is enabled but execution is overdue")
    elif states["progress"] == "stale":
        overall, action = "STALLED", "diagnose_no_progress"
        reasons.append("no meaningful repository/provider progress within the configured progress window")
    elif states["lease"] in {"stale", "expired"} and states["invocation"] in {"running", "unknown"}:
        overall, action = "DEGRADED", "diagnose_owner_liveness"
        reasons.append("lease freshness and invocation liveness disagree")
    elif any(state == "unknown" for state in states.values()) or states["progress"] == "none":
        overall, action = "DEGRADED", "complete_health_probe"
        reasons.append("one or more watchdog health signals are unknown or lack progress evidence")

    fingerprint = _fingerprint(probe["repository"], states, overall, action)
    return {
        "schema": ASSESSMENT_SCHEMA,
        "repository": probe["repository"],
        "observed_at_utc": probe["observed_at_utc"],
        "overall": overall,
        "states": states,
        "reasons": reasons,
        "recovery_action": action,
        "fingerprint": fingerprint,
        "authorizes_takeover": False,
        "authorizes_external_start": False,
        "authorizes_product_write": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", help="watchdog-health-probe/v1 JSON file")
    parser.add_argument("--output", help="optional assessment JSON output path")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.probe).read_text(encoding="utf-8")
        if len(raw) > 262144:
            raise ValueError("health probe exceeds 256 KiB")
        result = assess(json.loads(raw))
        rendered = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
