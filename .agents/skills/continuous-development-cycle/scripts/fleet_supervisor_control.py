#!/usr/bin/env python3
"""Generation-fenced single-leader Fleet Supervisor state and one-shot side-effect claims."""
from __future__ import annotations
import copy,hashlib,json,re
from datetime import datetime, timedelta
import execution_lease_v2 as leasev2

SCHEMA="fleet-supervisor-state/v1"
EFFECT_SCHEMA="fleet-side-effect/v1"
KINDS={"fleet_write","project_wake","scheduler_repair","continuation_enqueue"}
EFFECT_STATES={"claimed","submitted","unknown","terminal"}
SHA=re.compile(r"^[0-9a-f]{40}$")
DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")

def _time(v,n):
    if not isinstance(v,str) or not v.endswith("Z"):raise ValueError(n+" must be UTC Z timestamp")
    try:return datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError as e:raise ValueError(n+" invalid timestamp") from e

def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(n+" invalid")

def _digest(v):
    raw=json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def initialize(fleet_repository,fleet_ref):
    _text(fleet_repository,"fleet_repository")
    if not isinstance(fleet_ref,str) or not fleet_ref.startswith("refs/heads/"):raise ValueError("fleet_ref invalid")
    return {"schema":SCHEMA,"fleet_repository":fleet_repository,"fleet_ref":fleet_ref,
            "lease":leasev2.initialize(fleet_repository,fleet_ref),"effects":[]}

def validate_effect(e):
    fields={"schema","effect_id","kind","target","intent_digest","owner_id","generation","invocation_id",
            "observed_fleet_head","state","claimed_at_utc","receipt_ref","outcome"}
    if not isinstance(e,dict) or set(e)!=fields or e.get("schema")!=EFFECT_SCHEMA:raise ValueError("fleet effect invalid")
    for n in ("target","owner_id","invocation_id"):_text(e[n],n)
    if not isinstance(e["effect_id"],str) or not DIGEST.fullmatch(e["effect_id"]):raise ValueError("effect_id must be sha256")
    if not isinstance(e["intent_digest"],str) or not DIGEST.fullmatch(e["intent_digest"]):raise ValueError("intent_digest must be sha256")
    if e["kind"] not in KINDS:raise ValueError("effect kind invalid")
    if e["state"] not in EFFECT_STATES:raise ValueError("effect state invalid")
    if type(e["generation"]) is not int or e["generation"]<1:raise ValueError("effect generation invalid")
    if not SHA.fullmatch(e["observed_fleet_head"]):raise ValueError("effect observed fleet head invalid")
    _time(e["claimed_at_utc"],"effect claimed_at_utc")
    if e["receipt_ref"] is not None:_text(e["receipt_ref"],"receipt_ref")
    if e["outcome"] is not None:_text(e["outcome"],"outcome")
    if e["state"]=="claimed" and (e["receipt_ref"] is not None or e["outcome"] is not None):raise ValueError("claimed effect cannot have receipt/outcome")
    if e["state"]=="submitted" and e["receipt_ref"] is None:raise ValueError("submitted effect requires receipt")
    if e["state"]=="unknown" and e["receipt_ref"] is None:raise ValueError("unknown effect requires attempted-effect receipt")
    if e["state"]=="terminal" and (e["receipt_ref"] is None or e["outcome"] is None):raise ValueError("terminal effect requires receipt/outcome")
    return e

def validate(state):
    if not isinstance(state,dict) or set(state)!={"schema","fleet_repository","fleet_ref","lease","effects"} or state.get("schema")!=SCHEMA:
        raise ValueError("fleet supervisor state invalid")
    _text(state["fleet_repository"],"fleet_repository")
    if not isinstance(state["fleet_ref"],str) or not state["fleet_ref"].startswith("refs/heads/"):raise ValueError("fleet_ref invalid")
    leasev2.validate(state["lease"])
    if state["lease"]["repository"]!=state["fleet_repository"] or state["lease"]["source_ref"]!=state["fleet_ref"]:
        raise ValueError("fleet leader lease binding mismatch")
    if not isinstance(state["effects"],list):raise ValueError("effects invalid")
    ids=set()
    for e in state["effects"]:
        validate_effect(e)
        if e["effect_id"] in ids:raise ValueError("duplicate fleet effect id")
        ids.add(e["effect_id"])
    return state

