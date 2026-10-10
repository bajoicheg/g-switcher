#!/usr/bin/env python3
"""CDC 2.8.1 decision-authority classifier; recognizes existing authority, never invents it."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
def classify(r):
    f={"schema","action_id","risk","reversibility","scope","destructive","requires_secret","protected_gate","policy_preapproved","authorization_ref"}
    if not isinstance(r,dict) or set(r)!=f or r.get("schema")!="decision-request/v1":raise ValueError("decision request invalid")
    if r["risk"] not in {"low","medium","high"} or r["reversibility"] not in {"reversible","compensatable","irreversible"} or r["scope"] not in {"existing","expanded"}:raise ValueError("decision dimensions invalid")
    for n in ("destructive","requires_secret","protected_gate","policy_preapproved"):
        if type(r[n]) is not bool:raise ValueError(f"{n} invalid")
    if r["authorization_ref"] is not None and (not isinstance(r["authorization_ref"],str) or not r["authorization_ref"].strip()):raise ValueError("authorization_ref invalid")
    human=r["scope"]=="expanded" or r["destructive"] or r["requires_secret"] or r["protected_gate"] or r["reversibility"]=="irreversible" or r["risk"]=="high"
    if human:return {"schema":"decision-authority/v1","decision":"REQUIRE_HUMAN","reason":"human_boundary","within_existing_authority":False,"creates_authority":False}
    if not r["policy_preapproved"] or r["authorization_ref"] is None:
        return {"schema":"decision-authority/v1","decision":"BLOCKED","reason":"no_existing_authority","within_existing_authority":False,"creates_authority":False}
    return {"schema":"decision-authority/v1","decision":"AUTO_EXECUTE","reason":"reversible_in_scope_preapproved","within_existing_authority":True,"creates_authority":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("request");a=p.parse_args(argv)
    try:r=classify(json.loads(Path(a.request).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["decision"]=="AUTO_EXECUTE" else 1
if __name__=="__main__":raise SystemExit(main())
