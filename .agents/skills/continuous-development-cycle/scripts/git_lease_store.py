#!/usr/bin/env python3
"""Small Git conditional store. Only normal fast-forward pushes to a separate ref."""
from __future__ import annotations

from git_object_integrity import git_object_environment

import json
import os
from pathlib import Path
import re
import secrets
import subprocess

import execution_lease
import execution_lease_v2
import operation_intent as op
from git_remote_identity import isolated_remote_args, remote_identity


def validate_coordination_record(record):
    if not isinstance(record, dict):
        raise ValueError('lease must be an object')
    schema = record.get('schema')
    if schema == 'execution-lease/v2':
        return execution_lease_v2.validate(record)
    if schema == 'execution-lease/v1':
        return execution_lease.validate(record)
    raise ValueError('unsupported lease schema')


def _validate_submission_resolution_transition(previous, record, *, expected_revision=None):
    prev_res=previous.get("submission_resolutions",[])
    curr_res=record.get("submission_resolutions",[])
    appended=curr_res[len(prev_res):]
    prev_guard=previous.get("external_guard")
    prev_claim=prev_guard.get("submission_claim") if isinstance(prev_guard,dict) else None
    guard_cleared=prev_guard is not None and record.get("external_guard") is None

    if appended:
        if previous.get("schema")!="execution-lease/v2" or record.get("schema")!="execution-lease/v2":
            raise ValueError("submission resolution append requires v2-to-v2 terminal reconciliation")
        if len(appended)!=1 or prev_claim is None or not guard_cleared:
            raise ValueError("submission resolution append requires exact prior guarded submission")
        terminal=record.get("last_terminal")
        if not isinstance(terminal,dict):
            raise ValueError("submission resolution append requires persisted terminal observation")
        resolution=appended[0]
        if (resolution["grant_id"]!=prev_claim["grant_id"]
                or resolution["evidence_reference"]!=terminal.get("evidence_reference")
                or resolution["observation_digest"]!=op._hash(terminal.get("observation"))
                or resolution["operation_key"]!=terminal.get("operation_key")
                or resolution["intent_digest"]!=terminal.get("intent_digest")
                or resolution["resolved_at_utc"]!=terminal.get("at_utc")):
            raise ValueError("submission resolution is not bound to exact persisted terminal evidence")
        # A resolution is an atomic guard->terminal transition. No unrelated state
        # may be smuggled through the same raw CAS.
        allowed={"external_guard","last_terminal","submission_resolutions"}
        all_fields=set(previous)|set(record)
        for name in all_fields-allowed:
            if previous.get(name)!=record.get(name):
                raise ValueError("terminal submission resolution CAS contains unrelated mutation")
        if previous["owner_id"] is None:
            from submission_recovery import resolve_released_guard
            if expected_revision is not None and terminal["observation"].get("lease_revision") != expected_revision:
                raise ValueError("taskless proof does not bind exact CAS lease revision")
            expected=resolve_released_guard(previous,terminal["observation"],
                                            terminal["evidence_reference"],terminal["at_utc"])
        else:
            expected=execution_lease_v2.clear_guard(
                previous,
                previous["owner_id"],previous["generation"],previous["invocation"]["invocation_id"],
                terminal["at_utc"],terminal["observation"],terminal["evidence_reference"])
        if expected!=record:
            raise ValueError("submission resolution must equal the canonical terminal guard reconciliation")
    elif prev_claim is not None and guard_cleared:
        raise ValueError("guarded submission cannot clear without append-only terminal resolution")
    return record


