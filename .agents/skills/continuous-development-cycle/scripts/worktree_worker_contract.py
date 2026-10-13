#!/usr/bin/env python3
"""CDC 2.10.2 durable per-wave isolated worker/worktree assignment contract."""
from __future__ import annotations

from git_object_integrity import git_object_environment
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
from parallel_task_planner import validate as validate_parallel_plan, plan as build_parallel_plan, validate_write_path, portable_path_key, overlaps, canonical_plan_ref

SCHEMA="worktree-worker-contract/v1"
INTEGRATION_SCHEMA="wave-integration-record/v1"
GATE_SCHEMA="wave-integration-gate-evidence/v1"
GATE_RESULT_SCHEMA="integration-gate-result/v1"
ASSEMBLY_SCHEMA="wave-assembly-evidence/v1"
SHA=re.compile(r"^[0-9a-f]{40}$");DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")
ROLES={"writer","read_only","review"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be nonempty text")
def _refs(v,n,allow_empty=False):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(f"{n} invalid")
    if not allow_empty and not v:raise ValueError(f"{n} must not be empty")
    if len(v)!=len(set(v)):raise ValueError(f"{n} contains duplicates")
def _sha(v,n):
    if not isinstance(v,str) or not SHA.fullmatch(v):raise ValueError(f"{n} invalid")
def _sha_list(v,n):
    if not isinstance(v,list):raise ValueError(f"{n} must be a list")
    for x in v:_sha(x,n+" item")
    if len(v)!=len(set(v)):raise ValueError(f"{n} contains duplicates")
    if v!=sorted(v):raise ValueError(f"{n} must be sorted")
    return v
def _digest(v,n):
    if not isinstance(v,str) or not DIGEST.fullmatch(v):raise ValueError(f"{n} invalid")
def canonical_branch_ref(branch):
    _text(branch,"branch")
    if branch.startswith("refs/") and not branch.startswith("refs/heads/"):
        raise ValueError("branch must name a local heads ref")
    name=branch.removeprefix("refs/heads/")
    if not name:raise ValueError("branch must name a local heads ref")
    return "refs/heads/"+name
def _safe_rel(path):
    if not isinstance(path,str) or not path.strip() or "\\" in path or path.startswith("/") or "//" in path:
        raise ValueError("unsafe integration artifact path")
    parts=path.split("/")
    if any(x in {"",".",".."} for x in parts):raise ValueError("unsafe integration artifact path")
    return path
def _artifact_ref(v,n):
    if not isinstance(v,dict) or set(v)!={"path","sha256"}:raise ValueError(f"{n} fields mismatch")
    _safe_rel(v["path"]);_digest(v["sha256"],f"{n}.sha256");return v
def _load_json_artifact(ref,evidence_root,label):
    _artifact_ref(ref,label)
    root=Path(evidence_root).resolve();target=(root/ref["path"]).resolve()
    try:target.relative_to(root)
    except ValueError as exc:raise ValueError(label+" escapes evidence root") from exc
    try:payload=target.read_bytes()
    except OSError as exc:raise ValueError(f"cannot read {label}: {exc}") from exc
    observed="sha256:"+hashlib.sha256(payload).hexdigest()
    if observed!=ref["sha256"]:raise ValueError(label+" digest mismatch")
    try:data=json.loads(payload)
    except json.JSONDecodeError as exc:raise ValueError(label+" JSON invalid") from exc
    return data,observed

def validate_gate_evidence(v):
    fields={"schema","change_id","plan_ref","wave","base_sha","shared_branch","ready","evidence_ref","result_artifact_ref"}
    if not isinstance(v,dict) or set(v)!=fields or v.get("schema")!=GATE_SCHEMA:raise ValueError("gate evidence fields/schema mismatch")
    _text(v["change_id"],"gate change_id");_digest(v["plan_ref"],"gate plan_ref")
    if type(v["wave"]) is not int or v["wave"]<1:raise ValueError("gate wave invalid")
    _sha(v["base_sha"],"gate base_sha");canonical_branch_ref(v["shared_branch"])
    if type(v["ready"]) is not bool or not v["ready"]:raise ValueError("gate evidence must be ready")
    _text(v["evidence_ref"],"gate evidence_ref");_artifact_ref(v["result_artifact_ref"],"gate result_artifact_ref")
    return v

def validate_gate_result(v):
    fields={"schema","change_id","wave","total_waves","final_wave","next_wave","plan_ref",
            "shared_branch","expected_shared_head","observed_shared_head","writer_result_shas",
            "action","ready","blockers","integrator_id","next_gate",
            "authorizes_shared_branch_write","authorizes_force_push","authorizes_merge",
            "authorizes_release","authorizes_scope_expansion"}
    if not isinstance(v,dict) or set(v)!=fields or v.get("schema")!=GATE_RESULT_SCHEMA:
        raise ValueError("integration gate result fields/schema mismatch")
    _text(v["change_id"],"gate result change_id");_digest(v["plan_ref"],"gate result plan_ref")
    if type(v["wave"]) is not int or v["wave"]<1:raise ValueError("gate result wave invalid")
    if type(v["total_waves"]) is not int or v["total_waves"]<v["wave"]:raise ValueError("gate result total_waves invalid")
    if type(v["final_wave"]) is not bool:raise ValueError("gate result final_wave invalid")
    if v["final_wave"]:
        if v["next_wave"] is not None:raise ValueError("final gate result cannot have next_wave")
    else:
        if type(v["next_wave"]) is not int or v["next_wave"]!=v["wave"]+1 or v["next_wave"]>v["total_waves"]:
            raise ValueError("nonfinal gate result next_wave invalid")
    canonical_branch_ref(v["shared_branch"]);_sha(v["expected_shared_head"],"gate result expected_shared_head");_sha(v["observed_shared_head"],"gate result observed_shared_head");_sha_list(v["writer_result_shas"],"gate result writer_result_shas")
    if v["action"] not in {"READY_FOR_INTEGRATOR","RECONCILE_OR_REPLAN"}:raise ValueError("gate result action invalid")
    if type(v["ready"]) is not bool:raise ValueError("gate result ready invalid")
    if not isinstance(v["blockers"],list) or any(not isinstance(x,str) or not x.strip() for x in v["blockers"]):raise ValueError("gate result blockers invalid")
    _text(v["integrator_id"],"gate result integrator_id");_text(v["next_gate"],"gate result next_gate")
    if v["ready"]!=(v["action"]=="READY_FOR_INTEGRATOR" and not v["blockers"]):
        raise ValueError("gate result ready/action/blockers inconsistent")
    for name in ("authorizes_shared_branch_write","authorizes_force_push","authorizes_merge","authorizes_release","authorizes_scope_expansion"):
        if type(v[name]) is not bool or v[name]:raise ValueError("gate result authority must be false: "+name)
    return v

def validate_assembly_evidence(v):
    fields={"schema","change_id","plan_ref","wave","base_sha","integrated_head","shared_branch","gate_sha256","writer_result_shas","assembled","evidence_ref"}
    if not isinstance(v,dict) or set(v)!=fields or v.get("schema")!=ASSEMBLY_SCHEMA:raise ValueError("assembly evidence fields/schema mismatch")
    _text(v["change_id"],"assembly change_id");_digest(v["plan_ref"],"assembly plan_ref")
    if type(v["wave"]) is not int or v["wave"]<1:raise ValueError("assembly wave invalid")
    _sha(v["base_sha"],"assembly base_sha");_sha(v["integrated_head"],"assembly integrated_head")
    if v["integrated_head"]==v["base_sha"]:raise ValueError("assembly must advance shared head")
    canonical_branch_ref(v["shared_branch"]);_digest(v["gate_sha256"],"assembly gate_sha256");_sha_list(v["writer_result_shas"],"assembly writer_result_shas")
    if type(v["assembled"]) is not bool or not v["assembled"]:raise ValueError("assembly evidence must be assembled")
    _text(v["evidence_ref"],"assembly evidence_ref");return v

def validate_prior_integration_record(record):
    fields={"schema","change_id","plan_ref","wave","base_sha","integrated_head","shared_branch","writer_result_shas",
            "gate_artifact_ref","assembly_artifact_ref","previous_integration"}
    if not isinstance(record,dict) or set(record)!=fields or record.get("schema")!=INTEGRATION_SCHEMA:
        raise ValueError("prior integration record fields/schema mismatch")
    _text(record["change_id"],"prior record change_id");_digest(record["plan_ref"],"prior record plan_ref")
    if type(record["wave"]) is not int or record["wave"]<1:raise ValueError("prior record wave invalid")
    _sha(record["base_sha"],"prior record base_sha");_sha(record["integrated_head"],"prior record integrated_head");_sha_list(record["writer_result_shas"],"prior record writer_result_shas")
    if record["base_sha"]==record["integrated_head"]:raise ValueError("prior integration must advance shared head")
    canonical_branch_ref(record["shared_branch"])
    _artifact_ref(record["gate_artifact_ref"],"gate_artifact_ref");_artifact_ref(record["assembly_artifact_ref"],"assembly_artifact_ref")
    if record["gate_artifact_ref"]["sha256"]==record["assembly_artifact_ref"]["sha256"]:
        raise ValueError("gate and assembly artifacts must be distinct")
    if record["previous_integration"] is not None:_artifact_ref(record["previous_integration"],"previous_integration")
    return record

def _resolve_integration_chain(ref,evidence_root,contract,expected_wave,seen=None,records=None):
    if evidence_root is None:raise ValueError("later wave requires resolvable prior integration artifacts")
    seen=set() if seen is None else seen
    records=[] if records is None else records
    _artifact_ref(ref,"prior integration artifact")
    if ref["sha256"] in seen:raise ValueError("prior integration evidence cycle")
    seen.add(ref["sha256"])
    record,_=_load_json_artifact(ref,evidence_root,"prior integration artifact")
    validate_prior_integration_record(record)
    if record["change_id"]!=contract["change_id"]:raise ValueError("prior integration change mismatch")
    if record["plan_ref"]!=contract["plan_ref"]:raise ValueError("prior integration plan mismatch")
    if record["wave"]!=expected_wave:raise ValueError("prior integration artifact wave mismatch")
    if canonical_branch_ref(record["shared_branch"])!=canonical_branch_ref(contract["shared_branch"]):
        raise ValueError("prior integration shared branch mismatch")
    if expected_wave==1:
        if record["previous_integration"] is not None:raise ValueError("wave one integration cannot have predecessor")
        if record["base_sha"]!=contract["plan"]["base_sha"]:raise ValueError("wave one integration base must match plan base")
    else:
        if record["previous_integration"] is None:raise ValueError("later integration record requires predecessor proof")
        previous=_resolve_integration_chain(record["previous_integration"],evidence_root,contract,expected_wave-1,seen,records)
        if record["base_sha"]!=previous["integrated_head"]:raise ValueError("integration chain base mismatch")
    gate,gate_digest=_load_json_artifact(record["gate_artifact_ref"],evidence_root,"integration gate artifact")
    validate_gate_evidence(gate)
    gate_result,_=_load_json_artifact(gate["result_artifact_ref"],evidence_root,"integration gate result artifact")
    validate_gate_result(gate_result)
    assembly,assembly_digest=_load_json_artifact(record["assembly_artifact_ref"],evidence_root,"assembly artifact")
    validate_assembly_evidence(assembly)
    for artifact,label in ((gate,"gate"),(assembly,"assembly")):
        if artifact["change_id"]!=record["change_id"] or artifact["plan_ref"]!=record["plan_ref"] or artifact["wave"]!=record["wave"]:
            raise ValueError(label+" evidence identity mismatch")
        if artifact["base_sha"]!=record["base_sha"]:raise ValueError(label+" evidence base mismatch")
        if canonical_branch_ref(artifact["shared_branch"])!=canonical_branch_ref(record["shared_branch"]):
            raise ValueError(label+" evidence shared branch mismatch")
    if gate_result["change_id"]!=record["change_id"] or gate_result["plan_ref"]!=record["plan_ref"] or gate_result["wave"]!=record["wave"]:
        raise ValueError("integration gate result identity mismatch")
    if canonical_branch_ref(gate_result["shared_branch"])!=canonical_branch_ref(record["shared_branch"]):
        raise ValueError("integration gate result shared branch mismatch")
    if gate_result["expected_shared_head"]!=record["base_sha"] or gate_result["observed_shared_head"]!=record["base_sha"]:
        raise ValueError("integration gate result base mismatch")
    if gate_result["integrator_id"]!=contract["integrator_id"]:raise ValueError("integration gate result integrator mismatch")
    if (not gate_result["ready"] or gate_result["action"]!="READY_FOR_INTEGRATOR" or gate_result["blockers"]):
        raise ValueError("resolved integration gate result is not GREEN")
    if gate_result["final_wave"] or gate_result["next_wave"]!=record["wave"]+1:
        raise ValueError("resolved prior gate does not route to the next wave")
    if gate_result["next_gate"]!="integrate_wave_then_contract_next_wave_on_fresh_head":
        raise ValueError("resolved prior gate has wrong next-wave route")
    if assembly["integrated_head"]!=record["integrated_head"]:raise ValueError("assembly integrated head mismatch")
    if gate_result["writer_result_shas"]!=record["writer_result_shas"]:raise ValueError("integration gate writer results do not match record")
    if assembly["writer_result_shas"]!=record["writer_result_shas"]:raise ValueError("assembly writer results do not match record")
    if assembly["gate_sha256"]!=gate_digest:raise ValueError("assembly does not bind resolved gate artifact")
    records.append(record)
    return record

def _resolve_prior_integration(prior,evidence_root,contract,records=None):
    if not isinstance(prior,dict) or set(prior)!={"wave","integrated_head","artifact_path","artifact_sha256"}:
        raise ValueError("later wave requires content-addressed prior integration proof")
    if type(prior["wave"]) is not int or prior["wave"]!=contract["wave"]-1:raise ValueError("prior integration wave mismatch")
    _sha(prior["integrated_head"],"prior integrated_head");_safe_rel(prior["artifact_path"]);_digest(prior["artifact_sha256"],"prior artifact sha256")
    records=[] if records is None else records
    record=_resolve_integration_chain({"path":prior["artifact_path"],"sha256":prior["artifact_sha256"]},evidence_root,contract,prior["wave"],records=records)
    if record["integrated_head"]!=prior["integrated_head"]:raise ValueError("prior integration artifact head mismatch")
    return record

def verify_prior_integration_live(d,evidence_root,git_worktree):
    if d["wave"]==1:return True
    records=[]
    record=_resolve_prior_integration(d["prior_wave_integration"],evidence_root,d,records=records)
    root=Path(git_worktree)
    if not root.is_dir():raise ValueError("git worktree missing")
    ref=canonical_branch_ref(d["shared_branch"])
    try:
        live=subprocess.check_output(["git","-C",str(root),"rev-parse","--verify",ref],env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15).strip()
        for historical in records:
            for sha in (historical["base_sha"],historical["integrated_head"],*historical["writer_result_shas"]):
                kind=subprocess.check_output(["git","-C",str(root),"cat-file","-t",sha],env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15).strip()
                if kind!="commit":raise ValueError("prior integration endpoint is not a commit")
            ancestry=subprocess.run(["git","-C",str(root),"merge-base","--is-ancestor",historical["base_sha"],historical["integrated_head"]],
                                    env=git_object_environment(), stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
            if ancestry.returncode!=0:raise ValueError("prior integrated head does not descend from prior base")
            for sha in historical["writer_result_shas"]:
                result_ancestry=subprocess.run(["git","-C",str(root),"merge-base","--is-ancestor",sha,historical["integrated_head"]],
                                               env=git_object_environment(), stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
                if result_ancestry.returncode!=0:raise ValueError("prior integrated head does not contain every gated writer result")
    except (OSError,subprocess.SubprocessError) as exc:raise ValueError(f"cannot verify prior integration live state: {exc}") from exc
    if live!=record["integrated_head"] or d["base_sha"]!=live:raise ValueError("later wave base is not current integrated shared head")
    return True

def validate(d,evidence_root=None):
    fields={"schema","change_id","plan_ref","plan","wave","base_sha","prior_wave_integration","integrator_id","shared_branch","assignments"}
    if not isinstance(d,dict) or set(d)!=fields or d.get("schema")!=SCHEMA:raise ValueError("worker contract fields/schema mismatch")
    for n in ("change_id","integrator_id","shared_branch"):_text(d[n],n)
    _digest(d["plan_ref"],"plan_ref")
    if type(d["wave"]) is not int or d["wave"]<1:raise ValueError("wave invalid")
    _sha(d["base_sha"],"base_sha")
    plan=validate_parallel_plan(d["plan"])
    if d["plan_ref"]!=canonical_plan_ref(plan):raise ValueError("embedded plan does not match durable plan_ref")
    if plan["change_id"]!=d["change_id"]:raise ValueError("plan change mismatch")
    if plan["integrator_id"]!=d["integrator_id"]:raise ValueError("plan integrator mismatch")
    if canonical_branch_ref(plan["shared_branch"])!=canonical_branch_ref(d["shared_branch"]):raise ValueError("plan shared branch mismatch")
    planned=build_parallel_plan(plan)
    if d["wave"]>len(planned["waves"]):raise ValueError("wave not present in plan")
    planned_wave=planned["waves"][d["wave"]-1];planned_ids=set(planned_wave["task_ids"])
    prior=d["prior_wave_integration"]
    if d["wave"]==1:
        if prior is not None:raise ValueError("first wave cannot have prior integration")
        if d["base_sha"]!=plan["base_sha"]:raise ValueError("first wave base must match plan base")
    else:
        record=_resolve_prior_integration(prior,evidence_root,d)
        if d["base_sha"]!=record["integrated_head"]:raise ValueError("later wave base must equal proven prior integrated head")
    if not isinstance(d["assignments"],list) or not d["assignments"]:raise ValueError("assignments required")
    if {a.get("task_id") for a in d["assignments"]}!=planned_ids:raise ValueError("assignments must exactly match planned wave")
    plan_tasks={t["id"]:t for t in plan["tasks"]};seen={k:set() for k in ("worker","task","branch","worktree")};writers=[]
    for i,a in enumerate(d["assignments"]):
        fields={"worker_id","task_id","role","branch","worktree_id","base_sha","write_paths","expected_outputs","expected_evidence","can_write_shared_branch"}
        if not isinstance(a,dict) or set(a)!=fields:raise ValueError("assignment fields mismatch")
        for n in ("worker_id","task_id","branch","worktree_id"):_text(a[n],f"assignment[{i}].{n}")
        if a["worker_id"]==d["integrator_id"]:raise ValueError("integrator cannot be delegated worker")
        if a["role"] not in ROLES:raise ValueError("assignment role invalid")
        _sha(a["base_sha"],"assignment base_sha")
        if a["base_sha"]!=d["base_sha"]:raise ValueError("assignment base mismatch")
        if canonical_branch_ref(a["branch"])==canonical_branch_ref(d["shared_branch"]):raise ValueError("worker branch cannot be shared branch")
        if type(a["can_write_shared_branch"]) is not bool or a["can_write_shared_branch"]:raise ValueError("worker shared-branch write forbidden")
        _refs(a["expected_outputs"],"expected_outputs");_refs(a["expected_evidence"],"expected_evidence")
        if not isinstance(a["write_paths"],list):raise ValueError("write_paths invalid")
        for p in a["write_paths"]:validate_write_path(p)
        if len(a["write_paths"])!=len(set(a["write_paths"])):raise ValueError("duplicate write path")
        keys=[portable_path_key(p) for p in a["write_paths"]]
        if len(keys)!=len(set(keys)):raise ValueError("portable duplicate write path")
        if a["role"]=="writer" and not a["write_paths"]:raise ValueError("writer requires write_paths")
        if a["role"]!="writer" and a["write_paths"]:raise ValueError("non-writer write_paths forbidden")
        pt=plan_tasks[a["task_id"]]
        if a["role"]!=pt["role"]:raise ValueError("assignment role differs from plan")
        if set(a["write_paths"])!=set(pt["write_paths"]):raise ValueError("assignment write set differs from plan")
        if set(a["expected_outputs"])!=set(pt["expected_outputs"]):raise ValueError("assignment outputs differ from plan")
        if set(a["expected_evidence"])!=set(pt["expected_evidence"]):raise ValueError("assignment evidence differs from plan")
        values={"worker":a["worker_id"],"task":a["task_id"],"branch":canonical_branch_ref(a["branch"]),"worktree":a["worktree_id"]}
        for key,val in values.items():
            if val in seen[key]:raise ValueError("duplicate "+key+" assignment")
            seen[key].add(val)
        if a["role"]=="writer":writers.append(a)
    for i,a in enumerate(writers):
        for b in writers[i+1:]:
            if any(overlaps(x,y) for x in a["write_paths"] for y in b["write_paths"]):raise ValueError("same-wave writer path overlap")
    return d

def assess(d,evidence_root=None,git_worktree=None):
    validate(d,evidence_root=evidence_root)
    if d["wave"]>1 and git_worktree is not None:verify_prior_integration_live(d,evidence_root,git_worktree)
    return {"schema":"worktree-worker-contract-result/v1","valid":True,"wave":d["wave"],"assignment_count":len(d["assignments"]),
            "base_sha":d["base_sha"],"plan_ref":d["plan_ref"],"integrator_id":d["integrator_id"],"shared_branch":d["shared_branch"],
            "authorizes_worker_launch":False,"authorizes_shared_branch_write":False,"authorizes_merge":False,
            "authorizes_release":False,"authorizes_scope_expansion":False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");p.add_argument("--evidence-root");p.add_argument("--git-worktree");a=p.parse_args(argv)
    try:
        d=json.loads(Path(a.input).read_text())
        if d.get("wave",1)>1 and not a.git_worktree:raise ValueError("later wave requires --git-worktree live integration proof")
        r=assess(d,evidence_root=a.evidence_root,git_worktree=a.git_worktree)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
