#!/usr/bin/env python3
"""One-shot managed execution, Linux command supervision, and parent closure.

Host backends implement start(request), observe(request, receipt), and
cancel(request, receipt). Only
ManagedExecutorRuntime may grant a new start, immediately after the durable CAS.
This is a cooperative execution adapter, not a command sandbox or a Work API.
"""
from __future__ import annotations

from git_object_integrity import git_object_environment

import argparse
import copy
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import execution_continuity
import managed_executor_attempt as attempts
import managed_executor_pool as pool
import managed_executor_handoff as handoffs


def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write(path, value):
    """Persist a replace atomically, including the directory entry."""
    path = Path(path)
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json(path):
    path=Path(path)
    if not path.exists():
        return None
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:
        raise ValueError("managed terminal marker invalid") from exc
    if not isinstance(value,dict):
        raise ValueError("managed terminal marker must be an object")
    return value

def _terminal_hold_paths(directory):
    directory=Path(directory)
    return {
        "intent":directory/"terminal-lease-intent.json",
        "acquire_done":directory/"terminal-lease-acquire-done.json",
        "owned":directory/"terminal-lease-owned.json",
        "release":directory/"terminal-lease-release.json",
        "abort":directory/"terminal-lease-abort.json",
    }

def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], env=git_object_environment(), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=20)
    if result.returncode:
        raise ValueError("Git operation failed: " + args[0])
    return result.stdout.strip()


def _process(pid):
    try:
        # comm may itself contain spaces or parentheses.
        row = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        status = Path(f"/proc/{pid}/status").read_text().splitlines()
        nspids = next(line.split()[1:] for line in status if line.startswith("NSpid:"))
        own = next(line.split()[1:] for line in Path("/proc/self/status").read_text().splitlines()
                   if line.startswith("NSpid:"))
        signal_pid = int(nspids[len(own) - 1]) if len(nspids) >= len(own) else None
        return {"state": row[0], "parent": int(row[1]), "birth": row[19], "signal_pid": signal_pid}
    except (OSError, ValueError, IndexError):
        return None


def _descendants(parent):
    rows = {}
    for item in Path("/proc").iterdir():
        if item.name.isdigit():
            state = _process(int(item.name))
            if state:
                rows[int(item.name)] = state
    found, frontier = {}, {parent}
    while frontier:
        children = {pid: value for pid, value in rows.items()
                    if value["parent"] in frontier and pid not in found}
        found.update(children)
        frontier = set(children)
    return found


def _boot():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _unknown(identity, reason):
    return {"schema": "managed-executor-observation/v1", "identity": identity,
            "status": "unknown", "quiescent": False, "reason": reason}


class ExecutionJournal:
    """Controller-owned records, independent of backend tool implementations."""

    def __init__(self, journal_root):
        self.journal_root = Path(journal_root).resolve()
        self.journal_root.mkdir(parents=True, exist_ok=True)

    def directory(self, identity):
        key = {k: identity[k] for k in ("pool_id", "task_id", "attempt_id")}
        return self.journal_root / _digest(key).split(":", 1)[1]

    def load_request(self, identity):
        path = self.directory(identity) / "request.json"
        if not path.exists():
            return None
        request = json.loads(path.read_text())
        if request["identity"] != identity:
            raise ValueError("durable request identity mismatch")
        return request

    def prepare(self, request):
        directory = self.directory(request["identity"])
        directory.mkdir()
        fd = os.open(self.journal_root, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        _write(directory / "request.json", request)


class LocalCommandBackend:
    """Linux subreaper supervisor; its journal must survive controller restarts."""
    name = "local_command"

    def __init__(self, journal_root):
        if sys.platform != "linux" or not Path("/proc/self/stat").exists():
            raise ValueError("local_command requires Linux /proc and child subreaper support")
        self.journal_root = Path(journal_root).resolve()

    def start(self, request):
        directory = Path(request["journal_directory"])
        # A repeated backend call cannot recreate an effect, even with the same claim.
        try:
            with (directory / "launch.lock").open("x") as stream:
                stream.write(_digest(request))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise ValueError("backend start already consumed; observe instead") from exc
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        with (directory / "supervisor.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()),
                                        "--supervise", str(directory)], stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True, close_fds=True)
        # Reap the supervisor without tying its lifetime to the controller.
        threading.Thread(target=process.wait, daemon=True).start()
        end = time.monotonic() + 3
        while time.monotonic() < end:
            observation = self.observe(request)
            if observation["status"] != "unknown":
                return observation
            if process.poll() is not None:
                break
            time.sleep(.01)
        return self.observe(request)

    def observe(self, request, receipt=None):
        path = Path(request["journal_directory"]) / "receipt.json"
        if not path.exists():
            return _unknown(request["identity"], "start receipt absent; never replay")
        receipt = json.loads(path.read_text())
        if (receipt["identity"] != request["identity"] or receipt["request_ref"] != _digest(request)
                or receipt["claim"] != request["claim"]):
            raise ValueError("durable receipt identity/claim mismatch")
        if receipt["quiescent"]:
            return receipt
        current = _process(receipt["supervisor_proc_pid"])
        if (_boot() != receipt["boot_id"] or not current
                or current["birth"] != receipt["supervisor_birth"] or current["state"] == "Z"):
            return {**receipt, "status": "unknown", "quiescent": False,
                    "reason": "supervisor unavailable; descendant quiescence unproved"}
        return receipt

    def cancel(self, request, receipt=None):
        # The live supervisor owns descendant termination. Absence is not quiescence.
        directory = Path(request["journal_directory"])
        _write(directory / "cancel.json", {"request_ref": _digest(request)})
        return self.observe(request)


