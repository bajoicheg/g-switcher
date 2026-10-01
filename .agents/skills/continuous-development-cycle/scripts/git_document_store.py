#!/usr/bin/env python3
"""Dedicated one-document Git CAS ref, isolated from all product branches."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import json
import os
import re
import secrets
import subprocess

from git_remote_identity import isolated_remote_args, remote_identity, repository_root
from parallel_task_planner import portable_path_key

STATE_FILE = "document.json"
REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_BYTES = 4 * 1024 * 1024


def canonical(document):
    if not isinstance(document, dict):
        raise ValueError("coordination document must be an object")
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("coordination document exceeds 4 MiB")
    return encoded


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate coordination JSON key")
        value[key] = item
    return value


class GitDocumentStore:
    """Non-force remote CAS; every proposal has an unpredictable commit nonce.

    This ref must be dedicated to document.json. Reads reject any other root
    content, so this store cannot silently erase another coordination format.
    """

    def __init__(self, repo, remote, coordination_ref, coordination_store_id, *, protected_refs=()):
        self.repo = repository_root(repo)
        self.remote = remote
        self.ref = coordination_ref
        self.store_id = coordination_store_id
        if not isinstance(self.ref, str) or not self.ref.startswith("refs/heads/cdc/"):
            raise ValueError("document coordination ref must be a dedicated refs/heads/cdc/ ref")
        if not isinstance(self.store_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.store_id):
            raise ValueError("coordination endpoint identity must be explicit")
        self._git("check-ref-format", self.ref)
        protected = {portable_path_key(ref) for ref in protected_refs}
        if portable_path_key(self.ref) in protected:
            raise ValueError("coordination ref must be portable-isolated from product refs")
        self._assert_remote_identity()

    def _assert_remote_identity(self):
        if remote_identity(self.repo, self.remote) != self.store_id:
            raise ValueError("document coordination remote identity drift")

    def _git(self, *args, input_text=None):
        env = git_object_environment(GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="CDC coordination",
                   GIT_AUTHOR_EMAIL="cdc@example.invalid", GIT_COMMITTER_NAME="CDC coordination",
                   GIT_COMMITTER_EMAIL="cdc@example.invalid")
        try:
            result = subprocess.run(["git", "-C", str(self.repo), *args], input=input_text, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=20)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Git document coordination unavailable") from None
        if result.returncode:
            raise ValueError("Git document coordination command failed")
        return result.stdout.rstrip("\n")

    def _remote_revision(self):
        self._assert_remote_identity()
        rows = self._git("ls-remote", "--refs", self.remote, self.ref).splitlines()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("ambiguous document coordination ref")
        parts = rows[0].split("\t")
        if len(parts) != 2 or parts[1] != self.ref or not REVISION.fullmatch(parts[0]):
            raise ValueError("invalid document coordination revision")
        return parts[0]

    def read(self):
        revision = self._remote_revision()
        if revision is None:
            return None, None
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "fetch", "--no-tags", "--no-write-fetch-head", "--refmap=", remote, self.ref)
        if self._git("cat-file", "-t", revision) != "commit":
            raise ValueError("document coordination ref must point to a commit")
        if self._git("ls-tree", "--name-only", revision).splitlines() != [STATE_FILE]:
            raise ValueError("dedicated coordination tree must contain only document.json")
        payload = self._git("show", f"{revision}:{STATE_FILE}") + "\n"
        if len(payload.encode("utf-8")) > MAX_BYTES:
            raise ValueError("coordination document exceeds 4 MiB")
        document = json.loads(payload, object_pairs_hook=unique_object)
        if canonical(document) != payload:
            raise ValueError("coordination document must have canonical JSON encoding")
        if revision != self._remote_revision():
            raise ValueError("coordination ref moved during read")
        return revision, document

    def read_revision(self, revision):
        """Read an immutable document from this coordination ref's authoritative history."""
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise ValueError("invalid historical document revision")
        current, _ = self.read()
        if current is None:
            raise ValueError("document coordination history is absent")
        if self._git("cat-file", "-t", revision) != "commit":
            raise ValueError("historical document revision must be a commit")
        try:
            base = self._git("merge-base", revision, current)
        except ValueError:
            raise ValueError("historical revision is not in authoritative document ancestry") from None
        if base != revision:
            raise ValueError("historical revision is not in authoritative document ancestry")
        if self._git("ls-tree", "--name-only", revision).splitlines() != [STATE_FILE]:
            raise ValueError("historical coordination tree must contain only document.json")
        payload = self._git("show", f"{revision}:{STATE_FILE}") + "\n"
        document = json.loads(payload, object_pairs_hook=unique_object)
        if canonical(document) != payload:
            raise ValueError("historical coordination document must have canonical JSON encoding")
        return document

    def compare_and_swap(self, expected_revision, document):
        payload = canonical(document)
        current, _ = self.read()
        if expected_revision != current:
            raise ValueError("stale expected document revision")
        blob = self._git("hash-object", "-w", "--stdin", input_text=payload)
        tree = self._git("mktree", input_text=f"100644 blob {blob}\t{STATE_FILE}\n")
        parent = ["-p", expected_revision] if expected_revision else []
        commit = self._git("commit-tree", tree, *parent,
                           input_text="Update CDC coordination\n\nCAS proposal: " + secrets.token_hex(32) + "\n")
        # Revalidate immediately before the side effect; never force-update the ref.
        self._assert_remote_identity()
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "-c", "push.followTags=false", "push", "--porcelain", remote, f"{commit}:{self.ref}")
        if self._remote_revision() != commit:
            raise ValueError("document CAS did not become authoritative")
        return commit
