#!/usr/bin/env python3
"""CDC 2.8.2 plans a sanitized public export; never changes repository visibility."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
def plan(d):
    f={"schema","source_repository","target_repository","publication_guard_green","history_clean","control_plane_externalized","allowed_paths","excluded_paths"}
    if not isinstance(d,dict) or set(d)!=f or d.get("schema")!="public-export-request/v1":raise ValueError("public export request invalid")
    for n in ("publication_guard_green","history_clean","control_plane_externalized"):
        if type(d[n]) is not bool:raise ValueError(f"{n} invalid")
    for n in ("allowed_paths","excluded_paths"):
        if not isinstance(d[n],list) or any(not isinstance(x,str) or not x.strip() for x in d[n]):raise ValueError(f"{n} invalid")
    direct=d["publication_guard_green"] and d["history_clean"] and d["control_plane_externalized"]
    if direct:
        action="EXPORT_NEW_HISTORY"
        reason="sanitized_export_ready"
    else:
        action="BLOCKED"
        reason="publication_preconditions_not_green"
    return {"schema":"public-export-plan/v1","action":action,"reason":reason,"target_repository":d["target_repository"],"copy_paths":d["allowed_paths"],"exclude_paths":d["excluded_paths"],"preserve_private_history":True,"authorizes_visibility_change":False,"authorizes_push":False}
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("request");a=p.parse_args(argv)
 try:r=plan(json.loads(Path(a.request).read_text()))
 except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
 print(json.dumps(r,sort_keys=True));return 0 if r["action"]=="EXPORT_NEW_HISTORY" else 1
if __name__=="__main__":raise SystemExit(main())
