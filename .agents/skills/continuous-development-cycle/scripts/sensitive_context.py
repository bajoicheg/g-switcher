#!/usr/bin/env python3
"""CDC 2.8 policy-driven sensitive-context scanner; complements secret scanners."""
from __future__ import annotations
import ipaddress,re
POLICY_SCHEMA="sensitive-context-policy/v1"
def _list(v,n):
    if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(f"{n} invalid")
    if len(set(x.lower() for x in v))!=len(v):raise ValueError(f"{n} duplicated")
def validate_policy(p):
    f={"schema","forbidden_literals","forbidden_domain_suffixes","allow_example_domains","detect_private_ips","case_insensitive"}
    if not isinstance(p,dict) or set(p)!=f or p.get("schema")!=POLICY_SCHEMA:raise ValueError("sensitive context policy invalid")
    for n in ("forbidden_literals","forbidden_domain_suffixes"):_list(p[n],n)
    for n in ("allow_example_domains","detect_private_ips","case_insensitive"):
        if type(p[n]) is not bool:raise ValueError(f"{n} must be bool")
    return p
def scan_text(text,policy,source="inline"):
    validate_policy(policy)
    if not isinstance(text,str):raise ValueError("text must be string")
    flags=re.IGNORECASE if policy["case_insensitive"] else 0
    findings=[]
    for lit in policy["forbidden_literals"]:
        for m in re.finditer(re.escape(lit),text,flags):
            findings.append({"kind":"forbidden_literal","source":source,"value":m.group(0),"offset":m.start()})
    domain_re=re.compile(r"\b(?:[a-z0-9_-]+\.)+[a-z]{2,63}\b",re.IGNORECASE)
    examples=(".example",".example.com",".example.net",".example.org",".test",".invalid",".localhost")
    suffixes=tuple(x.lower().lstrip(".") for x in policy["forbidden_domain_suffixes"])
    for m in domain_re.finditer(text):
        d=m.group(0).lower().rstrip(".")
        if policy["allow_example_domains"] and any(d==x.lstrip(".") or d.endswith(x) for x in examples):continue
        if suffixes and any(d==s or d.endswith("."+s) for s in suffixes):
            findings.append({"kind":"forbidden_domain","source":source,"value":m.group(0),"offset":m.start()})
    if policy["detect_private_ips"]:
        ip_re=re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
        for m in ip_re.finditer(text):
            try:ip=ipaddress.ip_address(m.group(0))
            except ValueError:continue
            if ip.is_private and not ip.is_loopback:
                findings.append({"kind":"private_ip","source":source,"value":m.group(0),"offset":m.start()})
    findings.sort(key=lambda x:(x["source"],x["offset"],x["kind"],x["value"].lower()))
    return findings
