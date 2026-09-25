#!/usr/bin/env python3
"""Run an authorized check plan sequentially and preserve exact-candidate evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


PLAN_SCHEMA = "command-check-plan/v1"
EVIDENCE_SCHEMA = "command-evidence/v1"
SKILL_VERSION = "2.6.0"
SHA_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
KINDS = {"build", "test", "lint", "schema", "check"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON: {value}")))


def load_plan(path):
    plan = load_json(path)
    if not isinstance(plan, dict) or set(plan) != {"schema", "checks"} or plan["schema"] != PLAN_SCHEMA:
        raise ValueError(f"plan requires schema {PLAN_SCHEMA} and checks only")
    if not isinstance(plan["checks"], list) or not plan["checks"]:
        raise ValueError("plan requires a nonempty checks list")
    identifiers = set()
    required = {"id", "kind", "required", "argv", "timeout_seconds"}
    for check in plan["checks"]:
        if not isinstance(check, dict) or not required <= set(check) or set(check) - required - {"expected_red"}:
            raise ValueError("each check requires id, kind, required, argv, timeout_seconds; only expected_red is optional")
        name = check["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name) or name in identifiers:
            raise ValueError("check ids must be unique safe names of at most 64 characters")
        identifiers.add(name)
        if not isinstance(check["kind"], str) or check["kind"] not in KINDS or type(check["required"]) is not bool:
            raise ValueError(f"{name}: unsupported kind or non-boolean required")
        argv = check["argv"]
        if not isinstance(argv, list) or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
            raise ValueError(f"{name}: argv must be a list of strings without NUL bytes")
        if argv and not argv[0].strip():
            raise ValueError(f"{name}: executable cannot be blank; use [] for an unavailable check")
        timeout = check["timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
            raise ValueError(f"{name}: timeout_seconds must be positive and at most 86400")
        if "expected_red" in check:
            red = check["expected_red"]
            if (not isinstance(red, dict) or set(red) != {"exit_code", "signature", "reason"}
                    or type(red["exit_code"]) is not int or not 1 <= red["exit_code"] <= 255
                    or any(not isinstance(red[key], str) or not red[key].strip() for key in ("signature", "reason"))):
                raise ValueError(f"{name}: expected_red requires nonzero exit_code (1..255), literal signature and reason")
    if not any(check["required"] for check in plan["checks"]):
        raise ValueError("plan must contain at least one required check")
    return plan


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git(worktree, *args):
    return subprocess.check_output(["git", "-C", str(worktree), *args], text=True,
                                   stderr=subprocess.PIPE, timeout=15).strip()


def observe_source(worktree):
    result = {"sha": None, "clean": False, "status_porcelain": None, "error": None}
    try:
        result["sha"] = git(worktree, "rev-parse", "HEAD")
        result["status_porcelain"] = git(worktree, "-c", "core.fsmonitor=false", "status", "--porcelain=v1",
                                         "--untracked-files=all", "--ignore-submodules=none")
        result["clean"] = result["status_porcelain"] == ""
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    return result


def source_matches(observation, candidate):
    return (isinstance(observation, dict) and observation.get("sha") == candidate
            and observation.get("clean") is True and observation.get("status_porcelain") == ""
            and observation.get("error") is None)


def environment_identity(identity, configuration_sha256):
    details = {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
               "python": platform.python_version(), "python_executable": sys.executable,
               "git": subprocess.check_output(["git", "--version"], text=True, timeout=15).strip()}
    result = {"id": identity, "configuration_sha256": configuration_sha256, "details": details}
    result["fingerprint"] = digest(canonical(result))
    return result


def artifact(root, relative):
    """Reject traversal and symlink artifacts instead of reading unrelated files."""
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("artifact path must stay inside the evidence directory")
    path = root / relative_path
    if path.resolve() != path.absolute() or not path.is_file():
        raise ValueError(f"artifact missing, not a regular file, or symlinked: {relative}")
    return path


def file_digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def junit_report(root, relative):
    result = {"path": relative, "sha256": None, "counts": None, "error": None}
    try:
        path = artifact(root, relative)
        result["sha256"] = file_digest(path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("JUnit report exceeds 16 MiB")
        xml = path.read_bytes()
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("JUnit DTDs/entities are not supported")
        element = ET.fromstring(xml)
        if any(node.tag.startswith("{") for node in element.iter()):
            raise ValueError("JUnit namespaces are unsupported")
        if element.tag not in {"testsuite", "testsuites"}:
            raise ValueError("JUnit root must be testsuite or testsuites")
        suites = [node for node in element.iter("testsuite") if not list(node.iter("testsuite"))[1:]]
        if not suites:
            raise ValueError("JUnit contains no test suites")
        totals = dict(tests=0, failures=0, errors=0, skipped=0)
        leaf_counts = {}
        for suite in suites:
            counters = {}
            for key in totals:
                value = suite.get(key, "0" if key == "skipped" else "")
                if not re.fullmatch(r"[0-9]+", value):
                    raise ValueError(f"JUnit suite lacks a nonnegative integer {key} counter")
                counters[key] = int(value)
            if counters["failures"] + counters["errors"] + counters["skipped"] > counters["tests"]:
                raise ValueError("JUnit outcome counters exceed tests")
            cases = suite.findall("testcase")
            if cases:
                actual = dict(tests=len(cases), failures=sum(case.find("failure") is not None for case in cases),
                              errors=sum(case.find("error") is not None for case in cases),
                              skipped=sum(case.find("skipped") is not None for case in cases))
                if actual != counters:
                    raise ValueError("JUnit counters disagree with testcase elements")
            leaf_counts[suite] = counters
            for key in totals:
                totals[key] += counters[key]
        for aggregate in element.iter():
            if aggregate.tag not in {"testsuite", "testsuites"} or aggregate in leaf_counts:
                continue
            if aggregate.findall("testcase"):
                raise ValueError("JUnit mixed direct testcases and nested suites are unsupported")
            descendants = [leaf_counts[node] for node in aggregate.iter("testsuite") if node in leaf_counts]
            for key in totals:
                value = aggregate.get(key)
                if value is not None and (not re.fullmatch(r"[0-9]+", value)
                                          or int(value) != sum(counts[key] for counts in descendants)):
                    raise ValueError("JUnit aggregate counters disagree with child suites")
        result["counts"] = totals
    except (ValueError, OSError, ET.ParseError) as error:
        result["error"] = str(error)
    return result


def render_argv(check, check_dir):
    return [arg.replace("{check_dir}", str(check_dir)).replace("{junit_xml}", str(check_dir / "junit.xml"))
            for arg in check["argv"]]


def signature_present(path, signature):
    needle = signature.encode("utf-8")
    tail = b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            data = tail + block
            if needle in data:
                return True
            tail = data[-max(0, len(needle) - 1):] if len(needle) > 1 else b""
    return False


def classify(check, result, root, candidate):
    if not result["executed"]:
        return "NOT_RUN", result["diagnostic"] or "command did not start"
    if not source_matches(result["before"], candidate) or not source_matches(result["after"], candidate):
        return "FAIL", "candidate SHA or clean source requirement failed"
    if result["termination"] != "completed" or type(result["exit_code"]) is not int:
        return "FAIL", "command did not complete normally"
    counts = None
    if check["kind"] == "test":
        report = result["test_report"]
        if report["error"] or report["counts"] is None:
            return "FAIL", "valid fresh JUnit report required"
        counts = report["counts"]
        if counts["tests"] - counts["skipped"] <= 0:
            return "FAIL", "JUnit must show at least one non-skipped test"
    red = check.get("expected_red")
    if red:
        if (result["exit_code"] == red["exit_code"]
                and signature_present(artifact(root, result["log"]["path"]), red["signature"])
                and (counts is None or counts["failures"] + counts["errors"] > 0)):
            return "EXPECTED_RED", red["reason"]
        return "FAIL", "predeclared RED exit/signature/test failure did not match"
    if result["exit_code"] != 0:
        return "FAIL", f"command exited {result['exit_code']}"
    if counts and counts["failures"] + counts["errors"]:
        return "FAIL", "JUnit reports failures or errors despite zero command exit"
    return "PASS", "command and required evidence passed"


def gate_status(evidence, plan):
    if evidence["runner_status"] != "COMPLETE" or len(evidence["checks"]) != len(plan["checks"]):
        return "NOT_RUN"
    if (not source_matches(evidence["source_before"], evidence["candidate_sha"])
            or not source_matches(evidence["source_after"], evidence["candidate_sha"])):
        return "FAIL"
    if any(not source_matches(check[side], evidence["candidate_sha"])
           for check in evidence["checks"] for side in ("before", "after")):
        return "FAIL"
    if any(check["required"] and check["status"] in {"FAIL", "NOT_RUN"} for check in evidence["checks"]):
        return "FAIL"
    if any(check["status"] == "EXPECTED_RED" for check in evidence["checks"]):
        return "EXPECTED_RED"
    return "GREEN"


def stop_process(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait(timeout=10)


def run_one(check, evidence, output, index, blocked):
    directory = output / f"{index:03d}-{check['id']}"
    directory.mkdir()
    relative = directory.relative_to(output)
    started = time.monotonic()
    result = {"schema": EVIDENCE_SCHEMA, "id": check["id"], "kind": check["kind"], "required": check["required"],
              "candidate_sha": evidence["candidate_sha"], "environment": evidence["environment"],
              "plan_sha256": evidence["plan_sha256"], "argv": render_argv(check, directory),
              "timeout_seconds": check["timeout_seconds"], "expected_red": check.get("expected_red"),
              "started_at_utc": utc_now(), "before": observe_source(evidence["worktree"]),
              "executed": False, "exit_code": None, "termination": "not_run", "diagnostic": "",
              "test_report": None, "result_path": (relative / "result.json").as_posix()}
    log_path = directory / "command.log"
    temporary_log = directory / "command.log.part"
    with temporary_log.open("xb") as log:
        if blocked or not source_matches(result["before"], evidence["candidate_sha"]):
            result["diagnostic"] = "candidate SHA or clean source requirement failed; command withheld"
        elif not check["argv"]:
            result["diagnostic"] = "empty argv: command unavailable"
        else:
            environment = dict(os.environ, EVIDENCE_CHECK_DIR=str(directory), EVIDENCE_JUNIT_XML=str(directory / "junit.xml"),
                               PYTHONDONTWRITEBYTECODE="1")
            try:
                process = subprocess.Popen(result["argv"], cwd=evidence["worktree"], env=environment, shell=False,
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=(os.name == "posix"))
                result["executed"] = True
            except OSError as error:
                result["diagnostic"] = f"command could not start: {error}"
            else:
                try:
                    result["exit_code"] = process.wait(timeout=check["timeout_seconds"])
                    result["termination"] = "completed"
                except subprocess.TimeoutExpired:
                    stop_process(process)
                    result["exit_code"] = process.returncode
                    result["termination"] = "timeout"
                    result["diagnostic"] = "timeout; process terminated"
                except BaseException:
                    stop_process(process)
                    raise
        log.flush()
        os.fsync(log.fileno())
    os.replace(temporary_log, log_path)
    result["log"] = {"path": (relative / "command.log").as_posix(), "sha256": file_digest(log_path)}
    if check["kind"] == "test":
        result["test_report"] = junit_report(output, (relative / "junit.xml").as_posix())
    result["after"] = observe_source(evidence["worktree"])
    result["ended_at_utc"] = utc_now()
    result["duration_seconds"] = round(time.monotonic() - started, 6)
    result["status"], result["reason"] = classify(check, result, output, evidence["candidate_sha"])
    atomic_json(directory / "result.json", result)
    return result


def run(args):
    plan = load_plan(args.plan)
    if not SHA_PATTERN.fullmatch(args.candidate_sha):
        raise ValueError("candidate-sha must be a full lowercase 40- or 64-character Git SHA")
    if not args.environment_id.strip():
        raise ValueError("environment-id cannot be blank")
    if not re.fullmatch(r"[0-9a-f]{64}", args.environment_config_sha256):
        raise ValueError("environment-config-sha256 must be a reviewed configuration digest: 64 lowercase hexadecimal characters")
    worktree = Path(git(Path(args.worktree).resolve(), "rev-parse", "--show-toplevel")).resolve()
    output = Path(os.path.abspath(args.output_dir))
    if output.resolve() != output or output == worktree or worktree in output.parents:
        raise ValueError("output-dir must be outside the worktree and have no symlink components")
    environment = environment_identity(args.environment_id, args.environment_config_sha256)
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"schema": EVIDENCE_SCHEMA, "skill_version": SKILL_VERSION, "candidate_sha": args.candidate_sha,
                "worktree": str(worktree), "output_dir": str(output), "environment": environment,
                "plan_sha256": digest(canonical(plan)), "started_at_utc": utc_now(), "ended_at_utc": None,
                "runner_status": "RUNNING", "gate_status": "NOT_RUN", "final_green": False,
                "source_before": observe_source(worktree), "source_after": None, "checks": []}
    atomic_json(output / "plan.json", plan)
    atomic_json(output / "evidence.json", evidence)
    try:
        blocked = False
        for index, check in enumerate(plan["checks"], 1):
            result = run_one(check, evidence, output, index, blocked)
            evidence["checks"].append(result)
            blocked = blocked or any(not source_matches(result[side], args.candidate_sha) for side in ("before", "after"))
            atomic_json(output / "evidence.json", evidence)
        evidence["source_after"] = observe_source(worktree)
        evidence["runner_status"] = "COMPLETE"
        evidence["gate_status"] = gate_status(evidence, plan)
        evidence["final_green"] = evidence["gate_status"] == "GREEN"
    except BaseException as error:
        evidence["runner_status"] = "ERROR"
        evidence["gate_status"] = "NOT_RUN"
        evidence["runner_error"] = str(error) or type(error).__name__
        raise
    finally:
        evidence["ended_at_utc"] = utc_now()
        atomic_json(output / "evidence.json", evidence)
    print(f"runner=COMPLETE gate={evidence['gate_status']} evidence={output / 'evidence.json'}")
    return 0 if evidence["final_green"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Exit 0: GREEN. Exit 1: completed, gate not GREEN (including EXPECTED_RED). Exit 2: input/runner error. Execute only already-authorized build/test/check commands.")
    parser.add_argument("--worktree", required=True, help="Git worktree; checks execute at its root")
    parser.add_argument("--candidate-sha", required=True, help="full exact candidate commit SHA")
    parser.add_argument("--plan", required=True, help="command-check-plan/v1 JSON")
    parser.add_argument("--output-dir", required=True, help="new directory outside the source worktree; must not exist")
    parser.add_argument("--environment-id", required=True, help="stable local/compute environment identity (no credentials)")
    parser.add_argument("--environment-config-sha256", required=True, help="64 lowercase hex SHA-256 of the reviewed SDK/dependency/setup contract")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print(f"ERROR: {error or type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
