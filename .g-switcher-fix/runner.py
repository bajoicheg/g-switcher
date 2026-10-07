#!/usr/bin/env python3
"""Actions scaffold: canonical CDC 2.11.9 bridge; no product implementation here.

Required environment: CDC_REPO_ROOT, CDC_WORKER_PATH, CDC_PAYLOAD_SHA256,
CDC_WRITE_PATHS_JSON. The worker must apply the pinned payload, validate it,
commit only its declared paths, leave its isolated worktree clean and exit.
Publication and project-lease release belong exclusively to managed_host_bridge.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

BASE = "e2159a7856ea12b4c6237820965263f5d6f92a4b"
PACKAGE_TREE = "6867b012d01d776c2c0236b110980ba2c1292c26"
REPOSITORY = "bajoicheg/g-switcher"
SOURCE_REF = "refs/heads/release/2.0.1"
LEASE_REF = "refs/heads/cdc/coordination"
MAX_POLL_SECONDS = 20 * 60
CANCEL_DRAIN_SECONDS = 60


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def git(repo, *argv):
    process = subprocess.run(
        ["git", "-C", str(repo), *argv], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=30,
    )
    if process.returncode:
        # Never print transport stderr/config that may include authentication.
        raise RuntimeError("Git command failed: " + argv[0])
    return process.stdout.strip()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def exact_remote_head(repo, ref):
    rows = git(repo, "ls-remote", "--refs", "origin", ref).splitlines()
    if len(rows) != 1:
        raise RuntimeError("Remote ref must resolve exactly once")
    sha, observed_ref = rows[0].split("\t")
    if observed_ref != ref or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Invalid remote ref response")
    return sha


def main():
    repo = Path(os.environ["CDC_REPO_ROOT"]).resolve()
    worker = Path(os.environ["CDC_WORKER_PATH"]).resolve()
    if not worker.is_file() or worker == repo or repo in worker.parents:
        raise RuntimeError("Worker script must be outside the product checkout")
    payload_digest = os.environ["CDC_PAYLOAD_SHA256"]
    if not re.fullmatch(r"[0-9a-f]{64}", payload_digest):
        raise RuntimeError("CDC_PAYLOAD_SHA256 must pin the actual payload bytes")
    paths = json.loads(os.environ["CDC_WRITE_PATHS_JSON"])
    if not isinstance(paths, list) or not paths:
        raise RuntimeError("Supply the explicit product write set")
    if any(path.startswith(".agents/") or path.startswith(".github/") for path in paths):
        raise RuntimeError("This product task cannot alter CDC or workflow files")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    key = "word-native-" + run_id + "-" + attempt
    run_root = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / ("cdc-" + key)
    journal_root = run_root / "journal"
    handle_root = run_root / "handles"
    protocol_root = run_root / "protocol"
    request_path = protocol_root / "start.json"
    recovering = request_path.exists()

    if git(repo, "rev-parse", "HEAD") != BASE:
        raise RuntimeError("Product checkout must be the pinned source commit")
    if not recovering and exact_remote_head(repo, SOURCE_REF) != BASE:
        raise RuntimeError("Live source moved; reconcile before a new attempt")
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("Product control checkout is dirty")
    observed_tree = git(repo, "rev-parse", BASE + ":.agents/skills/continuous-development-cycle")
    if observed_tree != PACKAGE_TREE:
        raise RuntimeError("Canonical CDC package identity mismatch")
    scripts = repo / ".agents/skills/continuous-development-cycle/scripts"
    sys.path.insert(0, str(scripts))
    import managed_host_bridge as bridge
    from git_lease_store import GitLeaseStore
    from git_remote_identity import remote_identity
    import managed_executor_pool as pool

    source_id = remote_identity(repo, "origin")
    lease_store = GitLeaseStore(repo, "origin", LEASE_REF)
    lease_revision, lease = lease_store.read()
    if lease is None or lease.get("repository") != REPOSITORY or lease.get("source_ref") != SOURCE_REF:
        raise RuntimeError("Authoritative project lease binding is absent or mismatched")
    if not recovering and (lease.get("owner_id") is not None or lease.get("external_guard") is not None):
        raise RuntimeError("Project is not at a released, unguarded boundary")

    # This verifies native runner push scope without advancing any shared ref.
    # The product payload deliberately contains no workflow changes.
    if not recovering:
        git(repo, "push", "--dry-run", "origin", BASE + ":" + SOURCE_REF)
        git(repo, "push", "--dry-run", "origin", lease_revision + ":" + LEASE_REF)
    task_id = os.environ.get("CDC_TASK_ID", "word-native-product-fix")
    expected_outputs = json.loads(os.environ.get("CDC_EXPECTED_OUTPUTS_JSON", '["out:word-native-product-candidate"]'))
    expected_evidence = json.loads(os.environ.get("CDC_EXPECTED_EVIDENCE_JSON", '["evidence:pinned-payload-and-worker-checks"]'))
    plan = {
        "schema": "managed-executor-pool-plan/v1", "pool_id": key,
        "change_id": "g-switcher-word-native-fix-publication",  # managed task only
        "parent_invocation_id": "github-actions:" + run_id + ":" + attempt,
        "base_sha": BASE, "integrator_id": "canonical-managed-host-bridge",
        "coordination_ref": "refs/heads/cdc/managed-word-fix/" + key,
        "coordination_store_id": source_id, "max_parallel": 1,
        "total_runtime_budget_seconds": MAX_POLL_SECONDS,
        "total_cost_budget_units": 1,
        "tasks": [{
            "id": task_id, "role": "writer", "required": True, "dependencies": [],
            "executor_id": "managed-word-native-writer",
            "branch": "cdc/managed-word-worker/" + key,
            # The runtime resolves this relative to repo.parent, outside repo.
            "worktree": "managed-worktrees/" + key,
            "write_paths": paths, "expected_outputs": expected_outputs,
            "expected_evidence": expected_evidence, "backend_preferences": ["local_command"],
            "max_runtime_seconds": 15 * 60, "max_cost_units": 1,
        }],
    }
    pool.validate_plan(plan)
    argv = [sys.executable, "-B", str(worker)]
    # Worker uses these existing environment bindings; it must independently
    # verify payload bytes and implement the required output/evidence labels.
    os.environ["CDC_WORKER_EVIDENCE_ROOT"] = str(run_root / "worker-evidence")
    if request_path.exists():
        request = json.loads(request_path.read_text())
        if request["plan"] != plan or request["argv"] != argv:
            raise RuntimeError("Do not change immutable context of an existing attempt")
    else:
        request = {
            "schema": "managed-host-start/v1", "repo_root": str(repo), "remote": "origin",
            "plan": plan, "journal_root": str(journal_root), "handle_root": str(handle_root),
            "lease_coordination_ref": LEASE_REF, "lease_repository": REPOSITORY,
            "lease_source_ref": SOURCE_REF, "task_id": task_id, "attempt_id": key + "-a1",
            "reservation_token": "reserve:" + key, "owner_id": str(uuid.uuid4()), "argv": argv,
        }
        write_json(request_path, request)
    prepared_checkpoint = {
        "schema": "g-switcher-managed-product-checkpoint/v1", "base_sha": BASE,
        "payload_sha256": payload_digest, "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
        "task_scope": plan["change_id"], "phase": "implementation",
        "remaining": ["fresh exact-candidate Windows validation", "real Word compatibility acceptance", "final review", "explicit public-promotion approval"],
        "public_promotion_authorized": False, "scheduler_mutations": 0,
    }
    checkpoint_path = protocol_root / "prepared-checkpoint.json"
    if checkpoint_path.exists() and json.loads(checkpoint_path.read_text()) != prepared_checkpoint:
        raise RuntimeError("Payload or worker bytes changed during an existing attempt")
    write_json(checkpoint_path, prepared_checkpoint)

    interrupted = []
    def interrupt(signum, _frame):
        interrupted.append(signum)
        emit("cancellation_requested", signal=signum)
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)

    handle = None
    try:
        handle = bridge.start(request)
        write_json(protocol_root / "handle.json", handle)
        emit("managed_started", handle_id=handle["handle_id"], state=handle["state"])
        observe_request = {"schema": "managed-host-observe/v1", "handle_root": str(handle_root), "handle_id": handle["handle_id"]}
        write_json(protocol_root / "observe.json", observe_request)
        deadline = time.monotonic() + MAX_POLL_SECONDS
        prior = None
        last_emit = 0.0
        while True:
            observed = bridge.observe(observe_request)
            write_json(protocol_root / "observed.json", observed)
            state = (observed.get("runtime_status"), observed.get("pending_terminal_status"))
            if state != prior or time.monotonic() - last_emit >= 45:
                emit("managed_observed", runtime_status=state[0], pending_terminal_status=state[1])
                prior = state
                last_emit = time.monotonic()
            if observed.get("runtime_status") == "awaiting_release":
                break
            if observed.get("state") == "released" and observed.get("quiescent") is True:
                break  # same exact handle/finish recovery, including post-release interruption
            if interrupted or time.monotonic() >= deadline:
                raise RuntimeError("Host poll deadline or cancellation reached")
            if observed.get("quiescent") is True:
                raise RuntimeError("Worker became quiescent before managed finalization")
            time.sleep(5)

        status = observed.get("pending_terminal_status") or observed.get("runtime_status")
        if status != "succeeded":
            # Validation logs contain compiler/test output only. Preserve the
            # canonical finish/release path even when evidence printing fails.
            try:
                evidence = run_root / "worker-evidence"
                checks_path = evidence / "checks.json"
                checks = json.loads(checks_path.read_text()) if checks_path.is_file() else []
                emit("worker_checks", checks=checks)
                for item in checks:
                    if item.get("exit_code") and re.fullmatch(r"[a-z0-9-]+", item.get("label", "")):
                        path = evidence / (item["label"] + ".log")
                        if path.is_file():
                            print("WORKER_FAILED_CHECK " + item["label"], flush=True)
                            print(path.read_text(errors="replace")[-24000:], flush=True)
            except Exception as error:
                emit("worker_diagnostic_unavailable", error_type=type(error).__name__)
        finish_request = {
            "schema": "managed-host-finish/v1", "handle_root": str(handle_root), "handle_id": handle["handle_id"],
            "output_refs": expected_outputs if status == "succeeded" else ["failure:worker:" + str(status)],
            "evidence_refs": expected_evidence + ["https://github.com/" + REPOSITORY + "/actions/runs/" + run_id] if status == "succeeded" else ["failure:runtime-terminal:" + str(status)],
            # Canonical writer finish selects a persisted git:source@candidate
            # checkpoint after publication. This is a managed task boundary,
            # never a claim of Word acceptance or project release completion.
            "checkpoint_ref": None,
        }
        write_json(protocol_root / "finish.json", finish_request)
        result = bridge.finish(finish_request)
        write_json(protocol_root / "finished.json", result)
        emit("managed_finished", **result)
        if result.get("final_response_allowed") is not True:
            raise RuntimeError("Canonical final-response gate did not pass")
        if result.get("worker_status") != "succeeded" or not result.get("scope_complete"):
            raise RuntimeError("Worker failed; its exact managed lease was finalized")
        candidate = result["published_commit"]
        if not candidate or exact_remote_head(repo, SOURCE_REF) != candidate:
            raise RuntimeError("Published candidate failed exact source readback")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                stream.write("candidate_sha=" + candidate + "\n")
                stream.write("managed_handle_id=" + handle["handle_id"] + "\n")
                stream.write("release_lease_revision=" + result["release_receipt"]["lease_revision"] + "\n")
        return 0
    except Exception as original:
        emit("host_error", error_type=type(original).__name__)
        # Recover an interrupted start through its already persisted exact
        # session, never invent a replacement worker or acquire a host lease.
        if handle is None:
            sessions = list(handle_root.glob("*.json")) if handle_root.exists() else []
            matching = [json.loads(p.read_text()) for p in sessions]
            matching = [s for s in matching if s.get("task_id") == task_id and s.get("attempt_id") == request["attempt_id"]]
            if len(matching) == 1:
                handle = {"handle_id": matching[0]["handle_id"]}
        if handle is not None:
            observe_request = {"schema": "managed-host-observe/v1", "handle_root": str(handle_root), "handle_id": handle["handle_id"]}
            try:
                observed = bridge.observe(observe_request)
                if observed.get("state") == "released" and observed.get("quiescent") is True:
                    emit("already_released", handle_id=handle["handle_id"], runtime_status=observed.get("runtime_status"))
                    return 1  # preserve the job failure; never reacquire or relaunch
                if observed.get("lease_owned") and observed.get("runtime_status") != "awaiting_release":
                    bridge.cancel({"schema": "managed-host-cancel/v1", "handle_root": str(handle_root), "handle_id": handle["handle_id"]})
                    deadline = time.monotonic() + CANCEL_DRAIN_SECONDS
                    while time.monotonic() < deadline:
                        observed = bridge.observe(observe_request)
                        if observed.get("runtime_status") == "awaiting_release":
                            break
                        time.sleep(2)
                status = observed.get("pending_terminal_status")
                # Successful publication rejection/unknown is NOT worker
                # failure. Preserve its publication journal and exact hold.
                # Retry the same finish only after authoritative reconciliation.
                if observed.get("runtime_status") == "awaiting_release" and status in {"failed", "cancelled", "timed_out"}:
                    recovery = bridge.finish({
                        "schema": "managed-host-finish/v1", "handle_root": str(handle_root), "handle_id": handle["handle_id"],
                        "output_refs": ["failure:worker:" + status], "evidence_refs": ["failure:runtime-terminal:" + status], "checkpoint_ref": None,
                    })
                    write_json(protocol_root / "failure-finished.json", recovery)
                    emit("failure_finalized", **recovery)
                else:
                    write_json(protocol_root / "recovery-blocker.json", {
                        "handle_id": handle["handle_id"], "observation": observed,
                        "next_action": "Reconcile this exact handle and publication journal, then retry its canonical finish; never start a replacement or hand-edit the lease.",
                    })
                    emit("reconciliation_required", handle_id=handle["handle_id"])
            except Exception as cleanup:
                emit("cleanup_blocked", error_type=type(cleanup).__name__, handle_id=handle["handle_id"])
        raise


if __name__ == "__main__":
    raise SystemExit(main())
