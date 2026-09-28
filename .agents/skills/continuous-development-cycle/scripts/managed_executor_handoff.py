#!/usr/bin/env python3
"""CDC 2.11.0 portable managed-executor result handoff and publication proof."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import sys
import unicodedata
from pathlib import Path

from parallel_task_planner import validate_write_path, portable_path_key
from git_remote_identity import remote_identity
from worktree_worker_contract import canonical_branch_ref

HANDOFF_SCHEMA = "managed-executor-handoff/v1"
PROOF_SCHEMA = "managed-executor-publication-proof/v1"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
TRANSPORTS = {"direct_branch", "content_artifact"}
ARTIFACT_FORMATS = {"git_bundle", "unified_diff"}
AUTHORITY_FIELDS = (
    "authorizes_product_write",
    "authorizes_shared_branch_write",
    "authorizes_force_push",
    "authorizes_merge",
    "authorizes_release",
    "authorizes_scope_expansion",
    "authorizes_scheduler_mutation",
)
HANDOFF_FIELDS = {
    "schema", "pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id",
    "executor_id", "base_sha", "assigned_branch", "publication_repository",
    "publication_remote_id", "transport", "source_result_commit",
    "direct_result_commit", "artifact_ref", "changed_paths", "evidence_refs",
}
PROOF_FIELDS = {
    "schema", "handoff_ref", "pool_id", "task_id", "attempt_id", "base_sha",
    "assigned_branch", "publication_repository", "publication_remote_id",
    "published_commit", "observed_changed_paths", "evidence_refs",
    "result_verified", *AUTHORITY_FIELDS,
}


def _text(value, name, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _sha(value, name, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase SHA")


def _digest(value, name):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f"{name} must be sha256:<hex>")


def _refs(value, name):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{name} must be a nonempty list of text refs")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} contains duplicates")


def _paths(value, name):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a nonempty list")
    keys = []
    for path in value:
        validate_write_path(path)
        keys.append(portable_path_key(path))
    if len(keys) != len(set(keys)):
        raise ValueError(f"{name} contains portable aliases")
    return value


def _safe_rel(path):
    validate_write_path(path)
    return path


def _artifact_ref(value):
    if not isinstance(value, dict) or set(value) != {"path", "sha256", "format"}:
        raise ValueError("artifact_ref fields mismatch")
    _safe_rel(value["path"])
    _digest(value["sha256"], "artifact_ref.sha256")
    if value["format"] not in ARTIFACT_FORMATS:
        raise ValueError("unsupported artifact format")
    return value


def validate_handoff(handoff):
    if not isinstance(handoff, dict) or set(handoff) != HANDOFF_FIELDS or handoff.get("schema") != HANDOFF_SCHEMA:
        raise ValueError("managed executor handoff fields/schema mismatch")
    for name in ("pool_id", "change_id", "task_id", "attempt_id", "parent_invocation_id", "executor_id"):
        _text(handoff[name], name)
    _sha(handoff["base_sha"], "base_sha")
    canonical_branch_ref(handoff["assigned_branch"])
    _text(handoff["publication_repository"], "publication_repository")
    _digest(handoff["publication_remote_id"], "publication_remote_id")
    if handoff["transport"] not in TRANSPORTS:
        raise ValueError("unsupported handoff transport")
    _sha(handoff["source_result_commit"], "source_result_commit", nullable=True)
    _paths(handoff["changed_paths"], "changed_paths")
    _refs(handoff["evidence_refs"], "evidence_refs")
    if handoff["transport"] == "direct_branch":
        _sha(handoff["direct_result_commit"], "direct_result_commit")
        if handoff["artifact_ref"] is not None:
            raise ValueError("direct_branch handoff cannot contain artifact_ref")
        if handoff["source_result_commit"] is not None and handoff["source_result_commit"] != handoff["direct_result_commit"]:
            raise ValueError("direct source/result commit mismatch")
    else:
        if handoff["direct_result_commit"] is not None:
            raise ValueError("content_artifact handoff cannot claim direct_result_commit")
        _artifact_ref(handoff["artifact_ref"])
    return handoff


def canonical_handoff_ref(handoff):
    validate_handoff(handoff)
    payload = json.dumps(handoff, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def resolve_artifact(handoff, evidence_root):
    validate_handoff(handoff)
    if handoff["transport"] != "content_artifact":
        raise ValueError("resolve_artifact requires content_artifact transport")
    if evidence_root is None:
        raise ValueError("content artifact requires evidence_root")
    root = Path(evidence_root).resolve()
    target = (root / handoff["artifact_ref"]["path"]).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact escapes evidence root") from exc
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read result artifact: {exc}") from exc
    if not payload:
        raise ValueError("result artifact must not be empty")
    observed = "sha256:" + hashlib.sha256(payload).hexdigest()
    if observed != handoff["artifact_ref"]["sha256"]:
        raise ValueError("result artifact digest mismatch")
    if handoff["artifact_ref"]["format"] == "unified_diff":
        parsed = subprocess.run(
            ["git", "apply", "--numstat", "--recount", "-"],
            env=git_object_environment(), input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
        if parsed.returncode != 0:
            raise ValueError("result artifact is not a syntactically valid unified_diff")
    return payload


def publication_plan(handoff, evidence_root=None):
    validate_handoff(handoff)
    if handoff["transport"] == "content_artifact":
        resolve_artifact(handoff, evidence_root)
        action = "IMPORT_CONTENT_ARTIFACT_TO_ASSIGNED_BRANCH"
    else:
        action = "VERIFY_DIRECT_ASSIGNED_BRANCH"
    return {
        "schema": "managed-executor-publication-plan/v1",
        "handoff_ref": canonical_handoff_ref(handoff),
        "pool_id": handoff["pool_id"],
        "task_id": handoff["task_id"],
        "attempt_id": handoff["attempt_id"],
        "base_sha": handoff["base_sha"],
        "assigned_branch": canonical_branch_ref(handoff["assigned_branch"]),
        "publication_repository": handoff["publication_repository"],
        "publication_remote_id": handoff["publication_remote_id"],
        "transport": handoff["transport"],
        "action": action,
        "artifact_ref": handoff["artifact_ref"],
        "direct_result_commit": handoff["direct_result_commit"],
        "requires_reexecution": False,
        **{name: False for name in AUTHORITY_FIELDS},
    }


def _portable_set(paths):
    _paths(paths, "paths")
    return {portable_path_key(p) for p in paths}


def _git_changed_paths(root, base_sha, result_commit):
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(root), "diff", "--name-only", "--no-renames", "-z",
             base_sha, result_commit],
            env=git_object_environment(), stderr=subprocess.PIPE, timeout=15,
        )
        text = raw.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot derive published changed paths: {exc}") from exc
    paths = [path for path in text.split("\0") if path]
    _paths(paths, "published changed paths")
    return paths


def _verify_unified_diff_artifact(handoff, payload, root, published_commit):
    fd, index_path = tempfile.mkstemp(prefix="cdc-handoff-index-")
    os.close(fd)
    os.unlink(index_path)
    env = git_object_environment(GIT_INDEX_FILE=index_path)
    try:
        read_tree = subprocess.run(
            ["git", "-C", str(root), "read-tree", handoff["base_sha"]],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=15,
        )
        if read_tree.returncode != 0:
            raise ValueError("cannot initialize artifact verification index from base")
        apply = subprocess.run(
            ["git", "-C", str(root), "apply", "--cached", "--whitespace=nowarn", "--recount", "-"],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=15,
        )
        if apply.returncode != 0:
            raise ValueError("authenticated unified_diff does not apply cleanly to declared base")
        expected_tree = subprocess.check_output(
            ["git", "-C", str(root), "write-tree"], env=env, text=True,
            stderr=subprocess.PIPE, timeout=15,
        ).strip()
        published_tree = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", f"{published_commit}^{{tree}}"],
            env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
        ).strip()
        raw_paths = subprocess.check_output(
            ["git", "-C", str(root), "diff", "--cached", "--name-only", "--no-renames", "-z",
             handoff["base_sha"]],
            env=env, stderr=subprocess.PIPE, timeout=15,
        )
        artifact_paths = [p for p in raw_paths.decode("utf-8").split("\0") if p]
        _paths(artifact_paths, "artifact changed paths")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot verify unified_diff publication: {exc}") from exc
    finally:
        try:
            os.unlink(index_path)
        except FileNotFoundError:
            pass
    if expected_tree != published_tree:
        raise ValueError("published commit tree does not match authenticated unified_diff result")
    if _portable_set(artifact_paths) != _portable_set(handoff["changed_paths"]):
        raise ValueError("authenticated unified_diff paths do not match handoff manifest")
    return expected_tree


def _verify_git_bundle_artifact(handoff, payload, root, published_commit):
    fd, snapshot_path = tempfile.mkstemp(prefix="cdc-handoff-bundle-", suffix=".bundle")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(snapshot_path, 0o600)
        verify = subprocess.run(
            ["git", "-C", str(root), "bundle", "verify", snapshot_path],
            env=git_object_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15,
        )
        if verify.returncode != 0:
            raise ValueError("git_bundle verification failed")
        heads = subprocess.check_output(
            ["git", "-C", str(root), "bundle", "list-heads", snapshot_path],
            env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
        ).splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot verify git_bundle publication: {exc}") from exc
    finally:
        try:
            os.unlink(snapshot_path)
        except FileNotFoundError:
            pass
    if not any(line.split()[0] == published_commit for line in heads if line.split()):
        raise ValueError("git_bundle does not contain published source result commit")
    return True


def publication_remote_identity(root, remote):
    return remote_identity(root, remote)


def _verify_remote_branch(root, remote, branch_ref, published_commit, expected_remote_id):
    observed_remote_id = publication_remote_identity(root, remote)
    if observed_remote_id != expected_remote_id:
        raise ValueError("publication remote identity mismatch")
    environment = git_object_environment(GIT_TERMINAL_PROMPT="0")
    try:
        query = subprocess.run(
            ["git", "-C", str(root), "ls-remote", "--refs", remote, branch_ref],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("cannot query authoritative publication remote") from exc
    if query.returncode != 0:
        raise ValueError("cannot query authoritative publication remote")
    rows = [line for line in query.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("authoritative remote branch must resolve exactly once")
    fields = rows[0].split("\t")
    if len(fields) != 2 or fields[1] != branch_ref or not SHA.fullmatch(fields[0]):
        raise ValueError("authoritative remote branch response is invalid")
    if fields[0] != published_commit:
        raise ValueError("published commit is not exact authoritative remote branch head")
    return True


def validate_publication_proof(proof, handoff, git_worktree, evidence_root=None, remote="origin",
                               trusted_repository=None, trusted_remote_id=None):
    validate_handoff(handoff)
    if not isinstance(proof, dict) or set(proof) != PROOF_FIELDS or proof.get("schema") != PROOF_SCHEMA:
        raise ValueError("managed executor publication proof fields/schema mismatch")
    if proof["handoff_ref"] != canonical_handoff_ref(handoff):
        raise ValueError("publication proof handoff_ref mismatch")
    for name in ("pool_id", "task_id", "attempt_id", "base_sha"):
        expected = handoff[name]
        if proof[name] != expected:
            raise ValueError(f"publication proof {name} mismatch")
    if canonical_branch_ref(proof["assigned_branch"]) != canonical_branch_ref(handoff["assigned_branch"]):
        raise ValueError("publication proof branch mismatch")
    _text(proof["publication_repository"], "publication proof repository")
    _digest(proof["publication_remote_id"], "publication proof remote identity")
    if trusted_repository is None or trusted_remote_id is None:
        raise ValueError("trusted publication identity is required")
    if (handoff["publication_repository"] != trusted_repository
            or proof["publication_repository"] != trusted_repository):
        raise ValueError("publication repository identity mismatch")
    if (handoff["publication_remote_id"] != trusted_remote_id
            or proof["publication_remote_id"] != trusted_remote_id):
        raise ValueError("publication remote identity mismatch")
    _sha(proof["published_commit"], "published_commit")
    if handoff["transport"] == "direct_branch" and proof["published_commit"] != handoff["direct_result_commit"]:
        raise ValueError("direct publication commit mismatch")
    if handoff["source_result_commit"] is not None and handoff["artifact_ref"] and handoff["artifact_ref"]["format"] == "git_bundle":
        if proof["published_commit"] != handoff["source_result_commit"]:
            raise ValueError("git_bundle publication must preserve source result commit")
    _paths(proof["observed_changed_paths"], "publication proof observed_changed_paths")
    _refs(proof["evidence_refs"], "publication proof evidence_refs")
    if type(proof["result_verified"]) is not bool or not proof["result_verified"]:
        raise ValueError("publication proof must be result_verified")
    for name in AUTHORITY_FIELDS:
        if type(proof[name]) is not bool or proof[name]:
            raise ValueError(f"{name} must remain false")
    root = Path(git_worktree)
    if not root.is_dir():
        raise ValueError("publication proof requires live git_worktree")
    branch_ref = canonical_branch_ref(handoff["assigned_branch"])
    try:
        for sha in (handoff["base_sha"], proof["published_commit"]):
            kind = subprocess.check_output(
                ["git", "-C", str(root), "cat-file", "-t", sha],
                env=git_object_environment(), text=True, stderr=subprocess.PIPE, timeout=15,
            ).strip()
            if kind != "commit":
                raise ValueError("publication ancestry endpoint is not a commit")
        ancestry = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", handoff["base_sha"], proof["published_commit"]],
            env=git_object_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15,
        )
        if ancestry.returncode != 0:
            raise ValueError("published result does not descend from handoff base")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot verify published result: {exc}") from exc
    _verify_remote_branch(
        root, remote, branch_ref, proof["published_commit"], trusted_remote_id)
    actual_changed_paths = _git_changed_paths(root, handoff["base_sha"], proof["published_commit"])
    if _portable_set(actual_changed_paths) != _portable_set(handoff["changed_paths"]):
        raise ValueError("actual published Git diff does not match handoff manifest")
    if _portable_set(actual_changed_paths) != _portable_set(proof["observed_changed_paths"]):
        raise ValueError("publication proof changed paths do not match actual Git diff")
    if handoff["transport"] == "content_artifact":
        artifact_root = Path(evidence_root).resolve() if evidence_root is not None else root.resolve()
        artifact_path = (artifact_root / handoff["artifact_ref"]["path"]).resolve()
        payload = resolve_artifact(handoff, artifact_root)
        if handoff["artifact_ref"]["format"] == "unified_diff":
            _verify_unified_diff_artifact(handoff, payload, root, proof["published_commit"])
        else:
            _verify_git_bundle_artifact(handoff, payload, root, proof["published_commit"])
    return proof


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("handoff")
    p.add_argument("--evidence-root")
    a = p.parse_args(argv)
    try:
        handoff = json.loads(Path(a.handoff).read_text())
        result = publication_plan(handoff, evidence_root=a.evidence_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
