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
import errno
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
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _signal_descendant(target, identity, sig):
    """Pin the translated syscall PID, then recheck its procfs birth.

    Procfs PIDs and syscall PIDs can differ: _process translates NSpid.
    A pidfd closes the check/kill reuse race; it grants no UID/LSM authority.
    No numeric kill fallback is safe if pidfds are unavailable.
    """
    evidence = {"pid": target, "birth": identity["birth"],
                "signal_pid": identity["signal_pid"], "signal": int(sig)}
    current = _process(target)
    if (not current or current["birth"] != identity["birth"]
            or current["signal_pid"] != identity["signal_pid"]):
        return {**evidence, "result": "identity_changed"}
    if type(current["signal_pid"]) is not int or current["signal_pid"] <= 0:
        return {**evidence, "result": "namespace_unavailable"}
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return {**evidence, "result": "pidfd_unavailable"}
    fd = None
    try:
        fd = os.pidfd_open(current["signal_pid"], 0)
        checked = _process(target)
        if (not checked or checked["birth"] != identity["birth"]
                or checked["signal_pid"] != current["signal_pid"]):
            return {**evidence, "result": "identity_changed"}
        signal.pidfd_send_signal(fd, sig)
        return {**evidence, "result": "sent"}
    except OSError as exc:
        return {**evidence, "result": "error", "errno": exc.errno,
                "error_type": type(exc).__name__, "error": str(exc)}
    finally:
        if fd is not None:
            os.close(fd)


# TERM grace remains .2s. Successful KILL is still not an ECHILD proof.
_TERMINATION_BOUND_SECONDS = 1.0


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


_TERMINAL_PROOF_SEAL=object()

