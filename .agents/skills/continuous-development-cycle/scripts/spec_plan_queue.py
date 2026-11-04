#!/usr/bin/env python3
"""CDC 2.10.1 specification → plan → continuation mapping."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

SCHEMA="spec-plan-queue/v1"
STATES={"pending","in_progress","complete","blocked"}
QUEUE_STATES={"queued","claimed"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")
def _refs(v,n,allow_empty=False):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v): raise ValueError(f"{n} invalid")
    if not allow_empty and not v: raise ValueError(f"{n} must not be empty")
    if len(v)!=len(set(v)): raise ValueError(f"{n} contains duplicates")

def _assert_acyclic(tasks):
    graph={t["id"]:t["dependencies"] for t in tasks}
    visiting=set();done=set()
    def visit(node):
        if node in done:return
        if node in visiting:raise ValueError("cyclic task dependency")
        visiting.add(node)
        for dep in graph[node]:visit(dep)
        visiting.remove(node);done.add(node)
    for node in graph:visit(node)

def validate(data):
    fields={"schema","change_id","material_change","ambiguity_state","brainstorming_ref",
            "approved_spec_ref","plan_ref","tasks","continuation_queue"}
    if not isinstance(data,dict) or set(data)!=fields or data.get("schema")!=SCHEMA:
        raise ValueError("spec-plan queue fields/schema mismatch")
    _text(data["change_id"],"change_id")
    if type(data["material_change"]) is not bool: raise ValueError("material_change must be boolean")
    if data["ambiguity_state"] not in {"clear","ambiguous"}: raise ValueError("ambiguity_state invalid")
    if data["brainstorming_ref"] is not None: _text(data["brainstorming_ref"],"brainstorming_ref")
    _text(data["approved_spec_ref"],"approved_spec_ref");_text(data["plan_ref"],"plan_ref")
    if not isinstance(data["tasks"],list) or not data["tasks"]: raise ValueError("tasks required")
    ids=[]
    for i,t in enumerate(data["tasks"]):
        if not isinstance(t,dict) or set(t)!={"id","spec_refs","expected_evidence","dependencies","state","evidence_refs"}:
            raise ValueError("task fields mismatch")
        _text(t["id"],f"task[{i}].id");_refs(t["spec_refs"],f"task[{i}].spec_refs");_refs(t["expected_evidence"],f"task[{i}].expected_evidence")
        _refs(t["dependencies"],f"task[{i}].dependencies",allow_empty=True);_refs(t["evidence_refs"],f"task[{i}].evidence_refs",allow_empty=True)
        if t["state"] not in STATES: raise ValueError("task state invalid")
        ids.append(t["id"])
    if len(ids)!=len(set(ids)): raise ValueError("duplicate task id")
    known=set(ids)
    for t in data["tasks"]:
        if t["id"] in t["dependencies"] or not set(t["dependencies"])<=known: raise ValueError("invalid task dependency")
    _assert_acyclic(data["tasks"])
    if not isinstance(data["continuation_queue"],list): raise ValueError("continuation_queue must be list")
    qids=[]
    for i,q in enumerate(data["continuation_queue"]):
        if not isinstance(q,dict) or set(q)!={"task_id","action","state"}: raise ValueError("queue item fields mismatch")
        if q["task_id"] not in known: raise ValueError("queue references unknown task")
        _text(q["action"],f"queue[{i}].action")
        if q["state"] not in QUEUE_STATES: raise ValueError("queue state invalid")
        qids.append(q["task_id"])
    if len(qids)!=len(set(qids)): raise ValueError("duplicate continuation task")
    return data

def evaluate(data):
    validate(data);blockers=[]
    if data["ambiguity_state"]=="ambiguous" and data["brainstorming_ref"] is None:
        blockers.append("brainstorming_required_for_ambiguity")
    tasks={t["id"]:t for t in data["tasks"]};queued={q["task_id"] for q in data["continuation_queue"]}
    for t in data["tasks"]:
        if t["state"]=="complete" and not t["evidence_refs"]:
            blockers.append("complete_task_missing_evidence:"+t["id"])
        if t["state"] not in {"complete","blocked"} and t["id"] not in queued:
            blockers.append("runnable_task_missing_continuation:"+t["id"])
        if t["state"]=="complete":
            unmet=[d for d in t["dependencies"] if tasks[d]["state"]!="complete"]
            if unmet: blockers.append("complete_task_has_unmet_dependency:"+t["id"])
    extra=queued-{t["id"] for t in data["tasks"] if t["state"] not in {"complete","blocked"}}
    for task_id in sorted(extra): blockers.append("nonrunnable_task_queued:"+task_id)
    return {
        "schema":"spec-plan-queue-result/v1","change_id":data["change_id"],
        "brainstorming_required":data["ambiguity_state"]=="ambiguous",
        "ready":not blockers,"blockers":blockers,
        "continuation_items":[q for q in data["continuation_queue"]],
        "authorizes_product_write":False,"authorizes_external_start":False,
        "authorizes_scope_expansion":False,"authorizes_merge":False,"authorizes_release":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=evaluate(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["ready"] else 1
if __name__=="__main__": raise SystemExit(main())
