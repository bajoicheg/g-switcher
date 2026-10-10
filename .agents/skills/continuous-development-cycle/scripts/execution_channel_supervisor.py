#!/usr/bin/env python3
"""CDC 2.8 execution-channel supervisor with bounded automatic failover."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from capability_router import validate_registry, validate_request
from cost_router import validate_policy, validate_context, route as cost_route

SCHEMA="channel-supervision/v1"
def validate(supervision):
    fields={"schema","attempted_backend_ids","failure_classes","max_failovers"}
    if not isinstance(supervision,dict) or set(supervision)!=fields or supervision.get("schema")!=SCHEMA:raise ValueError("invalid channel supervision state")
    if not isinstance(supervision["attempted_backend_ids"],list) or any(not isinstance(x,str) or not x.strip() for x in supervision["attempted_backend_ids"]):raise ValueError("attempted_backend_ids invalid")
    if len(set(supervision["attempted_backend_ids"]))!=len(supervision["attempted_backend_ids"]):raise ValueError("duplicate attempted backend")
    if not isinstance(supervision["failure_classes"],dict):raise ValueError("failure_classes must be object")
    if set(supervision["failure_classes"])-set(supervision["attempted_backend_ids"]):raise ValueError("failure class without attempted backend")
    for v in supervision["failure_classes"].values():
        if v not in {"setup","network","provider","runtime","product","permission","budget","unknown"}:raise ValueError("unsupported failure class")
    if type(supervision["max_failovers"]) is not int or supervision["max_failovers"]<0:raise ValueError("max_failovers invalid")
    return supervision

def supervise(registry,request,policy,context,supervision,now_utc):
    validate_registry(registry);validate_request(request);validate_policy(policy);validate_context(context);validate(supervision)
    attempted=supervision["attempted_backend_ids"]
    if len(attempted)>supervision["max_failovers"]:
        return {"schema":"channel-supervision-result/v1","action":"BLOCKED","reason":"failover_budget_exhausted","backend_id":None,
                "attempted_backend_ids":attempted,"next_action":"persist blocker and re-evaluate capabilities","authorizes_external_start":False}
    product=[b for b in attempted if supervision["failure_classes"].get(b)=="product"]
    if product:
        return {"schema":"channel-supervision-result/v1","action":"BLOCKED","reason":"product_failure_requires_fix","backend_id":None,
                "attempted_backend_ids":attempted,"next_action":"fix product/test failure before more compute","authorizes_external_start":False}
    q=dict(request)
    q["forbidden_backend_ids"]=list(dict.fromkeys(list(q["forbidden_backend_ids"])+attempted))
    routed=cost_route(registry,q,policy,context,now_utc)
    if routed["action"]=="route":
        return {"schema":"channel-supervision-result/v1","action":"ROUTE","reason":"next_policy_authorized_backend","backend_id":routed["backend_id"],
                "backend_kind":routed["backend_kind"],"attempted_backend_ids":attempted,
                "next_action":f"submit exact-SHA work to {routed['backend_id']} through normal authority gate","authorizes_external_start":False}
    return {"schema":"channel-supervision-result/v1","action":"WAIT","reason":routed["reason"],"backend_id":None,
            "attempted_backend_ids":attempted,"next_action":"persist exact capability/cost blocker and re-probe on trigger","authorizes_external_start":False}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("registry","request","policy","context","supervision"):p.add_argument(n)
    p.add_argument("--now",required=True);a=p.parse_args(argv)
    try:
        vals=[json.loads(Path(getattr(a,n)).read_text()) for n in ("registry","request","policy","context","supervision")]
        r=supervise(*vals,a.now)
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"]=="ROUTE" else 1
if __name__=="__main__":raise SystemExit(main())
