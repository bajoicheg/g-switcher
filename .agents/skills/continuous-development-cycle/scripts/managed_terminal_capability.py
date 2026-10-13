#!/usr/bin/env python3
"""Non-serializable managed terminal-lifecycle capability for execution-lease/v2 admission."""
from __future__ import annotations
import copy,hashlib,json
from datetime import datetime,timezone

_SEAL=object()

def _digest(value):
    return "sha256:"+hashlib.sha256(
        json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    ).hexdigest()

def _utc(value,name):
    if not isinstance(value,str) or not value.endswith("Z"):
        raise ValueError(name+" must be UTC Z timestamp")
    try:return datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc:raise ValueError(name+" invalid") from exc

class _VerifiedManagedTerminalCapability:
    def __init__(self,seal,runtime,payload):
        if seal is not _SEAL:raise ValueError("managed terminal capability cannot be caller-constructed")
        self._seal=seal;self._runtime=runtime;self._payload=copy.deepcopy(payload)

    @property
    def payload(self):
        return copy.deepcopy(self._payload)

    def invocation(self):
        p=self._payload
        return {"invocation_id":p["invocation_id"],"automation_id":None,"conversation_id":None,
                "execution_surface":"managed","started_at_utc":p["started_at_utc"]}

    def revalidate(self,at):
        _utc(at,"acquisition time")
        p=self._payload
        runtime=self._runtime
        historical=runtime.store.read_revision(p["managed_store_revision"])
        if historical.get("revision")!=p["managed_state_revision"]:
            raise ValueError("managed terminal capability state revision mismatch")
        if historical.get("pool_id")!=p["pool_id"] or historical.get("coordination_ref")!=p["managed_store_ref"] or historical.get("coordination_store_id")!=p["managed_store_id"]:
            raise ValueError("managed terminal capability coordination binding mismatch")
        task=next((row for row in historical["tasks"] if row["id"]==p["task_id"]),None)
        if task is None or task["status"]!="running" or task["active_attempt_id"]!=p["attempt_id"]:
            raise ValueError("managed terminal capability does not bind a durable running attempt")
        request=runtime._request(p["task_id"],p["attempt_id"])
        if request is None or _digest(request)!=p["request_ref"]:
            raise ValueError("managed terminal capability request binding mismatch")
        observation=runtime.observe(p["task_id"],p["attempt_id"])
        if observation.get("status") not in {"starting","running","awaiting_release"} or observation.get("quiescent") is not False:
            raise ValueError("managed terminal capability requires a live nonterminal supervisor")
        if observation.get("launch_id")!=p["launch_id"] or observation.get("request_ref")!=p["request_ref"]:
            raise ValueError("managed terminal capability live launch binding mismatch")
        if _utc(p["observed_at_utc"],"capability observation")>_utc(at,"acquisition time"):
            raise ValueError("managed terminal capability observation is from the future")
        return copy.deepcopy(p)

def issue(runtime,task_id,attempt_id,*,lease_repository,lease_source_ref,observed_at_utc=None):
    # Exact package runtime type: a generic object implementing the same method names is not capability evidence.
    from managed_executor_runtime import ManagedExecutorRuntime,LocalCommandBackend,ExecutionJournal
    from managed_executor_store import GitManagedExecutorStore
    if (type(runtime) is not ManagedExecutorRuntime or type(runtime.store) is not GitManagedExecutorStore
            or type(runtime.backend) is not LocalCommandBackend or type(runtime.journal) is not ExecutionJournal):
        raise ValueError("managed terminal capability requires exact package-owned managed runtime/store/backend/journal")
    if not isinstance(lease_repository,str) or not lease_repository.strip():
        raise ValueError("lease_repository invalid")
    if not isinstance(lease_source_ref,str) or not lease_source_ref.startswith("refs/heads/"):
        raise ValueError("lease_source_ref invalid")
    request=runtime._request(task_id,attempt_id)
    if request is None:
        raise ValueError("managed attempt has no package-owned launch request")
    observation=runtime.observe(task_id,attempt_id)
    if observation.get("status") not in {"starting","running"} or observation.get("quiescent") is not False:
        raise ValueError("managed attempt is not live")
    revision,state=runtime.store.read()
    if revision is None or state is None:
        raise ValueError("managed pool state unavailable")
    task=next((row for row in state["tasks"] if row["id"]==task_id),None)
    if task is None or task["status"]!="running" or task["active_attempt_id"]!=attempt_id:
        raise ValueError("managed pool does not bind the live attempt")
    request_ref=_digest(request)
    if observation.get("request_ref")!=request_ref or not isinstance(observation.get("launch_id"),str):
        raise ValueError("managed runtime observation does not bind launch request")
    observed_at=observed_at_utc or observation.get("created_at_utc")
    _utc(observed_at,"capability observation")
    identity={"pool_id":state["pool_id"],"task_id":task_id,"attempt_id":attempt_id,
              "launch_id":observation["launch_id"],"managed_store_revision":revision,
              "lease_repository":lease_repository,"lease_source_ref":lease_source_ref}
    invocation_id="managed-terminal:"+_digest(identity).split(":",1)[1]
    payload={"schema":"managed-terminal-capability/v1","invocation_id":invocation_id,
             "execution_surface":"managed","managed_store_ref":runtime.store.ref,
             "managed_store_id":runtime.store.store_id,"managed_store_revision":revision,
             "managed_state_revision":state["revision"],"pool_id":state["pool_id"],
             "task_id":task_id,"attempt_id":attempt_id,"request_ref":request_ref,
             "launch_id":observation["launch_id"],"lease_repository":lease_repository,
             "lease_source_ref":lease_source_ref,"observed_at_utc":observed_at,
             "started_at_utc":observation.get("created_at_utc") or observed_at}
    return _VerifiedManagedTerminalCapability(_SEAL,runtime,payload)

def reference(value):
    if type(value) is not _VerifiedManagedTerminalCapability or value._seal is not _SEAL:
        raise ValueError("managed terminal capability reference requires verified capability")
    return _digest(value.payload)

def validate_verified(value,invocation,repository,source_ref,at):
    if type(value) is not _VerifiedManagedTerminalCapability or value._seal is not _SEAL:
        raise ValueError("independent managed terminal capability proof required")
    payload=value.revalidate(at)
    if payload["lease_repository"]!=repository or payload["lease_source_ref"]!=source_ref:
        raise ValueError("managed terminal capability lease binding mismatch")
    if invocation!=value.invocation():
        raise ValueError("managed terminal capability invocation mismatch")
    return payload
