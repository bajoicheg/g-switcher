#!/usr/bin/env python3
"""CDC 2.6 version/package convergence assessment; migration remains separately authorized."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
SEMVER=re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
FP=re.compile(r"^(?:sha256:[0-9a-f]{64}|git-tree:[0-9a-f]{40})$")

def _ver(v):
    if not isinstance(v,str) or not SEMVER.fullmatch(v):raise ValueError("invalid semver")
    return tuple(map(int,v.split(".")))
def _text(v,n):
    if not isinstance(v,str) or not v.strip():raise ValueError(f"{n} must be text")
def validate_target(t):
    f={"schema","target_version","target_package_fingerprint","checkpoint_schema","safe_boundary_required"}
    if not isinstance(t,dict) or set(t)!=f or t["schema"]!="version-convergence-target/v1":raise ValueError("invalid convergence target")
    _ver(t["target_version"])
    if not isinstance(t["target_package_fingerprint"],str) or not FP.fullmatch(t["target_package_fingerprint"]):raise ValueError("invalid target package fingerprint")
    _text(t["checkpoint_schema"],"checkpoint_schema")
    if t["safe_boundary_required"] is not True:raise ValueError("safe_boundary_required must be true")
    return t
def validate_snapshot(s):
    f={"schema","repository","source_ref","cdc_version","package_fingerprint","checkpoint_schema","owner_active","guard_present","policy_revision"}
    if not isinstance(s,dict) or set(s)!=f or s["schema"]!="version-convergence-snapshot/v1":raise ValueError("invalid convergence snapshot")
    _text(s["repository"],"repository");_text(s["source_ref"],"source_ref");_ver(s["cdc_version"]);_text(s["policy_revision"],"policy_revision")
    if not s["source_ref"].startswith("refs/heads/"):raise ValueError("source_ref invalid")
    if not isinstance(s["package_fingerprint"],str) or not FP.fullmatch(s["package_fingerprint"]):raise ValueError("invalid package fingerprint")
    _text(s["checkpoint_schema"],"checkpoint_schema")
    if type(s["owner_active"]) is not bool or type(s["guard_present"]) is not bool:raise ValueError("owner_active/guard_present must be boolean")
    return s
def assess(target,s):
    validate_target(target);validate_snapshot(s);tv=_ver(target["target_version"]);sv=_ver(s["cdc_version"])
    safe=not s["owner_active"] and not s["guard_present"]
    if sv[0]!=tv[0]:state,reason="INCOMPATIBLE","major_version_mismatch"
    elif sv>tv:state,reason="AHEAD","project_version_ahead_of_fleet_target"
    elif sv<tv:state,reason="LAGGING","project_version_behind_fleet_target"
    elif s["package_fingerprint"]!=target["target_package_fingerprint"]:state,reason="DRIFT","package_fingerprint_mismatch"
    elif s["checkpoint_schema"]!=target["checkpoint_schema"]:state,reason="DRIFT","checkpoint_schema_mismatch"
    else:state,reason="CONVERGED","exact_version_package_schema_match"
    if state=="CONVERGED":action="none"
    elif not safe:action="wait_safe_boundary"
    elif state in {"LAGGING","DRIFT"}:action="prepare_adoption"
    else:action="manual_reconciliation"
    return {"state":state,"reason":reason,"safe_boundary":safe,"recommended_action":action,
            "authorizes_merge":False,"authorizes_write":False,"authorizes_takeover":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("target");p.add_argument("snapshot");a=p.parse_args(argv)
    try:r=assess(json.loads(Path(a.target).read_text()),json.loads(Path(a.snapshot).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
