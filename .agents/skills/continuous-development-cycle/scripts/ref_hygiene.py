#!/usr/bin/env python3
"""CDC 2.8.1 safe branch/ref hygiene planner; never deletes refs."""
from __future__ import annotations
import argparse,fnmatch,json,sys
from pathlib import Path
SCHEMA="ref-inventory/v1"
def validate(i):
    f={"schema","refs","policy"}
    if not isinstance(i,dict) or set(i)!=f or i.get("schema")!=SCHEMA:raise ValueError("ref inventory invalid")
    p=i["policy"]
    if not isinstance(p,dict) or set(p)!={"max_terminal_age_days","deletable_prefixes","protected_prefixes"}:raise ValueError("ref hygiene policy invalid")
    if type(p["max_terminal_age_days"]) is not int or p["max_terminal_age_days"]<0:raise ValueError("max_terminal_age_days invalid")
    for n in ("deletable_prefixes","protected_prefixes"):
        if not isinstance(p[n],list) or any(not isinstance(x,str) or not x for x in p[n]):raise ValueError(f"{n} invalid")
    if not isinstance(i["refs"],list):raise ValueError("refs must be list")
    fields={"name","head","age_days","terminal","protected","open_pr","unreconciled_guard","referenced"}
    for r in i["refs"]:
        if not isinstance(r,dict) or set(r)!=fields:raise ValueError("ref fields mismatch")
        if not isinstance(r["name"],str) or not r["name"].startswith("refs/"):raise ValueError("ref name invalid")
        if not isinstance(r["head"],str) or len(r["head"])!=40:raise ValueError("head invalid")
        if type(r["age_days"]) is not int or r["age_days"]<0:raise ValueError("age_days invalid")
        for n in ("terminal","protected","open_pr","unreconciled_guard","referenced"):
            if type(r[n]) is not bool:raise ValueError(f"{n} invalid")
    return i
def assess(i):
    validate(i);p=i["policy"];delete=[];keep=[]
    for r in i["refs"]:
        name=r["name"]
        protected=r["protected"] or any(name.startswith(x) for x in p["protected_prefixes"]) or name in {"refs/heads/main","refs/heads/master"}
        deletable=any(name.startswith(x) for x in p["deletable_prefixes"])
        reason=None
        if protected:reason="protected"
        elif r["open_pr"]:reason="open_pr"
        elif r["unreconciled_guard"]:reason="unreconciled_guard"
        elif r["referenced"]:reason="durably_referenced"
        elif not r["terminal"]:reason="nonterminal"
        elif r["age_days"]<p["max_terminal_age_days"]:reason="retention_window"
        elif not deletable:reason="prefix_not_deletable"
        if reason:keep.append({"name":name,"reason":reason})
        else:delete.append({"name":name,"head":r["head"],"reason":"terminal_unreferenced_expired"})
    return {"schema":"ref-hygiene-plan/v1","keep":keep,"delete_candidates":delete,"authorizes_delete":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("inventory");a=p.parse_args(argv)
    try:r=assess(json.loads(Path(a.inventory).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
