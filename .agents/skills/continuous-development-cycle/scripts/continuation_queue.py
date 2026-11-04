#!/usr/bin/env python3
"""CDC 2.5 durable continuation-event queue; event delivery is not execution authority."""
from __future__ import annotations
from datetime import datetime,timedelta
import copy,hashlib,json,re
EVENT_TYPES={"external_terminal","ci_terminal","backend_available","scheduler_recovered","policy_changed","manual_kick"};ITEM_STATES={"pending","claimed","acked"}
SHA=re.compile(r"^[0-9a-f]{40}$");OPKEY=re.compile(r"^sha256:[0-9a-f]{64}$")
def _text(v,n,nullable=False):
    if v is None and nullable:return
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be nonempty text")
def _time(v,n):
    if not isinstance(v,str) or not v.endswith("Z"):raise ValueError(f"{n} must be UTC Z timestamp")
    try:return datetime.fromisoformat(v[:-1]+"+00:00")
    except ValueError as e:raise ValueError(f"{n} invalid timestamp") from e
def _canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def dedupe_key(e):return "sha256:"+hashlib.sha256(_canonical({k:e[k] for k in e if k!="dedupe_key"})).hexdigest()
def validate_event(e):
    f={"schema","event_id","event_type","repository","source_ref","candidate_sha","operation_key","task_id","observed_at_utc","source","evidence_refs","dedupe_key"}
    if not isinstance(e,dict) or set(e)!=f or e["schema"]!="continuation-event/v1":raise ValueError("invalid continuation event")
    _text(e["event_id"],"event_id");_text(e["repository"],"repository");_text(e["source_ref"],"source_ref");_text(e["source"],"source")
    if not e["source_ref"].startswith("refs/heads/") or e["event_type"] not in EVENT_TYPES:raise ValueError("event binding/type invalid")
    if e["candidate_sha"] is not None and not SHA.fullmatch(e["candidate_sha"]):raise ValueError("candidate_sha invalid")
    if e["operation_key"] is not None and not OPKEY.fullmatch(e["operation_key"]):raise ValueError("operation_key invalid")
    _text(e["task_id"],"task_id",True);_time(e["observed_at_utc"],"observed_at_utc")
    if not isinstance(e["evidence_refs"],list) or any(not isinstance(x,str) or not x.strip() for x in e["evidence_refs"]):raise ValueError("evidence_refs invalid")
    if len(set(e["evidence_refs"]))!=len(e["evidence_refs"]):raise ValueError("duplicate evidence refs")
    if e["event_type"] in {"external_terminal","ci_terminal"} and (e["candidate_sha"] is None or e["task_id"] is None or not e["evidence_refs"]):raise ValueError("terminal event requires candidate/task/evidence")
    if e["event_type"]=="external_terminal" and e["operation_key"] is None:raise ValueError("external_terminal requires operation_key")
    if e["dedupe_key"]!=dedupe_key(e):raise ValueError("dedupe_key mismatch")
    return e
def initialize(repository,source_ref):
    _text(repository,"repository");_text(source_ref,"source_ref")
    if not source_ref.startswith("refs/heads/"):raise ValueError("source_ref invalid")
    return {"schema":"continuation-queue/v1","repository":repository,"source_ref":source_ref,"generation":0,"items":[]}
