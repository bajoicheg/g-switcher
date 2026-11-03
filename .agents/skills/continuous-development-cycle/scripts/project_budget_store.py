"""CAS custody of an existing registered task budget, never launch authority.

The host supplies trusted registration and authenticates the original policy
authority before constructing this store. JSON syntax and a ledger digest do
not authenticate an owner decision, a provider outcome or a fresh wake.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
import subprocess
import unicodedata

import budget
from git_object_integrity import git_object_environment
from git_remote_identity import isolated_remote_args, remote_identity, repository_root
from parallel_task_planner import portable_path_key

MAX_BYTES = 4 * 1024 * 1024
REVISION = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
BINDING_FIELDS = {'schema', 'repository', 'source_ref', 'coordination_ref',
                  'coordination_store_id', 'ledger_path', 'budget_field', 'task_id',
                  'anchor_revision', 'anchor_ledger_digest', 'wake_authorizations'}


def ledger_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}; keys = set()
    for key, value in pairs:
        portable = unicodedata.normalize('NFC', key).casefold()
        if portable in keys:
            raise ValueError('duplicate or ambiguous budget document key')
        keys.add(portable); result[key] = value
    return result


def _constant(value):
    raise ValueError('nonfinite budget document value')


def _float(value):
    result = float(value)
    if not math.isfinite(result): raise ValueError('nonfinite budget document value')
    return result


def _decode(payload, field):
    """Locate only the actual top-level value; retain every other lexical byte."""
    if len(payload) > MAX_BYTES: raise ValueError('budget document exceeds 4 MiB')
    try:
        text = payload.decode('utf-8')
        decoder = json.JSONDecoder(object_pairs_hook=_unique, parse_constant=_constant, parse_float=_float)
        document = decoder.decode(text)
        if not isinstance(document, dict): raise ValueError('budget document must be an object')
        if field is None: return document, None, text
        if field not in document: raise ValueError('registered budget field missing')
        def space(index):
            while index < len(text) and text[index] in ' \t\r\n': index += 1
            return index
        index = space(0) + 1
        while True:
            index = space(index)
            key, index = decoder.raw_decode(text, index)
            index = space(index)
            if text[index] != ':': raise ValueError('invalid budget field separator')
            start = space(index + 1); _, end = decoder.raw_decode(text, start)
            if key == field: return document[field], (start, end), text
            index = space(end)
            if text[index] != ',': raise ValueError('registered budget field missing')
            index += 1
    except (UnicodeError, json.JSONDecodeError, RecursionError, IndexError) as error:
        raise ValueError('invalid registered budget JSON') from None


def _extends(previous, current):
    for key in ('schema', 'task_id', 'policy', 'policy_digest'):
        if current[key] != previous[key]: raise ValueError('original budget identity/policy changed')
    if current['events'][:len(previous['events'])] != previous['events']:
        raise ValueError('original budget event history changed or truncated')
    if current['wake_ids'][:len(previous['wake_ids'])] != previous['wake_ids']:
        raise ValueError('original budget wake history changed or truncated')
    closed = set(previous['wake_ids'][:-1])
    if any(event['wake_id'] in closed for event in current['events'][len(previous['events']):]):
        raise ValueError('cannot append into previously closed wake')


class GitProjectBudgetStore:
    """Registered original ref/path/task custody with non-force sibling CAS.

    Registration is trusted host configuration, never an operator task payload.
    anchor_revision/digest pin the already authenticated original ledger/policy;
    every later revision is checked, including intermediate rewrites subsequently
    restored. Original policy-authority verification is a separate prerequisite.
    """

    def __init__(self, repo, remote, registered_binding, *, protected_refs=()):
        if not isinstance(registered_binding, dict) or set(registered_binding) != BINDING_FIELDS:
            raise ValueError('registered project budget binding fields mismatch')
        self.binding = copy.deepcopy(registered_binding)
        value = self.binding
        if value['schema'] != 'project-budget-binding/v1': raise ValueError('unsupported budget binding')
        if not isinstance(value['repository'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value['repository']):
            raise ValueError('registered repository identity required')
        self.repo = repository_root(repo); self.remote = remote
        self.ref = value['coordination_ref']; self.store_id = value['coordination_store_id']
        if not isinstance(self.ref, str) or not self.ref.startswith('refs/heads/cdc/'):
            raise ValueError('registered original coordination ref required')
        if not isinstance(value['source_ref'], str) or not value['source_ref'].startswith('refs/heads/'):
            raise ValueError('registered source ref required')
        self._git('check-ref-format', self.ref); self._git('check-ref-format', value['source_ref'])
        if portable_path_key(self.ref) in {portable_path_key(x) for x in (*protected_refs, value['source_ref'])}:
            raise ValueError('budget ref collides with protected source')
        if not isinstance(self.store_id, str) or not DIGEST.fullmatch(self.store_id):
            raise ValueError('registered coordination endpoint required')
        self.path = value['ledger_path']; self.field = value['budget_field']
        if (not isinstance(self.path, str) or self.field is not None and not isinstance(self.field, str)
                or (self.path, self.field) not in {('budget.json', None), ('budget-ledger.json', None), ('document.json', 'budget')}):
            raise ValueError('unregistered budget path/field')
        budget._text(value['task_id'], 'original task_id')
        if not isinstance(value['anchor_revision'], str) or not REVISION.fullmatch(value['anchor_revision']):
            raise ValueError('immutable original budget anchor required')
        if not isinstance(value['anchor_ledger_digest'], str) or not DIGEST.fullmatch(value['anchor_ledger_digest']):
            raise ValueError('original ledger digest required')
        wakes = value['wake_authorizations']
        if not isinstance(wakes, dict): raise ValueError('trusted wake authorization map required')
        for wake, reference in wakes.items():
            budget._text(wake, 'authorized wake'); budget._text(reference, 'owner wake reference')
        self._last_observed = None
        self.read()

    def _git(self, *args, input_bytes=None):
        env = git_object_environment(GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='CDC budget custody',
                                    GIT_AUTHOR_EMAIL='cdc@example.invalid', GIT_COMMITTER_NAME='CDC budget custody',
                                    GIT_COMMITTER_EMAIL='cdc@example.invalid')
        try:
            result = subprocess.run(['git', '-C', str(self.repo), *args], input=input_bytes,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise ValueError('project budget Git transport unavailable') from None
        if result.returncode: raise ValueError('project budget Git command failed')
        return result.stdout

    def _assert_identity(self):
        if remote_identity(self.repo, self.remote) != self.store_id:
            raise ValueError('registered project budget endpoint changed')

    def _remote_revision(self):
        self._assert_identity()
        rows = self._git('ls-remote', '--refs', self.remote, self.ref).decode('ascii').splitlines()
        if len(rows) != 1: raise ValueError('original budget ref absent or ambiguous')
        parts = rows[0].split('\t')
        if len(parts) != 2 or parts[1] != self.ref or not REVISION.fullmatch(parts[0]):
            raise ValueError('invalid original budget revision')
        return parts[0]

    def _object(self, revision):
        rows = [x for x in self._git('ls-tree', '--full-tree', '-z', revision, '--', self.path).split(b'\0') if x]
        if len(rows) != 1: raise ValueError('original budget blob missing')
        metadata, name = rows[0].split(b'\t', 1); mode, kind, oid = metadata.split()
        if name != self.path.encode() or mode not in {b'100644', b'100755'} or kind != b'blob':
            raise ValueError('original budget must be one regular blob')
        size = self._git('cat-file', '-s', oid.decode('ascii')).strip()
        if not re.fullmatch(rb'[0-9]+', size):
            raise ValueError('invalid original budget blob size')
        if int(size) > MAX_BYTES:
            raise ValueError('budget document exceeds 4 MiB')
        payload = self._git('cat-file', 'blob', oid.decode('ascii'))
        ledger, span, text = _decode(payload, self.field)
        budget.validate_ledger(ledger)
        if ledger['task_id'] != self.binding['task_id']: raise ValueError('original budget task changed')
        return ledger, payload, span, text, mode

    def _history(self, current, *, historical=False):
        from immutable_history_cache import _cache,_context,_linear_chain
        anchor = self.binding['anchor_revision']
        if self._git('rev-parse','--is-shallow-repository').decode().strip()!='false':
            raise ValueError('complete project budget history required')
        if self._git('merge-base', anchor, current).decode().strip() != anchor:
            raise ValueError('original budget anchor is outside canonical ancestry')
        if self._last_observed is not None and self._git('merge-base', self._last_observed, current).decode().strip() != self._last_observed:
            raise ValueError('canonical budget history rewound')
        rows=self._git('rev-list','--reverse','--ancestry-path','--parents',anchor+'..'+current).decode().splitlines()
        chain=[[anchor]]+_linear_chain(rows,anchor=anchor)
        if chain[-1][0]!=current:raise ValueError('original budget parent chain incomplete')
        context=_context(self,'project-budget-tip/v2',ledger_digest(self.binding))
        prior=_cache.get(context)
        if prior is not None:
            if historical and prior['chain'][:len(chain)]==chain:
                # The fresh canonical chain matches an already authenticated prefix.
                # Only its tip snapshot is retained; load the selected immutable
                # object when the requested revision is earlier than that tip.
                if current==prior['chain'][-1][0]:
                    return prior['tip']
                return self._object(current)[0]
            if chain[:len(prior['chain'])]!=prior['chain']:
                raise ValueError('canonical budget history rewound or rewritten')
            previous=prior['tip'];verified=len(prior['chain'])
        else:
            previous=self._object(anchor)[0]
            if ledger_digest(previous)!=self.binding['anchor_ledger_digest']:
                raise ValueError('original budget anchor digest mismatch')
            verified=1
        for parts in chain[verified:]:
            revision=parts[0];value=self._object(revision)[0];_extends(previous,value)
            if any(wake not in self.binding['wake_authorizations'] for wake in value['wake_ids'][len(previous['wake_ids']):]):
                raise ValueError('new budget wake lacks trusted owner authorization')
            previous=value
        if not historical:_cache.put(context,{'chain':chain,'tip':previous})
        return previous

    def read(self):
        current = self._remote_revision()
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, 'fetch', '--no-tags', '--no-write-fetch-head', '--refmap=', remote, self.ref)
        value = self._history(current)
        if self._remote_revision() != current: raise ValueError('original budget ref moved during read')
        self._last_observed = current
        return current, copy.deepcopy(value)

    def read_revision(self, revision):
        if not isinstance(revision, str) or not REVISION.fullmatch(revision): raise ValueError('invalid historical budget revision')
        current, _ = self.read()
        if self._git('merge-base', revision, current).decode().strip() != revision:
            raise ValueError('historical budget revision outside canonical ancestry')
        # _history also ensures the requested revision is at/after the trusted anchor.
        latest = self._last_observed; self._last_observed = None
        try: value = self._history(revision,historical=True)
        finally: self._last_observed = latest
        if self._remote_revision() != current: raise ValueError('budget ref moved during historical read')
        return copy.deepcopy(value)

    def _receipt(self, revision, ledger, *, already_recorded):
        return {'revision': revision, 'ledger': copy.deepcopy(ledger), 'already_recorded': already_recorded,
                'authorizes_launch': False, 'authorizes_product_write': False}

    def observe_event(self, event):
        event = copy.deepcopy(event); budget._validate_event(event)
        revision, ledger = self.read()
        matches = [old for old in ledger['events'] if old['event_id'] == event['event_id']]
        if matches and matches != [event]: raise ValueError('original budget event identity conflict')
        if event['task_id'] != self.binding['task_id']: raise ValueError('original budget task changed')
        return self._receipt(revision, ledger, already_recorded=bool(matches))

    def _commit(self, expected, previous, updated):
        _extends(previous, updated)
        if self._remote_revision() != expected: raise ValueError('stale expected project budget revision')
        _, payload, span, text, mode = self._object(expected)
        encoded = json.dumps(updated, sort_keys=True, separators=(',', ':'), allow_nan=False)
        replacement = (encoded + '\n').encode() if span is None else (text[:span[0]] + encoded + text[span[1]:]).encode('utf-8')
        if len(replacement) > MAX_BYTES: raise ValueError('budget document exceeds 4 MiB')
        oid = self._git('hash-object', '-w', '--stdin', input_bytes=replacement).decode().strip()
        rows = [x for x in self._git('ls-tree', '--full-tree', '-z', expected).split(b'\0') if x]
        neighbors = [x for x in rows if x.split(b'\t', 1)[1] != self.path.encode()]
        entries = neighbors + [mode + b' blob ' + oid.encode() + b'\t' + self.path.encode()]
        tree = self._git('mktree', '-z', input_bytes=b'\0'.join(entries) + b'\0').decode().strip()
        proposal = self._git('commit-tree', tree, '-p', expected,
                             input_bytes=('Append original CDC budget\n\nCAS proposal: ' + secrets.token_hex(32) + '\n').encode()).decode().strip()
        # Every proposal is a sibling of competing writes; ordinary push accepts at most one.
        self._assert_identity()
        config, remote = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, '-c', 'push.followTags=false', 'push', '--porcelain', remote, proposal + ':' + self.ref)
        current, observed = self.read()
        if current != proposal or observed != updated: raise ValueError('project budget CAS readback changed; observe only')
        return self._receipt(current, observed, already_recorded=False)

    def append_event(self, expected_revision, event):
        event = copy.deepcopy(event)
        revision, previous = self.read()
        if expected_revision != revision: raise ValueError('stale expected project budget revision')
        updated = budget.apply_event(previous, event)
        if updated == previous: return self._receipt(revision, previous, already_recorded=True)
        return self._commit(revision, previous, updated)

    def begin_wake(self, expected_revision, wake_id, owner_reference=None):
        """Append an explicitly registered fresh owner wake; retain all old liability."""
        reference = self.binding['wake_authorizations'].get(wake_id)
        if reference is None or (owner_reference is not None and reference != owner_reference):
            raise ValueError('genuine registered owner wake required')
        revision, previous = self.read()
        if expected_revision != revision: raise ValueError('stale expected project budget revision')
        updated = budget.begin_wake(previous, wake_id)
        if updated == previous: return self._receipt(revision, previous, already_recorded=True)
        return self._commit(revision, previous, updated)