def _leader(state,owner_id,generation,invocation_id,at,freshness_seconds=600):
    validate(state);lease=state["lease"]
    if lease["owner_id"]!=owner_id or lease["generation"]!=generation:raise ValueError("not fleet leader")
    if lease["invocation"] is None or lease["invocation"]["invocation_id"]!=invocation_id:raise ValueError("fleet leader invocation mismatch")
    if lease["finalization"]["state"]!="active":raise ValueError("fleet leader not active")
    now=_time(at,"at");heartbeat=_time(lease["heartbeat_at_utc"],"heartbeat");expiry=_time(lease["expires_at_utc"],"expiry")
    if now>=expiry or (now-heartbeat).total_seconds()>=freshness_seconds:raise ValueError("fleet leader lease not fresh")
    return lease

def leader_binding(state,owner_id,generation,invocation_id,at,observed_fleet_head):
    _leader(state,owner_id,generation,invocation_id,at)
    if not isinstance(observed_fleet_head,str) or not SHA.fullmatch(observed_fleet_head):
        raise ValueError("observed fleet head invalid")
    return {"schema":"fleet-leader-binding/v1","fleet_repository":state["fleet_repository"],"fleet_ref":state["fleet_ref"],
            "owner_id":owner_id,"generation":generation,"invocation_id":invocation_id,
            "observed_fleet_head":observed_fleet_head}

def _unresolved_effects(state,generation):
    return [e for e in state["effects"] if e["generation"]==generation and e["state"]!="terminal"]

def acquire_record(state,owner_id,at,invocation,*,terminal_capability,ttl=1200,quiescence=None):
    validate(state);old=state["lease"]
    if old["owner_id"] is not None and _unresolved_effects(state,old["generation"]):
        raise ValueError("prior fleet leader has unresolved side effects")
    result=copy.deepcopy(state)
    result["lease"]=leasev2.acquire(old,owner_id,at,invocation=invocation,terminal_capability=terminal_capability,ttl=ttl,quiescence=quiescence)
    return validate(result)

def acquire_cas(store,expected_revision,fleet_repository,fleet_ref,owner_id,at,invocation,*,terminal_capability,ttl=1200,quiescence=None):
    revision,state=store.read()
    if revision!=expected_revision:raise ValueError("stale fleet supervisor revision")
    if state is None:state=initialize(fleet_repository,fleet_ref)
    validate(state)
    if state["fleet_repository"]!=fleet_repository or state["fleet_ref"]!=fleet_ref:raise ValueError("fleet supervisor endpoint binding mismatch")
    result=acquire_record(state,owner_id,at,invocation,terminal_capability=terminal_capability,ttl=ttl,quiescence=quiescence)
    new_revision=store.compare_and_swap(expected_revision,result)
    return {"revision":new_revision,"state":result,"owner_id":owner_id,"generation":result["lease"]["generation"]}

