#!/usr/bin/env python3
"""Resolve a fresh Fleet target and verify its immutable canonical Git release.

This reader fetches objects into a local cache but never updates product refs,
adopts a package, or operates a scheduler. Trust comes from configured endpoint
identities and the release binding committed alongside the live registry.
"""
from __future__ import annotations

from git_object_integrity import git_object_environment

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Protocol

from fleet_supervisor import validate_registry
from git_remote_identity import remote_identity, repository_root
from version_convergence import validate_target

SHA = re.compile(r"[0-9a-f]{40}")
IDENTITY = re.compile(r"sha256:[0-9a-f]{64}")
PATH = re.compile(r"[A-Za-z0-9._/-]+")


def _utc_now():
    return datetime.now(timezone.utc)


def _instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return value.astimezone(timezone.utc)


def _stamp(value):
    return _instant(value).isoformat().replace("+00:00", "Z")


def _path(value):
    if (not isinstance(value, str) or not PATH.fullmatch(value)
            or value.startswith("/") or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise ValueError("unsafe Git document path")
    return value


def _sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("expected exact Git SHA-1 object identity")
    return value


def _identity(value):
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise ValueError("trusted endpoint identity is required")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json(source, snapshot, path):
    def invalid_constant(_value):
        raise ValueError("invalid JSON numeric constant")
    try:
        return json.loads(source.read_file(snapshot, _path(path)),
                          object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    except json.JSONDecodeError:
        raise ValueError("invalid Git JSON document") from None


@dataclass(frozen=True)
class Revision:
    """A live read observation, not a commit timestamp or a local cache claim."""
    revision: str
    ref: str
    source_identity: str
    observed_at_utc: str


class RegistrySource(Protocol):
    """Caller-supplied live read capability with independently configured trust."""
    def identity(self) -> str: ...
    def pin(self, ref: str) -> Revision: ...
    def read_file(self, snapshot: Revision, path: str) -> str: ...
    def assert_current(self, snapshot: Revision) -> None: ...


class ReleaseSource(RegistrySource, Protocol):
    def tree_oid(self, snapshot: Revision, path: str, *, revision=None) -> str: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...


class GitSource:
    """Read one configured Git endpoint; aliases are never authority by themselves.

    expected_identity must come from trusted deployment configuration, using the
    shared git_remote_identity normalization. Do not derive it from an unchecked
    alias at the point where the resolver is making a trust decision.
    """
    def __init__(self, repo, remote, expected_identity, *, clock=_utc_now):
        self.repo = repository_root(Path(repo))
        self.remote = remote
        self.expected_identity = _identity(expected_identity)
        self.clock = clock
        self.identity()

    def identity(self):
        actual = remote_identity(self.repo, self.remote)
        if actual != self.expected_identity:
            raise ValueError("Git source identity disagrees with trusted endpoint")
        return actual

    def _git(self, *args, allow_nonancestor=False):
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *args], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=git_object_environment(GIT_TERMINAL_PROMPT="0"), timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Git source transport unavailable") from None
        if result.returncode and not (allow_nonancestor and result.returncode == 1):
            # Endpoint URLs and credential-helper output must not leak in errors.
            raise ValueError("Git source operation failed")
        return result.returncode, result.stdout.rstrip("\n")

    def _ref_revision(self, ref):
        if not isinstance(ref, str) or not ref.startswith("refs/heads/"):
            raise ValueError("source ref must be an exact refs/heads/ ref")
        self._git("check-ref-format", ref)
        self.identity()
        rows = self._git("ls-remote", "--refs", self.remote, ref)[1].splitlines()
        if len(rows) != 1:
            raise ValueError("missing or ambiguous live Git ref")
        fields = rows[0].split("\t")
        if len(fields) != 2 or fields[1] != ref:
            raise ValueError("live Git ref identity mismatch")
        self.identity()
        return _sha(fields[0])

    def pin(self, ref):
        observed = _stamp(self.clock())
        revision = self._ref_revision(ref)
        # Empty refmap prevents remote-tracking updates; no destination ref and
        # no FETCH_HEAD means only the local object cache changes.
        self._git("fetch", "--no-tags", "--no-write-fetch-head", "--refmap=",
                  self.remote, revision)
        if self._git("cat-file", "-t", revision)[1] != "commit":
            raise ValueError("live ref must point to a commit")
        snapshot = Revision(revision, ref, self.identity(), observed)
        self.assert_current(snapshot)
        return snapshot

    def _check_snapshot(self, snapshot):
        _sha(snapshot.revision)
        if self.identity() != snapshot.source_identity:
            raise ValueError("snapshot source identity mismatch")

    def read_file(self, snapshot, path):
        self._check_snapshot(snapshot)
        return self._git("cat-file", "blob", snapshot.revision + ":" + _path(path))[1]

    def tree_oid(self, snapshot, path, *, revision=None):
        self._check_snapshot(snapshot)
        commit = _sha(revision if revision is not None else snapshot.revision)
        if self._git("cat-file", "-t", commit)[1] != "commit":
            raise ValueError("release provenance must point to a commit")
        tree = _sha(self._git("rev-parse", "--verify", commit + ":" + _path(path))[1])
        if self._git("cat-file", "-t", tree)[1] != "tree":
            raise ValueError("package path must be a Git tree")
        return tree

    def is_ancestor(self, ancestor, descendant):
        return self._git("merge-base", "--is-ancestor", _sha(ancestor), _sha(descendant),
                         allow_nonancestor=True)[0] == 0

    def assert_current(self, snapshot):
        self._check_snapshot(snapshot)
        if self._ref_revision(snapshot.ref) != snapshot.revision:
            raise ValueError("live Git ref moved during resolution")


def _fresh(snapshot, identity, ref, now, maximum):
    _identity(identity)
    if not isinstance(snapshot, Revision) or snapshot.source_identity != identity or snapshot.ref != ref:
        raise ValueError("transport observation identity/ref mismatch")
    _sha(snapshot.revision)
    stamp = snapshot.observed_at_utc
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        raise ValueError("observation must be a UTC Z timestamp")
    try:
        observed = datetime.fromisoformat(stamp[:-1] + "+00:00")
    except ValueError:
        raise ValueError("observation timestamp is invalid") from None
    age = (_instant(now) - _instant(observed)).total_seconds()
    if age < 0 or age > maximum:
        raise ValueError("live target observation is stale or future")


def _release_binding(binding, target, canonical_repository):
    fields = {"schema", "version", "canonical_repository", "release_ref", "release_commit", "package_tree"}
    if not isinstance(binding, dict):
        raise ValueError("invalid live target release provenance")
    schema = binding.get("schema")
    if schema == "live-target-release/v2":
        fields = fields | {"evidence_binding"}
    if schema not in {"live-target-release/v1", "live-target-release/v2"} or set(binding) != fields:
        raise ValueError("invalid live target release provenance")
    expected = {
        "version": target["target_version"], "canonical_repository": canonical_repository,
        "release_ref": "refs/heads/release/v" + target["target_version"],
        "package_tree": target["target_package_fingerprint"].removeprefix("git-tree:"),
    }
    if not target["target_package_fingerprint"].startswith("git-tree:"):
        raise ValueError("live target requires an exact Git package tree")
    for name, value in expected.items():
        if binding[name] != value:
            raise ValueError("live target release provenance disagrees: " + name)
    _sha(binding["release_commit"])
    _sha(binding["package_tree"])



def _evidence_binding(binding, canonical_identity):
    value = binding.get("evidence_binding")
    fields = {"schema", "source_identity", "ref", "commit", "path"}
    if (not isinstance(value, dict) or set(value) != fields
            or value.get("schema") != "canonical-release-evidence-binding/v1"):
        raise ValueError("invalid canonical evidence binding")
    if _identity(value["source_identity"]) != canonical_identity:
        raise ValueError("canonical evidence source identity disagrees")
    ref = _path(value["ref"])
    if (not ref.startswith("refs/heads/") or ".." in ref or ref.endswith(".")
            or any(part.endswith(".lock") for part in ref.split("/"))):
        raise ValueError("canonical evidence ref must be an exact branch ref")
    _sha(value["commit"])
    if _path(value["path"]) != "release/evidence-" + binding["version"] + ".json":
        raise ValueError("canonical evidence path disagrees with release version")
    return value


def verify_release_binding(canonical_source: ReleaseSource, binding, *, canonical_repository,
                           package_path="src/continuous-development-cycle", max_age_seconds=300,
                           clock=_utc_now):
    """Verify exact configured release objects; this grants no effect authority."""
    if not isinstance(canonical_repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", canonical_repository):
        raise ValueError("independently configured canonical_repository is required")
    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be a positive integer")
    _path(package_path)
    if not isinstance(binding, dict):
        raise ValueError("invalid release binding")
    target = {"schema": "version-convergence-target/v1", "target_version": binding.get("version"),
              "target_package_fingerprint": "git-tree:" + str(binding.get("package_tree")),
              "checkpoint_schema": "development-work-status/v4", "safe_boundary_required": True}
    validate_target(target)
    _release_binding(binding, target, canonical_repository)
    canonical_identity = _identity(canonical_source.identity())
    release_revision = canonical_source.pin(binding["release_ref"])
    _fresh(release_revision, canonical_identity, binding["release_ref"], clock(), max_age_seconds)
    if release_revision.revision != binding["release_commit"]:
        raise ValueError("canonical release_commit disagrees with immutable live binding")
    if canonical_source.tree_oid(release_revision, package_path) != binding["package_tree"]:
        raise ValueError("canonical package tree disagrees with live target")
    if canonical_source.read_file(release_revision, package_path + "/VERSION").strip() != binding["version"]:
        raise ValueError("canonical package VERSION disagrees with live target")
    evidence_revision = release_revision
    evidence_path = "release/evidence-" + binding["version"] + ".json"
    split_evidence = binding["schema"] == "live-target-release/v2"
    if split_evidence:
        evidence_binding = _evidence_binding(binding, canonical_identity)
        evidence_revision = canonical_source.pin(evidence_binding["ref"])
        _fresh(evidence_revision, canonical_identity, evidence_binding["ref"], clock(), max_age_seconds)
        if evidence_revision.revision != evidence_binding["commit"]:
            raise ValueError("canonical evidence commit disagrees with pinned binding")
        if not canonical_source.is_ancestor(release_revision.revision, evidence_revision.revision):
            raise ValueError("canonical release is not an evidence ancestor")
        if canonical_source.tree_oid(evidence_revision, package_path) != binding["package_tree"]:
            raise ValueError("canonical evidence package tree disagrees")
        evidence_path = evidence_binding["path"]
    evidence = _json(canonical_source, evidence_revision, evidence_path)
    if (not isinstance(evidence, dict) or evidence.get("schema") != "cdc-release-evidence/v1"
            or evidence.get("status") != "released"):
        raise ValueError("canonical release evidence is missing or unreleased")
    for name in ("version", "canonical_repository", "release_ref", "package_tree"):
        if evidence.get(name) != binding[name]:
            raise ValueError("canonical release evidence disagrees: " + name)
    if split_evidence and "release_commit" not in evidence:
        raise ValueError("canonical split evidence requires release_commit")
    if "release_commit" in evidence and evidence["release_commit"] != binding["release_commit"]:
        raise ValueError("canonical evidence release_commit disagrees")
    candidate = _sha(evidence.get("candidate_source_commit"))
    if not canonical_source.is_ancestor(candidate, release_revision.revision):
        raise ValueError("canonical candidate is not a release ancestor")
    if canonical_source.tree_oid(release_revision, package_path, revision=candidate) != binding["package_tree"]:
        raise ValueError("canonical candidate package tree disagrees")
    canonical_source.assert_current(release_revision)
    if split_evidence:
        canonical_source.assert_current(evidence_revision)
    finished = clock()
    _fresh(release_revision, canonical_source.identity(), binding["release_ref"], finished, max_age_seconds)
    if split_evidence:
        _fresh(evidence_revision, canonical_source.identity(), evidence_binding["ref"], finished, max_age_seconds)
    return {"schema": "canonical-release-verification/v1", "release": binding,
            "release_revision": release_revision, "evidence_revision": evidence_revision,
            "evidence": evidence, "canonical_source_identity": canonical_identity,
            "observed_at_utc": _stamp(finished), "authorizes_adoption": False,
            "authorizes_product_write": False, "authorizes_scheduler_write": False}


def resolve_live_target(registry_source: RegistrySource, canonical_source: ReleaseSource, *, registry_ref,
                        canonical_repository, registry_path="fleet/registry.json",
                        target_path=None, release_path="fleet/target-release.json",
                        package_path="src/continuous-development-cycle",
                        max_age_seconds=300, clock=_utc_now):
    """Read one live registry revision, then verify its canonical release binding.

    A transport implements identity(), pin(ref), read_file(revision, path),
    tree_oid(revision, path, revision=None), is_ancestor(a, b), assert_current().
    GitSource is the real Git implementation. External transports must provide
    equivalent trusted identity, exact objects and independently timed live reads.
    Any unknown, disagreement, stale observation or moved authority raises
    ValueError. The successful result confers no permission for side effects.
    """
    if not isinstance(canonical_repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", canonical_repository):
        raise ValueError("independently configured canonical_repository is required")
    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be a positive integer")
    for path in (registry_path, release_path, package_path):
        _path(path)
    if target_path is not None:
        _path(target_path)
    registry_identity = _identity(registry_source.identity())
    canonical_identity = _identity(canonical_source.identity())
    registry_revision = registry_source.pin(registry_ref)
    _fresh(registry_revision, registry_identity, registry_ref, clock(), max_age_seconds)
    registry = _json(registry_source, registry_revision, registry_path)
    validate_registry(registry)
    target = registry["target"]
    if target_path is not None:
        standalone = _json(registry_source, registry_revision, target_path)
        validate_target(standalone)
        if standalone != target:
            raise ValueError("embedded and standalone live targets disagree")
    binding = _json(registry_source, registry_revision, release_path)
    _release_binding(binding, target, canonical_repository)
    proof = verify_release_binding(canonical_source, binding,
        canonical_repository=canonical_repository, package_path=package_path,
        max_age_seconds=max_age_seconds, clock=clock)
    release_revision = proof["release_revision"]
    evidence_revision = proof["evidence_revision"]
    split_evidence = binding["schema"] == "live-target-release/v2"
    if split_evidence:
        evidence_binding = binding["evidence_binding"]
    registry_source.assert_current(registry_revision)
    canonical_source.assert_current(release_revision)
    if split_evidence:
        canonical_source.assert_current(evidence_revision)
    finished = clock()
    _fresh(registry_revision, registry_source.identity(), registry_ref, finished, max_age_seconds)
    _fresh(release_revision, canonical_source.identity(), binding["release_ref"], finished, max_age_seconds)
    if split_evidence:
        _fresh(evidence_revision, canonical_source.identity(), evidence_binding["ref"], finished, max_age_seconds)
    result = {
        "schema": "live-target-resolution/v1", "observed_at_utc": _stamp(finished),
        "registry_source_identity": registry_identity, "registry_ref": registry_ref,
        "registry_revision": registry_revision.revision,
        "registry_observed_at_utc": registry_revision.observed_at_utc,
        "canonical_source_identity": canonical_identity,
        "release_observed_at_utc": release_revision.observed_at_utc,
        "registry": registry, "target": target, "release": binding,
        "authorizes_adoption": False, "authorizes_scheduler_write": False,
    }
    if split_evidence:
        result["evidence_observation"] = {
            "source_identity": evidence_revision.source_identity,
            "ref": evidence_revision.ref, "revision": evidence_revision.revision,
            "observed_at_utc": evidence_revision.observed_at_utc,
        }
    return result