class VerifiedTerminalProof(dict):
    """Only an actual original runtime can issue current owner-final proof.

    JSON serialization remains ordinary evidence, never this live capability.
    Every use rechecks the original runtime/control chain and physical absence.
    """
    def __init__(self,seal,runtime,lease_store,release_receipt,evidence,*,boot_transition_path=None):
        if seal is not _TERMINAL_PROOF_SEAL:raise ValueError('package-owned terminal proof required')
        super().__init__(evidence)
        self._seal=seal;self._runtime=runtime;self._store=lease_store
        self._receipt=copy.deepcopy(release_receipt)
        self._task_id=evidence['task_id'];self._attempt_id=evidence['attempt_id']
        self._boot_transition_path=boot_transition_path
    def revalidate_for(self,store,invocation_id,owned,receipt):
        from git_lease_store import GitLeaseStore
        if type(self) is not VerifiedTerminalProof or self._seal is not _TERMINAL_PROOF_SEAL or type(store) is not GitLeaseStore:
            raise ValueError('authentic original terminal proof required')
        if (store.store_id,store.ref)!=(self._store.store_id,self._store.ref) or receipt!=self._receipt:
            raise ValueError('native owner-final endpoint/release binding substituted')
        if self._boot_transition_path is None:
            current=self._runtime.verify_terminal(self._task_id,self._attempt_id,include_controller=True,lease_store=store,release_receipt=receipt)
        else:
            current=self._runtime.verify_released_terminal_after_reboot(self._task_id,self._attempt_id,
                lease_store=store,release_receipt=receipt,boot_transition_path=self._boot_transition_path)
        binding=current['ownership']
        if binding['invocation_id']!=invocation_id or owned!={'owner_id':binding['owner_id'],'generation':binding['generation']}:
            raise ValueError('native owner-final original invocation substituted')
        return dict(current)

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
               "exit_code": None, "elapsed_seconds": 0, "runtime_seconds": 0, "failure": None,
               "process_births": [{"pid":proc_pid,"birth":_process(proc_pid)['birth'],"role":"supervisor"}]}
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
        if request['identity']['role'] == 'read_only':
            history = _git(cwd, 'reflog', 'show', '--format=%H', 'HEAD').splitlines()
            if not history or any(sha != request['identity']['base_sha'] for sha in history):
                raise ValueError('read_only worker requires initial exact-base reflog history')
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
            child_identity=_process(child.pid)
            receipt['process_births'].append({'pid':child.pid,'birth':child_identity['birth'] if child_identity else None,'role':'worker','unknown_reason':None if child_identity else 'exited_before_birth_observation'})
            receipt.update(status="running", started_at_utc=_utc(), worker_pid=child.pid)
            _write(directory / "receipt.json", receipt)
        while True:
            # Capture genuine births while processes exist; never reconstruct
            # missing historical births after a wrapper has already exited.
            recorded={item['pid'] for item in receipt['process_births']}
            for descendant,identity in _descendants(proc_pid).items():
                if descendant not in recorded:
                    receipt['process_births'].append({'pid':descendant,'birth':identity['birth'],'role':'descendant'})
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
                receipt['quiescence_proof']={'method':'waitpid_ECHILD','boot_id':receipt['boot_id'],'supervisor_birth':receipt['supervisor_birth'],'request_ref':receipt['request_ref'],'process_births_digest':_digest(receipt['process_births']),'observed_at_utc':_utc()}
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
                    outcome = _signal_descendant(target, identity, sig)
                    previous = receipt.get("signal_failure", {})
                    if (outcome["result"] != "sent" and
                            (not previous or
                             (outcome.get("errno") is not None and previous.get("errno") is None) or
                             (outcome.get("errno") == errno.EPERM and previous.get("errno") != errno.EPERM))):
                        # Persist first failure; prefer actual errno, especially EPERM.
                        # ESRCH is not closure; never replace an EPERM with success.
                        receipt.update(status="unknown", quiescent=False,
                                       termination_reason=termination,
                                       reason="termination signal unproved; descendant quiescence unproved",
                                       signal_failure={**outcome, "observed_at_utc": _utc()},
                                       elapsed_seconds=elapsed,
                                       runtime_seconds=min(elapsed, request["timeout_seconds"]))
                        _write(directory / "receipt.json", receipt)
                if time.monotonic() - stopping_at >= _TERMINATION_BOUND_SECONDS:
                    receipt.update(status="unknown", quiescent=False,
                                   termination_reason=termination,
                                   reason="termination deadline exceeded; descendant quiescence unproved",
                                   failure="bounded termination failed", exit_code=exit_code,
                                   elapsed_seconds=elapsed,
                                   runtime_seconds=min(elapsed, request["timeout_seconds"]))
                    _write(directory / "receipt.json", receipt)
                    return
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
        receipt.pop("reason", None)
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
        # Save the actual issued descriptor, not a later invented capability.
        _write(directory/'terminal-capability-descriptor.json',{'schema':'original-managed-capability-descriptor/v1','capability_ref':managed_terminal_capability.reference(capability),'payload':payload})
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
        # Ordinary start remains asynchronous so preparation may be cancelled.
        # Only capability admission waits for the genuine worker birth; issuance
        # still rejects missing births, terminal/unknown state and stale joins.
        end=time.monotonic()+3
        while time.monotonic()<end:
            observation=self.observe(task_id,attempt_id)
            if observation.get('status')!='starting':break
            time.sleep(.01)
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

    def verify_terminal(self,task_id,attempt_id,*,include_controller=False,lease_store=None,release_receipt=None):
        """Package-owned original journal + Git claim + current physical proof."""
        return self._verify_terminal(task_id,attempt_id,include_controller=include_controller,
            lease_store=lease_store,release_receipt=release_receipt)

    def verify_released_terminal_after_reboot(self,task_id,attempt_id,*,lease_store,release_receipt,boot_transition_path):
        """Explicit failed/released original only; no launch or lease capability."""
        from managed_boot_transition import authenticate
        request=self._request(task_id,attempt_id)
        if request is None:raise ValueError('original runtime request missing')
        observation=self.backend.observe(request,self._saved_receipt(request))
        self._validate_receipt(request,observation)
        transition=authenticate(boot_transition_path,request,observation,release_receipt)
        return self._verify_terminal(task_id,attempt_id,include_controller=True,lease_store=lease_store,
            release_receipt=release_receipt,boot_transition=transition)

    def _verify_terminal(self,task_id,attempt_id,*,include_controller=False,lease_store=None,release_receipt=None,boot_transition=None):
        from managed_executor_store import GitManagedExecutorStore
        if type(self) is not ManagedExecutorRuntime or type(self.backend) is not LocalCommandBackend or type(self.store) is not GitManagedExecutorStore or type(self.journal) is not ExecutionJournal:
            raise ValueError('authentic package-owned terminal runtime required')
        request=self._request(task_id,attempt_id)
        if request is None:raise ValueError('original runtime request missing')
        observation=self.observe(task_id,attempt_id)
        if not observation.get('quiescent') or observation.get('status') not in {'succeeded','failed','cancelled','timed_out'}:
            raise ValueError('actual supervisor not terminal/quiescent')
        proof=observation.get('quiescence_proof');births=observation.get('process_births')
        if not isinstance(proof,dict) or proof.get('method')!='waitpid_ECHILD':raise ValueError('authentic supervisor quiescence proof required; wrapper exit is insufficient')
        if (proof.get('boot_id')!=observation.get('boot_id') or proof.get('supervisor_birth')!=observation.get('supervisor_birth') or proof.get('request_ref')!=_digest(request) or not isinstance(births,list) or proof.get('process_births_digest')!=_digest(births)):
            raise ValueError('original birth/request/boot quiescence binding mismatch')
        reconciliation=None
        if boot_transition is None:
            if proof['boot_id']!=_boot():raise ValueError('original birth/request/boot quiescence binding mismatch')
        else:
            from managed_boot_transition import _VerifiedBootTransition
            if type(boot_transition) is not _VerifiedBootTransition or not include_controller:
                raise ValueError('authentic released original boot transition required')
            reconciliation=boot_transition.revalidate(request,observation,release_receipt)
        historical=self.store.read_revision(request['claim']['store_revision'])
        if pool.canonical_state_ref(historical)!=request['claim']['state_ref'] or historical['revision']!=request['claim']['state_revision']:
            raise ValueError('terminal original canonical Git launch claim mismatch')
        task=next((row for row in historical['tasks'] if row['id']==task_id),None)
        if task is None or task['active_attempt_id']!=attempt_id or task['reservation_token']!=request['claim']['reservation_token']:
            raise ValueError('terminal original task/attempt/reservation mismatch')
        births=copy.deepcopy(births)
        ownership=None
        if include_controller:
            from git_lease_store import GitLeaseStore
            from managed_terminal_capability import _digest as capability_digest,invocation_identity
            if type(lease_store) is not GitLeaseStore:raise ValueError('terminal controller requires authentic canonical lease history')
            paths=_terminal_hold_paths(Path(request['journal_directory']))
            intent=_read_json(paths['intent']);owned=_read_json(paths['owned']);released=_read_json(paths['release'])
            descriptor=_read_json(Path(request['journal_directory'])/'terminal-capability-descriptor.json')
            if not all(isinstance(x,dict) for x in (intent,owned,released,descriptor)):raise ValueError('original issued capability/hold/release records missing; never mint historical capability')
            payload=descriptor.get('payload')
            if not isinstance(payload,dict) or descriptor.get('schema')!='original-managed-capability-descriptor/v1':raise ValueError('original capability descriptor invalid')
            ref=capability_digest(payload)
            if payload.get('schema')!='managed-terminal-capability/v2' or payload.get('boot_id')!=proof['boot_id'] or any(intent.get(k)!=payload.get(k) for k in ('controller_proc_pid','controller_birth')):
                raise ValueError('original controller canonical birth/boot binding mismatch; legacy proof remains historical')
            originals=payload.get('runtime_processes')
            if (not isinstance(originals,list) or {x.get('role') for x in originals}!={'worker','supervisor'} or
                any(not isinstance(x.get('birth'),str) or not x['birth'].isdigit() or
                    not any((x['pid'],x['birth'],x['role'])==(row.get('pid'),row.get('birth'),row.get('role')) for row in births) or
                    x['pid']!=observation.get('worker_pid' if x['role']=='worker' else 'supervisor_proc_pid') for x in originals)):
                raise ValueError('original canonical runtime process PID/birth binding mismatch')
            derived='managed-terminal:'+capability_digest(invocation_identity(payload)).split(':',1)[1]
            if (any(value.get('capability_ref')!=ref for value in (descriptor,intent,owned,released)) or any(value.get('invocation_id')!=derived for value in (payload,intent,owned,released)) or payload.get('request_ref')!=_digest(request) or payload.get('launch_id')!=_digest(request) or payload.get('managed_store_ref')!=self.store.ref or payload.get('managed_store_id')!=self.store.store_id or any(payload.get(key)!=request['identity'].get(key) for key in ('pool_id','task_id','attempt_id'))):raise ValueError('terminal original ownership/launch/capability chain mismatch')
            running=self.store.read_revision(payload['managed_store_revision'])
            row=next((x for x in running['tasks'] if x['id']==task_id),None)
            if running['revision']!=payload['managed_state_revision'] or row is None or row['status']!='running' or row['active_attempt_id']!=attempt_id or row['reservation_token']!=request['claim']['reservation_token']:raise ValueError('terminal original canonical running pool mismatch')
            original=lease_store.read_revision(owned['lease_revision'])
            if original['owner_id']!=owned['owner_id'] or original['generation']!=owned['generation'] or not original['invocation'] or original['invocation']['invocation_id']!=derived:raise ValueError('terminal original owned lease mismatch')
            if release_receipt!=released.get('release_receipt') or not isinstance(release_receipt,dict):raise ValueError('terminal actual release receipt mismatch')
            release_record=lease_store.read_revision(release_receipt['lease_revision'])
            rel=release_receipt['release']
            if release_record['owner_id'] is not None or release_record['last_release']!=rel or rel['owner_id']!=owned['owner_id'] or rel['generation']!=owned['generation'] or rel['invocation_id']!=derived:raise ValueError('terminal canonical historical release mismatch')
            if reconciliation is not None and release_record.get('external_guard') is not None:
                raise ValueError('original reboot reconciliation requires released unguarded custody')
            births.append({'pid':intent['controller_proc_pid'],'birth':intent['controller_birth'],'role':'controller'})
            ownership={'invocation_id':derived,'owner_id':owned['owner_id'],'generation':owned['generation'],'original_owned_revision':owned['lease_revision'],'release_revision':release_receipt['lease_revision']}
        seen=set();reused_descendants=[]
        for item in births:
            pid=item.get('pid');birth=item.get('birth')
            if type(pid) is not int or pid<=0 or pid in seen or not isinstance(birth,str) or not birth.isdigit():raise ValueError('recorded birth missing/invalid; UNKNOWN remains UNKNOWN')
            seen.add(pid)
            current=_process(pid)
            if current is None and reconciliation is not None:
                # The ordinary process reader also returns None on unreadable
                # procfs data. Only a missing proc directory proves absence.
                try:Path(f'/proc/{pid}').stat()
                except FileNotFoundError:pass
                except OSError as error:raise ValueError('physical PID identity unavailable') from error
                else:raise ValueError('physical PID identity unavailable')
            if current is not None:
                current_birth=current.get('birth')
                # Only the explicitly authenticated reboot route may distinguish
                # an old descendant from a foreign process reusing its PID. Main
                # process presence and ordinary same-boot proof remain strict.
                if (reconciliation is None or item.get('role')!='descendant' or
                    not isinstance(current_birth,str) or not current_birth.isascii() or
                    not current_birth.isdecimal() or int(current_birth)==int(birth)):
                    raise ValueError('physical PID still present; no wrapper-exit shortcut')
                reused_descendants.append({'pid':pid,'original_birth':birth,'current_birth':current_birth})
        if not {observation.get('worker_pid'),observation.get('supervisor_proc_pid')}<=seen:raise ValueError('terminal exact worker/supervisor PID set missing')
        evidence={'schema':'managed-runtime-terminal-proof/v1','task_id':task_id,'attempt_id':attempt_id,'request_ref':_digest(request),'status':observation['status'],'exit_code':observation['exit_code'],'quiescence_method':'waitpid_ECHILD','boot_id':proof['boot_id'],'processes':births,'fresh_physical_absence':True,'observed_at_utc':_utc(),'original_claim_revision':request['claim']['store_revision'],'ownership':ownership,'authorizes_release':False}
        if reconciliation is not None:evidence['boot_reconciliation']=reconciliation
        if reused_descendants:evidence['reused_descendant_pids']=reused_descendants
        if include_controller:
            _,current_state=self.store.read()
            current_task=next((row for row in current_state['tasks'] if row['id']==task_id),None)
            if observation['status']=='succeeded':
                result=_read_json(Path(request['journal_directory'])/'result.json')
                if (current_task is None or current_task['status']!='succeeded' or not current_task['integrated'] or
                    not isinstance(result,dict) or current_task['accepted_result_ref']!=_digest(result) or result.get('attempt_id')!=attempt_id):
                    raise ValueError('native owner-final requires actual accepted/integrated pool result')
            return VerifiedTerminalProof(_TERMINAL_PROOF_SEAL,self,lease_store,release_receipt,evidence,
                boot_transition_path=None if boot_transition is None else str(boot_transition._path))
        return evidence

    def rejection(self, task_id, attempt_id):
        return _read_json(self._terminal_hold_directory(task_id, attempt_id) / 'rejected-preparation.json')

    def reject_preparation(self, task_id, attempt_id, *, disposition, lease_store, reconcile=False):
        """Issue the negative artifact, then reconcile only after real release/proof."""
        from managed_executor_store import GitManagedExecutorStore
        from git_lease_store import GitLeaseStore
        if (type(self) is not ManagedExecutorRuntime or type(self.backend) is not LocalCommandBackend
                or type(self.store) is not GitManagedExecutorStore or type(lease_store) is not GitLeaseStore):
            raise ValueError('authentic rejection runtime required')
        if self._task(task_id)['role'] != 'writer':
            raise ValueError('rejection requires writer')
        request = self._request(task_id, attempt_id)
        if request is None:
            raise ValueError('original rejection request missing')
        historical = self.store.read_revision(request['claim']['store_revision'])
        original = next(row for row in historical['tasks'] if row['id'] == task_id)
        if (pool.canonical_state_ref(historical) != request['claim']['state_ref']
                or historical['revision'] != request['claim']['state_revision']
                or original['status'] != 'running' or original['active_attempt_id'] != attempt_id
                or original['reservation_token'] != request['claim']['reservation_token']):
            raise ValueError('rejection original launch claim mismatch')
        directory = Path(request['journal_directory'])
        intent = _read_json(_terminal_hold_paths(directory)['intent'])
        owned = _read_json(_terminal_hold_paths(directory)['owned'])
        descriptor = _read_json(directory / 'terminal-capability-descriptor.json')
        from managed_terminal_capability import _digest as capability_digest, invocation_identity
        if not all(isinstance(value, dict) for value in (intent, owned, descriptor)):
            raise ValueError('original issued rejection ownership missing')
        payload = descriptor.get('payload', {})
        derived = 'managed-terminal:' + capability_digest(invocation_identity(payload)).split(':', 1)[1]
        if (descriptor.get('schema') != 'original-managed-capability-descriptor/v1'
                or payload.get('schema') != 'managed-terminal-capability/v2'
                or any(value.get('capability_ref') != capability_digest(payload) for value in (descriptor, intent, owned))
                or any(value.get('invocation_id') != derived for value in (payload, intent, owned))
                or payload.get('request_ref') != _digest(request) or payload.get('launch_id') != _digest(request)
                or payload.get('managed_store_ref') != self.store.ref or payload.get('managed_store_id') != self.store.store_id
                or any(payload.get(key) != request['identity'][key] for key in ('pool_id', 'task_id', 'attempt_id'))
                or disposition['invocation_id'] != derived or disposition['owner_id'] != owned['owner_id']
                or disposition['generation'] != owned['generation']
                or disposition['reservation_token'] != request['claim']['reservation_token']
                or disposition['runtime_launch_id'] != _digest(request)
                or intent['lease_repository'] != disposition['lease_repository']
                or intent['lease_source_ref'] != disposition['lease_source_ref']):
            raise ValueError('rejection original capability/assignment mismatch')
        original_lease = lease_store.read_revision(owned['lease_revision'])
        if (original_lease['owner_id'] != owned['owner_id'] or original_lease['generation'] != owned['generation']
                or original_lease['invocation']['invocation_id'] != derived):
            raise ValueError('rejection original lease mismatch')
        path = directory / 'rejected-preparation.json'
        artifact = self.rejection(task_id, attempt_id)
        if artifact is not None:
            if artifact.get('disposition') != disposition or artifact.get('request_ref') != _digest(request):
                raise ValueError('conflicting durable rejection')
        else:
            observation = self.observe(task_id, attempt_id)
            if observation.get('status') != 'awaiting_release' or observation.get('pending_terminal_status') != 'succeeded':
                raise ValueError('rejection requires actual successful worker awaiting release')
            revision, state = self.store.read()
            row = next(row for row in state['tasks'] if row['id'] == task_id)
            if row['status'] != 'running' or row['active_attempt_id'] != attempt_id or row['reservation_token'] != request['claim']['reservation_token']:
                raise ValueError('rejection requires original active allocation')
            artifact = {'schema': 'managed-rejected-preparation/v1', 'identity': request['identity'],
                        'claim': request['claim'], 'request_ref': _digest(request), 'launch_id': _digest(request),
                        'disposition': copy.deepcopy(disposition), 'observation': observation}
            _write(path, artifact)
        if not reconcile:
            return artifact
        released = self.reconcile_execution_lease_hold(lease_store, task_id, attempt_id)
        if released['status'] != 'released':
            raise ValueError('rejection reconciliation requires actual release')
        receipt = released['release_marker']['release_receipt']
        historical_release = lease_store.read_revision(receipt['lease_revision'])
        if (historical_release['owner_id'] is not None or historical_release['last_release'] != receipt['release']
                or receipt['release']['owner_id'] != owned['owner_id']
                or receipt['release']['generation'] != owned['generation']
                or receipt['release']['invocation_id'] != derived
                or receipt['release']['checkpoint_ref'] != disposition['checkpoint_ref']):
            raise ValueError('rejection historical release mismatch')
        proof = self.verify_terminal(task_id, attempt_id)
        terminal = self.observe(task_id, attempt_id)
        if proof['status'] != 'succeeded' or terminal['status'] != 'succeeded':
            raise ValueError('rejected worker success changed')
        closure_path = directory / 'rejected-preparation-closure.json'
        closure = _read_json(closure_path)
        if closure is None:
            closure = {'schema': 'managed-rejected-preparation-closure/v1', 'rejection_ref': _digest(artifact),
                       'release_receipt': receipt, 'terminal_observation': terminal, 'physical_proof': proof}
            _write(closure_path, closure)
        if (closure['rejection_ref'] != _digest(artifact) or closure['release_receipt'] != receipt
                or closure['terminal_observation'] != terminal):
            raise ValueError('rejection closure binding changed')
        record = {'attempt_id': attempt_id, 'rejection_ref': _digest(closure),
                  'review_ref': disposition['review_ref'], 'request_ref': _digest(request), 'launch_id': _digest(request),
                  'runtime_seconds': terminal['runtime_seconds'], 'elapsed_seconds': terminal['elapsed_seconds']}
        revision, state = self.store.read()
        updated = pool.reject_preparation(self.plan, state, task_id, attempt_id,
                    reservation_token=request['claim']['reservation_token'], rejection=record, expected_revision=state['revision'])
        if updated != state:
            self.store.compare_and_swap(revision, updated)
        return record

    def accept(self, task_id, attempt_id, *, result_commit, output_refs, evidence_refs, cost_units=0):
        if self.rejection(task_id, attempt_id) is not None:
            raise ValueError('rejected preparation cannot be accepted')
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

    def evaluate_parent(self, continuity_state, *, now_utc=None, reporting_authority=None):
        """Read fresh pool state and combine it with the real continuity evaluator."""
        if continuity_state.get("invocation_id") != self.plan["parent_invocation_id"]:
            raise ValueError("parent invocation identity mismatch")
        revision, state = self.store.read()
        assessment = pool.assess(self.plan, state)
        continuity = execution_continuity.evaluate(continuity_state, now_utc=now_utc, reporting_authority=reporting_authority)
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
