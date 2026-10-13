#!/usr/bin/env python3
"""Minimal independent sentinel for the Fleet Supervisor watchdog materialization.

The sentinel is intentionally small. It does not supervise product work and does
not become a second Fleet controller. An external scheduler may invoke it with an
authorized watchdog-survivability backend/store; the durable desired state remains
authoritative.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

from git_document_store import GitDocumentStore
from watchdog_survivability import now_utc
from watchdog_survivability_runtime import WatchdogSurvivabilityRuntime

SCHEMA = "fleet-supervisor-sentinel/v1"


def validate_binding(binding):
    if (not isinstance(binding, dict)
            or set(binding) != {"project_id", "source_ref", "role"}
            or binding.get("role") != "fleet-supervisor"):
        raise ValueError("sentinel binding must target the fleet-supervisor role")
    for key in ("project_id", "source_ref"):
        if not isinstance(binding.get(key), str) or not binding[key].strip():
            raise ValueError("sentinel binding is incomplete")
    return binding


def reconcile_supervisor(runtime, binding):
    validate_binding(binding)
    result = runtime.reconcile(binding)
    if not isinstance(result, dict) or not isinstance(result.get("outcome"), str):
        raise ValueError("survivability runtime result invalid")
    assessment = result.get("assessment", {})
    continuation = True
    if result["outcome"] == "no_effect":
        continuation = assessment.get("overall") not in {
            "HEALTHY", "OWNER_PAUSED", "PROJECT_TERMINAL"
        }
    elif result["outcome"] == "run_requested":
        continuation = False
    elif result["outcome"] == "duplicates_quiesced":
        continuation = assessment.get("action") == "QUIESCE_DUPLICATES"
    return {
        "schema": SCHEMA,
        "binding": dict(binding),
        "result": result,
        "continuation_required": bool(continuation),
        "authorizes_product_write": False,
        "authorizes_scheduler_mutation": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON with store, binding and optional backend_config")
    parser.add_argument("--backend", required=True,
                        help="explicit installed module:factory supplying survivability scheduler capabilities")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.config).read_text(encoding="utf-8")
        if len(raw) > 1048576:
            raise ValueError("sentinel config exceeds 1 MiB")
        config = json.loads(raw)
        module, separator, factory = args.backend.partition(":")
        if not separator or not module or not factory:
            raise ValueError("backend must be an explicit module:factory")
        backend = getattr(importlib.import_module(module), factory)(config.get("backend_config", {}))
        store = GitDocumentStore(**config["store"])
        runtime = WatchdogSurvivabilityRuntime(
            store, backend, clock=now_utc,
            max_age_seconds=config.get("max_age_seconds", 120))
        result = reconcile_supervisor(runtime, config["binding"])
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, AttributeError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
