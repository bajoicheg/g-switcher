#!/usr/bin/env python3
"""CDC 2.10.2 dependency/write-set planner for safe parallel waves."""
from __future__ import annotations
import argparse,hashlib,json,math,re,sys,unicodedata
from pathlib import Path

SCHEMA="parallel-task-plan/v1";SHA=re.compile(r"^[0-9a-f]{40}$")
ROLES={"writer","read_only","review"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")
def _refs(v,n,allow_empty=False):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v): raise ValueError(f"{n} invalid")
    if not allow_empty and not v: raise ValueError(f"{n} must not be empty")
    if len(v)!=len(set(v)): raise ValueError(f"{n} contains duplicates")
WINDOWS_RESERVED={"CON","PRN","AUX","NUL"}|{f"COM{i}" for i in range(1,10)}|{f"LPT{i}" for i in range(1,10)}
WINDOWS_FORBIDDEN=set('<>:"|?*')

def validate_write_path(p):
    if not isinstance(p,str) or not p.strip() or "\\" in p or p.startswith("/") or p.endswith("/") or "//" in p:
        raise ValueError("unsafe write path")
    parts=p.split("/")
    if any(x in {"",".",".."} for x in parts):raise ValueError("unsafe write path")
    for part in parts:
        if part.endswith((" ",".")) or any(ord(ch)<32 or ch in WINDOWS_FORBIDDEN for ch in part):
            raise ValueError("non-portable write path")
        stem=part.split(".",1)[0].upper()
        if stem in WINDOWS_RESERVED:raise ValueError("non-portable write path")
    return p
def portable_path_key(p):
    validate_write_path(p)
    return "/".join(unicodedata.normalize("NFC",part).casefold() for part in p.rstrip("/").split("/"))

def overlaps(a,b):
    a=portable_path_key(a);b=portable_path_key(b)
    return a==b or a.startswith(b+"/") or b.startswith(a+"/")

def canonical_plan_ref(plan):
    validate(plan)
    payload=json.dumps(plan,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(payload).hexdigest()

def _acyclic(tasks):
    graph={t["id"]:t["dependencies"] for t in tasks};visiting=set();done=set()
    def visit(node):
        if node in done:return
        if node in visiting:raise ValueError("cyclic task dependency")
        visiting.add(node)
        for dep in graph[node]:visit(dep)
        visiting.remove(node);done.add(node)
    for node in graph:visit(node)

def validate(d):
    fields={"schema","change_id","base_sha","integrator_id","shared_branch","tasks"}
    if not isinstance(d,dict) or set(d)!=fields or d.get("schema")!=SCHEMA:raise ValueError("parallel plan fields/schema mismatch")
    for n in ("change_id","integrator_id","shared_branch"):_text(d[n],n)
    if not isinstance(d["base_sha"],str) or not SHA.fullmatch(d["base_sha"]):raise ValueError("base_sha invalid")
    if not isinstance(d["tasks"],list) or not d["tasks"]:raise ValueError("tasks required")
    ids=[]
    for i,t in enumerate(d["tasks"]):
        if not isinstance(t,dict) or set(t)!={"id","role","dependencies","write_paths","expected_outputs","expected_evidence","estimated_seconds"}:
            raise ValueError("task fields mismatch")
        _text(t["id"],f"task[{i}].id")
        if t["role"] not in ROLES:raise ValueError("task role invalid")
        _refs(t["dependencies"],f"task[{i}].dependencies",allow_empty=True)
        _refs(t["expected_outputs"],f"task[{i}].expected_outputs")
        _refs(t["expected_evidence"],f"task[{i}].expected_evidence")
        if (type(t["estimated_seconds"]) not in {int,float} or not math.isfinite(t["estimated_seconds"])
                or t["estimated_seconds"]<=0):raise ValueError("estimated_seconds invalid")
        if not isinstance(t["write_paths"],list):raise ValueError("write_paths invalid")
        for p in t["write_paths"]:validate_write_path(p)
        if len(t["write_paths"])!=len(set(t["write_paths"])):raise ValueError("duplicate write path")
        portable_keys=[portable_path_key(p) for p in t["write_paths"]]
        if len(portable_keys)!=len(set(portable_keys)):raise ValueError("portable duplicate write path")
        if t["role"]=="writer" and not t["write_paths"]:raise ValueError("writer requires write_paths")
        if t["role"]!="writer" and t["write_paths"]:raise ValueError("non-writer cannot declare write_paths")
        ids.append(t["id"])
    if len(ids)!=len(set(ids)):raise ValueError("duplicate task id")
    known=set(ids)
    for t in d["tasks"]:
        if t["id"] in t["dependencies"] or not set(t["dependencies"])<=known:raise ValueError("invalid task dependency")
    _acyclic(d["tasks"])
    return d

def plan(d):
    validate(d);tasks={t["id"]:t for t in d["tasks"]};remaining=set(tasks);done=set();waves=[]
    order=[t["id"] for t in d["tasks"]]
    while remaining:
        ready=[i for i in order if i in remaining and set(tasks[i]["dependencies"])<=done]
        if not ready:raise ValueError("dependency deadlock")
        wave=[];writer_paths=[]
        for task_id in ready:
            t=tasks[task_id]
            if t["role"]=="writer":
                if any(overlaps(p,q) for p in t["write_paths"] for q in writer_paths):
                    continue
                writer_paths.extend(t["write_paths"])
            wave.append(task_id)
        if not wave:
            wave=[ready[0]]
        waves.append({"wave":len(waves)+1,"task_ids":wave,"estimated_seconds":max(tasks[x]["estimated_seconds"] for x in wave)})
        remaining-=set(wave);done|=set(wave)
    sequential=sum(t["estimated_seconds"] for t in d["tasks"]);parallel=sum(w["estimated_seconds"] for w in waves)
    return {
      "schema":"parallel-task-plan-result/v1","change_id":d["change_id"],"base_sha":d["base_sha"],
      "integrator_id":d["integrator_id"],"shared_branch":d["shared_branch"],"waves":waves,
      "sequential_estimate_seconds":sequential,"parallel_estimate_seconds":parallel,
      "estimated_seconds_saved":sequential-parallel,"parallel_safe":True,
      "authorizes_worker_launch":False,"authorizes_product_write":False,"authorizes_merge":False,
      "authorizes_release":False,"authorizes_scope_expansion":False
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=plan(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