def claim_effect_record(state,owner_id,generation,invocation_id,at,live_fleet_head,request):
    _leader(state,owner_id,generation,invocation_id,at)
    if not SHA.fullmatch(live_fleet_head):raise ValueError("live fleet head invalid")
    fields={"kind","target","observed_fleet_head","intent"}
    if not isinstance(request,dict) or set(request)!=fields:raise ValueError("effect request invalid")
    _text(request["target"],"target")
    if request["kind"] not in KINDS:raise ValueError("effect kind invalid")
    if not SHA.fullmatch(request["observed_fleet_head"]):raise ValueError("request fleet head invalid")
    canonical_effect={"kind":request["kind"],"target":request["target"],"observed_fleet_head":request["observed_fleet_head"],"intent":request["intent"]}
    effect_id=_digest(canonical_effect)
    intent_digest=_digest(request["intent"])
    for e in state["effects"]:
        if e["effect_id"]==effect_id:
            if e["intent_digest"]!=intent_digest:raise ValueError("derived fleet effect identity collision")
            return copy.deepcopy(state),{"action":"OBSERVE_EXISTING","authorizes_effect":False,"effect":copy.deepcopy(e)}
    pending=[e for e in state["effects"]
             if e["state"]!="terminal" and e["kind"]==request["kind"] and e["target"]==request["target"]]
    if pending:
        return copy.deepcopy(state),{"action":"OBSERVE_PENDING_CONFLICT","authorizes_effect":False,
                                     "effect":copy.deepcopy(pending[0])}
    if request["observed_fleet_head"]!=live_fleet_head:
        return copy.deepcopy(state),{"action":"REPLAN_FLEET_HEAD","authorizes_effect":False,"effect":None}
    result=copy.deepcopy(state)
    effect={"schema":EFFECT_SCHEMA,"effect_id":effect_id,"kind":request["kind"],"target":request["target"],
            "intent_digest":intent_digest,"owner_id":owner_id,"generation":generation,"invocation_id":invocation_id,
            "observed_fleet_head":live_fleet_head,"state":"claimed","claimed_at_utc":at,"receipt_ref":None,"outcome":None}
    result["effects"].append(effect);validate(result)
    return result,{"action":"SUBMIT_ONCE","authorizes_effect":True,"effect":copy.deepcopy(effect)}

def claim_effect_cas(store,expected_revision,owner_id,generation,invocation_id,at,live_fleet_head,request):
    revision,state=store.read()
    if revision!=expected_revision or state is None:raise ValueError("stale fleet supervisor revision")
    result,decision=claim_effect_record(state,owner_id,generation,invocation_id,at,live_fleet_head,request)
    if decision["action"]!="SUBMIT_ONCE":return {"revision":revision,"state":state,**decision}
    new_revision=store.compare_and_swap(expected_revision,result)
    return {"revision":new_revision,"state":result,**decision}

def update_effect_record(state,owner_id,generation,invocation_id,at,effect_id,new_state,receipt_ref,outcome=None):
    _leader(state,owner_id,generation,invocation_id,at)
    if new_state not in {"submitted","unknown","terminal"}:raise ValueError("effect transition invalid")
    result=copy.deepcopy(state);match=None
    for e in result["effects"]:
        if e["effect_id"]==effect_id:match=e;break
    if match is None:raise ValueError("effect not found")
    if match["owner_id"]!=owner_id or match["generation"]!=generation or match["invocation_id"]!=invocation_id:
        raise ValueError("effect not owned by exact leader")
    if match["state"]=="terminal":raise ValueError("terminal effect immutable")
    _text(receipt_ref,"receipt_ref")
    if new_state=="terminal":_text(outcome,"outcome")
    elif outcome is not None:raise ValueError("nonterminal effect cannot have outcome")
    match["state"]=new_state;match["receipt_ref"]=receipt_ref;match["outcome"]=outcome
    validate(result);return result

def validate_effect_observation(o):
    fields={"schema","effect_id","intent_digest","lookup_complete","observed_at_utc","state","receipt_ref","outcome","evidence_ref"}
    if not isinstance(o,dict) or set(o)!=fields or o.get("schema")!="fleet-effect-observation/v1":raise ValueError("effect observation invalid")
    _text(o["evidence_ref"],"evidence_ref")
    if not isinstance(o["effect_id"],str) or not DIGEST.fullmatch(o["effect_id"]):raise ValueError("effect observation id invalid")
    if not isinstance(o["intent_digest"],str) or not DIGEST.fullmatch(o["intent_digest"]):raise ValueError("effect observation intent digest invalid")
    if type(o["lookup_complete"]) is not bool:raise ValueError("effect lookup_complete invalid")
    _time(o["observed_at_utc"],"effect observation time")
    if o["state"] not in {"running","terminal","not_found","unknown"}:raise ValueError("effect observation state invalid")
    if o["receipt_ref"] is not None:_text(o["receipt_ref"],"effect observation receipt_ref")
    if o["outcome"] is not None:_text(o["outcome"],"effect observation outcome")
    if o["state"]=="running" and o["receipt_ref"] is None:raise ValueError("running observation requires receipt")
    if o["state"]=="terminal" and (o["receipt_ref"] is None or o["outcome"] is None):raise ValueError("terminal observation requires receipt/outcome")
    if o["state"]=="not_found" and (not o["lookup_complete"] or o["receipt_ref"] is not None or o["outcome"] is not None):
        raise ValueError("not_found requires complete lookup with no receipt/outcome")
    return o

