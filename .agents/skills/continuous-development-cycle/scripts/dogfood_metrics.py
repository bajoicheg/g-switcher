#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
METRICS=("terminal_state_accuracy","no_idle_compliance","exact_sha_validation","recovery_diversity","control_plane_isolation","consumer_evidence","command_timestamp_accuracy","premature_milestone_stop_avoidance","feedback_loop_closure","fleet_improvement_harvest")
def measure(d):
    if not isinstance(d,dict) or set(d)!={"schema","window","metrics"} or d.get("schema")!="cdc-dogfood-input/v1":raise ValueError("dogfood input invalid")
    m=d["metrics"]
    if not isinstance(m,dict) or set(m)!=set(METRICS):raise ValueError("metrics mismatch")
    out={};total=0
    for name in METRICS:
        x=m[name]
        if not isinstance(x,dict) or set(x)!={"pass_count","total_count"}:raise ValueError("metric record invalid")
        if type(x["pass_count"]) is not int or type(x["total_count"]) is not int or x["total_count"]<=0 or not 0<=x["pass_count"]<=x["total_count"]:raise ValueError("metric counts invalid")
        rate=x["pass_count"]/x["total_count"];out[name]={"rate":rate,"pass_count":x["pass_count"],"total_count":x["total_count"]};total+=rate
    return {"schema":"cdc-dogfood-metrics/v1","window":d["window"],"metrics":out,"compliance_percent":round(100*total/len(METRICS),2),"authorizes_release":False,"authorizes_policy_change":False}
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("input");a=p.parse_args(argv)
 try:r=measure(json.loads(Path(a.input).read_text()))
 except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
 print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
