#!/usr/bin/env python3
"""Opaque Git endpoint identities shared by coordination and publication."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import urlsplit


def _git(repo, *args, allow_missing=False):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=git_object_environment(GIT_TERMINAL_PROMPT="0"), timeout=15,
        )
        if allow_missing and result.returncode == 1:
            return None
        if result.returncode:
            raise ValueError
        return result.stdout.rstrip("\n")
    except (OSError, subprocess.SubprocessError, ValueError):
        # Git errors/exception chains may contain credential-bearing endpoints.
        raise ValueError("cannot resolve Git remote identity") from None


def repository_root(repo):
    """Resolve Git's working root, including calls from nested or bare directories."""
    bare = _git(repo, "rev-parse", "--is-bare-repository")
    option = "--absolute-git-dir" if bare == "true" else "--show-toplevel"
    return Path(_git(repo, "rev-parse", option)).resolve()


def _endpoint(value):
    if (not isinstance(value, str) or not value.strip()
            or any(char in value for char in ("\n", "\r", "\0"))):
        raise ValueError("Git remote endpoint is invalid")
    return value


def _local_path(value, root):
    path = Path(value).expanduser()
    if not path.is_absolute():
        if root is None:
            raise ValueError("relative Git remote requires a repository")
        path = root / path
    return str(path.resolve())


def _identity_for_effective_endpoint(value, root):
    """Hash an already Git-resolved endpoint; do not apply insteadOf a second time."""
    value = _endpoint(value)
    try:
        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme == "file":
                if parsed.netloc not in {"", "localhost"} or parsed.query or parsed.fragment:
                    raise ValueError
                key = _local_path(parsed.path, root)
            else:
                if not parsed.hostname:
                    raise ValueError
                # Preserve account/path/query semantics; passwords never leave parsing.
                key = json.dumps([
                    parsed.scheme.lower(), parsed.username, parsed.hostname.lower(),
                    parsed.port, parsed.path, parsed.query, parsed.fragment,
                ], ensure_ascii=False, separators=(",", ":"))
        else:
            scp = re.fullmatch(r"(?:(?P<user>[^@/:]+)@)?(?P<host>\[[^\]]+\]|[^/:]+):(?P<path>.+)", value)
            if scp:
                # The leading slash distinguishes server-root from login-home paths.
                key = json.dumps([
                    "scp", scp["user"], scp["host"].lower(), scp["path"],
                ], ensure_ascii=False, separators=(",", ":"))
            else:
                key = _local_path(value, root)
        return "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()
    except (OSError, ValueError, RuntimeError):
        raise ValueError("Git remote endpoint is invalid") from None


def endpoint_identity(value, *, repo_root=None):
    """Identify an endpoint, honoring Git insteadOf rules when a repository is given."""
    value = _endpoint(value)
    root = repository_root(repo_root) if repo_root is not None else None
    if root is not None:
        # --get-url is local configuration resolution only; it does not contact a remote.
        value = _git(root, "ls-remote", "--get-url", "--", value)
    return _identity_for_effective_endpoint(value, root)


def remote_identity(repo, remote):
    """Identify one configured authoritative fetch/push destination without network IO."""
    if not isinstance(remote, str) or not remote.strip() or remote.startswith("-"):
        raise ValueError("Git remote name is invalid")
    root = repository_root(repo)
    if remote not in _git(root, "remote").splitlines():
        raise ValueError("Git remote is not configured")
    fetch = _git(root, "remote", "get-url", "--all", remote).splitlines()
    push = _git(root, "remote", "get-url", "--push", "--all", remote).splitlines()
    if len(fetch) != 1 or len(push) != 1:
        raise ValueError("Git remote requires one identical fetch/push endpoint")
    fetch_id = _identity_for_effective_endpoint(fetch[0], root)
    if _identity_for_effective_endpoint(push[0], root) != fetch_id:
        raise ValueError("Git remote requires one identical fetch/push endpoint")
    return fetch_id


def isolated_remote_args(repo, remote, expected_identity):
    """Return command-scoped remote args without inherited local ref mappings.

    Copy RAW configured endpoints so Git applies insteadOf/pushInsteadOf exactly
    once. Verify the source's effective fetch/push identities before transport.
    Passing an already resolved URL back to Git could apply a second rewrite;
    passing the original remote could update arbitrary local tracking/product refs.
    Returned configuration may contain credentials and must never be logged.
    """
    root = repository_root(repo)
    if remote_identity(root, remote) != expected_identity:
        raise ValueError("Git coordination remote identity drift")
    raw_fetch = _git(root, "config", "--get-all", f"remote.{remote}.url").splitlines()
    raw_push_value = _git(root, "config", "--get-all", f"remote.{remote}.pushurl", allow_missing=True)
    raw_push = raw_push_value.splitlines() if raw_push_value is not None else []
    if len(raw_fetch) != 1 or len(raw_push) > 1:
        raise ValueError("Git transport requires one configured endpoint")
    alias = "cdc-isolated-" + secrets.token_hex(16)
    config = ["-c", f"remote.{alias}.url={_endpoint(raw_fetch[0])}"]
    if raw_push:
        config += ["-c", f"remote.{alias}.pushurl={_endpoint(raw_push[0])}"]
    # remote get-url requires a remote defined in a repository-scoped config and
    # rejects command-only aliases. ls-remote --get-url resolves their fetch URL
    # without IO. The unchanged raw pushURL (or its absence) uses the identical
    # Git rewrite rules as the source remote, whose push identity is checked again.
    effective = _git(root, *config, "ls-remote", "--get-url", "--", alias).splitlines()
    if len(effective) != 1 or _identity_for_effective_endpoint(effective[0], root) != expected_identity:
        raise ValueError("Git isolated transport identity drift")
    if remote_identity(root, remote) != expected_identity:
        raise ValueError("Git coordination remote identity drift")
    return config, alias
