#!/usr/bin/env python3
"""Validate an immutable CDC consumer release lock."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
SEMVER=re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA=re.compile(r"^[0-9a-f]{40}$")
REPO=re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FIELDS={"schema","canonical_repository","version","release_ref","release_commit","package_tree","checkpoint_schema","safe_boundary_required","local_core_modifications_allowed"}
def validate(lock):
    if not isinstance(lock,dict) or set(lock)!=FIELDS: raise ValueError("invalid consumer lock fields")
    if lock["schema"]!="cdc-consumer-lock/v1": raise ValueError("unsupported consumer lock schema")
    v=lock["version"]
    if not isinstance(v,str) or not SEMVER.fullmatch(v): raise ValueError("stable semantic version required")
    repo=lock["canonical_repository"]
    if not isinstance(repo,str) or not REPO.fullmatch(repo): raise ValueError("canonical_repository must be owner/repository")
    if lock["release_ref"]!="refs/heads/release/v"+v: raise ValueError("release_ref must bind the versioned immutable release branch")
    if not SHA.fullmatch(lock["release_commit"]) or not SHA.fullmatch(lock["package_tree"]): raise ValueError("release commit/package tree binding invalid")
    if lock["checkpoint_schema"]!="development-work-status/v4": raise ValueError("checkpoint schema compatibility lost")
    if lock["safe_boundary_required"] is not True: raise ValueError("safe ownership boundary must be required")
    if lock["local_core_modifications_allowed"] is not False: raise ValueError("vendored core must remain immutable")
    return lock
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("lock");a=p.parse_args(argv)
    try: validate(json.loads(Path(a.lock).read_text(encoding="utf-8")))
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError) as exc:
        print("FAIL:",exc,file=sys.stderr);return 1
    print("PASS: cdc-consumer-lock/v1");return 0
if __name__=="__main__": raise SystemExit(main())