def validate_coordination_transition(previous, record, *, ownership_capability=None, expected_revision=None):
    validate_coordination_record(record)
    if previous is None:
        return record
    validate_coordination_record(previous)
    if any(previous[key] != record[key] for key in ('repository', 'source_ref')):
        raise ValueError('coordination binding is immutable')
    prev_schema=previous.get('schema');new_schema=record.get('schema')
    if prev_schema=='execution-lease/v1' and new_schema=='execution-lease/v1':
        if record['owner_id'] is not None and (record['generation']>previous['generation']
                or record['owner_id']!=previous['owner_id']):
            raise ValueError('new execution-lease/v1 ownership is disabled; migrate to managed v2')
    if prev_schema=='execution-lease/v2' and new_schema=='execution-lease/v2':
        if previous['owner_id'] is None and record['owner_id'] is None and record != previous:
            if not (previous['external_guard'] is not None
                    and previous['external_guard']['submission_claim'] is not None
                    and record['external_guard'] is None
                    and len(record.get('submission_resolutions', [])) == len(previous.get('submission_resolutions', [])) + 1):
                raise ValueError('released v2 state is sealed except for canonical guarded resolution')
        if (record.get('last_release') != previous.get('last_release')
                and not (previous['owner_id'] is not None and record['owner_id'] is None)):
            raise ValueError('release history can change only through canonical owner release')
        ownership_changed=(record['owner_id']!=previous['owner_id']
                           or record['generation']!=previous['generation'])
        if record['owner_id'] is not None and ownership_changed:
            if ownership_capability is None:
                raise ValueError('v2 ownership transition requires verified managed terminal capability')
            ttl=int((op._timestamp(record['expires_at_utc'],'expiry')
                     -op._timestamp(record['acquired_at_utc'],'acquired')).total_seconds())
            expected=execution_lease_v2.acquire(
                previous,record['owner_id'],record['acquired_at_utc'],
                invocation=record['invocation'],terminal_capability=ownership_capability,
                ttl=ttl,quiescence=record.get('takeover_evidence'))
            if expected!=record:
                raise ValueError('v2 ownership transition must equal canonical managed acquire')
        if previous['owner_id'] is not None and record['owner_id'] is None:
            release=record.get('last_release')
            if not isinstance(release,dict):
                raise ValueError('v2 release transition requires last_release')
            expected=execution_lease_v2.release(
                previous,previous['owner_id'],previous['generation'],
                previous['invocation']['invocation_id'],release['at_utc'])
            if expected!=record:
                raise ValueError('v2 owner release transition must equal canonical transactional release')
    if previous.get('schema') == 'execution-lease/v2' and record.get('schema') != 'execution-lease/v2':
        raise ValueError('execution-lease/v2 cannot downgrade to v1')
    if record['submission_claims'][:len(previous['submission_claims'])] != previous['submission_claims']:
        raise ValueError('consumed submission history cannot be removed or rewritten')
    _validate_submission_resolution_transition(previous, record, expected_revision=expected_revision)
    previous_resolutions=previous.get('submission_resolutions', [])
    current_resolutions=record.get('submission_resolutions', [])
    if current_resolutions[:len(previous_resolutions)] != previous_resolutions:
        raise ValueError('submission resolution history cannot be removed or rewritten')
    if record['generation'] < previous['generation']:
        raise ValueError('lease generation cannot decrease')
    return record


