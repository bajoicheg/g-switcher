#!/usr/bin/env python3
"""Plan operation-budget-aware detached-tree migration transactions."""
from __future__ import annotations
import argparse,hashlib,json,re,sys
from pathlib import Path
SCHEMA="migration-transaction/v1";OUT="migration-transaction-plan/v1"
SHA=re.compile(r"^[0-9a-f]{40}$");DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$");PATH=re.compile(r"^[A-Za-z0-9._/-]+$")
def validate(s):
    fields={"schema","transaction_id","source_head","target_ref","items","completed_paths","operation_budget","per_item_operations","batch_overhead_operations","finalization_reserve_operations","detached_checkpoints","final_tree_sha","expected_subtree_tree","observed_subtree_tree","policy_reconciled"}
    if not isinstance(s,dict) or set(s)!=fields or s.get("schema")!=SCHEMA:raise ValueError("invalid migration transaction")
    if not isinstance(s["transaction_id"],str) or not s["transaction_id"].strip():raise ValueError("transaction_id invalid")
    if not SHA.fullmatch(s["source_head"]):raise ValueError("source_head invalid")
    if not isinstance(s["target_ref"],str) or not s["target_ref"].startswith("refs/heads/"):raise ValueError("target_ref invalid")
    if not isinstance(s["items"],list) or not s["items"]:raise ValueError("items must be nonempty")
    paths=[]
    for item in s["items"]:
        if not isinstance(item,dict) or set(item) not in ({"path","blob_sha1"},{"path","object_type","object_sha1"}):
            raise ValueError("migration item fields mismatch")
        path=item["path"]
        if not isinstance(path,str) or not PATH.fullmatch(path) or path.startswith("/") or path.endswith("/") or any(p in {"",".",".."} for p in path.split("/")):raise ValueError("migration item path invalid")
        if "blob_sha1" in item:
            if not isinstance(item["blob_sha1"],str) or not SHA.fullmatch(item["blob_sha1"]):raise ValueError("migration blob identity invalid")
        else:
            if item["object_type"] not in {"blob","tree"}:raise ValueError("migration object_type invalid")
            if not isinstance(item["object_sha1"],str) or not SHA.fullmatch(item["object_sha1"]):raise ValueError("migration object identity invalid")
        paths.append(path)
    if len(paths)!=len(set(paths)):raise ValueError("duplicate migration path")
    completed=s["completed_paths"]
    if not isinstance(completed,list) or len(completed)!=len(set(completed)) or not set(completed)<=set(paths):raise ValueError("completed_paths invalid")
    for name in ("operation_budget","per_item_operations","finalization_reserve_operations"):
        if type(s[name]) is not int or s[name]<=0:raise ValueError(f"{name} must be positive integer")
    if type(s["batch_overhead_operations"]) is not int or s["batch_overhead_operations"]<0:raise ValueError("batch_overhead_operations invalid")
    if not isinstance(s["detached_checkpoints"],list):raise ValueError("detached_checkpoints must be list")
    last=-1
    for cp in s["detached_checkpoints"]:
        if not isinstance(cp,dict) or set(cp)!={"completed_count","tree_sha"}:raise ValueError("detached checkpoint invalid")
        count=cp["completed_count"]
        if type(count) is not int or count<=last or count>len(completed) or not SHA.fullmatch(cp["tree_sha"]):raise ValueError("detached checkpoint ordering/identity invalid")
        last=count
    for name in ("final_tree_sha","observed_subtree_tree"):
        if s[name] is not None and (not isinstance(s[name],str) or not SHA.fullmatch(s[name])):raise ValueError(f"{name} invalid")
    if not SHA.fullmatch(s["expected_subtree_tree"]):raise ValueError("expected_subtree_tree invalid")
    if type(s["policy_reconciled"]) is not bool:raise ValueError("policy_reconciled must be boolean")
    if s["final_tree_sha"] is not None and len(completed)!=len(paths):raise ValueError("final tree cannot exist before all items complete")
    if s["observed_subtree_tree"] is not None and s["final_tree_sha"] is None:raise ValueError("observed subtree requires final tree")
    return s
