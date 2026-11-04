#!/usr/bin/env python3
"""Bind durable project-lane admission to an actual worker backend start.

The coordinator owns the durable one-shot start claim. This adapter only calls
backend.start() after that claim is committed and re-read. Unknown backend
outcomes retain the lane pending-effect state and are observed, never replayed.

A compatible backend exposes start(request) and observe(request, receipt=None).
The released managed-executor LocalCommandBackend satisfies this contract and
prepares the isolated Git worktree before launching the worker command.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from project_lanes import LaneKind, READ_ONLY_ROLES


TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
ACTIVE = {"starting", "running"}
OBSERVED = ACTIVE | TERMINAL | {"unknown"}


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _write_request(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise ValueError("lane start journal identity mismatch") from None
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ProjectLaneExecutionAdapter:
    def __init__(self, coordinator, repo_root, backend, *, worktree_root, journal_root=None):
        self.coordinator = coordinator
        self.backend = backend
        self.repo_root = Path(repo_root).resolve()
        if not (self.repo_root / ".git").exists():
            # Worktree roots have a .git file; a bare/non-worktree root is not valid.
            raise ValueError("project lane execution requires a Git worktree root")
        self.worktree_root = Path(worktree_root).resolve()
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        if (self.worktree_root == self.repo_root
                or self.repo_root in self.worktree_root.parents
                or self.worktree_root in self.repo_root.parents):
            raise ValueError("worktree_root must be isolated from the product worktree")
        root = journal_root if journal_root is not None else getattr(backend, "journal_root", None)
        if root is None:
            raise ValueError("project lane execution requires a durable journal_root")
        self.journal_root = Path(root).resolve()
        self.journal_root.mkdir(parents=True, exist_ok=True)
        if (self.journal_root == self.repo_root or self.repo_root in self.journal_root.parents
                or self.journal_root == self.worktree_root
                or self.journal_root in self.worktree_root.parents
                or self.worktree_root in self.journal_root.parents):
            raise ValueError("journal_root must be isolated from product and worktree roots")

    def _lane(self, lane_id):
        state = self.coordinator.snapshot()
        lane = state["lanes"].get(lane_id)
        if lane is None:
            raise ValueError("unknown lane")
        return lane

    @staticmethod
    def _validate_argv(argv):
        if (not isinstance(argv, list) or not argv
                or any(not isinstance(item, str) or not item or "\0" in item for item in argv)):
            raise ValueError("argv must be a nonempty argument array")

    def _identity(self, lane):
        claim = lane["claim"]
        kind = LaneKind(claim["kind"])
        if kind == LaneKind.INTEGRATOR:
            capability = "integrator"
        elif kind == LaneKind.REVIEW or claim["role"] in READ_ONLY_ROLES:
            capability = "review"
        else:
            capability = "writer" if claim["write_paths"] else "review"
        return {
            "lane_id": claim["lane_id"],
            "invocation_id": claim["invocation_id"],
            "generation": lane["generation"],
            "executor_id": claim["executor_id"],
            "role": capability,
            "branch": claim["branch"],
            "base_sha": claim["source_head"],
        }

    def _directory(self, identity):
        return self.journal_root / _digest(identity).split(":", 1)[1]

    def _request(self, lane, operation, argv, timeout_seconds):
        claim = lane["claim"]
        if claim["kind"] == LaneKind.INTEGRATOR.value:
            raise ValueError("integrator lane cannot launch a worker backend")
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")
        identity = self._identity(lane)
        directory = self._directory(identity)
        raw_worktree = Path(claim["worktree"])
        cwd = (raw_worktree if raw_worktree.is_absolute()
               else self.worktree_root / raw_worktree).resolve()
        if cwd == self.worktree_root or self.worktree_root not in cwd.parents:
            raise ValueError("lane worktree escapes authorized worktree_root")
        if cwd == self.repo_root or self.repo_root in cwd.parents:
            raise ValueError("lane worktree overlaps the product worktree")
        if (cwd == self.journal_root or self.journal_root in cwd.parents
                or cwd in self.journal_root.parents):
            raise ValueError("lane worktree overlaps the execution journal")
        return {
            "schema": "project-lane-start/v1",
            "identity": identity,
            "claim": {
                "operation_id": operation["operation_id"],
                "lane_id": operation["lane_id"],
                "invocation_id": operation["invocation_id"],
                "generation": operation["generation"],
                "executor_id": operation["executor_id"],
                "source_head": operation["source_head"],
            },
            "argv": list(argv),
            "repo_root": str(self.repo_root),
            "cwd": str(cwd),
            "timeout_seconds": timeout_seconds,
            "journal_directory": str(directory),
        }

    @staticmethod
    def _validate_receipt(request, receipt):
        if not isinstance(receipt, dict):
            raise ValueError("lane backend observation must be a mapping")
        if receipt.get("identity") != request["identity"]:
            raise ValueError("lane backend observation identity mismatch")
        status = receipt.get("status")
        if status not in OBSERVED:
            raise ValueError("lane backend observation status invalid")
        if status == "unknown":
            if receipt.get("quiescent") is not False:
                raise ValueError("unknown lane backend state cannot prove quiescence")
            return
        if (receipt.get("claim") != request["claim"]
                or receipt.get("request_ref") != _digest(request)
                or receipt.get("launch_id") != _digest(request)):
            raise ValueError("lane backend receipt does not bind the durable start claim")
        terminal = status in TERMINAL
        if receipt.get("quiescent") is not terminal:
            raise ValueError("lane backend terminal state requires descendant quiescence")

    def _record(self, request, receipt):
        self._validate_receipt(request, receipt)
        status = receipt["status"]
        evidence_ref = receipt.get("launch_id") or _digest({
            "identity": request["identity"], "status": status,
            "reason": receipt.get("reason"),
        })
        ident = request["identity"]
        self.coordinator.reconcile_start(
            ident["lane_id"], invocation_id=ident["invocation_id"],
            generation=ident["generation"], executor_id=ident["executor_id"],
            operation_id=request["claim"]["operation_id"], status=status,
            evidence_ref=evidence_ref,
        )
        return receipt

    def start(self, lane_id, *, invocation_id, generation, executor_id, argv,
              timeout_seconds):
        self._validate_argv(argv)
        decision = self.coordinator.claim_start(
            lane_id, invocation_id=invocation_id, generation=generation,
            executor_id=executor_id)
        lane = self._lane(lane_id)
        operation = self.coordinator.start_operation(lane_id)
        if operation is None:
            raise ValueError("durable lane start claim missing after admission")
        if not decision["claimed"]:
            return self.observe(lane_id)

        try:
            request = self._request(lane, operation, argv, timeout_seconds)
        except (OSError, ValueError):
            identity = self._identity(lane)
            evidence_ref = _digest({
                "identity": identity,
                "operation_id": operation["operation_id"],
                "state": "preflight_failed_before_backend_effect",
            })
            self.coordinator.reconcile_start(
                identity["lane_id"], invocation_id=identity["invocation_id"],
                generation=identity["generation"], executor_id=identity["executor_id"],
                operation_id=operation["operation_id"], status="failed",
                evidence_ref=evidence_ref,
            )
            raise
        directory = Path(request["journal_directory"])
        request_path = directory / "request.json"

        # The durable claim exists before any journal/worktree/process side effect.
        latest = self._lane(lane_id)
        current = self.coordinator.start_operation(lane_id)
        if (latest["state"] != "running" or not latest["pending_effects"]
                or current is None or current["operation_id"] != decision["operation_id"]
                or current["status"] != "claimed"):
            raise ValueError("lane start gate changed after durable claim")

        _write_request(request_path, request)
        try:
            receipt = self.backend.start(request)
            self._validate_receipt(request, receipt)
            if receipt["status"] != "unknown":
                (directory / "backend-receipt.json").write_text(
                    json.dumps(receipt, sort_keys=True), encoding="utf-8")
            return self._record(request, receipt)
        except Exception:
            unknown = {
                "schema": "project-lane-observation/v1",
                "identity": request["identity"],
                "status": "unknown", "quiescent": False,
                "reason": "backend start outcome unconfirmed; observe without replay",
            }
            self._record(request, unknown)
            return unknown

    def observe(self, lane_id):
        lane = self._lane(lane_id)
        operation = self.coordinator.start_operation(lane_id)
        if operation is None:
            raise ValueError("lane has no durable start operation")
        identity = self._identity(lane)
        directory = self._directory(identity)
        path = directory / "request.json"
        if not path.exists():
            evidence_ref = _digest({
                "identity": identity,
                "operation_id": operation["operation_id"],
                "state": "request_absent",
            })
            self.coordinator.reconcile_start(
                identity["lane_id"], invocation_id=identity["invocation_id"],
                generation=identity["generation"], executor_id=identity["executor_id"],
                operation_id=operation["operation_id"], status="unknown",
                evidence_ref=evidence_ref,
            )
            return {
                "schema": "project-lane-observation/v1",
                "identity": identity, "status": "unknown",
                "quiescent": False,
                "reason": "durable request absent; start claim retained and never replayed",
            }
        request = json.loads(path.read_text(encoding="utf-8"))
        if (request.get("identity") != identity
                or request.get("claim", {}).get("operation_id") != operation["operation_id"]):
            raise ValueError("lane request journal identity mismatch")
        receipt_path = directory / "backend-receipt.json"
        saved_receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        receipt = self.backend.observe(request, saved_receipt)
        self._validate_receipt(request, receipt)
        if receipt["status"] != "unknown":
            receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
        return self._record(request, receipt)
