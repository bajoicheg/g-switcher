#!/usr/bin/env python3
"""CDC 2.10.2 per-wave single-integrator gate bound to worker contract and Git diff proofs."""
from __future__ import annotations

from git_object_integrity import git_object_environment
import argparse,json,re,subprocess,sys
from pathlib import Path
from worktree_worker_contract import validate as validate_worker_contract
from parallel_task_planner import plan as build_parallel_plan, validate_write_path, portable_path_key

SCHEMA="integration-gate/v1"
SHA=re.compile(r"^[0-9a-f]{40}$")
STATES={"success","failed","stale"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be nonempty text")
def _refs(v,n,allow_empty=False):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(f"{n} invalid")
    if not allow_empty and not v:raise ValueError(f"{n} must not be empty")
    if len(v)!=len(set(v)):raise ValueError(f"{n} contains duplicates")
def _path(path):
    return validate_write_path(path)
def _assert_portable_unique(paths,label):
    keys=[portable_path_key(p) for p in paths]
    if len(keys)!=len(set(keys)):
        raise ValueError(label+" contains portable path aliases")
def _within(path,allowed):
    path=portable_path_key(path);allowed=portable_path_key(allowed)
    return path==allowed or path.startswith(allowed+"/")
def _sha(v,n):
    if not isinstance(v,str) or not SHA.fullmatch(v):raise ValueError(f"{n} invalid")

def resolve_shared_head(worktree, shared_branch):
    root=Path(worktree)
    if not root.is_dir():raise ValueError("git worktree missing")
    _text(shared_branch,"shared_branch")
    ref="refs/heads/"+shared_branch.removeprefix("refs/heads/")
    try:
        head=subprocess.check_output(["git","-C",str(root),"rev-parse","--verify",ref],
                                     env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15).strip()
    except (OSError,subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot resolve live shared branch {ref}: {exc}") from exc
    _sha(head,"live shared head")
    return head

def _branch_ref(branch):
    _text(branch,"branch")
    return branch if branch.startswith("refs/heads/") else "refs/heads/"+branch

def parse_worker_worktrees(values):
    mapping={}
    for raw in values or []:
        if not isinstance(raw,str) or "=" not in raw:raise ValueError("worker worktree mapping must be WORKTREE_ID=PATH")
        worktree_id,path=raw.split("=",1);_text(worktree_id,"worktree_id");_text(path,"worker worktree path")
        if worktree_id in mapping:raise ValueError("duplicate worker worktree mapping")
        mapping[worktree_id]=path
    return mapping

def _registered_worktrees(shared_worktree):
    root=Path(shared_worktree)
    try:
        out=subprocess.check_output(["git","-C",str(root),"worktree","list","--porcelain"],
                                    env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15)
    except (OSError,subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot inspect registered worktrees: {exc}") from exc
    result=[];current={}
    for line in out.splitlines()+[""]:
        if not line:
            if current:
                result.append(current);current={}
            continue
        key,_,value=line.partition(" ")
        if key in {"worktree","HEAD","branch"}:current[key]=value
    return result

def verify_worker_origins(d, shared_worktree, worker_worktrees, evidence_root=None):
    validate(d,evidence_root=evidence_root)
    root=Path(shared_worktree).resolve()
    registry=_registered_worktrees(root)
    by_path={str(Path(x["worktree"]).resolve()):x for x in registry if "worktree" in x}
    assignments={a["task_id"]:a for a in d["worker_contract"]["assignments"]}
    shared_ref=_branch_ref(d["shared_branch"])
    for r in d["worker_results"]:
        if r["role"]!="writer" or r["state"]!="success":continue
        a=assignments[r["task_id"]];worktree_id=a["worktree_id"]
        if worktree_id not in worker_worktrees:raise ValueError("missing live worker worktree mapping: "+worktree_id)
        worker_path=Path(worker_worktrees[worktree_id]).resolve()
        if worker_path==root:raise ValueError("writer worktree cannot be the shared integration worktree")
        record=by_path.get(str(worker_path))
        if record is None:raise ValueError("worker path is not a registered Git worktree")
        expected_ref=_branch_ref(a["branch"])
        if expected_ref==shared_ref:raise ValueError("writer branch cannot equal shared branch")
        if record.get("branch")!=expected_ref:raise ValueError("registered worktree branch does not match assignment")
        if record.get("HEAD")!=r["result_sha"]:raise ValueError("registered worktree HEAD does not match worker result")
        try:
            branch_head=subprocess.check_output(["git","-C",str(root),"rev-parse","--verify",expected_ref],
                                               env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15).strip()
            actual_head=subprocess.check_output(["git","-C",str(worker_path),"rev-parse","HEAD"],
                                               env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15).strip()
        except (OSError,subprocess.SubprocessError) as exc:
            raise ValueError(f"cannot verify worker branch/worktree origin: {exc}") from exc
        if branch_head!=r["result_sha"] or actual_head!=r["result_sha"]:
            raise ValueError("worker branch/worktree does not resolve to result SHA")
    return True

def resolve_git_diff(worktree, *, worker_id, task_id, base_sha, result_sha, evidence_ref):
    root=Path(worktree)
    if not root.is_dir():raise ValueError("git worktree missing")
    _text(worker_id,"worker_id");_text(task_id,"task_id");_text(evidence_ref,"evidence_ref")
    _sha(base_sha,"base_sha");_sha(result_sha,"result_sha")
    for sha in (base_sha,result_sha):
        try:t=subprocess.check_output(["git","-C",str(root),"cat-file","-t",sha],env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=15).strip()
        except (OSError,subprocess.SubprocessError) as exc:raise ValueError(f"cannot resolve worker commit {sha}: {exc}") from exc
        if t!="commit":raise ValueError("worker diff endpoint is not a commit")
    try:
        ancestry=subprocess.run(["git","-C",str(root),"merge-base","--is-ancestor",base_sha,result_sha],
                                env=git_object_environment(), stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
    except (OSError,subprocess.SubprocessError) as exc:raise ValueError(f"cannot verify worker ancestry: {exc}") from exc
    if ancestry.returncode==1:raise ValueError("worker result does not descend from contracted base")
    if ancestry.returncode!=0:raise ValueError("worker ancestry verification failed")
    try:
        out=subprocess.check_output(["git","-C",str(root),"diff","--name-only","--no-renames",base_sha,result_sha,"--"],env=git_object_environment(), text=True,stderr=subprocess.PIPE,timeout=30)
    except (OSError,subprocess.SubprocessError) as exc:raise ValueError(f"cannot resolve worker diff: {exc}") from exc
    paths=[x for x in out.splitlines() if x.strip()]
    for p in paths:_path(p)
    if len(paths)!=len(set(paths)):raise ValueError("resolved diff contains duplicate path")
    _assert_portable_unique(paths,"resolved diff")
    return {"worker_id":worker_id,"task_id":task_id,"base_sha":base_sha,"result_sha":result_sha,
            "resolver":"git_diff_name_only","changed_paths":paths,"evidence_ref":evidence_ref}

def _validate_proof(p):
    fields={"worker_id","task_id","base_sha","result_sha","resolver","changed_paths","evidence_ref"}
    if not isinstance(p,dict) or set(p)!=fields:raise ValueError("diff proof fields mismatch")
    _text(p["worker_id"],"diff proof worker_id");_text(p["task_id"],"diff proof task_id");_text(p["evidence_ref"],"diff proof evidence_ref")
    _sha(p["base_sha"],"diff proof base_sha");_sha(p["result_sha"],"diff proof result_sha")
    if p["resolver"]!="git_diff_name_only":raise ValueError("unsupported diff resolver")
    if not isinstance(p["changed_paths"],list):raise ValueError("diff proof changed_paths invalid")
    for path in p["changed_paths"]:_path(path)
    if len(p["changed_paths"])!=len(set(p["changed_paths"])):raise ValueError("duplicate diff proof path")
    _assert_portable_unique(p["changed_paths"],"diff proof")
    return p

def validate(d,evidence_root=None):
    fields={"schema","change_id","integrator_id","shared_branch","expected_shared_head",
            "observed_shared_head","worker_contract","worker_results","diff_proofs",
            "unresolved_conflicts","force_push_requested","verification_refs"}
    if not isinstance(d,dict) or set(d)!=fields or d.get("schema")!=SCHEMA:raise ValueError("integration gate fields/schema mismatch")
    for n in ("change_id","integrator_id","shared_branch"):_text(d[n],n)
    for n in ("expected_shared_head","observed_shared_head"):_sha(d[n],n)
    if type(d["force_push_requested"]) is not bool:raise ValueError("force_push_requested must be boolean")
    _refs(d["verification_refs"],"verification_refs");_refs(d["unresolved_conflicts"],"unresolved_conflicts",allow_empty=True)

    contract=validate_worker_contract(d["worker_contract"],evidence_root=evidence_root)
    if contract["change_id"]!=d["change_id"]:raise ValueError("worker contract change mismatch")
    if contract["integrator_id"]!=d["integrator_id"]:raise ValueError("worker contract integrator mismatch")
    if contract["shared_branch"]!=d["shared_branch"]:raise ValueError("worker contract shared branch mismatch")
    if contract["base_sha"]!=d["expected_shared_head"]:raise ValueError("worker contract base mismatch")

    assignments={a["task_id"]:a for a in contract["assignments"]}
    if not isinstance(d["worker_results"],list):raise ValueError("worker_results must be list")
    seen_tasks=set();seen_workers=set()
    results={}
    for i,r in enumerate(d["worker_results"]):
        fields={"worker_id","task_id","role","base_sha","result_sha","state","changed_paths","output_refs","evidence_refs"}
        if not isinstance(r,dict) or set(r)!=fields:raise ValueError("worker result fields mismatch")
        for n in ("worker_id","task_id"):_text(r[n],f"worker[{i}].{n}")
        if r["task_id"] in seen_tasks or r["worker_id"] in seen_workers:raise ValueError("duplicate worker/task result")
        seen_tasks.add(r["task_id"]);seen_workers.add(r["worker_id"])
        if r["task_id"] not in assignments:raise ValueError("result references unknown assignment")
        a=assignments[r["task_id"]]
        if r["worker_id"]!=a["worker_id"] or r["role"]!=a["role"]:raise ValueError("result identity/role does not match assignment")
        if r["state"] not in STATES:raise ValueError("worker state invalid")
        for n in ("base_sha","result_sha"):_sha(r[n],f"worker {n}")
        if r["base_sha"]!=a["base_sha"]:raise ValueError("result base does not match assignment")
        _refs(r["output_refs"],"worker outputs",allow_empty=r["state"]!="success")
        _refs(r["evidence_refs"],"worker evidence",allow_empty=r["state"]!="success")
        if r["state"]=="success" and not set(a["expected_outputs"])<=set(r["output_refs"]):raise ValueError("worker result missing expected output")
        if r["state"]=="success" and not set(a["expected_evidence"])<=set(r["evidence_refs"]):raise ValueError("worker result missing expected evidence")
        if not isinstance(r["changed_paths"],list):raise ValueError("changed_paths invalid")
        for changed in r["changed_paths"]:_path(changed)
        if len(r["changed_paths"])!=len(set(r["changed_paths"])):raise ValueError("duplicate changed path")
        _assert_portable_unique(r["changed_paths"],"worker changed_paths")
        if r["role"]!="writer":
            if r["changed_paths"]:raise ValueError("non-writer changed paths forbidden")
            if r["state"]=="success" and r["result_sha"]!=r["base_sha"]:raise ValueError("non-writer result SHA must remain at base")
        else:
            if r["state"]=="success" and not r["changed_paths"]:raise ValueError("successful writer requires changed paths")
            if r["state"]=="success" and r["result_sha"]==r["base_sha"]:raise ValueError("successful writer result SHA must differ from base")
            for changed in r["changed_paths"]:
                if not any(_within(changed,allowed) for allowed in a["write_paths"]):raise ValueError("worker changed path outside assigned write set")
        results[r["task_id"]]=r

    if not isinstance(d["diff_proofs"],list):raise ValueError("diff_proofs must be list")
    proofs={};proof_workers=set()
    for p in d["diff_proofs"]:
        _validate_proof(p)
        if p["task_id"] in proofs or p["worker_id"] in proof_workers:raise ValueError("duplicate diff proof")
        proofs[p["task_id"]]=p;proof_workers.add(p["worker_id"])
    successful_writers={r["task_id"]:r for r in d["worker_results"] if r["role"]=="writer" and r["state"]=="success"}
    if set(proofs)!=set(successful_writers):raise ValueError("diff proofs must exactly cover successful writers")
    for task_id,r in successful_writers.items():
        p=proofs[task_id]
        if p["worker_id"]!=r["worker_id"] or p["base_sha"]!=r["base_sha"] or p["result_sha"]!=r["result_sha"]:
            raise ValueError("diff proof identity/SHA mismatch")
        if p["changed_paths"]!=r["changed_paths"]:raise ValueError("reported changed_paths differ from resolved diff proof")
    return d

def verify_git_diff_proofs(d, worktree, evidence_root=None):
    validate(d,evidence_root=evidence_root)
    by_task={p["task_id"]:p for p in d["diff_proofs"]}
    for r in d["worker_results"]:
        if r["role"]!="writer" or r["state"]!="success":continue
        observed=resolve_git_diff(worktree,worker_id=r["worker_id"],task_id=r["task_id"],base_sha=r["base_sha"],result_sha=r["result_sha"],
                                  evidence_ref=by_task[r["task_id"]]["evidence_ref"])
        if observed!=by_task[r["task_id"]]:raise ValueError("stored diff proof does not match actual Git diff")
    return True

def evaluate(d,evidence_root=None):
    validate(d,evidence_root=evidence_root)
    contract=d["worker_contract"];base=d["expected_shared_head"];b=[]
    if d["observed_shared_head"]!=base:b.append("shared_head_moved_reconcile_required")
    if d["force_push_requested"]:b.append("force_push_forbidden")
    if d["unresolved_conflicts"]:b.append("unresolved_conflicts")
    results={r["task_id"]:r for r in d["worker_results"]}
    for a in contract["assignments"]:
        r=results.get(a["task_id"])
        if r is None:b.append("missing_worker_result:"+a["task_id"]);continue
        if r["state"]!="success":b.append("worker_not_success:"+a["task_id"])
        if r["base_sha"]!=base:b.append("worker_base_stale:"+a["task_id"])
    writers=[r for r in d["worker_results"] if r["role"]=="writer"]
    writer_result_shas=sorted(r["result_sha"] for r in writers if r["state"]=="success")
    for i,a in enumerate(writers):
        for x in writers[i+1:]:
            for p in a["changed_paths"]:
                for q in x["changed_paths"]:
                    if _within(p,q) or _within(q,p):b.append("same_wave_worker_result_path_overlap:"+a["task_id"]+":"+x["task_id"])
    planned=build_parallel_plan(contract["plan"]);total_waves=len(planned["waves"]);final_wave=contract["wave"]==total_waves
    next_wave=None if final_wave else contract["wave"]+1
    next_gate=("cdc_2.10.1_review_branch_finish_then_2.10.0_verification" if final_wave
               else "integrate_wave_then_contract_next_wave_on_fresh_head")
    ready=not b
    return {"schema":"integration-gate-result/v1","change_id":d["change_id"],"wave":contract["wave"],"total_waves":total_waves,
            "final_wave":final_wave,"next_wave":next_wave,"plan_ref":contract["plan_ref"],
            "shared_branch":d["shared_branch"],"expected_shared_head":d["expected_shared_head"],
            "observed_shared_head":d["observed_shared_head"],"writer_result_shas":writer_result_shas,
            "action":"READY_FOR_INTEGRATOR" if ready else "RECONCILE_OR_REPLAN","ready":ready,"blockers":b,
            "integrator_id":d["integrator_id"],"next_gate":next_gate,
            "authorizes_shared_branch_write":False,"authorizes_force_push":False,"authorizes_merge":False,
            "authorizes_release":False,"authorizes_scope_expansion":False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");p.add_argument("--git-worktree")
    p.add_argument("--evidence-root")
    p.add_argument("--worker-worktree",action="append",default=[],metavar="WORKTREE_ID=PATH")
    a=p.parse_args(argv)
    try:
        d=json.loads(Path(a.input).read_text())
        if not a.git_worktree:raise ValueError("--git-worktree is required for live shared-head verification")
        live_head=resolve_shared_head(a.git_worktree,d["shared_branch"])
        if live_head!=d["observed_shared_head"]:
            raise ValueError("observed_shared_head does not match live shared branch")
        if any(r.get("role")=="writer" and r.get("state")=="success" for r in d.get("worker_results",[])):
            worker_worktrees=parse_worker_worktrees(a.worker_worktree)
            verify_worker_origins(d,a.git_worktree,worker_worktrees,evidence_root=a.evidence_root)
            verify_git_diff_proofs(d,a.git_worktree,evidence_root=a.evidence_root)
        r=evaluate(d,evidence_root=a.evidence_root)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["ready"] else 1

if __name__=="__main__":raise SystemExit(main())
