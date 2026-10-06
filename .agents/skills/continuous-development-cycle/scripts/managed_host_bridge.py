#!/usr/bin/env python3
"""Host-facing package-managed execution bridge.

The bridge exposes a serializable host contract while keeping the real
managed-terminal capability non-serializable and package-owned. It is intended
to be wrapped by Chat/Work/plugin transports; those hosts never receive lease
authority directly.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import execution_lease_v2 as leasev2
import final_response_gate
import managed_executor_pool as pool
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_remote_identity import remote_identity, repository_root
from managed_executor_runtime import ManagedExecutorRuntime, LocalCommandBackend
from managed_executor_store import GitManagedExecutorStore
from project_lane_git import GitLaneIntegrationPublisher
from project_lanes import LaneClaim, LaneKind

START_SCHEMA = "managed-host-start/v1"
OBSERVE_SCHEMA = "managed-host-observe/v1"
CANCEL_SCHEMA = "managed-host-cancel/v1"
FINISH_SCHEMA = "managed-host-finish/v1"
HANDLE_SCHEMA = "managed-host-handle/v1"
SESSION_SCHEMA = "managed-host-session/v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

_START_FIELDS = {
    "schema", "repo_root", "remote", "plan", "journal_root", "handle_root",
    "lease_coordination_ref", "lease_repository", "lease_source_ref",
    "task_id", "attempt_id", "reservation_token", "owner_id", "argv",
}
_OBSERVE_FIELDS = {"schema", "handle_root", "handle_id"}
_CANCEL_FIELDS = {"schema", "handle_root", "handle_id"}
_FINISH_FIELDS = {
    "schema", "handle_root", "handle_id", "output_refs", "evidence_refs", "checkpoint_ref",
}
_IMMUTABLE_SESSION_FIELDS = (
    "handle_id", "repo_root", "remote", "plan", "journal_root", "handle_root",
    "lease_coordination_ref", "lease_repository", "lease_source_ref",
    "task_id", "attempt_id", "reservation_token",
    "owner_id", "argv_digest", "publication_ref", "gate_directory",
)


def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _digest(value):
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("managed host durable state unavailable") from exc
    if not isinstance(value, dict):
        raise ValueError("managed host durable state must be an object")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(name + " must be nonempty trimmed text")
    return value


def _refs(value, name):
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(name + " must be a unique nonempty list of references")
    return value


def _heads_ref(value, name):
    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise ValueError(name + " must be an exact refs/heads/ ref")
    suffix = value.removeprefix("refs/heads/")
    if not suffix or value != "refs/heads/" + suffix:
        raise ValueError(name + " must be canonical")
    return value


def _git(repo, *args, check=True):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("managed host Git operation unavailable") from exc
    if check and result.returncode:
        raise ValueError("managed host Git operation failed: " + args[0])
    return result.stdout.strip(), result.returncode


def _remote_head(repo, remote, source_ref):
    output, _ = _git(repo, "ls-remote", "--refs", remote, source_ref)
    rows = output.splitlines()
    if len(rows) != 1:
        raise ValueError("source HEAD must resolve exactly once")
    parts = rows[0].split("\t")
    if len(parts) != 2 or parts[1] != source_ref or not SHA.fullmatch(parts[0]):
        raise ValueError("source HEAD response invalid")
    return parts[0]


def _require_read_only_reflog(repo):
    value, code = _git(repo, 'config', '--get', 'core.logAllRefUpdates', check=False)
    if code == 1 and _git(repo, 'rev-parse', '--is-bare-repository')[0] == 'false':
        return  # Git enables reflogs by default for a non-bare repository.
    if code or value.lower() not in {'true', 'yes', 'on', '1', 'always'}:
        raise ValueError('read_only execution requires enabled reflog history recording')


def _isolated_path(path, repo, name):
    value = Path(path)
    if not value.is_absolute():
        raise ValueError(name + " must be an absolute durable path")
    value = value.resolve()
    repo = Path(repo).resolve()
    if value == repo or repo in value.parents or value in repo.parents:
        raise ValueError(name + " must be isolated from the product repository")
    return value


def _task(plan, task_id):
    row = next((item for item in plan["tasks"] if item["id"] == task_id), None)
    if row is None:
        raise ValueError("managed host task_id is not in the plan")
    if row["role"] not in {"writer", "read_only"} or not row["required"]:
        raise ValueError("managed host v1 requires one required writer or read_only task")
    return row


def _session_context(session):
    context = {name: copy.deepcopy(session[name]) for name in _IMMUTABLE_SESSION_FIELDS}
    for name in ("coordination_remote", "source_remote_id"):
        if name in session:
            context[name] = copy.deepcopy(session[name])
    return context


def _routes(session):
    repo = session["repo_root"]
    control = session.get("coordination_remote", session["remote"])
    source_id = session.get("source_remote_id", session["plan"]["coordination_store_id"])
    if remote_identity(repo, session["remote"]) != source_id:
        raise ValueError("managed host source remote identity drift")
    if remote_identity(repo, control) != session["plan"]["coordination_store_id"]:
        raise ValueError("managed host coordination remote identity drift")
    return control, source_id


def _session_path(handle_root, handle_id):
    _text(handle_id, "handle_id")
    if "/" in handle_id or "\\" in handle_id or handle_id.startswith("."):
        raise ValueError("handle_id invalid")
    return Path(handle_root).resolve() / (handle_id + ".json")


def _validate_session(session):
    if not isinstance(session, dict) or session.get("schema") != SESSION_SCHEMA:
        raise ValueError("managed host session schema invalid")
    for name in _IMMUTABLE_SESSION_FIELDS:
        if name not in session:
            raise ValueError("managed host session missing immutable context")
    pool.validate_plan(session["plan"])
    if session.get("context_digest") != _digest(_session_context(session)):
        raise ValueError("managed host session context digest mismatch")
    if session["owner_id"] is not None and not UUID.fullmatch(session["owner_id"]):
        raise ValueError("managed host session owner_id invalid")
    _task(session["plan"], session["task_id"])
    return session


def _save_session(session):
    _validate_session(session)
    _write(_session_path(session["handle_root"], session["handle_id"]), session)


def _load_session(handle_root, handle_id):
    root = Path(handle_root).resolve()
    return _validate_session(_read(_session_path(root, handle_id)))


def _runtime(session):
    repo = Path(session["repo_root"])
    control, _ = _routes(session)
    store = GitManagedExecutorStore(
        repo, control, session["plan"]["coordination_ref"], session["plan"],
        protected_refs=[
            session["lease_source_ref"],
            session["lease_coordination_ref"],
            session["publication_ref"],
        ],
    )
    backend = LocalCommandBackend(session["journal_root"])
    return ManagedExecutorRuntime(
        session["plan"], store, repo, backend, journal_root=session["journal_root"]
    )


def _lease_store(session):
    control, _ = _routes(session)
    return GitLeaseStore(
        session["repo_root"], control, session["lease_coordination_ref"]
    )


def _public_handle(session):
    return {
        "schema": HANDLE_SCHEMA,
        "handle_id": session["handle_id"],
        "state": session["state"],
        "task_id": session["task_id"],
        "attempt_id": session["attempt_id"],
        "owner_id": session.get("owner_id"),
        "generation": session.get("generation"),
        "invocation_id": session.get("invocation_id"),
        "lease_revision": session.get("lease_revision"),
        "publication_ref": session["publication_ref"],
    }


def _gate_paths(session):
    directory = Path(session["gate_directory"])
    return {
        "payload": directory / "worker-payload.json",
        "go": directory / "go.json",
        "abort": directory / "abort.json",
    }


def _worker_gate(payload_path):
    payload = _read(payload_path)
    if (set(payload) != {"schema", "handle_id", "argv", "go_path", "abort_path"}
            or payload.get("schema") != "managed-host-worker-gate/v1"):
        raise ValueError("managed host worker gate payload invalid")
    argv = payload["argv"]
    if (not isinstance(argv, list) or not argv
            or any(not isinstance(item, str) or not item or "\0" in item for item in argv)):
        raise ValueError("managed host worker argv invalid")
    go = Path(payload["go_path"])
    abort = Path(payload["abort_path"])
    while True:
        if abort.exists():
            return 125
        if go.exists():
            break
        time.sleep(.02)
    return subprocess.run(argv, check=False).returncode


def _validate_start(request):
    if (not isinstance(request, dict)
            or set(request) not in (_START_FIELDS, _START_FIELDS | {"coordination_remote", "source_remote_id"})
            or request.get("schema") != START_SCHEMA):
        raise ValueError("managed host start request fields/schema mismatch")
    plan = request["plan"]
    pool.validate_plan(plan)
    if len(plan["tasks"]) != 1:
        raise ValueError("managed host v1 requires exactly one task")
    repo = repository_root(request["repo_root"])
    remote = _text(request["remote"], "remote")
    source_ref = _heads_ref(request["lease_source_ref"], "lease_source_ref")
    lease_ref = _heads_ref(request["lease_coordination_ref"], "lease_coordination_ref")
    if source_ref == lease_ref or plan["coordination_ref"] in {source_ref, lease_ref}:
        raise ValueError("managed host coordination refs must be isolated")
    _routes(request)
    _task(plan, _text(request["task_id"], "task_id"))
    for name in ("attempt_id", "reservation_token", "lease_repository"):
        _text(request[name], name)
    if not UUID.fullmatch(request["owner_id"]):
        raise ValueError("owner_id must be a canonical UUID")
    argv = request["argv"]
    if (not isinstance(argv, list) or not argv
            or any(not isinstance(item, str) or not item or "\0" in item for item in argv)):
        raise ValueError("argv must be a nonempty argument array")
    journal = _isolated_path(request["journal_root"], repo, "journal_root")
    handles = _isolated_path(request["handle_root"], repo, "handle_root")
    if journal == handles or journal in handles.parents or handles in journal.parents:
        raise ValueError("journal_root and handle_root must be isolated")
    return repo, journal, handles


def start(request):
    repo, journal_root, handle_root = _validate_start(request)
    identity = {"repo_root": str(repo), "store": request["plan"]["coordination_store_id"],
                "coordination_ref": request["plan"]["coordination_ref"],
                "pool_id": request["plan"]["pool_id"], "task_id": request["task_id"],
                "attempt_id": request["attempt_id"]}
    handle_id = str(uuid.uuid5(uuid.NAMESPACE_URL, _canonical(identity)))
    # This host-local lock serializes handle creation only; lease and shared
    # publication authority still come exclusively from their Git CAS stores.
    import fcntl
    lock_path = handle_root / "locks" / (handle_id + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _start_locked(request, repo, journal_root, handle_root, handle_id)


def _start_locked(request, repo, journal_root, handle_root, handle_id):
    plan = copy.deepcopy(request["plan"])
    publication_ref = "refs/heads/cdc/managed-host-publish-" + handle_id.replace("-", "")
    gate_directory = (handle_root / "gates" / handle_id).resolve()
    session = {
        "schema": SESSION_SCHEMA,
        "handle_id": handle_id,
        "state": "prepared",
        "repo_root": str(repo),
        "remote": request["remote"],
        "plan": plan,
        "journal_root": str(journal_root),
        "handle_root": str(handle_root),
        "lease_coordination_ref": request["lease_coordination_ref"],
        "lease_repository": request["lease_repository"],
        "lease_source_ref": request["lease_source_ref"],
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "reservation_token": request["reservation_token"],
        "owner_id": request["owner_id"],
        "argv_digest": _digest(request["argv"]),
        "publication_ref": publication_ref,
        "gate_directory": str(gate_directory),
        "created_at_utc": _utc(),
        "runtime_launch_id": None,
        "lease_revision": None,
        "generation": None,
        "invocation_id": None,
        "terminal_capability_ref": None,
        "result_commit": None,
        "publication": None,
        "release_receipt": None,
        "final_response_gate": None,
    }
    if "coordination_remote" in request:
        session.update(coordination_remote=request["coordination_remote"],
                       source_remote_id=request["source_remote_id"])
    session["context_digest"] = _digest(_session_context(session))
    resume_queued = False
    path = _session_path(handle_root, handle_id)
    if path.exists():
        existing = _load_session(handle_root, handle_id)
        if existing["context_digest"] != session["context_digest"]:
            raise ValueError("managed host repeated attempt has conflicting immutable context")
        _, prior_pool = _runtime(existing).store.read()
        prior_task = next((row for row in prior_pool["tasks"] if row["id"] == existing["task_id"]), None) if prior_pool else None
        resume_queued = bool(prior_task and prior_task["status"] == "queued"
                             and prior_task["active_attempt_id"] == existing["attempt_id"])
        attempted = bool(prior_task and existing["attempt_id"] in prior_task["attempt_ids"])
        if existing["state"] != "prepared" or (attempted and not resume_queued):
            recovered, _, _ = _recover_session(handle_root, handle_id)
            return _public_handle(recovered)
        session = existing
    if _remote_head(repo, request["remote"], request["lease_source_ref"]) != plan["base_sha"]:
        raise ValueError("source HEAD drifted from managed host plan base")
    if _task(plan, request['task_id'])['role'] == 'read_only':
        _require_read_only_reflog(repo)
    _save_session(session)

    gate = _gate_paths(session)
    _write(gate["payload"], {
        "schema": "managed-host-worker-gate/v1",
        "handle_id": handle_id,
        "argv": request["argv"],
        "go_path": str(gate["go"]),
        "abort_path": str(gate["abort"]),
    })

    control, _ = _routes(session)
    store = GitManagedExecutorStore(
        repo, control, plan["coordination_ref"], plan,
        protected_refs=[request["lease_source_ref"], request["lease_coordination_ref"], publication_ref],
    )
    store_revision, pool_state = store.read()
    if pool_state is None:
        store_revision = store.compare_and_swap(
            None, pool.initial_state(plan, parallel_capable=plan["max_parallel"] > 1)
        )
    runtime = ManagedExecutorRuntime(
        plan, store, repo, LocalCommandBackend(journal_root), journal_root=journal_root
    )
    wrapped = [
        sys.executable, "-B", str(Path(__file__).resolve()),
        "--worker-gate", str(gate["payload"]),
    ]
    launch = runtime.start_queued if resume_queued else runtime.start
    observation = launch(
        store_revision, request["task_id"], request["attempt_id"],
        reservation_token=request["reservation_token"], argv=wrapped,
    )
    session["runtime_launch_id"] = observation.get("launch_id")
    if observation.get("status") == "unknown":
        session["state"] = "start_unknown"
        _save_session(session)
        return _public_handle(session)
    if observation.get("status") not in {"starting", "running"}:
        session["state"] = "terminal_without_lease"
        _save_session(session)
        return _public_handle(session)

    lease_store = _lease_store(session)
    lease_revision, lease_record = lease_store.read()
    if lease_revision is None or lease_record is None:
        _write(gate["abort"], {"reason": "lease coordination absent"})
        session["state"] = "lease_unavailable"
        _save_session(session)
        raise ValueError("managed host project lease coordination is absent")
    try:
        acquired = runtime.acquire_execution_lease(
            lease_store, lease_revision, request["lease_repository"],
            request["lease_source_ref"], request["owner_id"], request["task_id"],
            request["attempt_id"], _utc(),
        )
    except Exception:
        _write(gate["abort"], {"reason": "managed lease acquisition failed"})
        session["state"] = "lease_acquire_failed"
        _save_session(session)
        raise

    session.update(
        state="owned",
        lease_revision=acquired["revision"],
        generation=acquired["generation"],
        invocation_id=acquired["invocation"]["invocation_id"],
        terminal_capability_ref=acquired["terminal_capability_ref"],
    )
    _save_session(session)
    _write(gate["go"], {
        "schema": "managed-host-worker-go/v1",
        "handle_id": handle_id,
        "invocation_id": session["invocation_id"],
    })
    session["state"] = "running"
    _save_session(session)
    return _public_handle(session)


def _recover_session(handle_root, handle_id):
    session = _load_session(handle_root, handle_id)
    runtime = _runtime(session)
    lease_store = _lease_store(session)
    if session.get("generation") is None:
        try:
            recovered = runtime.reconcile_execution_lease_hold(
                lease_store, session["task_id"], session["attempt_id"])
        except ValueError as exc:
            if "hold marker missing" not in str(exc) and "intent missing" not in str(exc):
                raise
            gate = _gate_paths(session)
            if session["state"] not in {"prepared", "start_unknown"} or gate["abort"].exists():
                return session, runtime, lease_store
            # A lost start reply is not a second start grant. Observe the exact
            # consumed attempt; only its now-live gated supervisor can obtain
            # the normal non-serializable managed terminal capability.
            observation = runtime.observe(session["task_id"], session["attempt_id"])
            if observation.get("status") not in {"starting", "running"}:
                if observation.get("quiescent") is True:
                    session["state"] = "terminal_without_lease"
                    _save_session(session)
                return session, runtime, lease_store
            session["runtime_launch_id"] = observation.get("launch_id")
            try:
                if _remote_head(session["repo_root"], session["remote"], session["lease_source_ref"]) != session["plan"]["base_sha"]:
                    raise ValueError("source HEAD drifted before unknown-start recovery")
                lease_revision, record = lease_store.read()
                if lease_revision is None or record is None:
                    raise ValueError("managed host project lease coordination is absent")
                acquired = runtime.acquire_execution_lease(
                    lease_store, lease_revision, session["lease_repository"],
                    session["lease_source_ref"], session["owner_id"], session["task_id"],
                    session["attempt_id"], _utc(),
                )
            except Exception:
                _write(gate["abort"], {"reason": "unknown-start managed acquisition failed"})
                session["state"] = "lease_acquire_failed"
                _save_session(session)
                raise
            session.update(state="owned", lease_revision=acquired["revision"],
                           generation=acquired["generation"],
                           invocation_id=acquired["invocation"]["invocation_id"],
                           terminal_capability_ref=acquired["terminal_capability_ref"])
            _save_session(session)
            recovered = {"status": "owned", "owned_marker": {
                "owner_id": session["owner_id"], "generation": session["generation"],
                "invocation_id": session["invocation_id"], "lease_revision": session["lease_revision"]}}
        if recovered["status"] == "owned":
            owned = recovered["owned_marker"]
            _, current = lease_store.read()
            if (current is None or current.get("owner_id") != owned["owner_id"]
                    or current.get("generation") != owned["generation"]):
                raise ValueError("managed host recovered ownership does not match live lease")
            session.update(
                state="owned",
                generation=owned["generation"],
                invocation_id=owned["invocation_id"],
                lease_revision=owned["lease_revision"],
            )
            _save_session(session)
        elif recovered["status"] == "released":
            session.update(
                state="released",
                generation=recovered["release_marker"]["generation"],
                invocation_id=recovered["release_marker"]["invocation_id"],
                lease_revision=recovered["release_marker"]["lease_revision"],
                release_receipt=recovered["release_marker"]["release_receipt"],
            )
            _save_session(session)

    if session.get("generation") is not None and session.get("release_receipt") is None:
        current_revision, current = lease_store.read()
        exact = bool(
            current is not None
            and current.get("owner_id") == session["owner_id"]
            and current.get("generation") == session["generation"]
            and current.get("invocation", {}).get("invocation_id") == session["invocation_id"]
        )
        if exact:
            session["lease_revision"] = current_revision
            gate = _gate_paths(session)
            if not gate["go"].exists():
                _write(gate["go"], {
                    "schema": "managed-host-worker-go/v1",
                    "handle_id": session["handle_id"],
                    "invocation_id": session["invocation_id"],
                })
            if session["state"] in {"prepared", "owned"}:
                session["state"] = "running"
            _save_session(session)
        else:
            try:
                released = lease_store.find_release_receipt(
                    session["owner_id"], session["generation"], session["invocation_id"])
            except ValueError:
                released = None
            if released is not None:
                # The authoritative release CAS may have succeeded before the
                # controller saved the supervisor marker. Repair that marker
                # from exact lease history before waiting for quiescence.
                recovered = runtime.reconcile_execution_lease_hold(
                    lease_store, session["task_id"], session["attempt_id"])
                if recovered["status"] != "released":
                    raise ValueError("managed host runtime release is not reconciled")
                session.update(
                    state="released",
                    lease_revision=released["release_receipt"]["lease_revision"],
                    release_receipt=released["release_receipt"],
                )
                _save_session(session)
    return session, runtime, lease_store


def observe(request):
    if not isinstance(request, dict) or set(request) != _OBSERVE_FIELDS or request.get("schema") != OBSERVE_SCHEMA:
        raise ValueError("managed host observe request fields/schema mismatch")
    session, runtime, lease_store = _recover_session(request["handle_root"], request["handle_id"])
    observation = runtime.observe(session["task_id"], session["attempt_id"])
    lease_revision, lease = lease_store.read()
    exact_owned = bool(
        session.get("generation") is not None and lease is not None
        and lease.get("owner_id") == session["owner_id"]
        and lease.get("generation") == session["generation"]
        and lease.get("invocation", {}).get("invocation_id") == session.get("invocation_id")
    )
    return {
        **_public_handle(session),
        "runtime_status": observation.get("status"),
        "quiescent": observation.get("quiescent"),
        "pending_terminal_status": observation.get("pending_terminal_status"),
        "runtime_launch_id": observation.get("launch_id"),
        "lease_owned": exact_owned,
        "lease_revision": lease_revision,
    }


def cancel(request):
    if not isinstance(request, dict) or set(request) != _CANCEL_FIELDS or request.get("schema") != CANCEL_SCHEMA:
        raise ValueError("managed host cancel request fields/schema mismatch")
    session, runtime, _ = _recover_session(request["handle_root"], request["handle_id"])
    observation = runtime.cancel(session["task_id"], session["attempt_id"])
    session["state"] = "cancelling"
    _save_session(session)
    return {
        **_public_handle(session),
        "runtime_status": observation.get("status"),
        "quiescent": observation.get("quiescent"),
        "requires_terminal_finalization": True,
    }


def _renew_for_result(session, lease_store, observation, *, action="product_write"):
    revision, record = lease_store.read()
    if (record is None or record.get("owner_id") != session["owner_id"]
            or record.get("generation") != session["generation"]
            or record.get("invocation", {}).get("invocation_id") != session["invocation_id"]):
        raise ValueError("managed host exact lease ownership is not live")
    activity_ref = "managed-host:awaiting-release:" + str(observation.get("launch_id"))
    if activity_ref not in record["activity_refs"]:
        renewed = leasev2.renew(
            record, session["owner_id"], session["generation"], session["invocation_id"],
            _utc(), activity_ref=activity_ref,
        )
        revision = lease_store.compare_and_swap(revision, renewed)
        record = renewed
    leasev2.check_record(
        record, session["owner_id"], session["generation"], session["invocation_id"],
        _utc(), action=action,
    )
    return revision, record


def _result(session, runtime):
    task = _task(session["plan"], session["task_id"])
    request = runtime._request(session["task_id"], session["attempt_id"])
    if request is None:
        raise ValueError("managed host worker request is unavailable")
    if _git(request["cwd"], "status", "--porcelain", "--untracked-files=all")[0]:
        raise ValueError("worker worktree must be clean before publication")
    branch = task["branch"]
    branch_ref = branch if branch.startswith("refs/heads/") else "refs/heads/" + branch
    result_commit, code = _git(request["cwd"], "rev-parse", "--verify", branch_ref, check=False)
    if code or not SHA.fullmatch(result_commit):
        raise ValueError("managed host worker did not produce an exact writer commit")
    changed, touched = pool._verify_writer_result_git(
        task, session["plan"]["base_sha"], result_commit, request["cwd"])
    if not pool._result_paths_within_claim(task, changed):
        raise ValueError("managed host worker result escapes declared write set")
    if {pool.portable_path_key(x) for x in changed} != {pool.portable_path_key(x) for x in touched}:
        raise ValueError("managed host worker history changed-path mismatch")
    return result_commit, changed, request


def _read_only_result(session, runtime):
    request = runtime._request(session["task_id"], session["attempt_id"])
    if request is None:
        raise ValueError("managed host worker request is unavailable")
    cwd = request["cwd"]
    base = session["plan"]["base_sha"]
    if _git(cwd, "status", "--porcelain", "--untracked-files=all")[0]:
        raise ValueError("read_only worker checkout must remain clean")
    if _git(cwd, "rev-parse", "HEAD")[0] != base:
        raise ValueError("read_only worker changed its Git head")
    branch, code = _git(cwd, "symbolic-ref", "-q", "HEAD", check=False)
    if code != 1 or branch:
        raise ValueError("read_only worker checkout must remain detached")
    _require_read_only_reflog(cwd)
    history = _git(cwd, "reflog", "show", "--format=%H", "HEAD")[0].splitlines()
    if not history or any(sha != base for sha in history):
        raise ValueError("read_only worker changed its Git history")
    if _remote_head(session["repo_root"], session["remote"], session["lease_source_ref"]) != base:
        raise ValueError("read_only source HEAD drifted from the plan base")


def _publish(session, result_commit):
    repo = Path(session["repo_root"])
    source_ref = session["lease_source_ref"]
    control, source_id = _routes(session)
    publication_store = GitDocumentStore(
        repo, control, session["publication_ref"],
        session["plan"]["coordination_store_id"],
        protected_refs=[
            source_ref, session["lease_coordination_ref"], session["plan"]["coordination_ref"]
        ],
    )
    publisher = GitLaneIntegrationPublisher(
        repo, session["remote"], source_ref, source_id,
        attempt_store=publication_store,
        attempt_store_id=session["plan"]["coordination_store_id"],
    )
    integrator = LaneClaim(
        lane_id="managed-host-integrator-" + session["handle_id"],
        invocation_id=session["invocation_id"],
        kind=LaneKind.INTEGRATOR,
        source_head=session["plan"]["base_sha"],
        worktree=str(repo),
        branch=source_ref,
        read_paths=frozenset(),
        write_paths=frozenset(),
        executor_id=session["plan"]["integrator_id"],
        role="integrator",
    )
    operation_id = _digest({
        "handle_id": session["handle_id"],
        "result_commit": result_commit,
        "observed_shared_head": session["plan"]["base_sha"],
        "shared_ref": source_ref,
    })
    item = {"lane_id": session["task_id"], "result_commit": result_commit}
    intent = {
        "operation_id": operation_id,
        "lane_id": session["task_id"],
        "result_commit": result_commit,
        "observed_shared_head": session["plan"]["base_sha"],
        "intended_integrated_head": result_commit,
    }
    evidence = publisher(item, integrator, intent)
    if evidence.get("conditional_update") is not True:
        raise ValueError("managed host publication lacks exact conditional-update proof")
    return evidence


def _continuity(session, result_commit, checkpoint_ref, publication, *, released):
    read_only = _task(session["plan"], session["task_id"])["role"] == "read_only"
    progress = (["managed-host:result:" + session["handle_id"], checkpoint_ref]
                if read_only else ["git:" + result_commit])
    completion = ["managed-host:worker:" + str(session["runtime_launch_id"])]
    if publication is not None:
        completion.append("managed-host:publication:" + publication["evidence_ref"])
    terminal = {
        "schema": "terminal-state/v2",
        "invocation_id": session["invocation_id"],
        "scope_id": session["plan"]["change_id"],
        "observed_head": session["plan"]["base_sha"] if read_only else result_commit,
        "decision": "COMPLETE",
        "runnable_actions": [],
        "pending_external": None,
        "blocker": None,
        "meaningful_progress_refs": progress,
        "completion_evidence_refs": completion,
        "checkpoint_ref": checkpoint_ref,
        "lease_released": released,
    }
    continuity = {
        "schema": "execution-continuity/v1",
        "invocation_id": session["invocation_id"],
        "current_state": "CHECKPOINT",
        "requested_terminal_outcome": "scope_complete",
        "runnable_next_action": False,
        "meaningful_progress_refs": progress,
        "primitive_steps": [],
        "external_binding": None,
        "blocker": None,
        "checkpoint_ref": checkpoint_ref,
        "next_action": None,
        "lease_release_required": released,
        "lease_released": released,
        "terminal_state": terminal,
    }
    if session.get("worker_status") != "succeeded":
        # A failed attempt is resumable, never project-scope completion. The
        # exact supervisor still holds the lease until this BLOCKED transaction
        # has persisted the terminal observation and release receipt.
        status = session["worker_status"]
        dependency = "managed-host-worker-" + status
        evidence = ["managed-host:terminal:" + str(session["runtime_launch_id"]) + ":" + status]
        next_action = "Diagnose the " + status + " worker and authorize the next exact attempt"
        trigger = "host supplies a corrected or explicitly retried managed attempt"
        blocker = {"code": dependency, "evidence_refs": evidence,
                   "next_action": next_action, "recheck_trigger": trigger}
        terminal.update(decision="BLOCKED", completion_evidence_refs=[], blocker=blocker)
        continuity.update(requested_terminal_outcome="blocked", blocker=dependency,
                          next_action=next_action,
                          blocker_proof={"schema": "blocked-state-proof/v1",
                                         "dependency_id": dependency, "category": "worker_terminal",
                                         "observed_at_utc": _utc(), "max_age_seconds": 120,
                                         "evidence_refs": evidence, "next_action": next_action,
                                         "recheck_trigger": trigger, "same_invocation_work_exhausted": True})
    return continuity


def _finalize_release(session, runtime, lease_store, result_commit, checkpoint_ref, publication):
    revision, record = lease_store.read()
    if (record is None or record.get("owner_id") != session["owner_id"]
            or record.get("generation") != session["generation"]
            or record.get("invocation", {}).get("invocation_id") != session["invocation_id"]):
        recovered = runtime.reconcile_execution_lease_hold(
            lease_store, session["task_id"], session["attempt_id"])
        if recovered["status"] != "released":
            raise ValueError("managed host lease is neither owned nor durably released")
        return recovered["release_marker"]["release_receipt"]

    at = _utc()
    if session.get('worker_status') == 'succeeded' and record['external_guard'] is not None:
        raise ValueError('successful managed worker cannot complete with unresolved external guard')
    if record["finalization"]["state"] in {"active", "failed"}:
        record = leasev2.begin_finalization(
            record, session["owner_id"], session["generation"], session["invocation_id"], at,
            pending_shared_writes=False,
        )
        revision = lease_store.compare_and_swap(revision, record)
    if record["finalization"]["state"] == "draining":
        record = leasev2.record_checkpoint(
            record, session["owner_id"], session["generation"], session["invocation_id"], _utc(),
            checkpoint_ref=checkpoint_ref, pending_shared_writes=False,
        )
        revision = lease_store.compare_and_swap(revision, record)
    if record["finalization"]["checkpoint_ref"] != checkpoint_ref:
        raise ValueError("managed host retry checkpoint does not match finalization")
    if record["finalization"]["state"] == "checkpointed":
        record = leasev2.reconcile_finalization(
            record, session["owner_id"], session["generation"], session["invocation_id"], _utc(),
            external_reconciliation=("unknown_preserved" if session.get('worker_status') in {'failed', 'cancelled', 'timed_out'} and publication is None and record['external_guard'] is not None else "none"),
        )
        revision = lease_store.compare_and_swap(revision, record)
    if record["finalization"]["state"] == "reconciled":
        continuity = _continuity(
            session, result_commit, checkpoint_ref, publication, released=False)
        record = leasev2.mark_ready(
            record, session["owner_id"], session["generation"], session["invocation_id"], _utc(),
            continuity_state=continuity,
        )
        revision = lease_store.compare_and_swap(revision, record)
    released = runtime.release_execution_lease(
        lease_store, revision, session["lease_repository"], session["lease_source_ref"],
        session["owner_id"], session["generation"], session["invocation_id"],
        session["task_id"], session["attempt_id"], _utc(),
    )
    return released["release_receipt"]


def _wait_terminal(runtime, session):
    end = time.monotonic() + 8
    last = None
    while time.monotonic() < end:
        last = runtime.observe(session["task_id"], session["attempt_id"])
        if last.get("quiescent") is True:
            return last
        time.sleep(.025)
    raise ValueError("managed host supervisor did not become quiescent after release")


def _complete_pool(session, runtime, result_commit, output_refs, evidence_refs):
    store = runtime.store
    _, state = store.read()
    current = next(row for row in state["tasks"] if row["id"] == session["task_id"])
    result_ref = current.get("accepted_result_ref")
    if current["status"] == "running":
        accepted = runtime.accept(
            session["task_id"], session["attempt_id"], result_commit=result_commit,
            output_refs=output_refs, evidence_refs=evidence_refs, cost_units=0,
        )
        result_ref = accepted["result_ref"]
        _, state = store.read()
        current = next(row for row in state["tasks"] if row["id"] == session["task_id"])
    if current["status"] != "succeeded" or not result_ref:
        raise ValueError("managed host pool result was not accepted")
    if not current["integrated"]:
        revision, state = store.read()
        updated = pool.mark_integrated(
            session["plan"], state, session["task_id"], result_ref,
            expected_revision=state["revision"],
        )
        store.compare_and_swap(revision, updated)
    _, final_state = store.read()
    assessment = pool.assess(session["plan"], final_state)
    if not assessment["complete"] or not assessment["terminal_allowed"]:
        raise ValueError("managed host pool did not reach terminal completion")
    return result_ref, assessment


def finish(request):
    if not isinstance(request, dict) or set(request) != _FINISH_FIELDS or request.get("schema") != FINISH_SCHEMA:
        raise ValueError("managed host finish request fields/schema mismatch")
    output_refs = _refs(request["output_refs"], "output_refs")
    evidence_refs = _refs(request["evidence_refs"], "evidence_refs")
    if request["checkpoint_ref"] is not None:
        _text(request["checkpoint_ref"], "checkpoint_ref")
    session = _load_session(request["handle_root"], request["handle_id"])
    task = _task(session["plan"], session["task_id"])
    # Read the exact terminal observation before recovering ownership. A failed
    # attempt supplies failure evidence; successful output labels cannot be
    # required for its no-publication release. Nonterminal/unknown stays strict.
    if session.get('release_receipt') is not None:
        observed_status = session.get('worker_status')
    else:
        prevalidation_observation = _runtime(session).observe(session['task_id'], session['attempt_id'])
        observed_status = prevalidation_observation.get('pending_terminal_status')
        if observed_status is None and prevalidation_observation.get('status') in {'failed', 'cancelled', 'timed_out'}:
            observed_status = prevalidation_observation['status']
    if observed_status not in {'failed','cancelled','timed_out'}:
        if not set(task["expected_outputs"]) <= set(output_refs):
            raise ValueError("worker result missing expected outputs")
        if not set(task["expected_evidence"]) <= set(evidence_refs):
            raise ValueError("worker result missing expected evidence")
    session, runtime, lease_store = _recover_session(request["handle_root"], request["handle_id"])
    if session.get("release_receipt") is not None and (session.get("final_response_gate") or {}).get("final_response_allowed") is True:
        return {
            **_public_handle(session),
            "published_commit": session["result_commit"] if session.get("publication") is not None else None,
            "release_receipt": session["release_receipt"],
            "final_response_allowed": True,
            "worker_status": session.get("worker_status", "succeeded"),
            "scope_complete": session.get("worker_status", "succeeded") == "succeeded",
        }

    observation = runtime.observe(session["task_id"], session["attempt_id"])
    if session.get("release_receipt") is None:
        status = observation.get("pending_terminal_status")
        if observation.get("status") != "awaiting_release" or status not in {"succeeded", "failed", "cancelled", "timed_out"}:
            raise ValueError("managed host finish requires a terminal worker awaiting managed lease release")
        session["worker_status"] = status
        if status == "succeeded":
            if not set(task["expected_outputs"]) <= set(output_refs) or not set(task["expected_evidence"]) <= set(evidence_refs):
                raise ValueError('successful worker result missing expected outputs/evidence')
            if task["role"] == "read_only":
                if request["checkpoint_ref"] is None:
                    raise ValueError("read_only finish requires a persisted result checkpoint")
                _renew_for_result(session, lease_store, observation, action="observe")
                _read_only_result(session, runtime)
                result_commit, publication = None, None
                default_checkpoint = request["checkpoint_ref"]
            elif session.get("publication") is None:
                _renew_for_result(session, lease_store, observation)
                result_commit, changed_paths, _ = _result(session, runtime)
                publication = _publish(session, result_commit)
            else:
                result_commit, publication = session["result_commit"], session["publication"]
            if task["role"] == "writer":
                default_checkpoint = "git:" + session["lease_source_ref"] + "@" + result_commit
        else:
            result_commit, publication = session["plan"]["base_sha"], None
            default_checkpoint = "managed-host:terminal:" + session["handle_id"] + ":" + status
            session["terminal_observation"] = observation
        checkpoint_ref = request["checkpoint_ref"] if request["checkpoint_ref"] is not None else default_checkpoint
        _text(checkpoint_ref, "checkpoint_ref")
        session.update(
            state="published",
            result_commit=result_commit,
            publication=publication,
        )
        _save_session(session)
        release_receipt = _finalize_release(
            session, runtime, lease_store, result_commit, checkpoint_ref, publication)
        session.update(
            state="released",
            lease_revision=release_receipt["lease_revision"],
            release_receipt=release_receipt,
        )
        _save_session(session)
    else:
        result_commit = session["result_commit"]
        publication = session["publication"]
        checkpoint_ref = request["checkpoint_ref"] or session["release_receipt"]["release"]["checkpoint_ref"]
        release_receipt = session["release_receipt"]

    terminal = _wait_terminal(runtime, session)
    status = session.get("worker_status", "succeeded")
    if terminal.get("status") != status:
        raise ValueError("managed host worker terminal status changed after release")
    if status == "succeeded":
        _complete_pool(session, runtime, result_commit, output_refs, evidence_refs)

    current_revision, current_lease = lease_store.read()
    release_record = lease_store.read_revision(release_receipt["lease_revision"])
    post = _continuity(session, result_commit, checkpoint_ref, publication, released=True)
    gate = final_response_gate.evaluate(
        session["invocation_id"], current_lease, post,
        {"owner_id": session["owner_id"], "generation": session["generation"]},
        release_receipt, release_record, _utc(),
    )
    if gate.get("final_response_allowed") is not True:
        raise ValueError("managed host final-response gate rejected released execution")
    session["final_response_gate"] = gate
    session["state"] = "released"
    _save_session(session)
    return {
        **_public_handle(session),
        "published_commit": result_commit if publication is not None else None,
        "changed_paths": changed_paths if "changed_paths" in locals() else None,
        "release_receipt": release_receipt,
        "current_lease_revision": current_revision,
        "final_response_allowed": True,
        "worker_status": status,
        "scope_complete": status == "succeeded",
    }


def _load_request(path):
    return _read(path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "--worker-gate":
        try:
            return _worker_gate(argv[1])
        except (OSError, ValueError) as exc:
            print("FAIL:", exc, file=sys.stderr)
            return 2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "observe", "cancel", "finish"))
    parser.add_argument("request")
    args = parser.parse_args(argv)
    try:
        request = _load_request(args.request)
        result = {
            "start": start,
            "observe": observe,
            "cancel": cancel,
            "finish": finish,
        }[args.action](request)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
