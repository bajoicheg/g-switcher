#!/usr/bin/env python3
"""CDC 2.10.2 resolved observed parallel-execution benchmark evidence contract."""
from __future__ import annotations
import argparse,hashlib,json,math,re,sys
from pathlib import Path
SCHEMA="parallel-benchmark/v1";OBS_SCHEMA="parallel-benchmark-observation/v1";PLAN_SCHEMA="cdc-parallel-benchmark-plan/v1";ENV_SCHEMA="cdc-parallel-benchmark-environment/v1"
SHA=re.compile(r"^[0-9a-f]{40}$");DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$");MODES={"sequential","parallel"};EVIDENCE_CLASSES={"fixture","release_observed"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be nonempty text")
def _sha(v,n):
    if not isinstance(v,str) or not SHA.fullmatch(v):raise ValueError(f"{n} invalid")
def _safe_rel(path):
    if not isinstance(path,str) or not path.strip() or "\\" in path or path.startswith("/") or "//" in path:
        raise ValueError("unsafe observation path")
    parts=path.split("/")
    if any(x in {"",".",".."} for x in parts):raise ValueError("unsafe observation path")
    return path
def validate_observation(v):
    fields={"schema","observation_id","mode","observed","candidate_sha","environment_ref","plan_ref","workload_fingerprint","elapsed_seconds","unresolved_conflicts","rollbacks","evidence_ref"}
    if not isinstance(v,dict) or set(v)!=fields or v.get("schema")!=OBS_SCHEMA:raise ValueError("benchmark observation fields/schema mismatch")
    _text(v["observation_id"],"observation_id")
    if v["mode"] not in MODES:raise ValueError("observation mode invalid")
    if type(v["observed"]) is not bool:raise ValueError("benchmark observation observed must be boolean")
    _sha(v["candidate_sha"],"observation candidate_sha")
    for k in ("environment_ref","evidence_ref"):_text(v[k],k)
    if not isinstance(v["plan_ref"],str) or not DIGEST.fullmatch(v["plan_ref"]):raise ValueError("observation plan_ref must be sha256 digest")
    if not isinstance(v["workload_fingerprint"],str) or not DIGEST.fullmatch(v["workload_fingerprint"]):raise ValueError("workload_fingerprint invalid")
    if (type(v["elapsed_seconds"]) not in {int,float} or not math.isfinite(v["elapsed_seconds"])
            or v["elapsed_seconds"]<=0):raise ValueError("elapsed_seconds invalid")
    for n in ("unresolved_conflicts","rollbacks"):
        if type(v[n]) is not int or v[n]<0:raise ValueError(n+" invalid")
    return v
def validate(d):
    fields={"schema","benchmark_id","evidence_class","representative_task_ref","candidate_sha","package_tree","environment_ref","environment_artifact_ref","plan_ref","plan_artifact_ref","workstreams","observation_refs"}
    if not isinstance(d,dict) or set(d)!=fields or d.get("schema")!=SCHEMA:raise ValueError("benchmark fields/schema mismatch")
    _text(d["benchmark_id"],"benchmark_id");_text(d["representative_task_ref"],"representative_task_ref")
    if d["evidence_class"] not in EVIDENCE_CLASSES:raise ValueError("benchmark evidence_class invalid")
    _text(d["environment_ref"],"environment_ref");_sha(d["candidate_sha"],"candidate_sha");_sha(d["package_tree"],"package_tree")
    env_artifact=d["environment_artifact_ref"]
    if not isinstance(env_artifact,dict) or set(env_artifact)!={"path","sha256"}:raise ValueError("environment artifact ref fields mismatch")
    _safe_rel(env_artifact["path"])
    if env_artifact["path"]!=d["environment_ref"]:raise ValueError("environment_ref must equal environment artifact path")
    if not isinstance(env_artifact["sha256"],str) or not DIGEST.fullmatch(env_artifact["sha256"]):raise ValueError("environment artifact sha256 invalid")
    if not isinstance(d["plan_ref"],str) or not DIGEST.fullmatch(d["plan_ref"]):raise ValueError("benchmark plan_ref must be sha256 digest")
    artifact=d["plan_artifact_ref"]
    if not isinstance(artifact,dict) or set(artifact)!={"path","sha256"}:raise ValueError("plan artifact ref fields mismatch")
    _safe_rel(artifact["path"])
    if not isinstance(artifact["sha256"],str) or not DIGEST.fullmatch(artifact["sha256"]):raise ValueError("plan artifact sha256 invalid")
    if artifact["sha256"]!=d["plan_ref"]:raise ValueError("plan_ref must equal resolved plan artifact digest")
    if type(d["workstreams"]) is not int or d["workstreams"]<2:raise ValueError("workstreams must be >=2")
    refs=d["observation_refs"]
    if not isinstance(refs,list) or len(refs)!=2:raise ValueError("benchmark requires exactly two observation refs")
    paths=[]
    for i,ref in enumerate(refs):
        if not isinstance(ref,dict) or set(ref)!={"path","sha256"}:raise ValueError("observation ref fields mismatch")
        paths.append(_safe_rel(ref["path"]))
        if not isinstance(ref["sha256"],str) or not DIGEST.fullmatch(ref["sha256"]):raise ValueError("observation ref sha256 invalid")
    if len(paths)!=len(set(paths)):raise ValueError("observation paths must be distinct")
    return d