class GitLeaseStore:
    def __init__(self, repo, remote, coordination_ref):
        self.repo = Path(repo)
        self.remote = remote
        self.ref = coordination_ref
        op._text(remote, 'configured remote name')
        if remote.startswith('-') or remote not in self._git('remote').splitlines():
            raise ValueError('remote must be an existing configured Git remote name')
        if not isinstance(coordination_ref, str) or not coordination_ref.startswith('refs/heads/'):
            raise ValueError('coordination ref must be an exact refs/heads/ ref')
        self._git('check-ref-format', coordination_ref)
        fetch = self._git('remote', 'get-url', '--all', remote).splitlines()
        push = self._git('remote', 'get-url', '--push', '--all', remote).splitlines()
        if len(fetch) != 1 or push != fetch:
            raise ValueError('coordination remote needs one identical fetch and push URL')
        self.store_id = remote_identity(self.repo, self.remote)

    def _assert_remote_identity(self):
        if remote_identity(self.repo, self.remote) != self.store_id:
            raise ValueError('lease coordination remote identity drift')

    def _git(self, *args, input=None, raw=False):
        environment = git_object_environment(GIT_TERMINAL_PROMPT='0',
                           GIT_AUTHOR_NAME='CDC coordination', GIT_AUTHOR_EMAIL='cdc@example.invalid',
                           GIT_COMMITTER_NAME='CDC coordination', GIT_COMMITTER_EMAIL='cdc@example.invalid')
        try:
            result = subprocess.run(['git', '-C', str(self.repo), *args], input=input,
                                    text=not raw, capture_output=True, env=environment, check=False)
        except OSError as exc:
            raise ValueError('Git coordination unavailable') from exc
        if result.returncode:
            # Do not echo transport stderr: URLs or helper diagnostics may contain credentials.
            raise ValueError(f'Git coordination {args[0]} failed (exit {result.returncode})')
        return result.stdout if raw else result.stdout.strip()

    def _lease_entry(self, revision):
        rows = self._git('ls-tree', '--full-tree', '-z', revision, '--', 'lease.json', raw=True).split(b'\0')
        rows = [row for row in rows if row]
        if len(rows) != 1:
            raise ValueError('coordination tree requires one regular lease.json')
        metadata, name = rows[0].split(b'\t', 1)
        mode, kind, blob = metadata.split(b' ')
        if name != b'lease.json' or mode not in {b'100644', b'100755'} or kind != b'blob':
            raise ValueError('coordination lease.json must be a regular file')
        return mode.decode('ascii'), blob.decode('ascii')

    def _read_record(self, revision):
        _, blob = self._lease_entry(revision)
        record = json.loads(self._git('cat-file', 'blob', blob), object_pairs_hook=op._unique_object)
        validate_coordination_record(record)
        if record['source_ref'] == self.ref:
            raise ValueError('coordination ref must differ from product source ref')
        return record

    def read(self):
        self._assert_remote_identity()
        rows = self._git('ls-remote', '--refs', self.remote, self.ref).splitlines()
        if not rows:
            return None, None
        if len(rows) != 1:
            raise ValueError('ambiguous coordination ref')
        revision, ref = rows[0].split('\t')
        if ref != self.ref or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', revision):
            raise ValueError('invalid coordination revision')
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, 'fetch', '--no-tags', '--no-write-fetch-head', '--refmap=', remote, self.ref)
        if self._git('cat-file', '-t', revision) != 'commit':
            raise ValueError('coordination ref must point to a commit')
        record = self._read_record(revision)
        self._assert_remote_identity()
        if self._git('ls-remote', '--refs', self.remote, self.ref).splitlines() != rows:
            raise ValueError('coordination ref moved during read; refetch before acting')
        return revision, record

    def read_revision(self, revision):
        """Read an immutable record from this coordination ref's authoritative history."""
        if not isinstance(revision, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', revision):
            raise ValueError('invalid historical coordination revision')
        current, _ = self.read()
        if current is None:
            raise ValueError('coordination history is absent')
        if self._git('cat-file', '-t', revision) != 'commit':
            raise ValueError('historical coordination revision must be a commit')
        try:
            base = self._git('merge-base', revision, current)
        except ValueError:
            raise ValueError('historical revision is not in authoritative coordination ancestry') from None
        if base != revision:
            raise ValueError('historical revision is not in authoritative coordination ancestry')
        return self._read_record(revision)

    def find_invocation_ownership(self, repository, source_ref, invocation_id):
        """Find exact authoritative owned generation for a managed invocation."""
        current, _ = self.read()
        if current is None:
            raise ValueError("coordination history is absent")
        revisions = self._git("rev-list", "--first-parent", current).splitlines()
        matches = []
        for revision in revisions[:10000]:
            record = self._read_record(revision)
            invocation = record.get("invocation")
            if (record.get("schema") == "execution-lease/v2" and record.get("repository") == repository
                    and record.get("source_ref") == source_ref and record.get("owner_id") is not None
                    and isinstance(invocation, dict) and invocation.get("invocation_id") == invocation_id):
                matches.append({"revision": revision, "owner_id": record["owner_id"],
                                "generation": record["generation"], "record": record})
        identities={(row["owner_id"],row["generation"]) for row in matches}
        if len(identities)>1:
            raise ValueError("managed invocation appears under multiple lease identities")
        if not matches:
            return None
        return matches[-1]

    def find_release_receipt(self, owner_id, generation, invocation_id):
        current, _ = self.read()
        if current is None:
            raise ValueError('coordination history is absent')
        revisions = self._git('rev-list', '--first-parent', current).splitlines()
        for revision in revisions[:10000]:
            record = self._read_record(revision)
            release = record.get('last_release')
            if (record.get('owner_id') is None and isinstance(release, dict)
                    and release.get('owner_id') == owner_id and release.get('generation') == generation
                    and release.get('invocation_id') == invocation_id and record.get('generation') == generation):
                return {'release_receipt': {'schema': 'execution-release-receipt/v1',
                                            'lease_revision': revision, 'release': release},
                        'release_record': record, 'current_revision': current}
        raise ValueError('exact historical lease release was not found')

    def compare_and_swap(self, expected_revision, record, *, ownership_capability=None):
        validate_coordination_record(record)
        if record['source_ref'] == self.ref:
            raise ValueError('coordination ref must differ from product source ref')
        current, previous = self.read()
        if current != expected_revision:
            raise ValueError('stale expected coordination revision')
        validate_coordination_transition(previous, record, ownership_capability=ownership_capability,
                                         expected_revision=expected_revision)
        blob = self._git('hash-object', '-w', '--stdin', input=op._canonical(record).decode() + '\n')
        mode = '100644'
        neighbors = []
        if current is not None:
            mode, _ = self._lease_entry(current)
            # Git names are bytes: text decoding also normalizes CR/LF sequences.
            neighbors = [row for row in self._git('ls-tree', '--full-tree', '-z', current, raw=True).split(b'\0')
                         if row and row.split(b'\t', 1)[1] != b'lease.json']
        entries = neighbors + [f'{mode} blob {blob}\tlease.json'.encode('ascii')]
        tree = self._git('mktree', '-z', input=b'\0'.join(entries) + b'\0', raw=True).decode('ascii').strip()
        parent = ['-p', expected_revision] if expected_revision else []
        commit = self._git('commit-tree', tree, *parent,
                           input='Update cooperative execution ownership\n\nCAS proposal: ' + secrets.token_hex(32) + '\n')
        # This commit has exactly the observed ref as its parent. Concurrent proposals
        # are siblings: normal push accepts at most one and rejects the other.
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, '-c', 'push.followTags=false', 'push', '--porcelain', remote, f'{commit}:{self.ref}')
        self._assert_remote_identity()
        if self._git('ls-remote', '--refs', self.remote, self.ref).splitlines() != [f'{commit}\t{self.ref}']:
            raise ValueError('lease CAS push did not become authoritative')
        return commit
