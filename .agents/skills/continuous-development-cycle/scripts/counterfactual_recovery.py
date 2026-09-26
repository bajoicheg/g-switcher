#!/usr/bin/env python3
"""CDC 2.8.2 enforces information-gaining recovery after repeated failures."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
def choose(d):
    f={"schema","failed_strategies","candidate_strategies"}
    if not isinstance(d,dict) or set(d)!=f or d.get("schema")!="counterfactual-recovery/v1":raise ValueError("counterfactual input invalid")
    failed=d["failed_strategies"];candidates=d["candidate_strategies"]
    if not isinstance(failed,list) or not isinstance(candidates,list):raise ValueError("strategies invalid")
    prior={x["strategy_id"] for x in failed}
    for x in failed:
        if not isinstance(x,dict) or set(x)!={"strategy_id","failure_class","information_gain"}:raise ValueError("failed strategy invalid")
    viable=[]
    for c in candidates:
        if not isinstance(c,dict) or set(c)!={"strategy_id","expected_information_gain","compatible","cost_rank"}:raise ValueError("candidate strategy invalid")
        if c["strategy_id"] in prior or not c["compatible"]:continue
        if type(c["expected_information_gain"]) not in (int,float) or c["expected_information_gain"]<=0:continue
        viable.append(c)
    viable.sort(key=lambda x:(-x["expected_information_gain"],x["cost_rank"],x["strategy_id"]))
    if not viable:return {"schema":"counterfactual-recovery-plan/v1","action":"BLOCKED","strategy_id":None,"reason":"no_new_information_gaining_strategy","authorizes_external_start":False}
    return {"schema":"counterfactual-recovery-plan/v1","action":"TRY_NEW_STRATEGY","strategy_id":viable[0]["strategy_id"],"reason":"different_information_gaining_strategy","authorizes_external_start":False}
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("input");a=p.parse_args(argv)
 try:r=choose(json.loads(Path(a.input).read_text()))
 except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
 print(json.dumps(r,sort_keys=True));return 0 if r["action"]=="TRY_NEW_STRATEGY" else 1
if __name__=="__main__":raise SystemExit(main())