def _supervise(directory):
    directory = Path(directory)
    request = json.loads((directory / "request.json").read_text())
    # Reparent orphan descendants to this supervisor, including detached sessions.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("cannot enable child subreaper; refusing worker start")
    pid = os.getpid()
    proc_pid = int(os.readlink("/proc/self"))
    receipt = {"schema": "managed-executor-observation/v1", "identity": request["identity"],
               "claim": request["claim"], "request_ref": _digest(request),
               "launch_id": _digest(request), "status": "starting", "quiescent": False,
               "supervisor_pid": pid, "supervisor_proc_pid": proc_pid,
               "supervisor_birth": _process(proc_pid)["birth"], "boot_id": _boot(),
               "created_at_utc": _utc(), "started_at_utc": None, "finished_at_utc": None,
               "exit_code": None, "elapsed_seconds": 0, "runtime_seconds": 0, "failure": None}
    _write(directory / "receipt.json", receipt)
    started = time.monotonic()
    try:
        cwd = Path(request["cwd"])
        cwd.parent.mkdir(parents=True, exist_ok=True)
        command = ["worktree", "add", "--quiet"]
        if request["identity"]["role"] == "writer":
            command += ["-b", request["identity"]["branch"].removeprefix("refs/heads/")]
        else:
            command += ["--detach"]
        _git(request["repo_root"], *command, str(cwd), request["identity"]["base_sha"])
        # Preparation is inside the admitted interval. Never create a new worker
        # after its deadline/cancellation, but still reap any preparation descendants.
        termination = ("cancelled" if (directory / "cancel.json").exists() else
                       "timed_out" if time.monotonic() - started >= request["timeout_seconds"] else None)
        stopping_at = time.monotonic() if termination else None
        child = None
        exit_code = None
        if termination is None:
            with (directory / "stdout.log").open("ab") as out, (directory / "stderr.log").open("ab") as err:
                child = subprocess.Popen(request["argv"], cwd=cwd, stdin=subprocess.DEVNULL,
                                         stdout=out, stderr=err, close_fds=True)
            receipt.update(status="running", started_at_utc=_utc(), worker_pid=child.pid)
            _write(directory / "receipt.json", receipt)
        while True:
            # waitpid(ECHILD) is the closure proof: root exit alone is insufficient.
            no_children = False
            while True:
                try:
                    reaped, status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    no_children = True
                    break
                if not reaped:
                    break
                if child is not None and reaped == child.pid:
                    exit_code = os.waitstatus_to_exitcode(status)
                    child.returncode = exit_code
            if no_children:
                break
            elapsed = time.monotonic() - started
            if termination is None:
                if (directory / "cancel.json").exists():
                    termination = "cancelled"
                elif elapsed >= request["timeout_seconds"]:
                    termination = "timed_out"
                if termination:
                    stopping_at = time.monotonic()
            if termination:
                sig = signal.SIGKILL if time.monotonic() - stopping_at >= .2 else signal.SIGTERM
                for target, identity in _descendants(proc_pid).items():
                    current = _process(target)
                    if current and current["birth"] == identity["birth"]:
                        try:
                            os.kill(current["signal_pid"], sig)
                        except ProcessLookupError:
                            pass
            time.sleep(.01)
        elapsed = time.monotonic() - started
        terminal_status=termination or ("succeeded" if exit_code == 0 else "failed")
        terminal_failure=None if terminal_status=="succeeded" else (termination or f"worker exit {exit_code}")
        paths=_terminal_hold_paths(directory)
        intent=_read_json(paths["intent"])
        if intent is not None:
            required={"schema","capability_ref","invocation_id","lease_repository","lease_source_ref","armed_at_utc",
                      "controller_proc_pid","controller_birth"}
            if set(intent)!=required or intent.get("schema")!="managed-terminal-lease-intent/v1":
                raise ValueError("managed terminal lease intent invalid")
            while True:
                release=_read_json(paths["release"])
                abort=_read_json(paths["abort"])
                owned=_read_json(paths["owned"])
                if release is not None:
                    expected={"schema","capability_ref","owner_id","generation","invocation_id","lease_revision","release_receipt"}
                    if (set(release)!=expected or release.get("schema")!="managed-terminal-lease-release/v1"
                            or release.get("capability_ref")!=intent["capability_ref"]
                            or release.get("invocation_id")!=intent["invocation_id"]):
                        raise ValueError("managed terminal lease release marker invalid")
                    break
                if abort is not None and owned is None:
                    expected={"schema","capability_ref","aborted_at_utc","reason"}
                    if (set(abort)!=expected or abort.get("schema")!="managed-terminal-lease-abort/v1"
                            or abort.get("capability_ref")!=intent["capability_ref"]):
                        raise ValueError("managed terminal lease abort marker invalid")
                    break
                receipt.update(status="awaiting_release",quiescent=False,finished_at_utc=None,
                               exit_code=exit_code,elapsed_seconds=elapsed,
                               runtime_seconds=min(elapsed,request["timeout_seconds"]),
                               failure=None,terminal_hold_ref=intent["capability_ref"],
                               pending_terminal_status=terminal_status)
                _write(directory/"receipt.json",receipt)
                time.sleep(.02)
                elapsed=time.monotonic()-started
        receipt.update(status=terminal_status,quiescent=True,finished_at_utc=_utc(),exit_code=exit_code,
                       elapsed_seconds=elapsed,runtime_seconds=min(elapsed,request["timeout_seconds"]),
                       failure=terminal_failure)
        receipt.pop("terminal_hold_ref",None);receipt.pop("pending_terminal_status",None)
        _write(directory / "receipt.json", receipt)
    except Exception as exc:
        # Unexpected supervisor failure may leave children. Never manufacture closure.
        if _descendants(proc_pid):
            raise
        elapsed = time.monotonic() - started
        receipt.update(status="failed", quiescent=True, finished_at_utc=_utc(),
                       elapsed_seconds=elapsed, runtime_seconds=min(elapsed, request["timeout_seconds"]),
                       failure=type(exc).__name__ + ": worker preparation/start failed")
        _write(directory / "receipt.json", receipt)


