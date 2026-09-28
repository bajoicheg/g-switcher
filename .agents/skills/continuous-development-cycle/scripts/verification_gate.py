#!/usr/bin/env python3
"""CDC 2.10 verification-before-terminal-claim gate."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path

SCHEMA="verification-gate/v1";SHA=re.compile(r"^[0-9a-f]{40}$")
CLAIMS={"COMPLETE","RELEASE_READY","INTEGRATED"}

def _text(v,n):
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be nonempty text")
def _sha(v,n):
    if not isinstance(v,str) or not SHA.fullmatch(v): raise ValueError(f"{n} must be full SHA")
def _refs(v,n,allow_empty=False):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v): raise ValueError(f"{n} invalid")
    if not allow_empty and not v: raise ValueError(f"{n} must not be empty")
    if len(v)!=len(set(v)): raise ValueError(f"{n} contains duplicates")

def validate(data):
    fields={"schema","claim_id","claim_kind","expected_head","observed_head","authoritative_source_fresh",
            "required_checks","checkpoint","ownership","artifacts","clean_state","completion_evidence_refs"}
    if not isinstance(data,dict) or set(data)!=fields or data.get("schema")!=SCHEMA:
        raise ValueError("verification gate fields/schema mismatch")
    _text(data["claim_id"],"claim_id")
    if data["claim_kind"] not in CLAIMS: raise ValueError("unsupported terminal claim")
    _sha(data["expected_head"],"expected_head");_sha(data["observed_head"],"observed_head")
    if type(data["authoritative_source_fresh"]) is not bool: raise ValueError("authoritative_source_fresh must be boolean")
    if not isinstance(data["required_checks"],list): raise ValueError("required_checks must be list")
    for i,c in enumerate(data["required_checks"]):
        if not isinstance(c,dict) or set(c)!={"id","state","candidate_sha","evidence_ref"}: raise ValueError("required check fields mismatch")
        _text(c["id"],f"check[{i}].id");_sha(c["candidate_sha"],f"check[{i}].candidate_sha");_text(c["evidence_ref"],f"check[{i}].evidence_ref")
        if c["state"] not in {"success","failed","not_run"}: raise ValueError("required check state invalid")
    cp=data["checkpoint"]
    if not isinstance(cp,dict) or set(cp)!={"required","valid","policy_current","evidence_ref"}: raise ValueError("checkpoint fields mismatch")
    for k in ("required","valid","policy_current"):
        if type(cp[k]) is not bool: raise ValueError(f"checkpoint.{k} must be boolean")
    _text(cp["evidence_ref"],"checkpoint.evidence_ref")
    own=data["ownership"]
    if not isinstance(own,dict) or set(own)!={"authoritative_source","lease_state","guard_state","evidence_ref"}: raise ValueError("ownership fields mismatch")
    if own["authoritative_source"]!="coordination": raise ValueError("ownership authority must be live coordination")
    if own["lease_state"] not in {"released","active","waiting_external"}: raise ValueError("lease_state invalid")
    if own["guard_state"] not in {"none","reconciled","active","unknown"}: raise ValueError("guard_state invalid")
    _text(own["evidence_ref"],"ownership.evidence_ref")
    if not isinstance(data["artifacts"],list): raise ValueError("artifacts must be list")
    for i,a in enumerate(data["artifacts"]):
        if not isinstance(a,dict) or set(a)!={"id","required","verified","candidate_sha","evidence_ref"}: raise ValueError("artifact fields mismatch")
        _text(a["id"],f"artifact[{i}].id");_sha(a["candidate_sha"],f"artifact[{i}].candidate_sha");_text(a["evidence_ref"],f"artifact[{i}].evidence_ref")
        if type(a["required"]) is not bool or type(a["verified"]) is not bool: raise ValueError("artifact required/verified must be boolean")
    clean=data["clean_state"]
    if not isinstance(clean,dict) or set(clean)!={"required","clean","evidence_ref"}: raise ValueError("clean_state fields mismatch")
    if type(clean["required"]) is not bool or type(clean["clean"]) is not bool: raise ValueError("clean_state booleans invalid")
    _text(clean["evidence_ref"],"clean_state.evidence_ref")
    _refs(data["completion_evidence_refs"],"completion_evidence_refs")
    return data

def evaluate(data):
    validate(data);b=[]
    expected=data["expected_head"]
    if not data["authoritative_source_fresh"]: b.append("authoritative_source_stale")
    if data["observed_head"]!=expected: b.append("source_head_mismatch")
    for c in data["required_checks"]:
        if c["state"]!="success": b.append("required_check_not_green:"+c["id"])
        elif c["candidate_sha"]!=expected: b.append("required_check_wrong_sha:"+c["id"])
    cp=data["checkpoint"]
    if cp["required"] and not cp["valid"]: b.append("checkpoint_invalid")
    if cp["required"] and not cp["policy_current"]: b.append("checkpoint_policy_stale")
    own=data["ownership"]
    if own["lease_state"]!="released": b.append("lease_not_released")
    if own["guard_state"] not in {"none","reconciled"}: b.append("guard_unreconciled")
    for a in data["artifacts"]:
        if a["required"] and not a["verified"]: b.append("artifact_unverified:"+a["id"])
        if a["required"] and a["candidate_sha"]!=expected: b.append("artifact_wrong_sha:"+a["id"])
    clean=data["clean_state"]
    if clean["required"] and not clean["clean"]: b.append("dirty_state")
    return {
        "schema":"verification-gate-result/v1","claim_id":data["claim_id"],"claim_kind":data["claim_kind"],
        "allowed":not b,"final_claim_allowed":not b,"blockers":b,
        "authorizes_product_write":False,"authorizes_takeover":False,"authorizes_external_start":False,
        "authorizes_merge":False,"authorizes_release":False,"authorizes_scope_expansion":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
    try:r=evaluate(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["allowed"] else 1

if __name__=="__main__":
    raise SystemExit(main())
