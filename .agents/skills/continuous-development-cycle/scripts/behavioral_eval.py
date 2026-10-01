#!/usr/bin/env python3
"""CDC 2.10 behavioral pressure-scenario RED→GREEN regression evaluator."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

SCHEMA="behavioral-eval-suite/v1"
CASE_SCHEMA="behavioral-eval-case/v1"
SCENARIOS={
    "premature_milestone_stop",
    "terminal_provider_stale_guard",
    "schema_invalid_checkpoint",
    "duplicate_command_timestamp",
    "stale_checkpoint_vs_live_lease",
    "unchanged_recovery_retry",
    "orphan_owned_final_response",
    "dual_fleet_supervisor",
    "partial_consumer_adoption",
    "successor_release_receipt",
}

def _text(v,n):
    if not isinstance(v,str) or not v.strip():
        raise ValueError(f"{n} must be nonempty text")

def _trace(v,n):
    if not isinstance(v,list) or not v or any(not isinstance(x,str) or not x.strip() for x in v):
        raise ValueError(f"{n} must be a nonempty list of event strings")
    return v

def _facts(case, expected):
    facts=case["facts"]
    if not isinstance(facts,dict) or set(facts)!=set(expected):
        raise ValueError(f"{case['scenario_type']} facts mismatch")
    for k,t in expected.items():
        if type(facts[k]) is not t:
            raise ValueError(f"{case['scenario_type']} fact {k} has wrong type")
    return facts

def validate_case(case):
    fields={"schema","scenario_id","scenario_type","facts","baseline_trace","corrected_trace"}
    if not isinstance(case,dict) or set(case)!=fields or case.get("schema")!=CASE_SCHEMA:
        raise ValueError("behavioral case fields/schema mismatch")
    _text(case["scenario_id"],"scenario_id")
    if case["scenario_type"] not in SCENARIOS:
        raise ValueError("unsupported behavioral scenario")
    _trace(case["baseline_trace"],"baseline_trace");_trace(case["corrected_trace"],"corrected_trace")
    kind=case["scenario_type"]
    if kind=="premature_milestone_stop":
        _facts(case,{"runnable_work":bool})
    elif kind=="terminal_provider_stale_guard":
        f=_facts(case,{"provider_state":str,"guard_state":str})
        if f["provider_state"]!="terminal" or f["guard_state"]!="running":
            raise ValueError("provider/guard facts must represent terminal-provider stale-guard pressure")
    elif kind=="schema_invalid_checkpoint":
        f=_facts(case,{"checkpoint_initial_valid":bool})
        if f["checkpoint_initial_valid"]:
            raise ValueError("checkpoint pressure requires initial invalid state")
    elif kind=="duplicate_command_timestamp":
        _facts(case,{"command_id":str})
    elif kind=="stale_checkpoint_vs_live_lease":
        f=_facts(case,{"checkpoint_lease_state":str,"coordination_lease_state":str})
        if f["checkpoint_lease_state"]!="released" or f["coordination_lease_state"]!="active":
            raise ValueError("ownership pressure requires stale released checkpoint and active coordination")
    elif kind=="unchanged_recovery_retry":
        _facts(case,{"failed_strategy":str})
    elif kind=="orphan_owned_final_response":
        f=_facts(case,{"lease_owned":bool,"runtime_state":str,"pending_effects":bool})
        if not f["lease_owned"] or f["runtime_state"]!="stopped" or f["pending_effects"]:
            raise ValueError("orphan pressure facts invalid")
    elif kind=="dual_fleet_supervisor":
        f=_facts(case,{"same_initial_revision":bool})
        if not f["same_initial_revision"]:
            raise ValueError("dual supervisor pressure requires same initial revision")
    elif kind=="partial_consumer_adoption":
        _facts(case,{"target_version":str})
    elif kind=="successor_release_receipt":
        f=_facts(case,{"first_generation":int,"successor_generation":int})
        if f["successor_generation"]<=f["first_generation"]:
            raise ValueError("successor release pressure generations invalid")
    return case

def _before(trace,a,b):
    return a in trace and b in trace and trace.index(a)<trace.index(b)

def judge(case,trace):
    validate_case(case)
    kind=case["scenario_type"];facts=case["facts"]
    if kind=="premature_milestone_stop":
        if not facts["runnable_work"]:
            return True,"no_runnable_pressure"
        premature="final_response" in trace and "terminal_complete" not in trace[:trace.index("final_response")]
        ok=("progress_update" in trace and "continue" in trace and "terminal_complete" in trace and
            "final_response" in trace and _before(trace,"continue","terminal_complete") and
            _before(trace,"terminal_complete","final_response") and not premature)
        return ok, "continued_to_verified_terminal" if ok else "premature_or_missing_continuation"
    if kind=="terminal_provider_stale_guard":
        ok=("observe_provider_terminal" in trace and "reconcile_provider" in trace and
            "takeover" not in trace and _before(trace,"observe_provider_terminal","reconcile_provider"))
        return ok,"exact_provider_reconciled_without_takeover" if ok else "stale_guard_not_reconciled_safely"
    if kind=="schema_invalid_checkpoint":
        ordered=("validate_checkpoint:reject" in trace and "build_typed_checkpoint" in trace and
                 "validate_checkpoint:pass" in trace and "commit_checkpoint:valid" in trace and
                 _before(trace,"validate_checkpoint:reject","build_typed_checkpoint") and
                 _before(trace,"build_typed_checkpoint","validate_checkpoint:pass") and
                 _before(trace,"validate_checkpoint:pass","commit_checkpoint:valid"))
        ok=ordered and "commit_checkpoint:invalid" not in trace
        return ok,"invalid_rejected_then_typed_green" if ok else "invalid_checkpoint_crossed_commit_boundary"
    if kind=="duplicate_command_timestamp":
        stamps=[x for x in trace if x.startswith("timestamp:")]
        ok=len(stamps)==1 and "suppress_duplicate_timestamp" in trace
        return ok,"exactly_one_timestamp" if ok else "timestamp_cardinality_violation"
    if kind=="stale_checkpoint_vs_live_lease":
        ok=("read_live_coordination" in trace and "authority:coordination" in trace and
            "authority:checkpoint" not in trace and "takeover" not in trace)
        return ok,"live_coordination_wins" if ok else "stale_checkpoint_used_as_authority"
    if kind=="unchanged_recovery_retry":
        failed=facts["failed_strategy"]
        same=f"retry:{failed}"
        new=[x for x in trace if x.startswith("retry:") and x!=same]
        ok=(f"failure:{failed}" in trace and same not in trace and
            ("block:needs_new_strategy" in trace or bool(new)))
        return ok,"strategy_changed_or_bounded_block" if ok else "unchanged_failed_strategy_retried"
    if kind=="orphan_owned_final_response":
        ok=("runtime:stopped" in trace and "classify:orphaned_recoverable" in trace
            and "gate:block_owned" in trace and "release" in trace and "release_receipt" in trace
            and "final_response" in trace and _before(trace,"release","release_receipt")
            and _before(trace,"release_receipt","final_response") and "status:active" not in trace)
        return ok,"orphan_released_before_final_response" if ok else "ghost_owner_or_premature_final_response"
    if kind=="dual_fleet_supervisor":
        effects=[x for x in trace if x.startswith("provider_effect:")]
        ok=("cas:a:leader" in trace and "cas:b:stale" in trace and len(effects)==1
            and _before(trace,"cas:a:leader",effects[0]))
        return ok,"single_cas_leader_single_effect" if ok else "dual_leader_or_duplicate_effect"
    if kind=="partial_consumer_adoption":
        ordered=all(x in trace for x in ("prepare:detached","verify:package_tree","claim:conditional_publish",
                                        "conditional_fast_forward","readback:package_tree"))
        if ordered:
            ordered=(_before(trace,"prepare:detached","verify:package_tree")
                     and _before(trace,"verify:package_tree","claim:conditional_publish")
                     and _before(trace,"claim:conditional_publish","conditional_fast_forward")
                     and _before(trace,"conditional_fast_forward","readback:package_tree"))
        ok=ordered and "shared_ref:partial_target" not in trace
        return ok,"single_atomic_publish_after_exact_tree" if ok else "partial_target_exposed_or_publish_unverified"
    if kind=="successor_release_receipt":
        ordered=all(x in trace for x in ("release:g1","capture_receipt:g1","release:g2","verify_receipt:g1","final_response:g1"))
        if ordered:
            ordered=(_before(trace,"release:g1","capture_receipt:g1")
                     and _before(trace,"capture_receipt:g1","release:g2")
                     and _before(trace,"release:g2","verify_receipt:g1")
                     and _before(trace,"verify_receipt:g1","final_response:g1"))
        ok=ordered and "final_response:g1:blocked" not in trace
        return ok,"immutable_prior_release_receipt_survives_successor" if ok else "mutable_last_release_erased_prior_proof"
    raise AssertionError(kind)

def evaluate_case(case):
    baseline_ok,baseline_reason=judge(case,case["baseline_trace"])
    corrected_ok,corrected_reason=judge(case,case["corrected_trace"])
    return {
        "scenario_id":case["scenario_id"],
        "scenario_type":case["scenario_type"],
        "baseline":"GREEN" if baseline_ok else "RED",
        "baseline_reason":baseline_reason,
        "corrected":"GREEN" if corrected_ok else "RED",
        "corrected_reason":corrected_reason,
        "regression_passed":(not baseline_ok and corrected_ok),
    }

def validate_suite(data):
    if not isinstance(data,dict) or set(data)!={"schema","cases"} or data.get("schema")!=SCHEMA:
        raise ValueError("behavioral suite fields/schema mismatch")
    if not isinstance(data["cases"],list) or not data["cases"]:
        raise ValueError("behavioral suite requires cases")
    ids=set();types=[]
    for case in data["cases"]:
        validate_case(case)
        if case["scenario_id"] in ids: raise ValueError("duplicate behavioral scenario_id")
        ids.add(case["scenario_id"]);types.append(case["scenario_type"])
    missing=SCENARIOS-set(types)
    if missing:
        raise ValueError("behavioral suite missing core scenarios: "+", ".join(sorted(missing)))
    return data

def evaluate_suite(data):
    validate_suite(data)
    results=[evaluate_case(c) for c in data["cases"]]
    passed=sum(1 for r in results if r["regression_passed"])
    return {
        "schema":"behavioral-eval-result/v1",
        "cases":results,
        "case_count":len(results),
        "passed":passed,
        "all_regressions_green":passed==len(results),
        "authorizes_product_write":False,
        "authorizes_takeover":False,
        "authorizes_release":False,
        "authorizes_scope_expansion":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("suite");a=p.parse_args(argv)
    try:r=evaluate_suite(json.loads(Path(a.suite).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["all_regressions_green"] else 1

if __name__=="__main__":
    raise SystemExit(main())
