#!/usr/bin/env python3
"""Dedicated one-document Git CAS ref, isolated from all product branches."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import json
import hashlib
import os
import re
import secrets
import select
import subprocess
import time

# Optional pinned local decoder; the original canonical encoder stays authoritative.
try:
    from _cdc_vendor.orjson import loads as _json_loads
except ImportError:
    _json_loads = json.loads

from git_remote_identity import isolated_remote_args, remote_identity, repository_root
from parallel_task_planner import portable_path_key

STATE_FILE = "document.json"
REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_BYTES = 4 * 1024 * 1024
# Optional physical task objects retain the original per-object bound. Logical
# decoding is separately bounded; it never relaxes legacy canonical().
MAX_LOGICAL_BYTES = 128 * 1024 * 1024
MAX_TASK_SHARDS = 16384
TASK_STORAGE_SCHEMA = "git-document-task-shards/v1"
TASK_DIRECTORY = "tasks"


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


_BATCH_TIMEOUT = 20


class _ObjectPipe:
    """One local cat-file pipe; bounded framing and deadline, no authority."""

    def __init__(self, repo, option):
        self.buffer = bytearray()
        try:
            self.process = subprocess.Popen(
                ["git", "-C", str(repo), "cat-file", option],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=git_object_environment(GIT_TERMINAL_PROMPT="0"), bufsize=0)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Git document coordination unavailable") from None
        try:
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
        except BaseException:
            self.finish(False)
            raise

    def _ready(self, deadline, *, writing=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("historical object batch timed out")
        fd = (self.process.stdin if writing else self.process.stdout).fileno()
        ready = select.select([] if writing else [fd], [fd] if writing else [], [], remaining)
        if not ready[1 if writing else 0]:
            raise ValueError("historical object batch timed out")
        return fd

    def send(self, specifications, deadline):
        # The empty request has the fixed ' missing' reply: a frame boundary,
        # never an additional object or caller-controlled Git expression.
        request = ("\n".join(specifications) + "\n\n").encode("ascii")
        offset = 0
        while offset < len(request):
            try:
                offset += os.write(self._ready(deadline, writing=True), request[offset:])
            except (OSError, subprocess.SubprocessError):
                raise ValueError("Git document coordination unavailable") from None

    def _fill(self, deadline):
        try:
            data = os.read(self._ready(deadline), 65536)
        except OSError:
            raise ValueError("Git document coordination unavailable") from None
        if not data:
            raise ValueError("incomplete historical object batch")
        self.buffer.extend(data)

    def line(self, deadline):
        while True:
            end = self.buffer.find(b"\n")
            if end >= 0:
                if end > 256:
                    raise ValueError("invalid historical object header")
                result = bytes(self.buffer[:end + 1]); del self.buffer[:end + 1]
                return result
            if len(self.buffer) > 256:
                raise ValueError("invalid historical object header")
            self._fill(deadline)

    def take(self, size, deadline):
        while len(self.buffer) < size:
            self._fill(deadline)
        result = bytes(self.buffer[:size]); del self.buffer[:size]
        return result

    def boundary(self, deadline):
        if self.line(deadline) != b" missing\n" or self.buffer:
            raise ValueError("unexpected historical object batch data")

    def finish(self, check):
        try:
            if check:
                self.process.stdin.close()
                deadline = time.monotonic() + _BATCH_TIMEOUT
                if self.buffer or os.read(self._ready(deadline), 1):
                    raise ValueError("unexpected historical object batch data")
                remaining = max(0.001, deadline - time.monotonic())
                if self.process.wait(timeout=remaining):
                    raise ValueError("Git document coordination command failed")
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Git document coordination unavailable") from None
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=1)
            self.process.stdin.close(); self.process.stdout.close()


class _ObjectBatchSession:
    """Ephemeral POSIX transport for one generator; no cross-call state."""

    def __init__(self, repo):
        self.repo = repo; self.pipes = []; self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.close(kind is None)

    def close(self, check):
        self.closed = True
        error = None
        for pipe in self.pipes:
            try:
                pipe.finish(check)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                if error is None: error = exc
        self.pipes = []
        if error is not None:
            raise ValueError("Git historical object session did not close cleanly") from error

    def read(self, specifications, object_type, max_bytes):
        if (self.closed or not 1 <= len(specifications) <= 16
                or object_type not in {"tree", "blob"}
                or max_bytes != (128 if object_type == "tree" else MAX_BYTES)
                or any(type(spec) is not str or re.fullmatch(
                    r"(?:[0-9a-f]{40}|[0-9a-f]{64})(?:\^\{tree\})?", spec) is None
                       for spec in specifications)):
            raise ValueError("invalid historical object batch")
        if not self.pipes:
            try:
                self.pipes.append(_ObjectPipe(self.repo, "--batch-check"))
                self.pipes.append(_ObjectPipe(self.repo, "--batch"))
            except BaseException:
                self.close(False)
                raise
        check, body = self.pipes
        deadline = time.monotonic() + _BATCH_TIMEOUT
        check.send(specifications, deadline)
        headers = [check.line(deadline) for _ in specifications]
        check.boundary(deadline)
        checked = []
        for header in headers:
            parts = header.split()
            if (len(parts) != 3 or not REVISION.fullmatch(parts[0].decode("ascii"))
                    or parts[1] != object_type.encode("ascii") or not parts[2].isdigit()
                    or int(parts[2]) > max_bytes):
                raise ValueError("invalid historical object type or size")
            checked.append((header, int(parts[2])))
        deadline = time.monotonic() + _BATCH_TIMEOUT
        body.send(specifications, deadline)
        values = []
        for header, size in checked:
            if body.line(deadline) != header:
                raise ValueError("historical object batch changed")
            values.append(body.take(size, deadline))
            if body.take(1, deadline) != b"\n":
                raise ValueError("incomplete historical object body")
        body.boundary(deadline)
        return values


class GitDocumentStore:
    """Non-force remote CAS; every proposal has an unpredictable commit nonce.

    The default ref contains only document.json. Explicit task_shards opt-in
    also permits one immutable task-object tree for original control documents.
    Every other root entry is rejected before any proposal can be published.
    """

    def __init__(self, repo, remote, coordination_ref, coordination_store_id, *, protected_refs=(), task_shards=False):
        if type(task_shards) is not bool:
            raise ValueError("task shard opt-in must be boolean")
        self.task_shards = task_shards
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

    def canonical(self, document):
        """Bounded logical comparison, never a capability or alternate store."""
        if not self.task_shards:
            return canonical(document)
        if (not isinstance(document, dict) or document.get("schema") != "cdc-vps-control/v1"
                or type(document.get("tasks")) is not dict
                or len(document["tasks"]) > MAX_TASK_SHARDS
                or any(type(key) is not str for key in document["tasks"])):
            raise ValueError("bounded original control task document required")
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False) + "\n"
        if len(payload.encode("utf-8")) > MAX_LOGICAL_BYTES:
            raise ValueError("logical task document exceeds decoding bound")
        return payload

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
        names = self._git("ls-tree", "--name-only", revision).splitlines()
        if names != [STATE_FILE] and not (self.task_shards and names == [STATE_FILE, TASK_DIRECTORY]):
            raise ValueError("dedicated coordination tree must contain only document.json")
        document = self._read_document_object(revision)
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
        return self._read_document_object(revision)

    def _read_document_object(self, revision):
        """Decode a genuine immutable object from an already authenticated snapshot."""
        document, = self._read_document_objects([revision])
        return document

    def _batch_objects(self, specifications, object_type, max_bytes, *, max_total_bytes=None):
        """Read a small immutable batch, checking sizes before materializing bodies.

        Specifications are constructed here from full object IDs, never caller
        expressions. Both subprocesses disable replacement refs and grafts.
        """
        request = ("\n".join(specifications) + "\n").encode("ascii")
        env = git_object_environment(GIT_TERMINAL_PROMPT="0")

        def run(option):
            try:
                result = subprocess.run(
                    ["git", "-C", str(self.repo), "cat-file", option], input=request,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=20)
            except (OSError, subprocess.SubprocessError):
                raise ValueError("Git document coordination unavailable") from None
            if result.returncode:
                raise ValueError("Git document coordination command failed")
            return result.stdout

        headers = run("--batch-check").splitlines()
        if len(headers) != len(specifications):
            raise ValueError("incomplete historical object batch")
        checked = []
        for header in headers:
            parts = header.split()
            if (len(parts) != 3 or not REVISION.fullmatch(parts[0].decode("ascii"))
                    or parts[1] != object_type.encode("ascii") or not parts[2].isdigit()
                    or int(parts[2]) > max_bytes):
                raise ValueError("invalid historical object type or size")
            checked.append((header, int(parts[2])))
        if max_total_bytes is not None and sum(size for _, size in checked) > max_total_bytes:
            raise ValueError("aggregate task objects exceed logical decoding bound")
        raw = run("--batch")
        offset = 0
        values = []
        for header, size in checked:
            prefix = header + b"\n"
            if raw[offset:offset + len(prefix)] != prefix:
                raise ValueError("historical object batch changed")
            offset += len(prefix)
            value = raw[offset:offset + size]
            offset += size
            if len(value) != size or raw[offset:offset + 1] != b"\n":
                raise ValueError("incomplete historical object body")
            offset += 1
            values.append(value)
        if offset != len(raw):
            raise ValueError("unexpected historical object batch data")
        return values

    def _read_document_objects(self, revisions):
        """Decode every authenticated revision, with bounded batched Git I/O.

        This is transport only: callers still authenticate the complete native
        graph, endpoint and fresh head. No process/persistent authority is added.
        At most 16 trees or 16 bounded document blobs are materialized at once.
        """
        from itertools import islice
        from contextlib import nullcontext
        revisions = iter(revisions)
        session = _ObjectBatchSession(self.repo) if os.name == "posix" else None
        with session if session is not None else nullcontext():
            batch = session.read if session is not None else self._batch_objects
            while True:
                chunk = list(islice(revisions, 16))
                if not chunk:
                    return
                if any(not isinstance(revision, str) or not REVISION.fullmatch(revision)
                       for revision in chunk):
                    raise ValueError("invalid historical document revision")
                trees = batch([revision + "^{tree}" for revision in chunk], "tree", 128)
                blobs = []
                task_trees = []
                for revision, tree in zip(chunk, trees):
                    # Authenticate the exact legacy root or the exact opted-in
                    # two-entry root before reading any document or task JSON.
                    header, separator, oid = tree.partition(b"\0")
                    width = len(revision) // 2
                    if (separator and re.fullmatch(rb"[0-7]+ document\.json", header)
                            and len(oid) == width):
                        blobs.append(oid.hex()); task_trees.append(None)
                    elif (self.task_shards and header == b"100644 document.json"
                            and len(oid) == width * 2 + len(b"40000 tasks\0")
                            and oid[width:width + len(b"40000 tasks\0")] == b"40000 tasks\0"):
                        blobs.append(oid[:width].hex()); task_trees.append(oid[-width:].hex())
                    else:
                        raise ValueError("historical coordination tree must contain only document.json or opted-in task shards")
                for payload, task_tree in zip(batch(blobs, "blob", MAX_BYTES), task_trees):
                    if task_tree is not None:
                        yield self._read_task_document(payload, task_tree, len(task_tree) // 2)
                        continue
                    # Match _git's text/universal-newline and trailing-LF handling.
                    payload = payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
                    # Exact canonical equality already excludes duplicate keys.
                    # Decode valid history in C; preserve the original strict
                    # decoder and its error ordering for every rejected payload.
                    try:
                        document = _json_loads(payload)
                        exact = canonical(document) == payload
                    except (ValueError, TypeError, RecursionError):
                        exact = False
                    if not exact:
                        document = None
                        document = json.loads(payload, object_pairs_hook=unique_object)
                        if canonical(document) != payload:
                            raise ValueError("historical coordination document must have canonical JSON encoding")
                    yield document

    @staticmethod
    def _decode_task_object(payload):
        # Shard objects have exact canonical bytes, without text normalization.
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
        if canonical(value).encode("utf-8") != payload:
            raise ValueError("task storage requires exact canonical JSON objects")
        return value

    def _read_task_document(self, payload, task_tree, width):
        manifest = self._decode_task_object(payload)
        if (set(manifest) != {"schema", "document", "task_count", "logical_sha256"}
                or manifest["schema"] != TASK_STORAGE_SCHEMA
                or type(manifest["task_count"]) is not int
                or not 0 <= manifest["task_count"] <= MAX_TASK_SHARDS
                or type(manifest["logical_sha256"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", manifest["logical_sha256"])
                or type(manifest["document"]) is not dict
                or manifest["document"].get("schema") != "cdc-vps-control/v1"
                or "tasks" in manifest["document"]):
            raise ValueError("invalid task storage manifest")
        tree, = self._batch_objects([task_tree], "tree", MAX_BYTES)
        entries = []; offset = 0
        while offset < len(tree):
            end = tree.find(b"\0", offset)
            if end < 0 or not re.fullmatch(rb"100644 [0-9a-f]{64}\.json", tree[offset:end]):
                raise ValueError("invalid task storage index path or mode")
            name = tree[offset + len(b"100644 "):end].decode("ascii")
            oid = tree[end + 1:end + 1 + width]
            if (len(oid) != width or (entries and name <= entries[-1][0])
                    or len(entries) >= MAX_TASK_SHARDS):
                raise ValueError("duplicate or unbounded task storage index")
            entries.append((name, oid.hex())); offset = end + 1 + width
        if len(entries) != manifest["task_count"]:
            raise ValueError("task storage index count mismatch")
        document = manifest["document"]; document["tasks"] = {}
        total = len(payload)
        for start in range(0, len(entries), 16):
            chunk = entries[start:start + 16]
            objects = self._batch_objects([oid for _, oid in chunk], "blob", MAX_BYTES,
                                         max_total_bytes=MAX_LOGICAL_BYTES - total)
            total += sum(len(raw) for raw in objects)
            for (name, _), raw in zip(chunk, objects):
                entry = self._decode_task_object(raw)
                if (set(entry) != {"task_id", "row"} or type(entry["task_id"]) is not str
                        or type(entry["row"]) is not dict
                        or type(entry["row"].get("task")) is not dict
                        or entry["row"]["task"].get("id") != entry["task_id"]
                        or hashlib.sha256(entry["task_id"].encode("utf-8")).hexdigest() + ".json" != name
                        or entry["task_id"] in document["tasks"]):
                    raise ValueError("task storage original ID/index binding mismatch")
                document["tasks"][entry["task_id"]] = entry["row"]
        logical = self.canonical(document)
        if hashlib.sha256(logical.encode("utf-8")).hexdigest() != manifest["logical_sha256"]:
            raise ValueError("task storage logical document digest mismatch")
        return document

    def _write_task_tree(self, document, logical):
        metadata = {key: value for key, value in document.items() if key != "tasks"}
        manifest = {"schema": TASK_STORAGE_SCHEMA, "document": metadata,
                    "task_count": len(document["tasks"]),
                    "logical_sha256": hashlib.sha256(logical.encode("utf-8")).hexdigest()}
        payload = canonical(manifest); total = len(payload.encode("utf-8")); entries = []
        for task_id, row in document["tasks"].items():
            if (type(row) is not dict or type(row.get("task")) is not dict
                    or row["task"].get("id") != task_id):
                raise ValueError("original task row ID binding required")
            raw = canonical({"task_id": task_id, "row": row})
            total += len(raw.encode("utf-8"))
            if total > MAX_LOGICAL_BYTES:
                raise ValueError("aggregate task objects exceed logical decoding bound")
            blob = self._git("hash-object", "-w", "--stdin", input_text=raw)
            name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".json"
            entries.append((name, blob))
        if len({name for name, _ in entries}) != len(entries):
            raise ValueError("task storage index collision")
        tasks = self._git("mktree", input_text="".join(
            f"100644 blob {blob}\t{name}\n" for name, blob in sorted(entries)))
        blob = self._git("hash-object", "-w", "--stdin", input_text=payload)
        return self._git("mktree", input_text=f"100644 blob {blob}\t{STATE_FILE}\n040000 tree {tasks}\t{TASK_DIRECTORY}\n")

    def compare_and_swap(self, expected_revision, document, *, recovery_capability=None):
        payload = self.canonical(document)
        current, previous = self.read()
        if expected_revision != current:
            raise ValueError("stale expected document revision")
        from unknown_recovery import validate_intake_transition
        validate_intake_transition(previous, document, store=self, expected_revision=expected_revision, recovery_capability=recovery_capability)
        if self.task_shards:
            tree = self._write_task_tree(document, payload)
        else:
            blob = self._git("hash-object", "-w", "--stdin", input_text=payload)
            tree = self._git("mktree", input_text=f"100644 blob {blob}\t{STATE_FILE}\n")
        parent = ["-p", expected_revision] if expected_revision else []
        commit = self._git("commit-tree", tree, *parent,
                           input_text="Update CDC coordination\n\nCAS proposal: " + secrets.token_hex(32) + "\n")
        # Only the SDK-issued one-use consumption can retain its own proposal.
        # This non-secret local commit identity is not a launch permission.
        from unknown_recovery import _StartConsumption
        if type(recovery_capability) is _StartConsumption:
            recovery_capability._bind_proposal(self, expected_revision, commit)
        # Revalidate immediately before the side effect; never force-update the ref.
        self._assert_remote_identity()
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "-c", "push.followTags=false", "push", "--porcelain", remote, f"{commit}:{self.ref}")
        if self._remote_revision() != commit:
            raise ValueError("document CAS did not become authoritative")
        return commit
