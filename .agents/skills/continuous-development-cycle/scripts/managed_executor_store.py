#!/usr/bin/env python3
"""CDC 2.11.0 durable Git CAS store for managed executor pool state."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import copy
import json
import os
import re
import secrets
import subprocess

from managed_executor_pool import validate_plan, validate_state
from git_remote_identity import endpoint_identity, isolated_remote_args, remote_identity, repository_root
from parallel_task_planner import portable_path_key

REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
STATE_FILE = "pool-state.json"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical(state):
    return json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"


def coordination_store_id_for_endpoint(value, *, repo_root=None):
    return endpoint_identity(value, repo_root=repo_root)


def _canonical_heads_ref(value, name):
    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise ValueError(f"{name} must be an exact refs/heads/ ref")
    if value != "refs/heads/" + value.removeprefix("refs/heads/"):
        raise ValueError(f"{name} must be canonical")
    return value




class GitManagedExecutorStore:
    """One-file Git-ref CAS store.

    Each state transition creates a sibling/child coordination commit and performs a
    normal non-force push. Competing proposals based on one revision therefore race
    at the remote ref; at most one can advance it.
    """

    def __init__(self, repo, remote, coordination_ref, plan, *, protected_refs=()):
        self.repo = repository_root(repo)
        validate_plan(plan)
        self.plan = copy.deepcopy(plan)
        if not isinstance(remote, str) or not remote.strip() or remote.startswith("-"):
            raise ValueError("pool store remote name invalid")
        self.remote = remote
        self.ref = _canonical_heads_ref(coordination_ref, "coordination_ref")
        if self.ref != plan["coordination_ref"]:
            raise ValueError("coordination ref does not match managed-pool plan")
        protected = {_canonical_heads_ref(ref, "protected_ref") for ref in protected_refs}
        writer_refs = set()
        for task in plan["tasks"]:
            if task["role"] == "writer":
                branch = task["branch"]
                writer_refs.add(branch if branch.startswith("refs/heads/") else "refs/heads/" + branch)
        coordination_key = portable_path_key(self.ref.removeprefix("refs/heads/"))
        occupied_keys = {
            portable_path_key(ref.removeprefix("refs/heads/"))
            for ref in protected | writer_refs
        }
        if coordination_key in occupied_keys:
            raise ValueError("coordination ref must be portable-isolated from product/shared/worker refs")
        self._git("check-ref-format", self.ref)
        try:
            self._assert_remote_identity()
        except ValueError as exc:
            if "identity drift" in str(exc):
                raise ValueError("pool store identity does not match managed-pool plan") from None
            raise
        self.store_id = plan["coordination_store_id"]

    def _assert_remote_identity(self):
        try:
            observed = remote_identity(self.repo, self.remote)
        except ValueError:
            raise ValueError("pool store remote configuration drift") from None
        if observed != self.plan["coordination_store_id"]:
            raise ValueError("pool store identity drift")
        return True

    def _git(self, *args, input_text=None):
        env = git_object_environment(GIT_TERMINAL_PROMPT="0",
            GIT_AUTHOR_NAME="CDC managed executor",
            GIT_AUTHOR_EMAIL="cdc@example.invalid",
            GIT_COMMITTER_NAME="CDC managed executor",
            GIT_COMMITTER_EMAIL="cdc@example.invalid",
        )
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Git managed-executor coordination unavailable") from exc
        if result.returncode:
            raise ValueError(f"Git managed-executor coordination {args[0]} failed")
        return result.stdout.strip()

    def _remote_rows(self):
        self._assert_remote_identity()
        rows = self._git("ls-remote", "--refs", self.remote, self.ref).splitlines()
        if not rows:
            return []
        if len(rows) != 1:
            raise ValueError("ambiguous managed-executor coordination ref")
        parts = rows[0].split("\t")
        if len(parts) != 2 or parts[1] != self.ref or not REVISION.fullmatch(parts[0]):
            raise ValueError("invalid managed-executor coordination revision")
        return rows

    def _decode_state(self, payload):
        try:
            state = json.loads(payload, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("invalid managed-executor pool state JSON") from exc
        if not isinstance(state, dict):
            raise ValueError("managed-executor pool state must be an object")
        if _canonical(state) != payload.encode("utf-8"):
            raise ValueError("managed-executor pool state must use canonical JSON encoding")
        validate_state(self.plan, state)
        return state

    def read(self):
        rows = self._remote_rows()
        if not rows:
            return None, None
        revision = rows[0].split("\t", 1)[0]
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "fetch", "--no-tags", "--no-write-fetch-head", "--refmap=", remote, self.ref)
        if self._git("cat-file", "-t", revision) != "commit":
            raise ValueError("managed-executor coordination ref must point to a commit")
        tree_rows = self._git("ls-tree", "--name-only", revision).splitlines()
        if tree_rows != [STATE_FILE]:
            raise ValueError("managed-executor coordination commit must contain only pool-state.json")
        payload = self._git("show", f"{revision}:{STATE_FILE}") + "\n"
        state = self._decode_state(payload)
        if self._remote_rows() != rows:
            raise ValueError("managed-executor coordination ref moved during read")
        return revision, state

    def compare_and_swap(self, expected_revision, new_state):
        validate_state(self.plan, new_state)
        if new_state["coordination_ref"] != self.ref or new_state["coordination_store_id"] != self.store_id:
            raise ValueError("managed-executor state coordination identity mismatch")
        current_revision, current_state = self.read()
        if current_revision != expected_revision:
            raise ValueError("stale expected managed-executor store revision")
        if expected_revision is None and current_state is not None:
            raise ValueError("managed-executor store already initialized")
        payload = _canonical(new_state).decode("utf-8")
        blob = self._git("hash-object", "-w", "--stdin", input_text=payload)
        tree = self._git("mktree", input_text=f"100644 blob {blob}\t{STATE_FILE}\n")
        parent = ["-p", expected_revision] if expected_revision is not None else []
        # Equal state/parent/clock must still produce competing sibling commits.
        # Otherwise Git accepts the second identical proposal as "up to date",
        # and both callers could receive the same one-shot launch authority.
        proposal_nonce = secrets.token_hex(32)
        commit = self._git(
            "commit-tree", tree, *parent,
            input_text=f"Update managed executor pool state\n\nCAS proposal: {proposal_nonce}\n",
        )
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "-c", "push.followTags=false", "push", "--porcelain", remote, f"{commit}:{self.ref}")
        rows = self._remote_rows()
        if len(rows) != 1 or rows[0].split("\t", 1)[0] != commit:
            raise ValueError("managed-executor CAS push did not become authoritative")
        return commit