def load_plan_artifact(d,evidence_root):
    validate(d);root=Path(evidence_root).resolve();ref=d["plan_artifact_ref"]
    path=(root/ref["path"]).resolve()
    try:path.relative_to(root)
    except ValueError as exc:raise ValueError("plan artifact escapes evidence root") from exc
    try:payload=path.read_bytes()
    except OSError as exc:raise ValueError(f"cannot read benchmark plan artifact: {exc}") from exc
    observed="sha256:"+hashlib.sha256(payload).hexdigest()
    if observed!=ref["sha256"] or observed!=d["plan_ref"]:raise ValueError("benchmark plan artifact digest mismatch")
    try:plan=json.loads(payload)
    except json.JSONDecodeError as exc:raise ValueError("benchmark plan artifact JSON invalid") from exc
    fields={"schema","version","candidate_source_commit","package_tree","representative_task_ref","workstreams",
            "warmup_repetitions_per_workstream","measurement_batches","repetitions_per_batch_per_workstream",
            "sequential_mode","parallel_mode","timer","acceptance"}
    if not isinstance(plan,dict) or set(plan)!=fields or plan.get("schema")!=PLAN_SCHEMA:
        raise ValueError("benchmark plan artifact fields/schema mismatch")
    _text(plan["version"],"benchmark plan version");_sha(plan["candidate_source_commit"],"benchmark plan candidate_source_commit")
    _sha(plan["package_tree"],"benchmark plan package_tree");_text(plan["representative_task_ref"],"benchmark plan representative_task_ref")
    if plan["candidate_source_commit"]!=d["candidate_sha"]:raise ValueError("benchmark plan candidate binding mismatch")
    if plan["package_tree"]!=d["package_tree"]:raise ValueError("benchmark plan package-tree binding mismatch")
    if plan["representative_task_ref"]!=d["representative_task_ref"]:raise ValueError("benchmark plan representative-task mismatch")
    if not isinstance(plan["workstreams"],list) or len(plan["workstreams"])!=d["workstreams"]:raise ValueError("benchmark plan workstream count mismatch")
    ids=[]
    for i,item in enumerate(plan["workstreams"]):
        if not isinstance(item,dict) or set(item)!={"id","command"}:raise ValueError("benchmark plan workstream fields mismatch")
        _text(item["id"],f"benchmark plan workstream[{i}].id");_text(item["command"],f"benchmark plan workstream[{i}].command");ids.append(item["id"])
    if len(ids)!=len(set(ids)):raise ValueError("benchmark plan workstream ids duplicated")
    for name in ("warmup_repetitions_per_workstream","measurement_batches","repetitions_per_batch_per_workstream"):
        if type(plan[name]) is not int or plan[name]<1:raise ValueError("benchmark plan "+name+" invalid")
    _text(plan["sequential_mode"],"benchmark plan sequential_mode");_text(plan["parallel_mode"],"benchmark plan parallel_mode")
    if plan["timer"]!="time.perf_counter()":raise ValueError("benchmark plan timer invalid")
    expected_acceptance={"parallel_elapsed_less_than_sequential","parallel_unresolved_conflicts_lte_baseline",
                         "parallel_rollbacks_lte_baseline","all_invocations_must_pass"}
    if not isinstance(plan["acceptance"],dict) or set(plan["acceptance"])!=expected_acceptance or any(v is not True for v in plan["acceptance"].values()):
        raise ValueError("benchmark plan acceptance invalid")
    return {"path":ref["path"],"sha256":observed,"candidate_source_commit":plan["candidate_source_commit"],
            "package_tree":plan["package_tree"],"representative_task_ref":plan["representative_task_ref"]}

