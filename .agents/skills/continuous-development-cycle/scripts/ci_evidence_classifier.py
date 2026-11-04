#!/usr/bin/env python3
"""Classify CI evidence before choosing product or execution-channel remediation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

SCHEMA = "ci-execution-observation/v1"
STATUSES = {"queued", "in_progress", "completed"}
CONCLUSIONS = {None, "success", "failure", "cancelled", "timed_out", "action_required", "startup_failure"}

def validate(data):
    fields = {
        "schema", "provider", "run_id", "run_status", "conclusion", "job_started",
        "executable_steps", "setup_steps_started", "product_steps_started", "product_failures"
    }
    if not isinstance(data, dict) or set(data) != fields or data.get("schema") != SCHEMA:
        raise ValueError("invalid CI execution observation")
    for name in ("provider", "run_id"):
        if not isinstance(data[name], str) or not data[name].strip():
            raise ValueError(f"{name} must be text")
    if data["run_status"] not in STATUSES or data["conclusion"] not in CONCLUSIONS:
        raise ValueError("CI status/conclusion invalid")
    if data["run_status"] != "completed" and data["conclusion"] is not None:
        raise ValueError("nonterminal run cannot have conclusion")
    if type(data["job_started"]) is not bool:
        raise ValueError("job_started must be boolean")
    for name in ("executable_steps", "setup_steps_started", "product_steps_started", "product_failures"):
        if type(data[name]) is not int or data[name] < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if data["setup_steps_started"] + data["product_steps_started"] > data["executable_steps"]:
        raise ValueError("step counters exceed executable_steps")
    if data["product_failures"] > data["product_steps_started"]:
        raise ValueError("product_failures exceed product_steps_started")
    if not data["job_started"] and data["executable_steps"]:
        raise ValueError("steps cannot execute before job start")
    return data

def classify(data):
    validate(data)
    terminal = data["run_status"] == "completed"
    if not data["job_started"] or data["executable_steps"] == 0:
        kind, action, proven, source = "pre_run_infrastructure", "recover_execution_channel", False, False
    elif data["product_steps_started"] == 0:
        kind, action, proven, source = "setup", "repair_setup_or_recover_channel", False, False
    elif terminal and data["conclusion"] == "success" and data["product_failures"] == 0:
        kind, action, proven, source = "terminal_success", "accept_success", True, False
    else:
        kind, proven = "product_test", True
        if not terminal:
            action, source = "observe_running_product_validation", False
        elif data["product_failures"] > 0:
            action, source = "correct_product_or_tests", True
        else:
            action, source = "inspect_product_execution_evidence", False
    return {
        "schema": "ci-evidence-classification/v1",
        "class": kind,
        "terminal": terminal,
        "product_execution_proven": proven,
        "source_change_allowed": source,
        "next_action": action,
        "authorizes_external_start": False,
        "authorizes_product_write": False,
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("observation"); args = p.parse_args(argv)
    try:
        result = classify(json.loads(Path(args.observation).read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr); return 2
    print(json.dumps(result, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