def reconcile_effect_record(state,effect_id,observation):
    """Evidence-only reconciliation for an effect owned by a stopped/absent leader.

    This function can never create or replay an effect. It only records an
    authoritative provider observation against the original durable effect ID
    and intent digest so a standby can eventually distinguish pending work from
    terminal/no-effect state before leader replacement.
    """
    validate(state);validate_effect_observation(observation)
    if observation["effect_id"]!=effect_id:raise ValueError("effect observation id mismatch")
    result=copy.deepcopy(state);match=None
    for e in result["effects"]:
        if e["effect_id"]==effect_id:match=e;break
    if match is None:raise ValueError("effect not found")
    if match["intent_digest"]!=observation["intent_digest"]:raise ValueError("effect observation intent mismatch")
    decision={"schema":"fleet-effect-reconciliation-result/v1","authorizes_effect":False,"authorizes_takeover":False,
              "effect_id":effect_id,"evidence_ref":observation["evidence_ref"]}
    state_name=observation["state"]
    if not observation["lookup_complete"] or state_name=="unknown":
        return copy.deepcopy(state),{**decision,"action":"OBSERVE_AGAIN","resolved":False}
    if state_name=="running":
        if match["state"]=="terminal":raise ValueError("terminal effect immutable")
        match["state"]="submitted";match["receipt_ref"]=observation["receipt_ref"];match["outcome"]=None
        validate(result)
        return result,{**decision,"action":"WAIT_EFFECT","resolved":False}
    if match["state"]=="terminal":
        expected_receipt=match["receipt_ref"]
        expected_outcome=match["outcome"]
        observed_receipt=observation["receipt_ref"] if state_name=="terminal" else expected_receipt
        observed_outcome=observation["outcome"] if state_name=="terminal" else expected_outcome
        if observed_receipt!=expected_receipt or observed_outcome!=expected_outcome:
            raise ValueError("terminal effect observation conflict")
        return copy.deepcopy(state),{**decision,"action":"TERMINAL_CONFIRMED","resolved":True}
    if state_name=="terminal":
        match["state"]="terminal";match["receipt_ref"]=observation["receipt_ref"];match["outcome"]=observation["outcome"]
    elif state_name=="not_found":
        match["state"]="terminal";match["receipt_ref"]="observation:"+observation["evidence_ref"];match["outcome"]="not_submitted_observed"
    validate(result)
    return result,{**decision,"action":"TERMINAL_RECONCILED","resolved":True}

def reconcile_effect_cas(store,expected_revision,effect_id,observation):
    revision,state=store.read()
    if revision!=expected_revision or state is None:raise ValueError("stale fleet supervisor revision")
    result,decision=reconcile_effect_record(state,effect_id,observation)
    if result==state:return {"revision":revision,"state":state,**decision}
    new_revision=store.compare_and_swap(expected_revision,result)
    return {"revision":new_revision,"state":result,**decision}

def update_effect_cas(store,expected_revision,owner_id,generation,invocation_id,at,effect_id,new_state,receipt_ref,outcome=None):
    revision,state=store.read()
    if revision!=expected_revision or state is None:raise ValueError("stale fleet supervisor revision")
    result=update_effect_record(state,owner_id,generation,invocation_id,at,effect_id,new_state,receipt_ref,outcome)
    new_revision=store.compare_and_swap(expected_revision,result)
    return {"revision":new_revision,"state":result,"effect":next(copy.deepcopy(e) for e in result["effects"] if e["effect_id"]==effect_id)}

