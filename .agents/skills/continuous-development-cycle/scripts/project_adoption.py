#!/usr/bin/env python3
"""Read-only native observation joining retained project coordination channels.

Registrations are trusted host configuration. An observation is neither a launch
capability nor a terminal proof; its serialization is informational only.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import re

import budget
import execution_lease_v2 as native_lease
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore, validate_coordination_transition
from git_remote_identity import remote_identity
from live_target import GitSource
from project_budget_store import GitProjectBudgetStore, ledger_digest
from project_setup import _checkpoint, _yaml
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24

_SEAL = object()
_REGISTRATION = {'schema', 'project_id', 'repository', 'source_ref', 'source_sha',
                 'source_store_id', 'lease_ref', 'lease_store_id', 'budget_binding_digest',
                 'authority_store_id', 'authority_ref', 'authority_revision',
                 'authority_path', 'authority_digest', 'final_platform', 'check_ids'}
_AUTHORIZATION = {'schema', 'project_id', 'repository', 'source_ref', 'source_sha',
                  'source_policy_revision', 'source_policy_digest', 'lease_ref', 'lease_store_id',
                  'budget_binding_digest', 'task_id', 'budget_policy_digest', 'anchor_revision',
                  'anchor_ledger_digest', 'preserved_counts', 'owner_decision_ref',
                  'owner_wake_id', 'owner_wake_ref', 'scope', 'remaining_work'}


def _digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                              allow_nan=False).encode()).hexdigest()


def _equal(left, right, message):
    # JSON equality must distinguish false from zero in authority contracts.
    if _digest(left) != _digest(right): raise ValueError(message)


def _text(value):
    if not isinstance(value, str) or not value.strip(): raise ValueError('missing authority text')


def _authority(document, path):
    try:
        container, key = path.split('/')
        return document[container][key]
    except (KeyError, TypeError, ValueError):
        raise ValueError('registered authorization path is absent') from None


def _history_transition(previous, record, expected_revision):
    """Check documentary edges without issuing historical/current capabilities."""
    ownership_changed = record['owner_id'] is not None and (
        record['owner_id'] != previous['owner_id'] or record['generation'] != previous['generation'])
    if ownership_changed:
        # Native acquire carries every prior effect and consumed submission. The
        # historical row is not an extinct physical capability or a new grant.
        old = _optional_history_fields(previous); new = _optional_history_fields(record)
        for field in ('schema', 'repository', 'source_ref', 'external_guard', 'last_terminal',
                      'last_release', 'submission_claims', 'submission_resolutions',
                      'submission_retirements', 'legacy_migration'):
            _equal(new[field], old[field], 'ownership transition altered protected ' + field)
        return
    retirements = record.get('submission_retirements', [])[len(previous.get('submission_retirements', [])):]
    if retirements:
        if len(retirements) != 1 or retirements[0]['proof']['lease_revision'] != expected_revision:
            raise ValueError('historical retirement must bind exact original revision')
        entry = retirements[0]
        if entry['schema'] == 'source-publication-quarantine/v1':
            from source_publication_quarantine import quarantine_source_guard as transition
        elif entry['schema'] == 'actions-submission-retirement/v1':
            from submission_retirement import retire_actions_unknown_guard as transition
        else:
            from submission_retirement import retire_unknown_guard as transition
        expected = transition(previous, entry['proof'], entry['evidence_reference'], entry['retired_at_utc'])
        _equal(record, expected, 'historical retirement contains noncanonical mutation')
        return
    validate_coordination_transition(previous, record, expected_revision=expected_revision)
    if previous['external_guard'] is not None and record['external_guard'] is None:
        # The current validator already authenticates claimed resolutions.
        # Claim-null owned guards also need their exact canonical terminal edge.
        terminal = record.get('last_terminal')
        if previous['owner_id'] is not None and previous['external_guard']['submission_claim'] is None:
            if not isinstance(terminal, dict): raise ValueError('guard clearing requires canonical terminal evidence')
            expected = native_lease.clear_guard(previous, previous['owner_id'], previous['generation'],
                previous['invocation']['invocation_id'], terminal['at_utc'], terminal['observation'], terminal['evidence_reference'])
            _equal(record, expected, 'guard clearing is not canonical terminal reconciliation')


def _lease_history(store, current, registration, original_revision):
    """Authenticate the Source-selected original interval, never older authority."""
    if store._git('rev-parse', '--is-shallow-repository') != 'false':
        raise ValueError('lease history is shallow')
    ancestry = [line.split() for line in store._git('rev-list', '--first-parent', '--parents', current).splitlines()]
    revisions = [row[0] for row in ancestry]
    if not revisions or len(revisions) > 10000: raise ValueError('lease history is incomplete or unbounded')
    if original_revision not in revisions:
        raise ValueError('checkpoint lease revision is not authentic original history')
    parents = {row[0]: row[1:] for row in ancestry}
    cached = {}

    def read(revision):
        if revision not in cached:
            record = store._read_record(revision)
            _equal([record['repository'], record['source_ref']],
                   [registration['repository'], registration['source_ref']], 'historical lease binding differs')
            cached[revision] = record
        return cached[revision]

    selected = read(original_revision)
    if selected['schema'] != 'execution-lease/v2':
        raise ValueError('selected checkpoint requires genuine native v2 closure')
    baseline = revisions.index(original_revision)
    if selected['owner_id'] is None:
        if selected['generation'] == 0:
            _equal(_optional_history_fields(selected), _optional_history_fields(
                native_lease.initialize(selected['repository'], selected['source_ref'])),
                'selected generation zero is not canonical native initialization')
        else:
            release = selected['last_release']
            if not isinstance(release, dict) or release['generation'] != selected['generation']:
                raise ValueError('selected checkpoint lacks genuine original release')
            # An unchanged released snapshot is not the release edge. Walk back
            # only through its exact selected identity to the actual predecessor.
            following = selected
            for index in range(baseline + 1, len(revisions)):
                revision = revisions[index]; record = read(revision)
                if record['generation'] != selected['generation']:
                    raise ValueError('selected checkpoint lacks genuine original release')
                if record['owner_id'] is not None:
                    if (record['owner_id'] != release['owner_id'] or record.get('invocation') is None
                            or record['invocation']['invocation_id'] != release['invocation_id']):
                        raise ValueError('selected original release identity differs')
                    _history_transition(record, following, revision)
                    baseline = index
                    break
                _equal(record['last_release'], release, 'selected original release was substituted')
                following = record
            else:
                raise ValueError('selected checkpoint lacks genuine original release')
    previous = None; records = {}; releases = {}
    for revision in reversed(revisions[:baseline + 1]):
        if len(parents[revision]) > 1: raise ValueError('merged lease history is ambiguous')
        # Missing/malformed interval records remain fatal, even when restored.
        try: record = read(revision)
        except ValueError as error:
            if 'requires one regular lease.json' in str(error):
                raise ValueError('native lease was deleted from selected history') from error
            raise
        if record['schema'] != 'execution-lease/v2': raise ValueError('native lease schema downgraded')
        if previous is not None:
            if record['generation'] < previous['generation']: raise ValueError('lease generation rewound')
            if record['owner_id'] is not None and (record['owner_id'] != previous['owner_id']
                    or record['generation'] != previous['generation']):
                if record['generation'] != previous['generation'] + 1:
                    raise ValueError('ownership generation must advance exactly once')
                if record['owner_id'] in (previous['owner_id'], (previous['last_release'] or {}).get('owner_id')):
                    raise ValueError('native ownership cannot reuse an owner UUID')
            for field in ('submission_claims', 'submission_resolutions', 'submission_retirements'):
                old = previous.get(field, []); new = record.get(field, [])
                _equal(new[:len(old)], old, 'lease history was rewritten')
            _history_transition(previous, record, parents[revision][0])
            if previous['owner_id'] is not None and record['owner_id'] is None:
                release = record['last_release']
                key = (release['owner_id'], release['generation'], release['invocation_id'])
                if key in releases: raise ValueError('duplicate original invocation closure')
                releases[key] = {'revision': revision, 'release': copy.deepcopy(release)}
            elif record.get('last_release') != previous.get('last_release'):
                raise ValueError('historical release was substituted')
            if (previous['owner_id'] is not None and record['owner_id'] is not None
                    and record['generation'] == previous['generation']):
                keys = ('invocation_id', 'execution_surface', 'started_at_utc')
                _equal([record['owner_id'], [record['invocation'][key] for key in keys]],
                       [previous['owner_id'], [previous['invocation'][key] for key in keys]],
                       'owned generation identity changed')
        records[revision] = record; previous = record
    return records, releases, revisions[baseline]


def _optional_history_fields(record):
    """Compare native optional empty fields without inventing historical edges."""
    result = copy.deepcopy(record)
    if result['schema'] == 'execution-lease/v2':
        result.setdefault('submission_resolutions', [])
        result.setdefault('submission_retirements', [])
    return result


def _collect(source, lease_store, budget_store, policy_authority_store, registration):
    for value, required in [(source, GitSource), (lease_store, GitLeaseStore),
                            (budget_store, GitProjectBudgetStore), (policy_authority_store, GitDocumentStore)]:
        if type(value) is not required: raise ValueError('authentic native channel objects required')
    if not isinstance(registration, dict) or set(registration) != _REGISTRATION:
        raise ValueError('invalid trusted project registration fields')
    r = copy.deepcopy(registration)
    if r['schema'] != 'project-adoption-registration/v1': raise ValueError('unsupported registration')
    for key in _REGISTRATION - {'check_ids'}: _text(r[key])
    if r['authority_path'] != 'project_adoption_authorizations/' + r['project_id']:
        raise ValueError('authorization path must name the registered project')
    if (not isinstance(r['check_ids'], list) or not r['check_ids']
            or any(not isinstance(item, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', item) for item in r['check_ids'])
            or len(set(r['check_ids'])) != len(r['check_ids'])):
        raise ValueError('fixed check identifiers required')
    _equal(source.identity(), r['source_store_id'], 'Source endpoint differs')
    _equal([lease_store.store_id, lease_store.ref], [r['lease_store_id'], r['lease_ref']], 'lease channel differs')
    _equal([policy_authority_store.store_id, policy_authority_store.ref],
           [r['authority_store_id'], r['authority_ref']], 'policy authority channel differs')
    b = copy.deepcopy(budget_store.binding)
    _equal(_digest(b), r['budget_binding_digest'], 'original budget binding differs')
    # The full binding digest pins the independently registered budget endpoint,
    # ref, path/field, task and anchor. Its channel need not be the lease channel.
    _equal([b['repository'], b['source_ref']], [r['repository'], r['source_ref']], 'budget channel is foreign')
    auth_document = policy_authority_store.read_revision(r['authority_revision'])
    a = copy.deepcopy(_authority(auth_document, r['authority_path']))
    if not isinstance(a, dict) or set(a) != _AUTHORIZATION: raise ValueError('invalid native owner authorization fields')
    if a['schema'] != 'project-adoption-authorization/v1': raise ValueError('unsupported authorization')
    _equal(_digest(a), r['authority_digest'], 'immutable authorization digest differs')
    # Authenticate all revisions after the anchor, rejecting a changed-and-restored record.
    authority_revision, _ = policy_authority_store.read()
    chain = policy_authority_store._git('rev-list', '--ancestry-path',
                                       r['authority_revision'] + '..' + authority_revision).splitlines()
    if len(chain) > 10000: raise ValueError('authority history exceeds bound')
    for revision in chain:
        _equal(_authority(policy_authority_store._read_document_object(revision), r['authority_path']), a,
               'original owner authorization changed')
    for key in ('project_id', 'repository', 'source_ref', 'source_sha', 'lease_ref', 'lease_store_id', 'budget_binding_digest'):
        _equal(a[key], r[key], 'owner authorization binding differs: ' + key)
    _text(a['owner_decision_ref']); _text(a['owner_wake_id']); _text(a['owner_wake_ref'])
    _equal(b['wake_authorizations'].get(a['owner_wake_id']), a['owner_wake_ref'], 'new owner wake is not registered')
    if not isinstance(a['remaining_work'], list) or not a['remaining_work']:
        raise ValueError('remaining original product work must be retained')
    for item in a['remaining_work']: _text(item)
    expected_scope = {'role': 'read_only', 'mode': 'COMPUTE_ONLY', 'execution_platform': 'linux',
                      'ci_starts': 0, 'agent_starts': 0, 'product_writes': False, 'check_ids': r['check_ids']}
    _equal(a['scope'], expected_scope, 'prospective scope exceeds fixed Linux checks')
    snapshot = source.pin(r['source_ref'])
    _equal(snapshot.revision, r['source_sha'], 'registered Source SHA changed')
    adapter = _yaml(source.read_file(snapshot, 'docs/development-cycle.yaml'))
    checkpoint, _ = _checkpoint(source.read_file(snapshot, 'docs/work-status/current.md'))
    policy = validate_adapter(adapter)
    validate_checkpoint_24(checkpoint, adapter)
    if checkpoint.get('schema') != 'development-work-status/v4':
        raise ValueError('adoption requires native invocation-bound v4 checkpoint')
    _equal([adapter['repository']['remote'], checkpoint['repository'], checkpoint['branch']],
           [r['repository'], r['repository'], r['source_ref'].removeprefix('refs/heads/')], 'Source repository or branch differs')
    _equal([policy['policy_revision'], policy['policy_digest']],
           [a['source_policy_revision'], a['source_policy_digest']], 'Source policy authority differs')
    _equal(adapter['validation']['final_platform'], r['final_platform'], 'original final platform changed')
    _equal(adapter['orchestration']['execution_lease']['coordination_ref'], r['lease_ref'], 'Source lease ref differs')
    _equal(remote_identity(source.repo, adapter['orchestration']['execution_lease']['remote']),
           r['lease_store_id'], 'Source configured lease endpoint differs')
    control = checkpoint.get('control', {})
    _equal(control.get('execution_lease_ref'), r['lease_ref'], 'checkpoint lease ref differs')
    budget_refs = {'https://github.com/' + r['repository'] + '/blob/' + b['coordination_ref'].removeprefix('refs/heads/') + '/' + b['ledger_path']}
    if b['budget_field'] is not None: budget_refs.add(b['coordination_ref'] + '#' + b['budget_field'])
    if control.get('budget_ref') not in budget_refs: raise ValueError('checkpoint original budget ref differs')
    for field in ('operation_intent_ref', 'operation_key', 'waiting_external_kind', 'waiting_external_id',
                  'waiting_external_sha', 'active_ci_run_id'):
        if checkpoint.get(field) not in (None, ''): raise ValueError('checkpoint has unresolved external state')
    if control.get('external_wait_ref') not in (None, ''): raise ValueError('checkpoint has unresolved external wait')
    lease_revision, current = lease_store.read()
    if (current is None or current.get('schema') != 'execution-lease/v2' or current['owner_id'] is not None
            or current.get('invocation') is not None or current.get('finalization') is not None
            or current.get('external_guard') is not None): raise ValueError('canonical lease is not released and unguarded')
    original_revision = control.get('execution_lease_revision')
    records, releases, baseline_revision = _lease_history(lease_store, lease_revision, r, original_revision)
    if original_revision not in records: raise ValueError('checkpoint lease revision is not authentic original history')
    original = records[original_revision]
    generation = control.get('lease_generation')
    _equal(original['generation'], generation, 'checkpoint generation differs from original revision')
    if current['generation'] < generation: raise ValueError('current lease precedes original checkpoint generation')
    classification = 'released_projection'; matched_release = None
    if checkpoint['lease_state'] == 'active':
        classification = 'stale_active_projection'
        owner = control.get('executor_id'); invocation = checkpoint['execution_continuity']['invocation_id']
        _equal([original['owner_id'], checkpoint['active_executor']],
               [owner, owner], 'stale active checkpoint owner differs')
        if (original.get('invocation') or {}).get('invocation_id') != invocation: raise ValueError('stale invocation differs')
        matched_release = releases.get((owner, generation, invocation))
        if matched_release is None: raise ValueError('stale active checkpoint has no genuine original release')
        active = checkpoint.get('active_compute')
        if active not in ('', 'none') and not re.fullmatch(r'managed-host:[0-9a-f-]{36}', active):
            raise ValueError('stale checkpoint compute identifier is not native')
    elif checkpoint['lease_state'] == 'released':
        if checkpoint.get('active_compute') not in ('', 'none'): raise ValueError('released checkpoint has unresolved compute')
        if original.get('owner_id') is not None:
            invocation = (original.get('invocation') or {}).get('invocation_id')
            matched_release = releases.get((original['owner_id'], generation, invocation))
        else:
            release = original.get('last_release')
            if release: matched_release = releases.get((release['owner_id'], generation, release.get('invocation_id')))
        if generation and matched_release is None: raise ValueError('released checkpoint lacks authentic historical closure')
        if matched_release:
            for retained, expected in [(control.get('executor_id'), matched_release['release']['owner_id']),
                                       (checkpoint['execution_continuity']['invocation_id'], matched_release['release']['invocation_id'])]:
                if retained is not None: _equal(retained, expected, 'released checkpoint retained identity differs')
    else: raise ValueError('checkpoint lease state is not eligible for read-only adoption')
    if matched_release and matched_release['release']['external_reconciliation'] not in ('none', 'terminal_reconciled'):
        raise ValueError('historical closure retains unresolved external activity')
    budget_revision, ledger = budget_store.read(); anchor = budget_store.read_revision(b['anchor_revision'])
    for key, value in [('task_id', ledger['task_id']), ('budget_policy_digest', ledger['policy_digest']),
                       ('anchor_revision', b['anchor_revision']), ('anchor_ledger_digest', ledger_digest(anchor))]:
        _equal(a[key], value, 'original budget authority differs: ' + key)
    counts = budget.summarize(anchor)
    preserved = {key: counts['task'][key] for key in ('compute_starts', 'ci_starts', 'agent_starts')}
    preserved['active_agents'] = counts['active_agents']
    _equal(a['preserved_counts'], preserved, 'original charged counts differ')
    source.assert_current(snapshot)
    if lease_store.read()[0] != lease_revision or budget_store.read()[0] != budget_revision:
        raise ValueError('coordination changed while joining channels')
    _equal(_authority(policy_authority_store.read()[1], r['authority_path']), a, 'policy authority changed while joining')
    return {'schema': 'project-adoption-observation/v1', 'project_id': r['project_id'], 'source_sha': snapshot.revision,
            'source_policy_digest': policy['policy_digest'], 'checkpoint': copy.deepcopy(checkpoint),
            'checkpoint_classification': classification, 'lease_revision': lease_revision,
            'lease_release': copy.deepcopy(matched_release['release']) if matched_release else None,
            'lease_release_revision': matched_release['revision'] if matched_release else None,
            'lease_baseline_revision': baseline_revision,
            'budget_revision': budget_revision, 'task_id': ledger['task_id'], 'budget_binding_digest': _digest(b),
            'budget_summary': budget.summarize(ledger), 'authority_revision': r['authority_revision'],
            'authority_digest': r['authority_digest'], 'scope': copy.deepcopy(expected_scope),
            'remaining_work': copy.deepcopy(a['remaining_work']), 'required_final_platform': r['final_platform'],
            'authorizes_launch': False, 'authorizes_product_acceptance': False, 'authorizes_product_write': False}


class ProjectAdoptionObservation:
    """Process-local sealed read-only facts, freshly revalidated before use."""
    def __init__(self, payload, channels, registration, clock, *, _seal=None):
        if _seal is not _SEAL: raise ValueError('use native observation factory')
        self._seal = _seal; self._payload = copy.deepcopy(payload); self._digest = _digest(self._payload)
        self._channels = tuple(channels); self._registration = copy.deepcopy(registration)
        self._registration_digest = _digest(registration); self._clock = clock; self._observed = clock()

    @property
    def payload(self): return copy.deepcopy(self._payload)

    @property
    def budget_store(self): return self._channels[2]

    @property
    def budget_revision(self): return self._payload['budget_revision']

    def revalidate_for(self, source, lease_store, budget_store, policy_authority_store, registration):
        if self._seal is not _SEAL or _digest(self._payload) != self._digest:
            raise ValueError('native observation seal or payload changed')
        if _digest(self._registration) != self._registration_digest or _digest(registration) != self._registration_digest:
            raise ValueError('trusted registration changed')
        if any(left is not right for left, right in zip(self._channels, (source, lease_store, budget_store, policy_authority_store))):
            raise ValueError('native observation channels substituted')
        age = (self._clock() - self._observed).total_seconds()
        if age < 0 or age > 90: raise ValueError('native observation is stale')
        fresh = _collect(source, lease_store, budget_store, policy_authority_store, registration)
        _equal(fresh, self._payload, 'native channels changed; obtain a fresh observation')
        return copy.deepcopy(fresh)


def observe_project_adoption(source, lease_store, budget_store, policy_authority_store, registration, *, clock=None):
    """Authenticate host-pinned original channels; performs no remote writes."""
    if clock is None: clock = lambda: datetime.now(timezone.utc)
    payload = _collect(source, lease_store, budget_store, policy_authority_store, registration)
    return ProjectAdoptionObservation(payload, (source, lease_store, budget_store, policy_authority_store),
                                      registration, clock, _seal=_SEAL)
