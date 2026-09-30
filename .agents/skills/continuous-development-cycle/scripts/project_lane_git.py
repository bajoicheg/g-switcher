#!/usr/bin/env python3
"""Real-Git result verifier for cooperative writer lanes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import copy
import re
import secrets
import subprocess

try:
    from git_document_store import GitDocumentStore
    from git_object_integrity import git_object_environment
    from git_remote_identity import isolated_remote_args, remote_identity
    from parallel_task_planner import validate_write_path
    from project_lanes import LaneKind, branch_key, validate_claim
except ModuleNotFoundError:
    from scripts.git_document_store import GitDocumentStore
    from scripts.git_object_integrity import git_object_environment
    from scripts.git_remote_identity import isolated_remote_args, remote_identity
    from scripts.parallel_task_planner import validate_write_path
    from scripts.project_lanes import LaneKind, branch_key, validate_claim

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})$")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}$")
INVALID_REF = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")


class GitLaneResultVerifier:
    """Validate ancestry and the union of every path touched by introduced commits."""

    def __init__(self, repo):
        self.repo = Path(repo).resolve()
        root, _ = self._run("rev-parse", "--show-toplevel")
        if Path(root).resolve() != self.repo:
            raise ValueError("lane verifier repo must be the Git worktree root")

    def _run(self, *args, check=True):
        env = git_object_environment(GIT_TERMINAL_PROMPT="0")
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Git lane result verification unavailable") from None
        if check and result.returncode:
            raise ValueError("Git lane result verification command failed")
        return result.stdout.rstrip("\n"), result.returncode

    def _commit_exists(self, revision):
        if not isinstance(revision, str) or not SHA.fullmatch(revision):
            raise ValueError("lane result revision must be an exact Git commit SHA")
        _, code = self._run("cat-file", "-e", revision + "^{commit}", check=False)
        if code:
            raise ValueError("lane result revision is not an available commit")

    def __call__(self, claim, result_commit):
        validate_claim(claim)
        self._commit_exists(claim.source_head)
        self._commit_exists(result_commit)
        _, code = self._run(
            "merge-base", "--is-ancestor", claim.source_head, result_commit, check=False)
        if code not in {0, 1}:
            raise ValueError("Git ancestry verification failed")
        if code == 1:
            return {
                "observed_base": claim.source_head,
                "base_ancestor": False,
                "touched_paths": set(),
            }
        revs, _ = self._run(
            "rev-list", "--reverse", result_commit, "^" + claim.source_head)
        touched = set()
        for commit in [line for line in revs.splitlines() if line]:
            names, _ = self._run(
                "diff-tree", "--root", "--no-commit-id", "--name-only",
                "-r", "-m", "-z", commit)
            for path in names.split("\0"):
                if not path:
                    continue
                validate_write_path(path)
                touched.add(path)
        return {
            "observed_base": claim.source_head,
            "base_ancestor": True,
            "touched_paths": touched,
        }


class GitLaneIntegrationVerifier(GitLaneResultVerifier):
    """Read-only ancestry/readback evidence; never publication authority."""

    def __init__(self, repo, source_ref):
        super().__init__(repo)
        if (not isinstance(source_ref, str) or not source_ref.startswith("refs/heads/")
                or source_ref.endswith(("/", ".")) or ".." in source_ref or "@{" in source_ref
                or "//" in source_ref or INVALID_REF.search(source_ref)):
            raise ValueError("integration source_ref must be a canonical branch ref")
        self.source_ref = source_ref

    def publication_binding(self):
        return {
            "shared_ref": self.source_ref,
            "remote_id": None,
            "durable_attempts": False,
            "attempt_store_ref": None,
            "attempt_store_id": None,
        }

    def __call__(self, item, integrator, intent):
        validate_claim(integrator)
        if integrator.kind != LaneKind.INTEGRATOR:
            raise ValueError("integration verifier requires an integrator lane")
        if (not isinstance(item, dict) or not isinstance(intent, dict)
                or item.get("lane_id") != intent.get("lane_id")
                or item.get("result_commit") != intent.get("result_commit")):
            raise ValueError("integration result and durable intent disagree")
        result_commit = item["result_commit"]
        observed = intent.get("observed_shared_head")
        intended = intent.get("intended_integrated_head")
        operation_id = intent.get("operation_id")
        for value, label in (
            (result_commit, "integration result_commit"),
            (observed, "integration observed_shared_head"),
            (intended, "integration intended_integrated_head"),
        ):
            if not isinstance(value, str) or not SHA.fullmatch(value):
                raise ValueError(label + " invalid")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("integration operation_id invalid")
        for revision in (result_commit, observed, intended):
            self._commit_exists(revision)
        current, code = self._run("rev-parse", "--verify", self.source_ref + "^{commit}", check=False)
        if code or not SHA.fullmatch(current):
            raise ValueError("shared integration ref is unavailable")
        self._commit_exists(current)
        for ancestor in (observed, result_commit):
            _, status = self._run("merge-base", "--is-ancestor", ancestor, current, check=False)
            if status != 0:
                raise ValueError("shared HEAD does not prove integration ancestry")
        if current != intended:
            raise ValueError("shared HEAD does not match the intended integrated head")
        return {
            "integrated": True,
            "operation_id": operation_id,
            "result_commit": result_commit,
            "observed_shared_head": observed,
            "integrated_head": current,
            "conditional_update": False,
            "force_push": False,
            "publication_attempt_id": None,
            "publication_attempt_state": "readback_only",
            "publication_remote_id": None,
            "publication_shared_ref": self.source_ref,
            "publication_attempt_store_ref": None,
            "evidence_ref": "git-readback:" + self.source_ref + "@" + current,
        }


class _PublicationRejected(Exception):
    pass


class _PublicationUnknown(Exception):
    pass


ATTEMPT_SCHEMA = "project-lane-publication-attempts/v1"
ATTEMPT_STATUSES = {"prepared", "submitted", "unknown", "confirmed", "rejected", "aborted"}


def _now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GitLaneIntegrationPublisher(GitLaneResultVerifier):
    """Conditional publication with a durable, remote-bound one-shot attempt journal."""

    def __init__(self, repo, remote, source_ref, remote_id, *, attempt_store=None, clock=None):
        super().__init__(repo)
        if not isinstance(remote, str) or not remote.strip() or remote.startswith("-"):
            raise ValueError("integration remote must be a configured remote name")
        if (not isinstance(source_ref, str) or not source_ref.startswith("refs/heads/")
                or source_ref.endswith(("/", ".")) or ".." in source_ref or "@{" in source_ref
                or "//" in source_ref or INVALID_REF.search(source_ref)):
            raise ValueError("integration source_ref must be a canonical branch ref")
        if not isinstance(remote_id, str) or not DIGEST.fullmatch(remote_id):
            raise ValueError("integration remote_id must be sha256")
        self.remote = remote
        self.source_ref = source_ref
        self.remote_id = remote_id
        self.attempt_store = attempt_store
        self.clock = clock or _now_utc
        if remote_identity(self.repo, self.remote) != self.remote_id:
            raise ValueError("integration remote identity drift")
        if self.attempt_store is not None:
            if not isinstance(self.attempt_store, GitDocumentStore):
                raise ValueError("publication attempt evidence requires the durable Git document store")
            if self.attempt_store.store_id != self.remote_id:
                raise ValueError("publication attempt store remote identity mismatch")
            if (not isinstance(self.attempt_store.ref, str)
                    or not self.attempt_store.ref.startswith("refs/heads/cdc/")
                    or branch_key(self.attempt_store.ref) == branch_key(self.source_ref)):
                raise ValueError("publication attempt store must use an isolated coordination ref")

    def publication_binding(self):
        return {
            "shared_ref": self.source_ref,
            "remote_id": self.remote_id,
            "durable_attempts": self.attempt_store is not None,
            "attempt_store_ref": None if self.attempt_store is None else self.attempt_store.ref,
            "attempt_store_id": None if self.attempt_store is None else self.attempt_store.store_id,
        }

    def publication_attempt(self, operation_id):
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("publication operation_id invalid")
        if self.attempt_store is None:
            return None
        _, state = self._read_attempt_state()
        attempt = state["attempts"].get(operation_id)
        return None if attempt is None else copy.deepcopy(attempt)

    def _remote_head(self):
        if remote_identity(self.repo, self.remote) != self.remote_id:
            raise ValueError("integration remote identity drift")
        config, alias = isolated_remote_args(self.repo, self.remote, self.remote_id)
        output, _ = self._run(*config, "ls-remote", "--refs", alias, self.source_ref)
        rows = [line for line in output.splitlines() if line.strip()]
        if len(rows) != 1:
            raise ValueError("shared integration remote ref must resolve exactly once")
        parts = rows[0].split("\t")
        if len(parts) != 2 or parts[1] != self.source_ref or not SHA.fullmatch(parts[0]):
            raise ValueError("shared integration remote ref response invalid")
        return parts[0]

    def _initial_attempt_state(self):
        if self.attempt_store is None:
            raise ValueError("conditional publication requires durable attempt state")
        return {
            "schema": ATTEMPT_SCHEMA,
            "remote_id": self.remote_id,
            "shared_ref": self.source_ref,
            "attempt_store_ref": self.attempt_store.ref,
            "attempts": {},
        }

    @staticmethod
    def _timestamp(value):
        return isinstance(value, str) and value.endswith("Z") and "T" in value

    def _read_attempt_state(self):
        if self.attempt_store is None:
            raise ValueError("conditional publication requires durable attempt state")
        revision, state = self.attempt_store.read()
        if state is None:
            return revision, self._initial_attempt_state()
        initial = self._initial_attempt_state()
        if (not isinstance(state, dict) or set(state) != set(initial)
                or state["schema"] != ATTEMPT_SCHEMA
                or state["remote_id"] != self.remote_id
                or state["shared_ref"] != self.source_ref
                or state["attempt_store_ref"] != self.attempt_store.ref
                or not isinstance(state["attempts"], dict)):
            raise ValueError("publication attempt journal identity mismatch")
        expected = {
            "attempt_id", "operation_id", "lane_id", "result_commit",
            "observed_shared_head", "intended_integrated_head",
            "remote_id", "shared_ref", "status",
            "prepared_at_utc", "submitted_at_utc", "resolved_at_utc",
        }
        for operation_id, attempt in state["attempts"].items():
            if (not isinstance(attempt, dict) or set(attempt) != expected
                    or attempt["operation_id"] != operation_id
                    or not isinstance(attempt["attempt_id"], str) or not attempt["attempt_id"]
                    or not isinstance(attempt["lane_id"], str) or not attempt["lane_id"]
                    or not SHA.fullmatch(attempt["result_commit"])
                    or not SHA.fullmatch(attempt["observed_shared_head"])
                    or not SHA.fullmatch(attempt["intended_integrated_head"])
                    or attempt["remote_id"] != self.remote_id
                    or attempt["shared_ref"] != self.source_ref
                    or attempt["status"] not in ATTEMPT_STATUSES
                    or not self._timestamp(attempt["prepared_at_utc"])
                    or (attempt["submitted_at_utc"] is not None
                        and not self._timestamp(attempt["submitted_at_utc"]))
                    or (attempt["resolved_at_utc"] is not None
                        and not self._timestamp(attempt["resolved_at_utc"]))):
                raise ValueError("publication attempt journal entry invalid")
            if attempt["status"] == "prepared" and attempt["submitted_at_utc"] is not None:
                raise ValueError("prepared publication attempt cannot claim submission")
            if attempt["status"] in {"submitted", "unknown", "confirmed", "rejected"} and attempt["submitted_at_utc"] is None:
                raise ValueError("publication attempt submission timestamp missing")
            if attempt["status"] in {"confirmed", "rejected", "aborted"}:
                if attempt["resolved_at_utc"] is None:
                    raise ValueError("resolved publication attempt timestamp missing")
            elif attempt["resolved_at_utc"] is not None:
                raise ValueError("unresolved publication attempt has resolved timestamp")
        return revision, state

    def _assert_attempt_matches(self, attempt, item, intent):
        if (attempt["operation_id"] != intent["operation_id"]
                or attempt["lane_id"] != item["lane_id"]
                or attempt["result_commit"] != item["result_commit"]
                or attempt["observed_shared_head"] != intent["observed_shared_head"]
                or attempt["intended_integrated_head"] != intent["intended_integrated_head"]
                or attempt["remote_id"] != self.remote_id
                or attempt["shared_ref"] != self.source_ref):
            raise ValueError("durable publication attempt does not match integration intent")
        return attempt

    def _get_attempt(self, item, intent):
        if self.attempt_store is None:
            return None
        _, state = self._read_attempt_state()
        attempt = state["attempts"].get(intent["operation_id"])
        if attempt is None:
            return None
        return copy.deepcopy(self._assert_attempt_matches(attempt, item, intent))

    def _prepare_attempt(self, item, intent):
        if self.attempt_store is None:
            raise ValueError("conditional publication requires durable attempt state")
        attempt_id = "publication-attempt-" + secrets.token_hex(24)
        prepared_at = self.clock()
        for _ in range(6):
            revision, state = self._read_attempt_state()
            existing = state["attempts"].get(intent["operation_id"])
            if existing is not None:
                return copy.deepcopy(self._assert_attempt_matches(existing, item, intent))
            attempt = {
                "attempt_id": attempt_id,
                "operation_id": intent["operation_id"],
                "lane_id": item["lane_id"],
                "result_commit": item["result_commit"],
                "observed_shared_head": intent["observed_shared_head"],
                "intended_integrated_head": intent["intended_integrated_head"],
                "remote_id": self.remote_id,
                "shared_ref": self.source_ref,
                "status": "prepared",
                "prepared_at_utc": prepared_at,
                "submitted_at_utc": None,
                "resolved_at_utc": None,
            }
            changed = copy.deepcopy(state)
            changed["attempts"][intent["operation_id"]] = attempt
            try:
                self.attempt_store.compare_and_swap(revision, changed)
                return copy.deepcopy(attempt)
            except ValueError:
                continue
        raise ValueError("publication attempt journal CAS contention")

    def _transition_attempt(self, item, intent, target, allowed):
        if target not in ATTEMPT_STATUSES:
            raise ValueError("publication attempt target status invalid")
        for _ in range(6):
            revision, state = self._read_attempt_state()
            attempt = state["attempts"].get(intent["operation_id"])
            if attempt is None:
                raise ValueError("durable publication attempt missing")
            self._assert_attempt_matches(attempt, item, intent)
            if attempt["status"] == target:
                return copy.deepcopy(attempt)
            if attempt["status"] not in allowed:
                raise ValueError("publication attempt state does not allow transition")
            changed = copy.deepcopy(state)
            current = changed["attempts"][intent["operation_id"]]
            current["status"] = target
            if target == "submitted" and current["submitted_at_utc"] is None:
                current["submitted_at_utc"] = self.clock()
            if target in {"confirmed", "rejected", "aborted"}:
                current["resolved_at_utc"] = self.clock()
            try:
                self.attempt_store.compare_and_swap(revision, changed)
                return copy.deepcopy(current)
            except ValueError:
                continue
        raise ValueError("publication attempt journal CAS contention")

    def _porcelain_proves_explicit_rejection(self, output):
        if not isinstance(output, str):
            return False
        target_suffix = ":" + self.source_ref
        for line in output.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            flag, refspec, summary = parts
            if flag != "!" or not refspec.endswith(target_suffix):
                continue
            status = summary.strip().casefold()
            return (
                status.startswith("[rejected]")
                or status.startswith("[remote rejected]")
            )
        return False

    def _push_cas(self, observed, intended):
        config, alias = isolated_remote_args(self.repo, self.remote, self.remote_id)
        env = git_object_environment(GIT_TERMINAL_PROMPT="0")
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *config, "-c", "push.followTags=false",
                 "push", "--porcelain",
                 "--force-with-lease=" + self.source_ref + ":" + observed,
                 alias, intended + ":" + self.source_ref],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            raise _PublicationUnknown("conditional publication outcome unknown") from None
        if result.returncode:
            if self._porcelain_proves_explicit_rejection(result.stdout):
                raise _PublicationRejected("conditional publication was explicitly rejected")
            raise _PublicationUnknown("conditional publication outcome unknown")
        return True

    def _evidence(self, item, intent, *, attempt=None, conditional):
        state = "absent" if attempt is None else attempt["status"]
        return {
            "integrated": True,
            "operation_id": intent["operation_id"],
            "result_commit": item["result_commit"],
            "observed_shared_head": intent["observed_shared_head"],
            "integrated_head": intent["intended_integrated_head"],
            "conditional_update": bool(conditional),
            "force_push": False,
            "publication_attempt_id": None if attempt is None else attempt["attempt_id"],
            "publication_attempt_state": state,
            "publication_remote_id": self.remote_id,
            "publication_shared_ref": self.source_ref,
            "publication_attempt_store_ref": None if self.attempt_store is None else self.attempt_store.ref,
            "evidence_ref": (
                ("git-cas:" if conditional else "git-readback:")
                + self.source_ref + "@" + intent["intended_integrated_head"]
            ),
        }

    def __call__(self, item, integrator, intent):
        validate_claim(integrator)
        if integrator.kind != LaneKind.INTEGRATOR:
            raise ValueError("integration publisher requires an integrator lane")
        if (not isinstance(item, dict) or not isinstance(intent, dict)
                or item.get("lane_id") != intent.get("lane_id")
                or item.get("result_commit") != intent.get("result_commit")):
            raise ValueError("integration result and durable intent disagree")
        result_commit = item["result_commit"]
        observed = intent.get("observed_shared_head")
        intended = intent.get("intended_integrated_head")
        operation_id = intent.get("operation_id")
        for value, label in (
            (result_commit, "integration result_commit"),
            (observed, "integration observed_shared_head"),
            (intended, "integration intended_integrated_head"),
        ):
            if not isinstance(value, str) or not SHA.fullmatch(value):
                raise ValueError(label + " invalid")
            self._commit_exists(value)
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("integration operation_id invalid")
        for ancestor in (observed, result_commit):
            _, status = self._run("merge-base", "--is-ancestor", ancestor, intended, check=False)
            if status != 0:
                raise ValueError("intended integration is not a fast-forward containing required ancestry")

        current = self._remote_head()
        if current == intended:
            attempt = self._get_attempt(item, intent)
            if attempt is None:
                return self._evidence(item, intent, attempt=None, conditional=False)
            if attempt["status"] in {"unknown", "confirmed"}:
                if attempt["status"] == "unknown":
                    attempt = self._transition_attempt(
                        item, intent, "confirmed", {"unknown"})
                return self._evidence(item, intent, attempt=attempt, conditional=True)
            # A durable submitted marker is written before transport invocation,
            # so a crash may leave submitted even though _push_cas() never ran.
            # Matching bytes therefore cannot upgrade prepared/submitted to proof
            # of this intent's expected-head CAS. Rejected/aborted are likewise
            # explicitly non-authoritative. None of these states is replayed.
            return self._evidence(item, intent, attempt=attempt, conditional=False)

        if current != observed:
            raise ValueError("shared integration ref moved before conditional publication")
        if self.attempt_store is None:
            raise ValueError("conditional publication requires durable attempt state")

        attempt = self._prepare_attempt(item, intent)
        if attempt["status"] in {"submitted", "unknown"}:
            raise ValueError("publication attempt outcome is unresolved; push will not be replayed")
        if attempt["status"] in {"confirmed", "rejected", "aborted"}:
            raise ValueError("publication attempt is terminal and cannot be replayed")

        # Verify the expected remote HEAD once more while the attempt is still
        # provably unsent. Only after that read is it marked submitted.
        current = self._remote_head()
        if current != observed:
            attempt = self._transition_attempt(item, intent, "aborted", {"prepared"})
            if current == intended:
                return self._evidence(item, intent, attempt=attempt, conditional=False)
            raise ValueError("shared integration ref moved before conditional publication")

        attempt = self._transition_attempt(item, intent, "submitted", {"prepared"})
        try:
            self._push_cas(observed, intended)
        except _PublicationRejected:
            self._transition_attempt(item, intent, "rejected", {"submitted"})
            raise ValueError("conditional integration publication was explicitly rejected") from None
        except _PublicationUnknown:
            self._transition_attempt(item, intent, "unknown", {"submitted"})
            raise ValueError("conditional integration publication outcome is unknown") from None

        try:
            current = self._remote_head()
        except ValueError:
            self._transition_attempt(item, intent, "unknown", {"submitted"})
            raise
        if current != intended:
            self._transition_attempt(item, intent, "unknown", {"submitted"})
            raise ValueError("conditional integration publication did not become authoritative")
        attempt = self._transition_attempt(item, intent, "confirmed", {"submitted"})
        return self._evidence(item, intent, attempt=attempt, conditional=True)