def plan(s):
    validate(s);completed=set(s["completed_paths"]);remaining=[i["path"] for i in s["items"] if i["path"] not in completed]
    common={"schema":OUT,"transaction_id":s["transaction_id"],"source_head":s["source_head"],"target_ref":s["target_ref"],"checkpoint_kind":"detached_tree","authorizes_product_write":False,"authorizes_ref_move":False}
    if remaining:
        usable=s["operation_budget"]-s["finalization_reserve_operations"]-s["batch_overhead_operations"];capacity=max(0,usable//s["per_item_operations"])
        if capacity<1:return {**common,"action":"BLOCKED_BUDGET","batch_paths":[],"batch_operation_cost":0,"ref_move_prerequisites_satisfied":False,"reason":"reserve_would_be_consumed"}
        batch=remaining[:capacity];cost=s["batch_overhead_operations"]+len(batch)*s["per_item_operations"]
        return {**common,"action":"APPLY_BATCH","batch_paths":batch,"batch_operation_cost":cost,"ref_move_prerequisites_satisfied":False,"reason":"bounded_detached_tree_batch"}
    if s["final_tree_sha"] is None:return {**common,"action":"BUILD_FINAL_TREE","batch_paths":[],"batch_operation_cost":0,"ref_move_prerequisites_satisfied":False,"reason":"all_items_completed"}
    if s["observed_subtree_tree"] is None:return {**common,"action":"VERIFY_FINAL_SUBTREE","batch_paths":[],"batch_operation_cost":0,"ref_move_prerequisites_satisfied":False,"reason":"exact_subtree_not_observed"}
    if s["observed_subtree_tree"]!=s["expected_subtree_tree"]:return {**common,"action":"RECONCILE_TREE_DRIFT","batch_paths":[],"batch_operation_cost":0,"ref_move_prerequisites_satisfied":False,"reason":"subtree_identity_mismatch"}
    if not s["policy_reconciled"]:return {**common,"action":"RECONCILE_POLICY","batch_paths":[],"batch_operation_cost":0,"ref_move_prerequisites_satisfied":False,"reason":"policy_not_reconciled_on_fresh_head"}
    return {**common,"action":"READY_TO_ADVANCE_REF","batch_paths":[],"batch_operation_cost":0,"ref_move_prerequisites_satisfied":True,"reason":"exact_tree_and_policy_converged"}
def _manifest_item(item):
    if "blob_sha1" in item:
        return {"path":item["path"],"object_type":"blob","object_sha1":item["blob_sha1"]}
    return {"path":item["path"],"object_type":item["object_type"],"object_sha1":item["object_sha1"]}

def _manifest_digest(manifest):
    raw=json.dumps(manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def validate_assembly_record(value):
    fields={"schema","transaction_id","source_head","target_ref","target_version","target_release_ref",
            "target_release_commit","final_tree_sha","expected_subtree_tree","manifest","manifest_digest",
            "completed_at_utc"}
    if not isinstance(value,dict) or set(value)!=fields or value.get("schema")!="migration-assembly-record/v1":
        raise ValueError("migration assembly record invalid")
    if not isinstance(value["transaction_id"],str) or not value["transaction_id"].strip():raise ValueError("assembly transaction_id invalid")
    if not SHA.fullmatch(value["source_head"]) or not SHA.fullmatch(value["target_release_commit"]) or not SHA.fullmatch(value["final_tree_sha"]) or not SHA.fullmatch(value["expected_subtree_tree"]):
        raise ValueError("assembly Git identity invalid")
    if not isinstance(value["target_ref"],str) or not value["target_ref"].startswith("refs/heads/"):raise ValueError("assembly target_ref invalid")
    if not isinstance(value["target_release_ref"],str) or not value["target_release_ref"].startswith("refs/heads/release/"):raise ValueError("assembly target_release_ref invalid")
    if not isinstance(value["target_version"],str) or not re.fullmatch(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",value["target_version"]):raise ValueError("assembly target_version invalid")
    if not isinstance(value["completed_at_utc"],str) or not value["completed_at_utc"].endswith("Z"):raise ValueError("assembly completion timestamp invalid")
    if not isinstance(value["manifest"],list) or not value["manifest"]:raise ValueError("assembly manifest invalid")
    seen=set()
    for item in value["manifest"]:
        if not isinstance(item,dict) or set(item)!={"path","object_type","object_sha1"}:raise ValueError("assembly manifest item invalid")
        path=item["path"]
        if not isinstance(path,str) or not PATH.fullmatch(path) or path.startswith("/") or path.endswith("/") or any(p in {"",".",".."} for p in path.split("/")):raise ValueError("assembly manifest path invalid")
        if item["object_type"] not in {"blob","tree"} or not SHA.fullmatch(item["object_sha1"]):raise ValueError("assembly manifest object invalid")
        if path in seen:raise ValueError("duplicate assembly manifest path")
        seen.add(path)
    if value["manifest_digest"]!=_manifest_digest(value["manifest"]):raise ValueError("assembly manifest digest mismatch")
    return value

def assembly_record(state,*,target_version,target_release_ref,target_release_commit,completed_at_utc):
    if plan(state)["action"]!="READY_TO_ADVANCE_REF":
        raise ValueError("migration transaction is not complete enough to produce assembly authority")
    manifest=[_manifest_item(item) for item in state["items"]]
    value={"schema":"migration-assembly-record/v1","transaction_id":state["transaction_id"],
           "source_head":state["source_head"],"target_ref":state["target_ref"],"target_version":target_version,
           "target_release_ref":target_release_ref,"target_release_commit":target_release_commit,
           "final_tree_sha":state["final_tree_sha"],"expected_subtree_tree":state["expected_subtree_tree"],
           "manifest":manifest,"manifest_digest":_manifest_digest(manifest),"completed_at_utc":completed_at_utc}
    return validate_assembly_record(value)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("state");a=p.parse_args(argv)
    try:r=plan(json.loads(Path(a.state).read_text(encoding="utf-8")))
    except (OSError,ValueError,json.JSONDecodeError) as exc:print(f"FAIL: {exc}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"]!="BLOCKED_BUDGET" else 1
if __name__=="__main__":raise SystemExit(main())
