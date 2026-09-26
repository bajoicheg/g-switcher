#!/usr/bin/env python3
"""Carrier-neutral CDC package transport verification with exact Git tree identity."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "cdc-package-transport/v1"
VERIFY_SCHEMA = "cdc-package-transport-verification/v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
MODES = {"100644", "100755"}

def _blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()

def _tree_oid(entries):
    root = {}
    for entry in entries:
        parts = entry["path"].split("/")
        node = root
        for part in parts[:-1]:
            current = node.setdefault(part, {})
            if not isinstance(current, dict):
                raise ValueError("file/directory path collision")
            node = current
        leaf = parts[-1]
        if leaf in node:
            raise ValueError("duplicate or colliding transport path")
        node[leaf] = (entry["mode"], entry["blob_sha1"])

    def emit(node):
        records = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, oid, is_tree = "40000", emit(value), True
            else:
                mode, oid, is_tree = value[0], value[1], False
            records.append((name, mode, oid, is_tree))
        records.sort(key=lambda item: (item[0] + ("/" if item[3] else "")).encode("utf-8"))
        body = b"".join(
            mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid)
            for name, mode, oid, _ in records
        )
        return hashlib.sha1(b"tree " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()
    return emit(root)

def validate_manifest(data):
    required = {
        "schema", "version", "canonical_repository", "release_ref",
        "release_commit", "package_tree", "hash_algorithm", "entries"
    }
    if not isinstance(data, dict) or set(data) != required or data.get("schema") != SCHEMA:
        raise ValueError("invalid package transport manifest")
    version = data["version"]
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ValueError("version must be stable semver")
    if not isinstance(data["canonical_repository"], str) or "/" not in data["canonical_repository"]:
        raise ValueError("canonical_repository invalid")
    if data["release_ref"] != f"refs/heads/release/v{version}":
        raise ValueError("release_ref must bind version")
    for name in ("release_commit", "package_tree"):
        if not isinstance(data[name], str) or not SHA.fullmatch(data[name]):
            raise ValueError(f"{name} invalid")
    if data["hash_algorithm"] != "git-sha1":
        raise ValueError("only git-sha1 transport identity is supported")
    entries = data["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries must be a nonempty list")
    paths = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "mode", "blob_sha1", "size"}:
            raise ValueError("transport entry fields mismatch")
        path = entry["path"]
        if (not isinstance(path, str) or not PATH.fullmatch(path) or path.startswith("/")
                or path.endswith("/") or "//" in path or any(p in {"", ".", ".."} for p in path.split("/"))):
            raise ValueError("unsafe transport path")
        if entry["mode"] not in MODES:
            raise ValueError("unsupported Git file mode")
        if not isinstance(entry["blob_sha1"], str) or not SHA.fullmatch(entry["blob_sha1"]):
            raise ValueError("blob_sha1 invalid")
        if type(entry["size"]) is not int or entry["size"] < 0:
            raise ValueError("entry size invalid")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("transport entries must be unique and path-sorted")
    if _tree_oid(entries) != data["package_tree"]:
        raise ValueError("manifest entries do not reconstruct package_tree")
    return data

def verify_binding(data, *, version, release_commit, package_tree):
    validate_manifest(data)
    expected = {"version": version, "release_commit": release_commit, "package_tree": package_tree}
    for name, value in expected.items():
        if data[name] != value:
            raise ValueError(f"transport {name} does not match trusted release binding")
    return True

def verify_directory(data, package_dir):
    validate_manifest(data)
    root = Path(package_dir)
    if not root.is_dir():
        raise ValueError("package directory missing")
    expected = {entry["path"]: entry for entry in data["entries"]}
    observed = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinks are not allowed in transported package")
        if path.is_file():
            observed[path.relative_to(root).as_posix()] = path
    extra = sorted(set(observed) - set(expected))
    missing = sorted(set(expected) - set(observed))
    mismatched = []
    for rel in sorted(set(observed) & set(expected)):
        payload = observed[rel].read_bytes()
        item = expected[rel]
        if len(payload) != item["size"] or _blob_oid(payload) != item["blob_sha1"]:
            mismatched.append(rel)
    verified = not extra and not missing and not mismatched
    return {
        "schema": VERIFY_SCHEMA,
        "version": data["version"],
        "release_commit": data["release_commit"],
        "package_tree": data["package_tree"],
        "content_verified": verified,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "authorizes_adoption": False,
    }

def verify_git_tree(data, worktree, package_path):
    validate_manifest(data)
    if not isinstance(package_path, str) or not PATH.fullmatch(package_path) or package_path.startswith("/"):
        raise ValueError("package_path invalid")
    try:
        observed = subprocess.check_output(
            ["git", "-C", str(Path(worktree)), "rev-parse", f"HEAD:{package_path}"],
            text=True, stderr=subprocess.PIPE, timeout=15,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot read vendored Git tree: {exc}") from exc
    return {
        "schema": VERIFY_SCHEMA,
        "version": data["version"],
        "release_commit": data["release_commit"],
        "package_tree": data["package_tree"],
        "observed_package_tree": observed,
        "git_tree_verified": observed == data["package_tree"],
        "authorizes_adoption": False,
    }

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("binding")
    b.add_argument("manifest"); b.add_argument("--version", required=True)
    b.add_argument("--release-commit", required=True); b.add_argument("--package-tree", required=True)
    d = sub.add_parser("directory")
    d.add_argument("manifest"); d.add_argument("package_dir")
    g = sub.add_parser("git-tree")
    g.add_argument("manifest"); g.add_argument("worktree"); g.add_argument("package_path")
    args = p.parse_args(argv)
    try:
        manifest = load(args.manifest)
        if args.command == "binding":
            verify_binding(manifest, version=args.version, release_commit=args.release_commit,
                           package_tree=args.package_tree)
            result = {"schema": VERIFY_SCHEMA, "binding_verified": True, "authorizes_adoption": False}
        elif args.command == "directory":
            result = verify_directory(manifest, args.package_dir)
        else:
            result = verify_git_tree(manifest, args.worktree, args.package_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr); return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if all(result.get(k, True) for k in ("content_verified", "git_tree_verified")) else 1

if __name__ == "__main__":
    raise SystemExit(main())
