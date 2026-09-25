#!/usr/bin/env python3
"""Small Git conditional store. Only normal fast-forward pushes to a separate ref."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import execution_lease
import execution_lease_v2
import operation_intent as op


def validate_coordination_record(record):
    if not isinstance(record, dict):
        raise ValueError('lease must be an object')
    schema = record.get('schema')
    if schema == 'execution-lease/v2':
        return execution_lease_v2.validate(record)
    if schema == 'execution-lease/v1':
        return execution_lease.validate(record)
    raise ValueError('unsupported lease schema')


def validate_coordination_transition(previous, record):
    validate_coordination_record(record)
    if previous is None:
        return record
    validate_coordination_record(previous)
    if any(previous[key] != record[key] for key in ('repository', 'source_ref')):
        raise ValueError('coordination binding is immutable')
    if previous.get('schema') == 'execution-lease/v2' and record.get('schema') != 'execution-lease/v2':
        raise ValueError('execution-lease/v2 cannot downgrade to v1')
    if record['submission_claims'][:len(previous['submission_claims'])] != previous['submission_claims']:
        raise ValueError('consumed submission history cannot be removed or rewritten')
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

    def _git(self, *args, input=None):
        environment = dict(os.environ, GIT_TERMINAL_PROMPT='0',
                           GIT_AUTHOR_NAME='CDC coordination', GIT_AUTHOR_EMAIL='cdc@example.invalid',
                           GIT_COMMITTER_NAME='CDC coordination', GIT_COMMITTER_EMAIL='cdc@example.invalid')
        try:
            result = subprocess.run(['git', '-C', str(self.repo), *args], input=input,
                                    text=True, capture_output=True, env=environment, check=False)
        except OSError as exc:
            raise ValueError('Git coordination unavailable') from exc
        if result.returncode:
            # Do not echo transport stderr: URLs or helper diagnostics may contain credentials.
            raise ValueError(f'Git coordination {args[0]} failed (exit {result.returncode})')
        return result.stdout.strip()

    def read(self):
        rows = self._git('ls-remote', '--refs', self.remote, self.ref).splitlines()
        if not rows:
            return None, None
        if len(rows) != 1:
            raise ValueError('ambiguous coordination ref')
        revision, ref = rows[0].split('\t')
        if ref != self.ref or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', revision):
            raise ValueError('invalid coordination revision')
        self._git('fetch', '--no-tags', '--no-write-fetch-head', self.remote, self.ref)
        if self._git('cat-file', '-t', revision) != 'commit':
            raise ValueError('coordination ref must point to a commit')
        record = json.loads(self._git('show', revision + ':lease.json'), object_pairs_hook=op._unique_object)
        validate_coordination_record(record)
        if record['source_ref'] == self.ref:
            raise ValueError('coordination ref must differ from product source ref')
        if self._git('ls-remote', '--refs', self.remote, self.ref).splitlines() != rows:
            raise ValueError('coordination ref moved during read; refetch before acting')
        return revision, record

    def compare_and_swap(self, expected_revision, record):
        validate_coordination_record(record)
        if record['source_ref'] == self.ref:
            raise ValueError('coordination ref must differ from product source ref')
        current, previous = self.read()
        if current != expected_revision:
            raise ValueError('stale expected coordination revision')
        validate_coordination_transition(previous, record)
        blob = self._git('hash-object', '-w', '--stdin', input=op._canonical(record).decode() + '\n')
        tree = self._git('mktree', input=f'100644 blob {blob}\tlease.json\n')
        parent = ['-p', expected_revision] if expected_revision else []
        commit = self._git('commit-tree', tree, *parent, input='Update cooperative execution ownership\n')
        # This commit has exactly the observed ref as its parent. Concurrent proposals
        # are siblings: normal push accepts at most one and rejects the other.
        self._git('-c', 'push.followTags=false', 'push', '--porcelain',
                  self.remote, f'{commit}:{self.ref}')
        return commit