def _mutate_leader_lease_cas(store,expected_revision,owner_id,generation,invocation_id,action,*,
                             at,checkpoint_ref=None,pending_shared_writes=None,
                             external_reconciliation=None,continuity_state=None):
    revision,state=store.read()
    if revision!=expected_revision or state is None:raise ValueError("stale fleet supervisor revision")
    validate(state)
    if state["lease"]["owner_id"]!=owner_id or state["lease"]["generation"]!=generation:
        raise ValueError("not fleet leader")
    result=copy.deepcopy(state)
    if action=="begin":
        result["lease"]=leasev2.begin_finalization(
            state["lease"],owner_id,generation,invocation_id,at,
            pending_shared_writes=pending_shared_writes)
    elif action=="checkpoint":
        result["lease"]=leasev2.record_checkpoint(
            state["lease"],owner_id,generation,invocation_id,at,
            checkpoint_ref=checkpoint_ref,pending_shared_writes=pending_shared_writes)
    elif action=="reconcile":
        pending=_unresolved_effects(state,generation)
        if pending:raise ValueError("Fleet leader finalization has unresolved side effects")
        result["lease"]=leasev2.reconcile_finalization(
            state["lease"],owner_id,generation,invocation_id,at,
            external_reconciliation=external_reconciliation)
    elif action=="ready":
        if _unresolved_effects(state,generation):raise ValueError("Fleet leader finalization has unresolved side effects")
        result["lease"]=leasev2.mark_ready(
            state["lease"],owner_id,generation,invocation_id,at,
            continuity_state=continuity_state)
    else:raise ValueError("unsupported Fleet leader finalization action")
    validate(result)
    new_revision=store.compare_and_swap(expected_revision,result)
    return {"revision":new_revision,"state":result}

def begin_finalization_cas(store,expected_revision,owner_id,generation,invocation_id,at,*,pending_shared_writes=False):
    return _mutate_leader_lease_cas(
        store,expected_revision,owner_id,generation,invocation_id,"begin",
        at=at,pending_shared_writes=pending_shared_writes)

def record_checkpoint_cas(store,expected_revision,owner_id,generation,invocation_id,at,*,checkpoint_ref):
    return _mutate_leader_lease_cas(
        store,expected_revision,owner_id,generation,invocation_id,"checkpoint",
        at=at,checkpoint_ref=checkpoint_ref,pending_shared_writes=False)

def reconcile_finalization_cas(store,expected_revision,owner_id,generation,invocation_id,at,*,external_reconciliation="none"):
    return _mutate_leader_lease_cas(
        store,expected_revision,owner_id,generation,invocation_id,"reconcile",
        at=at,external_reconciliation=external_reconciliation)

def mark_ready_cas(store,expected_revision,owner_id,generation,invocation_id,at,*,continuity_state):
    return _mutate_leader_lease_cas(
        store,expected_revision,owner_id,generation,invocation_id,"ready",
        at=at,continuity_state=continuity_state)

def release_leader_cas(store,expected_revision,owner_id,generation,invocation_id,at):
    revision,state=store.read()
    if revision!=expected_revision or state is None:raise ValueError("stale fleet supervisor revision")
    validate(state)
    if _unresolved_effects(state,generation):raise ValueError("Fleet leader release has unresolved side effects")
    result=copy.deepcopy(state)
    result["lease"]=leasev2.release(state["lease"],owner_id,generation,invocation_id,at)
    validate(result)
    new_revision=store.compare_and_swap(expected_revision,result)
    return {
        "revision":new_revision,
        "state":result,
        "release_receipt":{
            "schema":"execution-release-receipt/v1",
            "lease_revision":new_revision,
            "release":copy.deepcopy(result["lease"]["last_release"]),
        },
    }

def assess_takeover(state):
    validate(state);lease=state["lease"]
    if lease["owner_id"] is None:return {"action":"ACQUIRE_FREE","pending_effects":[],"authorizes_takeover":False}
    pending=_unresolved_effects(state,lease["generation"])
    if pending:return {"action":"BLOCK_PENDING_EFFECTS","pending_effects":[e["effect_id"] for e in pending],"authorizes_takeover":False}
    return {"action":"REQUIRE_EXECUTOR_STOPPED_EVIDENCE","pending_effects":[],"authorizes_takeover":False}
