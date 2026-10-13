#!/usr/bin/env python3
"""CDC 2.8 publication safety guard for tree, refs, conversations and control-plane metadata."""
from __future__ import annotations
import argparse,fnmatch,json,sys
from pathlib import Path
from sensitive_context import validate_policy,scan_text
SCHEMA="publication-inventory/v1"
CONTROL_PATTERNS=("authorizations/*","capability-requests/*","capability-routes/*","operations/*","handoffs/*",
                  "lease.json","budget-ledger.json","backend-registry.json","continuation-queue.json",
                  "control-plane-audit.json","execution-continuity/*","plans/*environment*.json")
RISKY_REF_PREFIXES=("refs/heads/cdc/coordination","refs/heads/backup/","refs/heads/migration/")
def _items(v,n,fields):
    if not isinstance(v,list):raise ValueError(f"{n} must be list")
    for x in v:
        if not isinstance(x,dict) or set(x)!=fields:raise ValueError(f"{n} fields mismatch")
def validate_inventory(i):
    f={"schema","repository","target_visibility","refs","files","conversations","artifacts"}
    if not isinstance(i,dict) or set(i)!=f or i.get("schema")!=SCHEMA:raise ValueError("publication inventory invalid")
    if not isinstance(i["repository"],str) or "/" not in i["repository"]:raise ValueError("repository invalid")
    if i["target_visibility"]!="public":raise ValueError("publication guard is for public target")
    if not isinstance(i["refs"],list) or any(not isinstance(x,str) or not x.startswith("refs/") for x in i["refs"]):raise ValueError("refs invalid")
    _items(i["files"],"files",{"path","content"});_items(i["conversations"],"conversations",{"kind","id","body"});_items(i["artifacts"],"artifacts",{"name","metadata"})
    return i
def _control(path):return any(fnmatch.fnmatch(path,p) or fnmatch.fnmatch(path.lstrip("./"),p) for p in CONTROL_PATTERNS)
def assess(inventory,policy):
    validate_inventory(inventory);validate_policy(policy)
    findings=[]
    for ref in inventory["refs"]:
        if any(ref.startswith(p) for p in RISKY_REF_PREFIXES):findings.append({"kind":"risky_ref","source":ref,"value":ref})
    for f in inventory["files"]:
        if _control(f["path"]):findings.append({"kind":"control_plane_path","source":f["path"],"value":f["path"]})
        findings.extend(scan_text(f["content"],policy,f["path"]))
    for c in inventory["conversations"]:findings.extend(scan_text(c["body"],policy,f"{c['kind']}:{c['id']}"))
    for a in inventory["artifacts"]:findings.extend(scan_text(a["metadata"],policy,f"artifact:{a['name']}"))
    findings.sort(key=lambda x:(x["source"],x["kind"],str(x.get("value","")).lower()))
    return {"schema":"publication-assessment/v1","repository":inventory["repository"],"pass":not findings,"finding_count":len(findings),
            "findings":findings,"requires_sanitized_export":bool(findings),"authorizes_visibility_change":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("inventory");p.add_argument("policy");a=p.parse_args(argv)
    try:r=assess(json.loads(Path(a.inventory).read_text()),json.loads(Path(a.policy).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["pass"] else 1
if __name__=="__main__":raise SystemExit(main())
