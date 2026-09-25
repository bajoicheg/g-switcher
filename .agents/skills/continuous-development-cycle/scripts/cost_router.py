#!/usr/bin/env python3
"""CDC 2.7.2 cost-aware compute routing; recommendation only."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

import capability_router as capability

POLICY_SCHEMA="compute-cost-policy/v1"
CONTEXT_SCHEMA="compute-cost-context/v1"
EVIDENCE_CLASSES={"portable","platform","artifact","release_attestation"}
FAILURES={"none","setup","network","provider","runtime","product","incompatible"}
EXPENSIVE_REASONS={"required_capability","final_platform","artifact","release_attestation","confirmed_provider_outage"}

def _time(value,name,nullable=False):
    if value is None and nullable:return None
    if not isinstance(value,str) or not value.endswith("Z"):raise ValueError(f"{name} must be UTC Z timestamp")
    try:return datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc:raise ValueError(f"{name} invalid timestamp") from exc

def _tokens(value,name):
    if not isinstance(value,list) or any(not isinstance(x,str) or not x.strip() for x in value):
        raise ValueError(f"{name} must be list of nonempty strings")
    if len(set(value))!=len(value):raise ValueError(f"{name} contains duplicates")
    return value

def validate_policy(policy):
    fields={"schema","primary_kind","kind_cost_weights","expensive_kinds","transient_failure_classes",
            "product_failure_classes","bounded_primary_recovery_attempts","probe_cooldown_seconds",
            "provider_outage_confirmation_required","expensive_fallback_reasons",
            "portable_wait_instead_of_expensive_fallback","github_actions_requires_reason"}
    if not isinstance(policy,dict) or set(policy)!=fields or policy["schema"]!=POLICY_SCHEMA:
        raise ValueError("invalid compute cost policy")
    if policy["primary_kind"] not in capability.KINDS:raise ValueError("unsupported primary kind")
    weights=policy["kind_cost_weights"]
    if not isinstance(weights,dict) or set(weights)!=capability.KINDS:raise ValueError("kind_cost_weights must cover every backend kind")
    if any(type(v) is not int or v<0 for v in weights.values()):raise ValueError("cost weights must be nonnegative integers")
    expensive=set(_tokens(policy["expensive_kinds"],"expensive_kinds"))
    if not expensive or not expensive<=capability.KINDS:raise ValueError("invalid expensive_kinds")
    transient=set(_tokens(policy["transient_failure_classes"],"transient_failure_classes"))
    product=set(_tokens(policy["product_failure_classes"],"product_failure_classes"))
    if not transient<=FAILURES or not product<=FAILURES or transient&product:raise ValueError("invalid failure classes")
    if type(policy["bounded_primary_recovery_attempts"]) is not int or policy["bounded_primary_recovery_attempts"]<1:
        raise ValueError("bounded_primary_recovery_attempts must be positive integer")
    if type(policy["probe_cooldown_seconds"]) is not int or policy["probe_cooldown_seconds"]<0:
        raise ValueError("probe_cooldown_seconds must be nonnegative integer")
    for name in ("provider_outage_confirmation_required","portable_wait_instead_of_expensive_fallback","github_actions_requires_reason"):
        if type(policy[name]) is not bool:raise ValueError(f"{name} must be boolean")
    reasons=set(_tokens(policy["expensive_fallback_reasons"],"expensive_fallback_reasons"))
    if not reasons<=EXPENSIVE_REASONS:raise ValueError("unsupported expensive fallback reason")
    return policy

def validate_context(context):
    fields={"schema","evidence_class","primary_failure_class","distinct_primary_recovery_attempts",
            "provider_outage_confirmed","required_capability_gap_on_primary","last_primary_failure_at_utc"}
    if not isinstance(context,dict) or set(context)!=fields or context["schema"]!=CONTEXT_SCHEMA:
        raise ValueError("invalid compute cost context")
    if context["evidence_class"] not in EVIDENCE_CLASSES:raise ValueError("unsupported evidence_class")
    if context["primary_failure_class"] not in FAILURES:raise ValueError("unsupported primary_failure_class")
    if type(context["distinct_primary_recovery_attempts"]) is not int or context["distinct_primary_recovery_attempts"]<0:
        raise ValueError("distinct_primary_recovery_attempts must be nonnegative integer")
    for name in ("provider_outage_confirmed","required_capability_gap_on_primary"):
        if type(context[name]) is not bool:raise ValueError(f"{name} must be boolean")
    _time(context["last_primary_failure_at_utc"],"last_primary_failure_at_utc",nullable=True)
    return context

def _result(action,reason,backend=None,*,expensive=False,expensive_reason=None,retry_after_seconds=None,missing=None):
    return {"action":action,"reason":reason,"backend_id":None if backend is None else backend["backend_id"],
            "backend_kind":None if backend is None else backend["kind"],
            "expensive_fallback":expensive,"expensive_reason":expensive_reason,
            "retry_after_seconds":retry_after_seconds,"missing_by_backend":missing or {},
            "authorizes_external_start":False,"authorizes_product_write":False,
            "authorizes_takeover":False,"authorizes_scheduler_mutation":False}

def route(registry,request,policy,context,now_utc):
    capability.validate_registry(registry);capability.validate_request(request)
    validate_policy(policy);validate_context(context)
    now=_time(now_utc,"now_utc");observed=_time(registry["observed_at_utc"],"registry.observed_at_utc")
    age=(now-observed).total_seconds()
    if age<0:return _result("blocked","registry_from_future")
    if age>request["max_registry_age_seconds"]:return _result("blocked","registry_stale")

    required=set(request["required_capabilities"]); forbidden=set(request["forbidden_backend_ids"])
    weights=policy["kind_cost_weights"]; expensive_kinds=set(policy["expensive_kinds"]); missing={}
    compatible=[]; ready=[]; primary=[]
    for backend in registry["backends"]:
        if request["required_backend_id"] is not None and backend["backend_id"]!=request["required_backend_id"]:continue
        absent=sorted(required-set(backend["capabilities"]))
        if absent:missing[backend["backend_id"]]=absent
        if backend["backend_id"] in forbidden or not backend["enabled"] or absent:continue
        compatible.append(backend)
        if backend["kind"]==policy["primary_kind"]:primary.append(backend)
        if backend["state"]=="ready":ready.append(backend)

    def order(backend):
        return (weights[backend["kind"]],0 if backend["kind"]==policy["primary_kind"] else 1,backend["rank"],backend["backend_id"])
    ready.sort(key=order); compatible.sort(key=order); primary.sort(key=order)
    cheap_ready=[b for b in ready if b["kind"] not in expensive_kinds]
    expensive_ready=[b for b in ready if b["kind"] in expensive_kinds]
    failure=context["primary_failure_class"]

    if failure in set(policy["product_failure_classes"]):
        return _result("blocked","product_failure_requires_fix_before_more_compute",missing=missing)

    if cheap_ready:
        return _result("route","lowest_cost_compatible_ready_backend",cheap_ready[0],missing=missing)

    cheap_compatible=[b for b in compatible if b["kind"] not in expensive_kinds]
    if not cheap_compatible:
        if not expensive_ready:return _result("waiting_compute","no_compatible_ready_backend",missing=missing)
        reason={"platform":"final_platform","artifact":"artifact","release_attestation":"release_attestation"}.get(context["evidence_class"],"required_capability")
        if reason not in set(policy["expensive_fallback_reasons"]):
            return _result("waiting_compute","expensive_fallback_reason_not_allowed",missing=missing)
        return _result("route","expensive_backend_required_by_capability_or_evidence",expensive_ready[0],
                       expensive=True,expensive_reason=reason,missing=missing)

    if failure=="incompatible" or context["required_capability_gap_on_primary"]:
        if expensive_ready and "required_capability" in set(policy["expensive_fallback_reasons"]):
            return _result("route","primary_incompatible_expensive_backend_required",expensive_ready[0],
                           expensive=True,expensive_reason="required_capability",missing=missing)
        return _result("waiting_compute","primary_incompatible_no_authorized_compatible_backend",missing=missing)

    if failure in set(policy["transient_failure_classes"]):
        last=_time(context["last_primary_failure_at_utc"],"last_primary_failure_at_utc",nullable=True)
        if last is not None:
            elapsed=(now-last).total_seconds()
            if elapsed<0:return _result("blocked","primary_failure_from_future",missing=missing)
            if elapsed<policy["probe_cooldown_seconds"]:
                return _result("waiting_compute","primary_probe_cooldown",retry_after_seconds=policy["probe_cooldown_seconds"]-int(elapsed),missing=missing)
        if context["distinct_primary_recovery_attempts"]<policy["bounded_primary_recovery_attempts"]:
            backend=primary[0] if primary else cheap_compatible[0]
            return _result("probe_primary","bounded_low_cost_primary_recovery",backend,missing=missing)
        outage_ok=context["provider_outage_confirmed"] or not policy["provider_outage_confirmation_required"]
        if outage_ok and expensive_ready:
            if "confirmed_provider_outage" in set(policy["expensive_fallback_reasons"]):
                return _result("route","confirmed_primary_provider_outage",expensive_ready[0],
                               expensive=True,expensive_reason="confirmed_provider_outage",missing=missing)
        return _result("waiting_compute","primary_recovery_exhausted_without_confirmed_outage",missing=missing)

    if expensive_ready and not policy["portable_wait_instead_of_expensive_fallback"]:
        reason="required_capability"
        if reason in set(policy["expensive_fallback_reasons"]):
            return _result("route","policy_allows_expensive_fallback",expensive_ready[0],expensive=True,expensive_reason=reason,missing=missing)
    return _result("waiting_compute","compatible_low_cost_backend_not_ready",missing=missing)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("registry");p.add_argument("request");p.add_argument("policy");p.add_argument("context");p.add_argument("--now",required=True)
    a=p.parse_args(argv)
    try:
        result=route(*(json.loads(Path(x).read_text()) for x in (a.registry,a.request,a.policy,a.context)),a.now)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}",file=sys.stderr);return 2
    print(json.dumps(result,sort_keys=True))
    return 0 if result["action"]=="route" else 1

if __name__=="__main__":
    raise SystemExit(main())
