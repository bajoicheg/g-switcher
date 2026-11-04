#!/usr/bin/env python3
"""Idempotent fresh-HEAD section-aware CDC policy migration."""
from __future__ import annotations
import argparse,copy,json,re,sys
from pathlib import Path
import yaml
from contracts import StrictLoader,digest
SCHEMA="policy-migration-request/v1"; OUT="policy-migration-plan/v1"
SHA=re.compile(r"^[0-9a-f]{40}$"); SECTION=re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
def _load_policy(text):
    if not isinstance(text,str) or not text.strip(): raise ValueError("current_policy_yaml must be nonempty text")
    try: value=yaml.load(text,Loader=StrictLoader)
    except (yaml.YAMLError,ValueError) as exc: raise ValueError(f"invalid strict YAML policy: {exc}") from exc
    if not isinstance(value,dict): raise ValueError("policy document must be a mapping")
    return value
def validate(request):
    fields={"schema","expected_source_head","observed_source_head","current_policy_yaml","desired_sections"}
    if not isinstance(request,dict) or set(request)!=fields or request.get("schema")!=SCHEMA: raise ValueError("invalid policy migration request")
    for name in ("expected_source_head","observed_source_head"):
        if not isinstance(request[name],str) or not SHA.fullmatch(request[name]): raise ValueError(f"{name} invalid")
    desired=request["desired_sections"]
    if not isinstance(desired,dict) or not desired: raise ValueError("desired_sections must be a nonempty mapping")
    for name,value in desired.items():
        if not isinstance(name,str) or not SECTION.fullmatch(name): raise ValueError("invalid managed section name")
        if not isinstance(value,dict): raise ValueError("managed sections must be mappings")
    return request
def plan(request):
    validate(request)
    if request["expected_source_head"]!=request["observed_source_head"]:
        return {"schema":OUT,"action":"REPLAN_ON_FRESH_HEAD","source_head":request["observed_source_head"],
                "changed_sections":[],"rendered_policy_yaml":None,"semantic_digest":None,
                "authorizes_product_write":False,"authorizes_force_push":False}
    current=_load_policy(request["current_policy_yaml"]); target=copy.deepcopy(current); changed=[]
    for name,value in request["desired_sections"].items():
        if target.get(name)!=value: target[name]=copy.deepcopy(value); changed.append(name)
    if not changed: rendered=request["current_policy_yaml"]; action="NOOP"
    else:
        rendered=yaml.safe_dump(target,sort_keys=False,allow_unicode=True)
        if _load_policy(rendered)!=target: raise ValueError("rendered policy failed semantic round-trip")
        action="APPLY"
    return {"schema":OUT,"action":action,"source_head":request["observed_source_head"],"changed_sections":changed,
            "rendered_policy_yaml":rendered,"semantic_digest":"sha256:"+digest(target),
            "authorizes_product_write":False,"authorizes_force_push":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("request");a=p.parse_args(argv)
    try:r=plan(json.loads(Path(a.request).read_text(encoding="utf-8")))
    except (OSError,ValueError,json.JSONDecodeError) as exc:print(f"FAIL: {exc}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"] in {"APPLY","NOOP"} else 1
if __name__=="__main__":raise SystemExit(main())
