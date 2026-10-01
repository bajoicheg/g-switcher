#!/usr/bin/env python3
"""Normalize CDC fleet adoption into an exact convergence vector."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

SCHEMA = "cdc-convergence-observation/v1"
OUT = "cdc-convergence-vector/v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
ADOPTION = {"not_started", "staged", "validated", "integrated", "blocked"}
LEASE = {"unowned", "owned", "released", "unknown"}
GUARD = {"none", "running", "terminal_unreconciled", "unknown"}

def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be text")

def validate(data):
    fields = {
        "schema", "repository", "source_ref", "source_head", "cdc_version",
        "package_tree", "consumer_lock", "policy_digest", "checkpoint",
        "lease", "guard", "adoption_state"
    }
    if not isinstance(data, dict) or set(data) != fields or data.get("schema") != SCHEMA:
        raise ValueError("invalid convergence observation")
    _text(data["repository"], "repository")
    if "/" not in data["repository"]:
        raise ValueError("repository invalid")
    if not isinstance(data["source_ref"], str) or not data["source_ref"].startswith("refs/heads/"):
        raise ValueError("source_ref invalid")
    if not isinstance(data["source_head"], str) or not SHA.fullmatch(data["source_head"]):
        raise ValueError("source_head invalid")
    if not isinstance(data["cdc_version"], str) or not SEMVER.fullmatch(data["cdc_version"]):
        raise ValueError("cdc_version invalid")
    if not isinstance(data["package_tree"], str) or not SHA.fullmatch(data["package_tree"]):
        raise ValueError("package_tree invalid")
    if not isinstance(data["policy_digest"], str) or not DIGEST.fullmatch(data["policy_digest"]):
        raise ValueError("policy_digest invalid")
    lock = data["consumer_lock"]
    if not isinstance(lock, dict) or set(lock) != {"version", "release_commit", "package_tree"}:
        raise ValueError("consumer_lock invalid")
    if not isinstance(lock["version"], str) or not SEMVER.fullmatch(lock["version"]):
        raise ValueError("consumer lock version invalid")
    if not SHA.fullmatch(lock["release_commit"]) or not SHA.fullmatch(lock["package_tree"]):
        raise ValueError("consumer lock identity invalid")
    checkpoint = data["checkpoint"]
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"valid", "source_head", "policy_digest"}:
        raise ValueError("checkpoint invalid")
    if type(checkpoint["valid"]) is not bool or not SHA.fullmatch(checkpoint["source_head"]):
        raise ValueError("checkpoint binding invalid")
    if not DIGEST.fullmatch(checkpoint["policy_digest"]):
        raise ValueError("checkpoint policy digest invalid")
    if not isinstance(data["lease"], dict) or set(data["lease"]) != {"state"} or data["lease"]["state"] not in LEASE:
        raise ValueError("lease state invalid")
    if not isinstance(data["guard"], dict) or set(data["guard"]) != {"state"} or data["guard"]["state"] not in GUARD:
        raise ValueError("guard state invalid")
    if data["adoption_state"] not in ADOPTION:
        raise ValueError("adoption_state invalid")
    return data

def normalize(data):
    validate(data)
    lock = data["consumer_lock"]
    checkpoint = data["checkpoint"]
    checks = {
        "lock_version_matches": lock["version"] == data["cdc_version"],
        "lock_tree_matches": lock["package_tree"] == data["package_tree"],
        "checkpoint_valid": checkpoint["valid"],
        "checkpoint_head_matches": checkpoint["source_head"] == data["source_head"],
        "checkpoint_policy_matches": checkpoint["policy_digest"] == data["policy_digest"],
        "owner_reconciled": data["lease"]["state"] in {"unowned", "released"},
        "guard_reconciled": data["guard"]["state"] == "none",
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    integrated = data["adoption_state"] == "integrated" and not blockers
    if data["adoption_state"] == "blocked":
        effective = "blocked"
    elif integrated:
        effective = "integrated"
    elif all(checks[name] for name in (
        "lock_version_matches", "lock_tree_matches", "checkpoint_valid",
        "checkpoint_head_matches", "checkpoint_policy_matches"
    )):
        effective = "validated"
    elif data["adoption_state"] == "not_started":
        effective = "not_started"
    else:
        effective = "staged"
    return {
        "schema": OUT,
        "repository": data["repository"],
        "source_ref": data["source_ref"],
        "source_head": data["source_head"],
        "cdc_version": data["cdc_version"],
        "package_tree": data["package_tree"],
        "consumer_release_commit": lock["release_commit"],
        "policy_digest": data["policy_digest"],
        "checkpoint_valid": checkpoint["valid"],
        "lease_state": data["lease"]["state"],
        "guard_state": data["guard"]["state"],
        "requested_adoption_state": data["adoption_state"],
        "adoption_state": effective,
        "checks": checks,
        "blockers": blockers,
        "integrated": integrated,
        "authorizes_product_write": False,
        "authorizes_takeover": False,
        "authorizes_external_start": False,
        "authorizes_merge": False,
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("observation"); args = p.parse_args(argv)
    try:
        result = normalize(json.loads(Path(args.observation).read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr); return 2
    print(json.dumps(result, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