def load_environment_artifact(d,evidence_root):
    validate(d);root=Path(evidence_root).resolve();ref=d["environment_artifact_ref"]
    path=(root/ref["path"]).resolve()
    try:path.relative_to(root)
    except ValueError as exc:raise ValueError("environment artifact escapes evidence root") from exc
    try:payload=path.read_bytes()
    except OSError as exc:raise ValueError(f"cannot read benchmark environment artifact: {exc}") from exc
    observed="sha256:"+hashlib.sha256(payload).hexdigest()
    if observed!=ref["sha256"]:raise ValueError("benchmark environment artifact digest mismatch")
    try:env=json.loads(payload)
    except json.JSONDecodeError as exc:raise ValueError("benchmark environment artifact JSON invalid") from exc
    fields={"schema","version","candidate_source_commit","package_tree","provider","working_directory","python_executable",
            "python_version","implementation","platform","architecture","reported_processing_units","timer","evidence_comment"}
    if not isinstance(env,dict) or set(env)!=fields or env.get("schema")!=ENV_SCHEMA:
        raise ValueError("benchmark environment artifact fields/schema mismatch")
    if env["version"]!="2.10.2":raise ValueError("benchmark environment version mismatch")
    _sha(env["candidate_source_commit"],"benchmark environment candidate_source_commit")
    _sha(env["package_tree"],"benchmark environment package_tree")
    if env["candidate_source_commit"]!=d["candidate_sha"]:raise ValueError("benchmark environment candidate binding mismatch")
    if env["package_tree"]!=d["package_tree"]:raise ValueError("benchmark environment package-tree binding mismatch")
    for name in ("provider","working_directory","python_executable","python_version","implementation","platform","architecture","evidence_comment"):
        _text(env[name],"benchmark environment "+name)
    if type(env["reported_processing_units"]) is not int or env["reported_processing_units"]<1:
        raise ValueError("benchmark environment reported_processing_units invalid")
    if env["timer"]!="time.perf_counter()":raise ValueError("benchmark environment timer invalid")
    return {"path":ref["path"],"sha256":observed,"candidate_source_commit":env["candidate_source_commit"],"package_tree":env["package_tree"]}

def load_observations(d,evidence_root):
    validate(d);root=Path(evidence_root).resolve();observations=[]
    for ref in d["observation_refs"]:
        path=(root/ref["path"]).resolve()
        try:path.relative_to(root)
        except ValueError as exc:raise ValueError("observation path escapes evidence root") from exc
        try:payload=path.read_bytes()
        except OSError as exc:raise ValueError(f"cannot read benchmark observation: {exc}") from exc
        observed_digest="sha256:"+hashlib.sha256(payload).hexdigest()
        if observed_digest!=ref["sha256"]:raise ValueError("benchmark observation digest mismatch")
        try:obs=json.loads(payload)
        except json.JSONDecodeError as exc:raise ValueError("benchmark observation JSON invalid") from exc
        validate_observation(obs);observations.append(obs)
    return observations
