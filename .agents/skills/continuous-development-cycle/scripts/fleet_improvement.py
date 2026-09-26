#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
SCHEMA="fleet-improvement-harvest/v1";KEY=re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
def harvest(d):
    f={"schema","run_id","observations","candidate","existing_fix_keys"}
    if not isinstance(d,dict) or set(d)!=f or d.get("schema")!=SCHEMA:raise ValueError("invalid fleet improvement input")
    if not isinstance(d["observations"],list) or not d["observations"]:raise ValueError("observations must be nonempty")
    c=d["candidate"]
    if not isinstance(c,dict) or set(c)!={"fix_key","problem","fix","benefit"} or not KEY.fullmatch(c["fix_key"]):raise ValueError("candidate invalid")
    action="REINFORCE_EXISTING" if c["fix_key"] in d["existing_fix_keys"] else "PROPOSE_NEW"
    return {"schema":"fleet-improvement-result/v1","run_id":d["run_id"],"action":action,"proposal":{**c,"evidence_count":len(d["observations"])},"proposal_count":1,"authorizes_scope_expansion":False,"authorizes_roadmap_write":False,"authorizes_product_write":False}
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("input");a=p.parse_args(argv)
    try:r=harvest(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
