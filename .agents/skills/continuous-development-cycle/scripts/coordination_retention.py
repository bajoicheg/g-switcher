#!/usr/bin/env python3
"""CDC 2.8.1 coordination-state retention planner."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
KINDS={"lease","operation","authorization","handoff","ledger","snapshot","environment","audit"}
def assess(data):
    if not isinstance(data,dict) or set(data)!={"schema","policy","records"} or data.get("schema")!="coordination-retention/v1":raise ValueError("invalid retention inventory")
    p=data["policy"]
    if not isinstance(p,dict) or set(p)!={"archive_after_seconds","delete_after_seconds","never_delete_kinds"}:raise ValueError("invalid retention policy")
    for n in ("archive_after_seconds","delete_after_seconds"):
        if type(p[n]) is not int or p[n]<0:raise ValueError(f"{n} invalid")
    if p["delete_after_seconds"]<p["archive_after_seconds"]:raise ValueError("delete threshold before archive threshold")
    if not isinstance(p["never_delete_kinds"],list) or not set(p["never_delete_kinds"])<=KINDS:raise ValueError("never_delete_kinds invalid")
    archive=[];delete=[];keep=[]
    fields={"id","kind","age_seconds","terminal","active_reference","guard_present"}
    for r in data["records"]:
        if not isinstance(r,dict) or set(r)!=fields or r["kind"] not in KINDS:raise ValueError("record invalid")
        if type(r["age_seconds"]) is not int or r["age_seconds"]<0:raise ValueError("age invalid")
        if any(type(r[n]) is not bool for n in ("terminal","active_reference","guard_present")):raise ValueError("record booleans invalid")
        if r["kind"] in p["never_delete_kinds"] or r["active_reference"] or r["guard_present"] or not r["terminal"]:keep.append({"id":r["id"],"reason":"protected_or_active"});continue
        if r["age_seconds"]>=p["delete_after_seconds"]:delete.append({"id":r["id"],"kind":r["kind"]})
        elif r["age_seconds"]>=p["archive_after_seconds"]:archive.append({"id":r["id"],"kind":r["kind"]})
        else:keep.append({"id":r["id"],"reason":"retention_window"})
    return {"schema":"coordination-retention-plan/v1","keep":keep,"archive_candidates":archive,"delete_candidates":delete,"authorizes_archive":False,"authorizes_delete":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("inventory");a=p.parse_args(argv)
    try:r=assess(json.loads(Path(a.inventory).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