def validate_queue(q):
    if not isinstance(q,dict) or set(q)!={"schema","repository","source_ref","generation","items"} or q["schema"]!="continuation-queue/v1":raise ValueError("invalid continuation queue")
    _text(q["repository"],"repository");_text(q["source_ref"],"source_ref")
    if type(q["generation"]) is not int or q["generation"]<0 or not isinstance(q["items"],list):raise ValueError("queue generation/items invalid")
    ids=set();keys=set()
    for i in q["items"]:
        if not isinstance(i,dict) or set(i)!={"event","state","claim","ack"}:raise ValueError("queue item invalid")
        validate_event(i["event"]);eid=i["event"]["event_id"];key=i["event"]["dedupe_key"]
        if eid in ids or key in keys:raise ValueError("duplicate event/dedupe key")
        ids.add(eid);keys.add(key)
        if i["state"] not in ITEM_STATES:raise ValueError("item state invalid")
        if i["state"]=="pending" and (i["claim"] is not None or i["ack"] is not None):raise ValueError("pending item cannot have claim/ack")
        if i["state"]=="claimed":
            if not isinstance(i["claim"],dict) or set(i["claim"])!={"invocation_id","claimed_at_utc","expires_at_utc"} or i["ack"] is not None:raise ValueError("claimed item invalid")
            _text(i["claim"]["invocation_id"],"claim.invocation_id");_time(i["claim"]["claimed_at_utc"],"claimed_at_utc");_time(i["claim"]["expires_at_utc"],"expires_at_utc")
        if i["state"]=="acked":
            if i["claim"] is None or not isinstance(i["ack"],dict) or set(i["ack"])!={"invocation_id","acked_at_utc","outcome_ref"}:raise ValueError("acked item invalid")
            _text(i["ack"]["invocation_id"],"ack.invocation_id");_time(i["ack"]["acked_at_utc"],"acked_at_utc");_text(i["ack"]["outcome_ref"],"outcome_ref")
    return q
def ingest(q,e):
    validate_queue(q);validate_event(e)
    if e["repository"]!=q["repository"] or e["source_ref"]!=q["source_ref"]:raise ValueError("event binding mismatch")
    for i in q["items"]:
        if i["event"]["dedupe_key"]==e["dedupe_key"]:
            if i["event"]!=e:raise ValueError("dedupe collision with differing event")
            return copy.deepcopy(q),{"inserted":False,"reason":"duplicate","event_id":e["event_id"],"wake_required":False,"authorizes_side_effects":False}
    r=copy.deepcopy(q);r["generation"]+=1;r["items"].append({"event":copy.deepcopy(e),"state":"pending","claim":None,"ack":None});return validate_queue(r),{"inserted":True,"reason":"new_event","event_id":e["event_id"],"wake_required":True,"authorizes_side_effects":False}
def claim_next(q,invocation_id,at,ttl_seconds=900):
    validate_queue(q);_text(invocation_id,"invocation_id");now=_time(at,"at")
    if type(ttl_seconds) is not int or ttl_seconds<=0:raise ValueError("ttl_seconds invalid")
    r=copy.deepcopy(q)
    for i in r["items"]:
        if i["state"]=="claimed" and _time(i["claim"]["expires_at_utc"],"expires")<=now:i.update(state="pending",claim=None,ack=None)
    pending=[i for i in r["items"] if i["state"]=="pending"]
    if not pending:return validate_queue(r),None
    pending.sort(key=lambda i:(i["event"]["observed_at_utc"],i["event"]["event_id"]));i=pending[0];expires=(now+timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00","Z")
    i["state"]="claimed";i["claim"]={"invocation_id":invocation_id,"claimed_at_utc":at,"expires_at_utc":expires};r["generation"]+=1;return validate_queue(r),copy.deepcopy(i["event"])
def ack(q,event_id,invocation_id,at,outcome_ref):
    validate_queue(q);_text(event_id,"event_id");_text(invocation_id,"invocation_id");_time(at,"at");_text(outcome_ref,"outcome_ref");r=copy.deepcopy(q)
    for i in r["items"]:
        if i["event"]["event_id"]==event_id:
            if i["state"]!="claimed" or i["claim"]["invocation_id"]!=invocation_id:raise ValueError("ack requires exact claiming invocation")
            i["state"]="acked";i["ack"]={"invocation_id":invocation_id,"acked_at_utc":at,"outcome_ref":outcome_ref};r["generation"]+=1;return validate_queue(r)
    raise ValueError("event not found")