class ManagedExecutorRuntime:
    """Orchestrate effects after CAS; leave publication/merging to the integrator."""
    def __init__(self, plan, store, repo_root, backend, *, journal_root=None):
        pool.validate_plan(plan)
        self.plan, self.store, self.backend = plan, store, backend
        self.journal = ExecutionJournal(journal_root if journal_root is not None else backend.journal_root)
        self.repo_root = Path(_git(repo_root, "rev-parse", "--show-toplevel")).resolve()
        if _git(self.repo_root, "rev-parse", plan["base_sha"] + "^{commit}") != plan["base_sha"]:
            raise ValueError("plan base is not an exact available commit")

    def _terminal_hold_directory(self,task_id,attempt_id):
        return self.journal.directory(self._identity(task_id,attempt_id))

    def _arm_terminal_hold(self,capability):
        import managed_terminal_capability
        payload=capability.payload
        directory=self._terminal_hold_directory(payload["task_id"],payload["attempt_id"])
        paths=_terminal_hold_paths(directory)
        if any(path.exists() for path in paths.values()):
            raise ValueError("managed terminal lease hold already armed or consumed")
        proc_pid=int(os.readlink("/proc/self"))
        proc_state=_process(proc_pid)
        if proc_state is None:
            raise ValueError("controller process identity unavailable")
        intent={"schema":"managed-terminal-lease-intent/v1",
                "capability_ref":managed_terminal_capability.reference(capability),
                "invocation_id":payload["invocation_id"],"lease_repository":payload["lease_repository"],
                "lease_source_ref":payload["lease_source_ref"],"armed_at_utc":_utc(),
                "controller_proc_pid":proc_pid,"controller_birth":proc_state["birth"]}
        _write(paths["intent"],intent)
        fd=os.open(directory,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return intent

    def _mark_terminal_acquire_done(self,capability,status):
        import managed_terminal_capability
        if status not in {"authoritative","error"}:
            raise ValueError("managed terminal acquire completion status invalid")
        payload=capability.payload
        paths=_terminal_hold_paths(self._terminal_hold_directory(payload["task_id"],payload["attempt_id"]))
        marker={"schema":"managed-terminal-lease-acquire-done/v1",
                "capability_ref":managed_terminal_capability.reference(capability),
                "status":status,"finished_at_utc":_utc()}
        _write(paths["acquire_done"],marker)
        return marker

    def _abort_terminal_hold(self,capability,reason):
        import managed_terminal_capability
        payload=capability.payload
        directory=self._terminal_hold_directory(payload["task_id"],payload["attempt_id"])
        paths=_terminal_hold_paths(directory)
        if paths["owned"].exists():
            raise ValueError("cannot abort terminal hold after lease ownership was recorded")
        _write(paths["abort"],{"schema":"managed-terminal-lease-abort/v1",
                               "capability_ref":managed_terminal_capability.reference(capability),
                               "aborted_at_utc":_utc(),"reason":reason})

    def terminal_capability(self,task_id,attempt_id,*,lease_repository,lease_source_ref,observed_at_utc=None):
        import managed_terminal_capability
        return managed_terminal_capability.issue(
            self,task_id,attempt_id,lease_repository=lease_repository,lease_source_ref=lease_source_ref,
            observed_at_utc=observed_at_utc)

    def acquire_execution_lease(self,lease_store,expected_revision,repository,source_ref,owner_id,task_id,attempt_id,at,*,ttl=1200,quiescence=None):
        import execution_lease_v2,managed_terminal_capability
        capability=self.terminal_capability(
            task_id,attempt_id,lease_repository=repository,lease_source_ref=source_ref,observed_at_utc=at)
        intent=self._arm_terminal_hold(capability)
        try:
            managed_terminal_capability.validate_verified(
                capability,capability.invocation(),repository,source_ref,at)
            result=execution_lease_v2.acquire_managed_cas(
                lease_store,expected_revision,repository,source_ref,owner_id,at,
                terminal_capability=capability,ttl=ttl,quiescence=quiescence)
            self._mark_terminal_acquire_done(capability,"authoritative")
        except Exception as exc:
            try:
                self._mark_terminal_acquire_done(capability,"error")
            except Exception:
                pass
            try:
                reconciled=self.reconcile_execution_lease_hold(lease_store,task_id,attempt_id)
            except Exception:
                raise
            if reconciled["status"]=="owned":
                current_revision,current_record=lease_store.read()
                owned=reconciled["owned_marker"]
                if (current_record is None or current_record.get("owner_id")!=owned["owner_id"]
                        or current_record.get("generation")!=owned["generation"]
                        or current_record.get("invocation",{}).get("invocation_id")!=owned["invocation_id"]):
                    raise ValueError("managed lease acquisition recovery lost exact ownership") from exc
                return {"revision":current_revision,"record":current_record,
                        "owner_id":owned["owner_id"],"generation":owned["generation"],
                        "invocation":copy.deepcopy(current_record["invocation"]),
                        "terminal_capability_ref":intent["capability_ref"],
                        "terminal_task_id":task_id,"terminal_attempt_id":attempt_id,
                        "recovered_after_acquire":True}
            if reconciled["status"]=="released":
                raise ValueError("managed lease acquisition was already released during reconciliation") from exc
            raise
        payload=capability.payload
        paths=_terminal_hold_paths(self._terminal_hold_directory(task_id,attempt_id))
        owned={"schema":"managed-terminal-lease-owned/v1","capability_ref":intent["capability_ref"],
               "owner_id":owner_id,"generation":result["generation"],
               "invocation_id":result["invocation"]["invocation_id"],"lease_revision":result["revision"]}
        if payload["invocation_id"]!=owned["invocation_id"]:
            raise ValueError("managed lease acquisition invocation mismatch")
        _write(paths["owned"],owned)
        return {**result,"terminal_capability_ref":intent["capability_ref"],
                "terminal_task_id":task_id,"terminal_attempt_id":attempt_id}

    def reconcile_execution_lease_hold(self,lease_store,task_id,attempt_id):
        directory=self._terminal_hold_directory(task_id,attempt_id)
        paths=_terminal_hold_paths(directory)
        intent=_read_json(paths["intent"])
        if intent is None:
            raise ValueError("managed terminal lease intent missing")
        release=_read_json(paths["release"])
        if release is not None:
            return {"status":"released","release_marker":release}
        abort=_read_json(paths["abort"])
        if abort is not None:
            return {"status":"aborted","abort_marker":abort}
        owned=_read_json(paths["owned"])
        if owned is None:
            recovered=lease_store.find_invocation_ownership(
                intent["lease_repository"],intent["lease_source_ref"],intent["invocation_id"])
            if recovered is None:
                done=_read_json(paths["acquire_done"])
                controller=_process(intent["controller_proc_pid"])
                controller_live=bool(controller and controller["birth"]==intent["controller_birth"])
                if done is None and controller_live:
                    return {"status":"acquire_pending","reason":"exact acquisition controller is still live"}
                if done is not None:
                    expected={"schema","capability_ref","status","finished_at_utc"}
                    if (set(done)!=expected or done.get("schema")!="managed-terminal-lease-acquire-done/v1"
                            or done.get("capability_ref")!=intent["capability_ref"]
                            or done.get("status") not in {"authoritative","error"}):
                        raise ValueError("managed terminal acquire completion marker invalid")
                marker={"schema":"managed-terminal-lease-abort/v1",
                        "capability_ref":intent["capability_ref"],
                        "aborted_at_utc":_utc(),
                        "reason":"authoritative lease history and controller quiescence prove acquisition absent"}
                _write(paths["abort"],marker)
                return {"status":"aborted","abort_marker":marker}
            owned={"schema":"managed-terminal-lease-owned/v1",
                   "capability_ref":intent["capability_ref"],
                   "owner_id":recovered["owner_id"],
                   "generation":recovered["generation"],
                   "invocation_id":intent["invocation_id"],
                   "lease_revision":recovered["revision"]}
            _write(paths["owned"],owned)
        try:
            released=lease_store.find_release_receipt(
                owned["owner_id"],owned["generation"],owned["invocation_id"])
        except ValueError as exc:
            if str(exc)!="exact historical lease release was not found":
                raise
            return {"status":"owned","owned_marker":owned}
        marker={"schema":"managed-terminal-lease-release/v1",
                "capability_ref":intent["capability_ref"],
                "owner_id":owned["owner_id"],"generation":owned["generation"],
                "invocation_id":owned["invocation_id"],
                "lease_revision":released["release_receipt"]["lease_revision"],
                "release_receipt":released["release_receipt"]}
        _write(paths["release"],marker)
        return {"status":"released","owned_marker":owned,"release_marker":marker,
                "release_record":released["release_record"],
                "current_revision":released["current_revision"]}

    def release_execution_lease(self,lease_store,expected_revision,repository,source_ref,owner_id,generation,invocation_id,task_id,attempt_id,at):
        import execution_lease_v2
        directory=self._terminal_hold_directory(task_id,attempt_id)
        paths=_terminal_hold_paths(directory)
        intent=_read_json(paths["intent"]);owned=_read_json(paths["owned"])
        if intent is None:
            raise ValueError("managed terminal hold marker missing")
        if owned is None:
            reconciled=self.reconcile_execution_lease_hold(lease_store,task_id,attempt_id)
            if reconciled["status"]=="released":
                receipt=reconciled["release_marker"]["release_receipt"]
                return {"revision":reconciled["current_revision"],"record":lease_store.read()[1],
                        "release_receipt":receipt,"release_record":reconciled["release_record"],
                        "recovered_after_release":True}
            if reconciled["status"]=="aborted":
                raise ValueError("managed terminal hold proves lease acquisition absent")
            owned=_read_json(paths["owned"])
        if (owned.get("schema")!="managed-terminal-lease-owned/v1"
                or owned.get("capability_ref")!=intent.get("capability_ref")
                or owned.get("owner_id")!=owner_id or owned.get("generation")!=generation
                or owned.get("invocation_id")!=invocation_id):
            raise ValueError("managed terminal ownership marker mismatch")
        current_revision,current_record=lease_store.read()
        if current_record is None or current_record.get("repository")!=repository or current_record.get("source_ref")!=source_ref:
            raise ValueError("managed terminal lease coordination binding mismatch")
        if current_record.get("owner_id")==owner_id and current_record.get("generation")==generation:
            if current_revision!=expected_revision:
                raise ValueError("stale expected lease revision before release")
            released=execution_lease_v2.release_cas(
                lease_store,expected_revision,repository,source_ref,owner_id,generation,invocation_id,at)
            receipt=released["release_receipt"]
        else:
            recovered=lease_store.find_release_receipt(owner_id,generation,invocation_id)
            receipt=recovered["release_receipt"]
            released={"revision":recovered["current_revision"],"record":current_record,
                      "release_receipt":receipt,"release_record":recovered["release_record"],
                      "recovered_after_release":True}
        marker={"schema":"managed-terminal-lease-release/v1","capability_ref":intent["capability_ref"],
                "owner_id":owner_id,"generation":generation,"invocation_id":invocation_id,
                "lease_revision":receipt["lease_revision"],"release_receipt":receipt}
        _write(paths["release"],marker)
        return released

    def _task(self, task_id):
        return next(task for task in self.plan["tasks"] if task["id"] == task_id)

    def _identity(self, task_id, attempt_id):
        task = self._task(task_id)
        return {**{k: self.plan[k] for k in ("pool_id", "change_id", "parent_invocation_id", "base_sha",
                                           "integrator_id", "coordination_ref", "coordination_store_id")},
                **{k: task[k] for k in ("executor_id", "role", "branch", "worktree")},
                "task_id": task_id, "attempt_id": attempt_id, "plan_ref": _digest(self.plan)}

    def _validate_start(self, task_id, argv):
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x or "\0" in x for x in argv):
            raise ValueError("argv must be a nonempty argument array")
        task = self._task(task_id)
        if self.backend.name not in task["backend_preferences"]:
            raise ValueError("backend not in task preferences")

    def start(self, expected_store_revision, task_id, attempt_id, *, reservation_token, argv):
        self._validate_start(task_id, argv)
        queued = pool.queue_task_cas(self.store, expected_store_revision, self.plan, task_id, attempt_id,
                                     reservation_token=reservation_token)
        return self.start_queued(queued["store_revision"], task_id, attempt_id,
                                 reservation_token=reservation_token, argv=argv)

    def start_queued(self, expected_store_revision, task_id, attempt_id, *, reservation_token, argv):
        """Resume only an unconsumed queue reservation, using a fresh launch CAS."""
        self._validate_start(task_id, argv)
        task = self._task(task_id)
        claim = pool.claim_launch_cas(self.store, expected_store_revision, self.plan, task_id, attempt_id,
                                      reservation_token=reservation_token)
        # Nothing after this point may retry a failed/uncertain backend start.
        _, state = self.store.read()
        current = next(row for row in state["tasks"] if row["id"] == task_id)
        identity = self._identity(task_id, attempt_id)
        directory = self.journal.directory(identity)
        cwd = (self.repo_root.parent / task["worktree"]).resolve() if task["role"] == "writer" else directory / "worktree"
        request = {"schema": "managed-executor-start/v1", "identity": identity, "claim": claim,
                   "argv": list(argv), "repo_root": str(self.repo_root), "cwd": str(cwd),
                   "timeout_seconds": task["max_runtime_seconds"] - current["runtime_seconds"],
                   "journal_directory": str(directory)}
        self.journal.prepare(request)
        receipt = self.backend.start(request)
        self._validate_receipt(request, receipt)
        _write(directory / "backend-receipt.json", receipt)
        return receipt

    def _request(self, task_id, attempt_id):
        identity = self._identity(task_id, attempt_id)
        _, state = self.store.read()
        current = next(row for row in state["tasks"] if row["id"] == task_id)
        if attempt_id not in current["attempt_ids"]:
            raise ValueError("attempt is not in durable pool history")
        request = self.journal.load_request(identity)
        if request is not None:
            claim = request["claim"]
            if (claim["task_id"] != task_id or claim["attempt_id"] != attempt_id or not claim["launch_allowed"]
                    or (current["active_attempt_id"] == attempt_id
                        and current["reservation_token"] != claim["reservation_token"])):
                raise ValueError("request does not match durable launch identity")
        return request

    def _saved_receipt(self, request):
        path = self.journal.directory(request["identity"]) / "backend-receipt.json"
        return json.loads(path.read_text()) if path.exists() else None

    @staticmethod
    def _validate_receipt(request, receipt):
        if receipt.get("identity") != request["identity"]:
            raise ValueError("backend observation identity mismatch")
        if receipt.get("status") == "unknown" and receipt.get("quiescent") is False:
            return
        if (receipt.get("schema") != "managed-executor-observation/v1"
                or receipt.get("claim") != request["claim"]
                or receipt.get("request_ref") != _digest(request)
                or receipt.get("launch_id") != _digest(request)):
            raise ValueError("backend observation claim/receipt mismatch")
        active = receipt.get("status") in {"running", "starting", "awaiting_release"}
        terminal = receipt.get("status") in {"succeeded", "failed", "cancelled", "timed_out"}
        if not (active or terminal) or receipt.get("quiescent") is not terminal:
            raise ValueError("backend must prove descendant quiescence before terminal status")

    def observe(self, task_id, attempt_id):
        request = self._request(task_id, attempt_id)
        if request is None:
            return _unknown(self._identity(task_id, attempt_id), "claimed start has no local receipt; never replay")
        receipt = self.backend.observe(request, self._saved_receipt(request))
        self._validate_receipt(request, receipt)
        if receipt["quiescent"] and receipt["status"] in {"failed", "cancelled", "timed_out"}:
            revision, state = self.store.read()
            current = next(row for row in state["tasks"] if row["id"] == task_id)
            if current["active_attempt_id"] == attempt_id:
                status = "cancelled" if receipt["status"] == "cancelled" else "failed"
                updated = pool.fail_attempt(self.plan, state, task_id, attempt_id, terminal_status=status,
                                           reservation_token=request["claim"]["reservation_token"],
                                           expected_revision=state["revision"], runtime_seconds=receipt["runtime_seconds"])
                self.store.compare_and_swap(revision, updated)
        return receipt

    def cancel(self, task_id, attempt_id):
        request = self._request(task_id, attempt_id)
        if request is None:
            return _unknown(self._identity(task_id, attempt_id), "no observed start to cancel")
        self.backend.cancel(request, self._saved_receipt(request))
        return self.observe(task_id, attempt_id)

    def accept(self, task_id, attempt_id, *, result_commit, output_refs, evidence_refs, cost_units=0):
        receipt = self.observe(task_id, attempt_id)
        if receipt["status"] != "succeeded" or not receipt["quiescent"]:
            raise ValueError("result requires observed quiescent process success")
        request = self._request(task_id, attempt_id)
        task = self._task(task_id)
        if _git(request["cwd"], "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("worker worktree must be clean before accepting a result")
        if task["role"] != "writer" and _git(request["cwd"], "rev-parse", "HEAD") != self.plan["base_sha"]:
            raise ValueError("non-writer changed its isolated Git head")
        changed = pool._git_changed_paths(self.plan["base_sha"], result_commit, request["cwd"]) if task["role"] == "writer" else []
        at = attempts.new_attempt(pool_id=self.plan["pool_id"], change_id=self.plan["change_id"], task_id=task_id,
                                  attempt_id=attempt_id, parent_invocation_id=self.plan["parent_invocation_id"],
                                  executor_id=task["executor_id"], backend=self.backend.name, role=task["role"],
                                  base_sha=self.plan["base_sha"], at_utc=receipt["created_at_utc"],
                                  write_paths=task["write_paths"], branch=task["branch"], worktree=task["worktree"])
        at = attempts.transition(at, "queued", receipt["created_at_utc"])
        at = attempts.transition(at, "running", receipt["started_at_utc"], activity_ref=receipt["launch_id"])
        at = attempts.transition(at, "succeeded", receipt["finished_at_utc"])
        result = {"schema": attempts.RESULT_SCHEMA,
                  **{k: at[k] for k in ("pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id", "role", "base_sha")},
                  "result_commit": result_commit, "changed_paths": changed, "evidence_refs": evidence_refs,
                  "completed_at_utc": receipt["finished_at_utc"], "integrated": False,
                  **{k: False for k in attempts.AUTHORITY_FIELDS}}
        attempts.validate_result(result, at)
        result_ref = _digest(result)
        revision, state = self.store.read()
        updated = pool.accept_result(
            self.plan, state, task_id=task_id, attempt_id=attempt_id, result_ref=result_ref,
            base_sha=self.plan["base_sha"], executor_id=task["executor_id"],
            parent_invocation_id=self.plan["parent_invocation_id"], integrator_id=self.plan["integrator_id"],
            branch=task["branch"], worktree=task["worktree"], reservation_token=request["claim"]["reservation_token"],
            result_commit=result_commit, changed_paths=changed, output_refs=output_refs, evidence_refs=evidence_refs,
            runtime_seconds=receipt["runtime_seconds"], cost_units=cost_units, git_worktree=request["cwd"],
            expected_revision=state["revision"])
        directory = self.journal.directory(request["identity"])
        _write(directory / "attempt.json", at)
        _write(directory / "result.json", result)
        self.store.compare_and_swap(revision, updated)
        return {"result_ref": result_ref, "result": result, "attempt": at}


    def record_integration(self, task_id, result_ref, *, integrator_id, handoff, proof,
                           integration_commit, integration_ref, remote,
                           trusted_repository, trusted_remote_id):
        """Record already-performed integration; this method never pushes or merges."""
        if integrator_id != self.plan["integrator_id"]:
            raise ValueError("only the assigned integrator can record integration")
        revision, state = self.store.read()
        current = next(row for row in state["tasks"] if row["id"] == task_id)
        if current["status"] != "succeeded" or current["accepted_result_ref"] != result_ref:
            raise ValueError("integration requires the exact accepted result")
        request = self._request(task_id, current["attempt_ids"][-1])
        result = json.loads((self.journal.directory(request["identity"]) / "result.json").read_text())
        if _digest(result) != result_ref:
            raise ValueError("accepted result digest mismatch")
        task = self._task(task_id)
        if task["role"] != "writer":
            raise ValueError("non-writer disposition requires the external integrator's pool API")
        for key in ("pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id", "executor_id", "base_sha"):
            if handoff[key] != request["identity"][key]:
                raise ValueError("handoff assignment identity mismatch")
        if (handoff["assigned_branch"] != task["branch"]
                or handoff["source_result_commit"] != result["result_commit"]
                or handoff["changed_paths"] != result["changed_paths"]
                or not set(result["evidence_refs"]) <= set(handoff["evidence_refs"])):
            raise ValueError("handoff does not bind the accepted worker result")
        handoffs.validate_publication_proof(proof, handoff, self.repo_root, remote=remote,
                                            trusted_repository=trusted_repository,
                                            trusted_remote_id=trusted_remote_id)
        if (not isinstance(integration_ref, str) or not integration_ref.startswith("refs/heads/")
                or integration_ref == self.plan["coordination_ref"]
                or integration_ref in {"refs/heads/" + t["branch"].removeprefix("refs/heads/")
                                       for t in self.plan["tasks"] if t["branch"]}):
            raise ValueError("integration ref must be separate from worker and coordination refs")
        if not isinstance(integration_commit, str) or not pool.SHA.fullmatch(integration_commit):
            raise ValueError("integration commit must be an exact SHA")
        ancestry = subprocess.run(["git", "-C", str(self.repo_root), "merge-base", "--is-ancestor",
                                   result["result_commit"], integration_commit], env=git_object_environment(), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=15)
        if ancestry.returncode:
            raise ValueError("integration does not contain the accepted worker result")
        if _git(self.repo_root, "rev-parse", "--verify", integration_ref) != integration_commit:
            raise ValueError("integration commit is not the exact integration ref head")
        handoffs._verify_remote_branch(self.repo_root, remote, integration_ref, integration_commit, trusted_remote_id)
        updated = pool.mark_integrated(self.plan, state, task_id, result_ref, expected_revision=state["revision"])
        _write(self.journal.directory(request["identity"]) / "integration.json",
               {"integrator_id": integrator_id, "result_ref": result_ref, "handoff": handoff, "proof": proof,
                "integration_commit": integration_commit, "integration_ref": integration_ref})
        return self.store.compare_and_swap(revision, updated)

    def evaluate_parent(self, continuity_state, *, now_utc=None):
        """Read fresh pool state and combine it with the real continuity evaluator."""
        if continuity_state.get("invocation_id") != self.plan["parent_invocation_id"]:
            raise ValueError("parent invocation identity mismatch")
        revision, state = self.store.read()
        assessment = pool.assess(self.plan, state)
        continuity = execution_continuity.evaluate(continuity_state, now_utc=now_utc)
        allowed = assessment["terminal_allowed"] and continuity["final_response_allowed"]
        return {"schema": "managed-executor-parent-assessment/v1", "store_revision": revision,
                "pool": assessment, "continuity": continuity, "final_response_allowed": allowed,
                "reason": continuity["reason"] if assessment["terminal_allowed"] else "managed_work_requires_continuation",
                **{k: False for k in pool.AUTHORITY_FIELDS}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervise", required=True, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    _supervise(args.supervise)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
