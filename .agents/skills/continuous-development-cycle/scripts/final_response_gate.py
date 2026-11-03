#!/usr/bin/env python3
"""Fail closed before a final response when this invocation acquired a lease."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
from execution_lease_v2 import validate as validate_lease
from execution_continuity import evaluate as evaluate_continuity

REVISION=re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

def _release_receipt(value):
    if not isinstance(value,dict) or set(value)!={"schema","lease_revision","release"} or value.get("schema")!="execution-release-receipt/v1":
        raise ValueError("release_receipt invalid")
    if not isinstance(value["lease_revision"],str) or not REVISION.fullmatch(value["lease_revision"]):
        raise ValueError("release receipt revision invalid")
    release=value["release"]
    fields={"owner_id","generation","invocation_id","at_utc","checkpoint_ref","external_reconciliation","completion_reason"}
    if not isinstance(release,dict) or set(release)!=fields:
        raise ValueError("release receipt payload invalid")
    return release

def release_boundary(invocation_id,lease,continuity,owned_lease=None,release_receipt=None,release_record=None,now_utc=None,*,reporting_authority=None):
    if not isinstance(invocation_id,str) or not invocation_id.strip():raise ValueError("invocation_id invalid")
    validate_lease(lease)
    if not isinstance(continuity,dict) or continuity.get("invocation_id")!=invocation_id:
        raise ValueError("continuity must bind exact invocation")
    common={"schema":"final-response-gate-result/v1","authorizes_product_write":False,"authorizes_takeover":False,
            "authorizes_external_start":False,"authorizes_merge":False,"authorizes_release":False}
    if owned_lease is not None:
        if not isinstance(owned_lease,dict) or set(owned_lease)!={"owner_id","generation"}:
            raise ValueError("owned_lease invalid")
        if type(owned_lease["generation"]) is not int or owned_lease["generation"]<0:raise ValueError("owned generation invalid")
        if lease["owner_id"]==owned_lease["owner_id"] and lease["generation"]==owned_lease["generation"]:
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"invocation_still_owns_exact_generation"}
        if release_receipt is None:
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"durable_release_receipt_required"}
        rel=_release_receipt(release_receipt)
        if release_record is None:
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"authoritative_release_revision_readback_required"}
        validate_lease(release_record)
        if (release_record.get("owner_id") is not None or release_record.get("generation")!=rel.get("generation")
                or release_record.get("last_release")!=rel):
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"release_receipt_revision_mismatch"}
        exact=bool(rel.get("owner_id")==owned_lease["owner_id"] and rel.get("generation")==owned_lease["generation"]
                   and rel.get("invocation_id")==invocation_id)
        if not exact:
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"exact_owned_generation_release_not_proven"}
        if continuity.get("checkpoint_ref")!=rel.get("checkpoint_ref"):
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"continuity_release_checkpoint_mismatch"}
        if continuity.get("lease_released") is not True or continuity.get("lease_release_required") is not True:
            return {**common,"allowed":False,"final_response_allowed":False,"reason":"continuity_does_not_record_post_release_state"}
    if continuity.get('schema')!='execution-continuity/v2':
        return {**common,'allowed':False,'final_response_allowed':False,'reason':'current_authentic_reporting_binding_required'}
    decision=evaluate_continuity(continuity,now_utc=now_utc,reporting_authority=reporting_authority)
    if not decision["allowed"] or decision.get("ready_for_native_closeout") is not True:
        return {**common,"allowed":False,"final_response_allowed":False,"reason":decision["reason"]}
    # A sealed inventory binding authenticates reporting, not caller-supplied
    # lease/release snapshots. Join those independently again at this boundary.
    native=reporting_authority.lease_store
    revision,actual=native.read()
    original=native.read_revision(decision['reporting']['historical_owned_revision'])
    if actual!=lease:
        return {**common,'allowed':False,'final_response_allowed':False,'reason':'current_canonical_lease_snapshot_mismatch'}
    if owned_lease!={'owner_id':original['owner_id'],'generation':original['generation']} or release_receipt is None:
        return {**common,'allowed':False,'final_response_allowed':False,'reason':'native_original_owned_release_binding_required'}
    if native.read_revision(release_receipt['lease_revision'])!=release_record:
        return {**common,'allowed':False,'final_response_allowed':False,'reason':'canonical_historical_release_snapshot_mismatch'}
    if native.read()!=(revision,actual):
        return {**common,'allowed':False,'final_response_allowed':False,'reason':'canonical_lease_changed_during_final_readback'}
    return {**common,"allowed":True,"release_boundary_allowed":True,"final_response_allowed":False,"controller_exit_required":True,"reason":"verified_preparatory_release_reporting_rca_boundary","reporting":decision['reporting'],'current_lease_revision':revision}

def evaluate(invocation_id,lease,continuity,owned_lease=None,release_receipt=None,release_record=None,now_utc=None,*,reporting_authority=None,native_terminal=None):
    boundary=release_boundary(invocation_id,lease,continuity,owned_lease,release_receipt,release_record,now_utc,reporting_authority=reporting_authority)
    if not boundary['allowed']:return boundary
    from managed_executor_runtime import VerifiedTerminalProof
    if type(native_terminal) is not VerifiedTerminalProof:
        return {**boundary,'allowed':False,'final_response_allowed':False,'reason':'authentic_original_controller_terminal_proof_required'}
    proof=native_terminal.revalidate_for(reporting_authority.lease_store,invocation_id,owned_lease,release_receipt)
    return {**boundary,'allowed':True,'final_response_allowed':True,'controller_exit_required':False,'reason':'verified_native_owner_final_boundary','native_terminal':proof}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("request");p.add_argument("--now")
    p.add_argument("--repo");p.add_argument("--remote");p.add_argument("--coordination-ref");a=p.parse_args(argv)
    try:
        d=json.loads(Path(a.request).read_text(encoding="utf-8"))
        fields={"schema","invocation_id","owned_lease","release_receipt","lease","continuity","runtime_binding"}
        if not isinstance(d,dict) or set(d)!=fields or d.get("schema")!="final-response-gate/v2":raise ValueError("request invalid")
        release_record=None
        if d["owned_lease"] is not None:
            if not (a.repo and a.remote and a.coordination_ref):
                raise ValueError("owned final-response gate requires coordination store for release readback")
            if d["release_receipt"] is None:
                raise ValueError("owned final-response gate requires release receipt")
            from git_lease_store import GitLeaseStore
            store=GitLeaseStore(a.repo,a.remote,a.coordination_ref)
            release_record=store.read_revision(d["release_receipt"]["lease_revision"])
        if not (a.repo and a.remote and a.coordination_ref):raise ValueError('current final response requires canonical reporting store')
        from git_lease_store import GitLeaseStore
        from reporting_contract import authenticate
        authority=authenticate(GitLeaseStore(a.repo,a.remote,a.coordination_ref),d['continuity'].get('reporting_binding'),d['invocation_id'],d['continuity']['checkpoint_ref'])
        from managed_host_bridge import _load_session,_runtime,_lease_store
        binding=d['runtime_binding']
        if not isinstance(binding,dict) or set(binding)!={'handle_root','handle_id'}:raise ValueError('original runtime binding required')
        session=_load_session(binding['handle_root'],binding['handle_id'])
        original=_lease_store(session)
        if (original.store_id,original.ref)!=(authority.lease_store.store_id,authority.lease_store.ref):raise ValueError('final runtime endpoint substituted')
        proof=_runtime(session).verify_terminal(session['task_id'],session['attempt_id'],include_controller=True,lease_store=original,release_receipt=d['release_receipt'])
        r=evaluate(d["invocation_id"],d["lease"],d["continuity"],d["owned_lease"],
                   d["release_receipt"],release_record,None,reporting_authority=authority,native_terminal=proof)
    except (OSError,ValueError,json.JSONDecodeError) as e:print("FAIL:",e,file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["allowed"] else 1
if __name__=="__main__":raise SystemExit(main())
