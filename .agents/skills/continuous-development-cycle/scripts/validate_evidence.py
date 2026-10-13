#!/usr/bin/env python3
"""Validate stored command evidence against an independently supplied plan and SHA."""
from __future__ import annotations

import argparse
from datetime import datetime
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
from run_checks import (EVIDENCE_SCHEMA, SHA_PATTERN, artifact, canonical, classify, digest,
                        file_digest, gate_status, junit_report, load_json, load_plan, render_argv)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timestamp(value):
    require(isinstance(value, str) and value.endswith("Z"), "UTC timestamp required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_observation(value):
    require(isinstance(value, dict) and set(value) == {"sha", "clean", "status_porcelain", "error"}, "invalid source observation")
    require(value["sha"] is None or isinstance(value["sha"], str) and SHA_PATTERN.fullmatch(value["sha"]), "invalid observed SHA")
    require(type(value["clean"]) is bool, "source clean must be boolean")
    require(value["status_porcelain"] is None or isinstance(value["status_porcelain"], str), "invalid source status")
    require(value["error"] is None or isinstance(value["error"], str) and bool(value["error"]), "invalid source error")
    require(not value["clean"] or value["sha"] and value["status_porcelain"] == "" and value["error"] is None,
            "clean source contradicts source observations")


def validate(evidence_path, plan_path, candidate, environment_config_sha256, environment_id=None):
    require(SHA_PATTERN.fullmatch(candidate), "expected candidate-sha must be a full lowercase SHA")
    require(re.fullmatch(r"[0-9a-f]{64}", environment_config_sha256), "expected environment configuration digest must be 64 lowercase hex characters")
    plan = load_plan(plan_path)
    root = Path(evidence_path).resolve().parent
    evidence = load_json(evidence_path)
    require(isinstance(evidence, dict) and evidence.get("schema") == EVIDENCE_SCHEMA, "wrong evidence schema")
    require(evidence.get("candidate_sha") == candidate, "evidence candidate differs from expected candidate")
    plan_sha = digest(canonical(plan))
    require(evidence.get("plan_sha256") == plan_sha, "evidence plan differs from expected check plan")
    require(load_json(artifact(root, "plan.json")) == plan, "saved plan differs from expected check plan")
    require(evidence.get("runner_status") == "COMPLETE", "runner did not finish; no final gate evidence")
    require(isinstance(evidence.get("checks"), list) and len(evidence["checks"]) == len(plan["checks"]),
            "missing or extra command results")
    started = timestamp(evidence["started_at_utc"])
    ended = timestamp(evidence["ended_at_utc"])
    require(started <= ended, "evidence ends before it starts")
    original_output = Path(evidence["output_dir"])
    worktree = Path(evidence["worktree"])
    require(original_output.is_absolute() and worktree.is_absolute() and original_output != worktree
            and worktree not in original_output.parents, "evidence output must be outside original source worktree")
    environment = evidence["environment"]
    require(isinstance(environment, dict) and set(environment) == {"id", "configuration_sha256", "details", "fingerprint"}, "invalid environment evidence")
    require(isinstance(environment["id"], str) and environment["id"].strip(), "environment identity required")
    require(environment_id is None or environment_id == environment["id"], "environment identity differs from expected environment")
    require(environment["configuration_sha256"] == environment_config_sha256, "environment configuration differs from expected configuration")
    require(isinstance(environment["details"], dict) and set(environment["details"]) ==
            {"system", "release", "machine", "python", "python_executable", "git"}, "missing environment details")
    require(all(isinstance(value, str) and value for value in environment["details"].values()), "empty environment detail")
    require(environment["fingerprint"] == digest(canonical({"id": environment["id"], "configuration_sha256": environment["configuration_sha256"], "details": environment["details"]})),
            "environment fingerprint mismatch")
    validate_observation(evidence["source_before"])
    validate_observation(evidence["source_after"])
    previous_end = started
    for index, (check, result) in enumerate(zip(plan["checks"], evidence["checks"]), 1):
        require(isinstance(result, dict), "invalid command result")
        name = f"{index:03d}-{check['id']}"
        expected_fields = {"schema": EVIDENCE_SCHEMA, "id": check["id"], "kind": check["kind"],
                           "required": check["required"], "candidate_sha": candidate, "plan_sha256": plan_sha,
                           "environment": environment, "timeout_seconds": check["timeout_seconds"],
                           "expected_red": check.get("expected_red"), "argv": render_argv(check, original_output / name),
                           "result_path": f"{name}/result.json"}
        for key, expected in expected_fields.items():
            require(result.get(key) == expected and (key != "required" or type(result[key]) is bool),
                    f"{check['id']}: {key} differs from declared plan/run")
        require(load_json(artifact(root, result["result_path"])) == result, f"{check['id']}: per-command result differs from summary")
        check_start, check_end = timestamp(result["started_at_utc"]), timestamp(result["ended_at_utc"])
        require(previous_end <= check_start <= check_end <= ended, "command timestamps contradict sequential execution")
        previous_end = check_end
        duration = result["duration_seconds"]
        require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0, "invalid command duration")
        for side in ("before", "after"):
            validate_observation(result[side])
        require(type(result["executed"]) is bool and isinstance(result["diagnostic"], str), "invalid execution facts")
        if result["executed"]:
            require(bool(result["argv"]) and type(result["exit_code"]) is int and result["termination"] in {"completed", "timeout"},
                    "executed command must have actual exit and termination")
        else:
            require(result["exit_code"] is None and result["termination"] == "not_run" and result["diagnostic"],
                    "NOT_RUN must have no exit and a diagnostic")
        require(result["log"]["path"] == f"{name}/command.log", "unexpected command log path")
        require(file_digest(artifact(root, result["log"]["path"])) == result["log"]["sha256"], "command log hash mismatch")
        if check["kind"] == "test":
            require(result["test_report"] == junit_report(root, f"{name}/junit.xml"), "JUnit bytes/counters differ from recorded evidence")
        else:
            require(result["test_report"] is None, "unexpected test report on non-test check")
        status, reason = classify(check, result, root, candidate)
        require(result["status"] == status and result["reason"] == reason, f"{check['id']}: reported status contradicts command evidence")
    gate = gate_status(evidence, plan)
    require(evidence.get("gate_status") == gate and type(evidence.get("final_green")) is bool
            and evidence["final_green"] == (gate == "GREEN"), "reported gate contradicts command evidence")
    return gate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Exit 0: valid GREEN evidence. Exit 1: valid non-green evidence. Exit 2: invalid/incomplete evidence or inputs. This verifies local records, not cryptographic remote attestation.")
    parser.add_argument("--evidence", required=True, help="evidence.json; keep plan, per-command JSON, logs and JUnit files beside it")
    parser.add_argument("--plan", required=True, help="independently trusted command-check-plan/v1 JSON")
    parser.add_argument("--candidate-sha", required=True, help="independently known full candidate SHA")
    parser.add_argument("--environment-config-sha256", required=True, help="independently trusted reviewed configuration SHA-256 (64 lowercase hex)")
    parser.add_argument("--environment-id", help="expected environment identity, when constrained")
    args = parser.parse_args(argv)
    try:
        gate = validate(args.evidence, args.plan, args.candidate_sha, args.environment_config_sha256, args.environment_id)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 2
    print(f"VALID: gate={gate}; final_green={str(gate == 'GREEN').lower()}")
    return 0 if gate == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