def evaluate(d,observations,plan_artifact=None,environment_artifact=None):
    validate(d)
    if plan_artifact is not None:
        expected={"path","sha256","candidate_source_commit","package_tree","representative_task_ref"}
        if not isinstance(plan_artifact,dict) or set(plan_artifact)!=expected:raise ValueError("resolved plan artifact proof invalid")
        if plan_artifact["sha256"]!=d["plan_ref"] or plan_artifact["candidate_source_commit"]!=d["candidate_sha"] or plan_artifact["package_tree"]!=d["package_tree"] or plan_artifact["representative_task_ref"]!=d["representative_task_ref"]:
            raise ValueError("resolved plan artifact proof binding mismatch")
    if environment_artifact is not None:
        expected={"path","sha256","candidate_source_commit","package_tree"}
        if not isinstance(environment_artifact,dict) or set(environment_artifact)!=expected:raise ValueError("resolved environment artifact proof invalid")
        if environment_artifact["path"]!=d["environment_ref"] or environment_artifact["candidate_source_commit"]!=d["candidate_sha"] or environment_artifact["package_tree"]!=d["package_tree"]:
            raise ValueError("resolved environment artifact proof binding mismatch")
    if not isinstance(observations,list) or len(observations)!=2:raise ValueError("resolved observations required")
    obs=[validate_observation(x) for x in observations];by={x["mode"]:x for x in obs}
    if d["evidence_class"]=="release_observed" and any(x["observed"] is not True for x in obs):
        raise ValueError("release benchmark observations must be observed")
    if d["evidence_class"]=="fixture" and any(x["observed"] is not False for x in obs):
        raise ValueError("fixture benchmark observations must be non-observed")
    if set(by)!=MODES:raise ValueError("benchmark requires one sequential and one parallel observation")
    if len({x["observation_id"] for x in obs})!=2:raise ValueError("observation_id must be distinct")
    if len({x["evidence_ref"] for x in obs})!=2:raise ValueError("observation evidence refs must be distinct")
    if len({x["workload_fingerprint"] for x in obs})!=1:raise ValueError("sequential and parallel workloads differ")
    for x in obs:
        if x["candidate_sha"]!=d["candidate_sha"]:raise ValueError("observation candidate binding mismatch")
        if x["environment_ref"]!=d["environment_ref"]:raise ValueError("observation environment binding mismatch")
        if x["plan_ref"]!=d["plan_ref"]:raise ValueError("observation plan binding mismatch")
    seq=by["sequential"]["elapsed_seconds"];par=by["parallel"]["elapsed_seconds"];b=[]
    if par>=seq:b.append("no_wall_clock_improvement")
    if by["parallel"]["unresolved_conflicts"]>by["sequential"]["unresolved_conflicts"]:b.append("conflict_rate_regressed")
    if by["parallel"]["rollbacks"]>by["sequential"]["rollbacks"]:b.append("rollback_rate_regressed")
    passed=not b
    return {"schema":"parallel-benchmark-result/v1","benchmark_id":d["benchmark_id"],"candidate_sha":d["candidate_sha"],
            "environment_ref":d["environment_ref"],"plan_ref":d["plan_ref"],"workload_fingerprint":by["sequential"]["workload_fingerprint"],
            "sequential_elapsed_seconds":seq,"parallel_elapsed_seconds":par,"passed":passed,
            "speedup_ratio":round(seq/par,3),"seconds_saved":seq-par,"blockers":b,
            "resolved_observation_count":2,"evidence_class":d["evidence_class"],
            "plan_artifact_verified":plan_artifact is not None,"environment_artifact_verified":environment_artifact is not None,
            "release_evidence_eligible":passed and d["evidence_class"]=="release_observed" and plan_artifact is not None and environment_artifact is not None,
            "authorizes_worker_launch":False,"authorizes_product_write":False,"authorizes_merge":False,"authorizes_release":False}
def evaluate_from_files(d,evidence_root):
    plan=load_plan_artifact(d,evidence_root)
    environment=load_environment_artifact(d,evidence_root)
    return evaluate(d,load_observations(d,evidence_root),plan_artifact=plan,environment_artifact=environment)
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");p.add_argument("--evidence-root",required=True);a=p.parse_args(argv)
    try:d=json.loads(Path(a.input).read_text());r=evaluate_from_files(d,a.evidence_root)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
