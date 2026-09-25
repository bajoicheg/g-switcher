#!/usr/bin/env python3
"""Cooperative ownership and durable external guards; not product/provider fencing."""
from __future__ import annotations

import argparse
import copy
from datetime import timedelta
import json
import sys
import uuid

import operation_intent as op

FIELDS = {'schema', 'repository', 'source_ref', 'generation', 'owner_id',
          'acquired_at_utc', 'heartbeat_at_utc', 'expires_at_utc', 'activity_refs',
          'external_guard', 'last_release', 'takeover_evidence', 'last_terminal', 'submission_claims'}


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('owner_id must be a canonical UUID')


def _generation(value):
    if type(value) is not int or value < 0:
        raise ValueError('generation must be a nonnegative integer')


def _validate_claim(claim, generation):
    op._object(claim, {'grant_id', 'owner_id', 'generation', 'operation_key', 'attempt_id',
                      'intent_digest', 'claimed_at_utc'}, 'submission claim')
    _uuid(claim['grant_id'])
    _uuid(claim['owner_id'])
    _generation(claim['generation'])
    op._timestamp(claim['claimed_at_utc'], 'claim time')
    op._digest(claim['intent_digest'], 'claimed intent digest')
    op._digest(claim['operation_key'], 'claimed operation key')
    op._text(claim['attempt_id'], 'claimed attempt')
    if not 0 < claim['generation'] <= generation:
        raise ValueError('submission claim generation mismatch')


def validate(record):
    op._object(record, FIELDS, 'lease')
    if record['schema'] != 'execution-lease/v1':
        raise ValueError('unsupported lease schema')
    for field in ('repository', 'source_ref'):
        op._text(record[field], field)
    if not record['source_ref'].startswith('refs/heads/'):
        raise ValueError('source_ref must be an exact refs/heads/ ref')
    _generation(record['generation'])
    if record['owner_id'] is not None:
        _uuid(record['owner_id'])
        if record['generation'] == 0:
            raise ValueError('owned lease must have positive generation')
        times = [op._timestamp(record[field], field) for field in
                 ('acquired_at_utc', 'heartbeat_at_utc', 'expires_at_utc')]
        if not times[0] <= times[1] < times[2]:
            raise ValueError('invalid lease time order')
    elif any(record[key] is not None for key in ('acquired_at_utc', 'heartbeat_at_utc', 'expires_at_utc')):
        raise ValueError('released lease must have null ownership times')
    if not isinstance(record['activity_refs'], list):
        raise ValueError('activity_refs must be a list')
    for ref in record['activity_refs']:
        op._text(ref, 'activity reference')
    if len(set(record['activity_refs'])) != len(record['activity_refs']):
        raise ValueError('duplicate activity reference')
    if record['last_release'] is not None:
        release = record['last_release']
        op._object(release, {'owner_id', 'generation', 'at_utc'}, 'last_release')
        _uuid(release['owner_id'])
        _generation(release['generation'])
        op._timestamp(release['at_utc'], 'release time')
        if release['generation'] > record['generation']:
            raise ValueError('release generation exceeds persistent generation')
    if record['owner_id'] is None and record['generation'] > 0:
        if record['last_release'] is None or record['last_release']['generation'] != record['generation']:
            raise ValueError('unowned state requires explicit release of the current generation')
    if not isinstance(record['submission_claims'], list):
        raise ValueError('submission_claims must be a list')
    identities = set()
    for claim in record['submission_claims']:
        _validate_claim(claim, record['generation'])
        identity = (claim['operation_key'], claim['attempt_id'])
        if identity in identities:
            raise ValueError('duplicate consumed operation attempt')
        identities.add(identity)
    guard = record['external_guard']
    if guard is not None:
        op._object(guard, {'operation_key', 'intent_reference', 'intent_digest', 'intent', 'submission_claim'}, 'external_guard')
        op.validate_intent(guard['intent'])
        op._text(guard['intent_reference'], 'intent_reference')
        if (guard['operation_key'] != guard['intent']['operation_key'] or
                guard['intent_digest'] != op._hash(guard['intent']) or
                guard['intent']['binding']['repository'] != record['repository'] or
                guard['intent']['source_ref'] != record['source_ref'] or
                guard['intent']['state'] not in {'submitting', 'unknown', 'accepted'}):
            raise ValueError('external guard binding or digest mismatch')
        claim = guard['submission_claim']
        if claim is not None:
            _validate_claim(claim, record['generation'])
            if (claim['operation_key'] != guard['operation_key'] or
                    claim['attempt_id'] != guard['intent']['attempt_id'] or
                    claim not in record['submission_claims']):
                raise ValueError('submission claim binding mismatch')
        elif (guard['operation_key'], guard['intent']['attempt_id']) in identities:
            raise ValueError('consumed attempt cannot be rearmed')
    return record


def initialize(repository, source_ref):
    return validate(dict(schema='execution-lease/v1', repository=repository, source_ref=source_ref,
                         generation=0, owner_id=None, acquired_at_utc=None, heartbeat_at_utc=None,
                         expires_at_utc=None, activity_refs=[], external_guard=None,
                         last_release=None, takeover_evidence=None, last_terminal=None, submission_claims=[]))


def _expiry(at, ttl):
    if type(ttl) is not int or ttl <= 0:
        raise ValueError('ttl must be positive integer seconds')
    return (op._timestamp(at, 'at') + timedelta(seconds=ttl)).isoformat().replace('+00:00', 'Z')


def _owner(record, owner_id, generation, at):
    validate(record)
    _uuid(owner_id)
    _generation(generation)
    if owner_id != record['owner_id'] or generation != record['generation']:
        raise ValueError('stale or non-owner executor')
    if op._timestamp(at, 'at') < op._timestamp(record['heartbeat_at_utc'], 'heartbeat'):
        raise ValueError('ownership action cannot move backwards in time')


def acquire(record, owner_id, at, *, ttl=1200, quiescence=None):
    validate(record)
    _uuid(owner_id)
    op._timestamp(at, 'at')
    last_release = record['last_release']
    if last_release is not None:
        if owner_id == last_release['owner_id']:
            raise ValueError('released executor UUID cannot be reused')
        if op._timestamp(at, 'at') < op._timestamp(last_release['at_utc'], 'release time'):
            raise ValueError('acquisition predates explicit release')
    if owner_id == record['owner_id']:
        raise ValueError('each acquisition needs a fresh executor UUID')
    if record['owner_id'] is not None:
        op._object(quiescence, {'owner_id', 'generation', 'repository', 'source_ref', 'kind', 'reference'}, 'quiescence evidence')
        for field in ('owner_id', 'generation', 'repository', 'source_ref'):
            if quiescence[field] != record[field]:
                raise ValueError('quiescence evidence must match the prior owner and generation')
        if quiescence['kind'] != 'executor_stopped':
            raise ValueError('quiescence evidence must establish prior executor stopped')
        op._text(quiescence['reference'], 'quiescence reference')
        if op._timestamp(at, 'at') < op._timestamp(record['heartbeat_at_utc'], 'heartbeat'):
            raise ValueError('acquisition predates prior heartbeat')
    elif quiescence is not None:
        raise ValueError('quiescence supplied without a prior owner')
    result = copy.deepcopy(record)
    result.update(owner_id=owner_id, generation=record['generation'] + 1,
                  acquired_at_utc=at, heartbeat_at_utc=at, expires_at_utc=_expiry(at, ttl),
                  activity_refs=[], takeover_evidence=copy.deepcopy(quiescence))
    return validate(result)


def renew(record, owner_id, generation, at, *, activity_ref, ttl=1200):
    _owner(record, owner_id, generation, at)
    op._text(activity_ref, 'activity_ref')
    if activity_ref in record['activity_refs']:
        raise ValueError('heartbeat requires unique observable activity')
    result = copy.deepcopy(record)
    result['activity_refs'].append(activity_ref)
    result.update(heartbeat_at_utc=at, expires_at_utc=_expiry(at, ttl))
    return validate(result)


def release(record, owner_id, generation, at):
    _owner(record, owner_id, generation, at)
    result = copy.deepcopy(record)
    result.update(owner_id=None, acquired_at_utc=None, heartbeat_at_utc=None, expires_at_utc=None,
                  last_release={'owner_id':owner_id, 'generation':generation, 'at_utc':at})
    return validate(result)


def set_guard(record, owner_id, generation, at, intent, intent_reference):
    _owner(record, owner_id, generation, at)
    op.validate_intent(intent)
    op._text(intent_reference, 'intent_reference')
    existing = record['external_guard']
    if existing is not None:
        old = existing['intent']
        if (old['operation_key'] != intent['operation_key'] or old['attempt_id'] != intent['attempt_id'] or
                intent['state'] not in {old['state']} | op.TRANSITIONS[old['state']] or
                op._timestamp(intent['updated_at_utc'], 'intent update') < op._timestamp(old['updated_at_utc'], 'old update') or
                (old['task'] is not None and old['task'] != intent['task'])):
            raise ValueError('cannot replace unresolved external operation')
    result = copy.deepcopy(record)
    result['external_guard'] = {'operation_key':intent['operation_key'], 'intent_reference':intent_reference,
                                'intent_digest':op._hash(intent), 'intent':copy.deepcopy(intent),
                                'submission_claim':copy.deepcopy(existing['submission_claim']) if existing else None}
    return validate(result)


def clear_guard(record, owner_id, generation, at, observation, evidence_reference):
    _owner(record, owner_id, generation, at)
    op._text(evidence_reference, 'terminal evidence reference')
    guard = record['external_guard']
    if guard is None:
        raise ValueError('no external guard to resolve')
    decision = op.decide(guard['intent'], observation)
    if decision['action'] != 'reuse_terminal':
        raise ValueError('guard requires matching confirmed terminal provider evidence')
    result = copy.deepcopy(record)
    result['last_terminal'] = {'operation_key':guard['operation_key'], 'intent_digest':guard['intent_digest'],
                               'intent_reference':guard['intent_reference'], 'observation':copy.deepcopy(observation),
                               'evidence_reference':evidence_reference, 'at_utc':at}
    result['external_guard'] = None
    return validate(result)


def check_record(record, owner_id, generation, at, *, action, intent_digest=None, heartbeat_freshness=600):
    _owner(record, owner_id, generation, at)
    if action not in {'product_write', 'external_start', 'observe'}:
        raise ValueError('unknown ownership action')
    if action == 'observe':
        return {'action':action, 'generation':generation, 'owner_id':owner_id}
    now = op._timestamp(at, 'at')
    if type(heartbeat_freshness) is not int or heartbeat_freshness <= 0:
        raise ValueError('heartbeat_freshness must be positive seconds')
    if (now >= op._timestamp(record['expires_at_utc'], 'expiry') or
            now - op._timestamp(record['heartbeat_at_utc'], 'heartbeat') >= timedelta(seconds=heartbeat_freshness)):
        raise ValueError('ownership is not fresh; observable owner activity required')
    guard = record['external_guard']
    if action == 'product_write' and guard is not None:
        raise ValueError('unresolved external guard blocks product writes')
    if action == 'external_start' and (guard is None or guard['submission_claim'] is not None or guard['intent']['state'] != 'submitting' or guard['intent_digest'] != intent_digest):
        raise ValueError('external start requires the exact durably guarded submitting intent')
    return {'action':action, 'generation':generation, 'owner_id':owner_id}


def check(store, expected_revision, repository, source_ref, owner_id, generation, at, **kwargs):
    revision, record = store.read()
    if revision != expected_revision or record is None:
        raise ValueError('stale coordination store revision')
    if record['repository'] != repository or record['source_ref'] != source_ref:
        raise ValueError('exact repository/source-ref binding mismatch')
    result = check_record(record, owner_id, generation, at, **kwargs)
    return dict(result, revision=revision, repository=repository, source_ref=source_ref)


def claim_submission(store, expected_revision, repository, source_ref, owner_id, generation, at,
                     *, intent_digest, heartbeat_freshness=600):
    """Consume one launch boundary. Only this fresh successful CAS returns a grant.

    A stored claim is recovery state, never permission to reconstruct a grant.
    Lost CAS responses must reconcile; this is not provider-side exactly-once.
    """
    revision, record = store.read()
    if revision != expected_revision or record is None:
        raise ValueError('stale coordination store revision')
    if record['repository'] != repository or record['source_ref'] != source_ref:
        raise ValueError('exact repository/source-ref binding mismatch')
    check_record(record, owner_id, generation, at, action='external_start',
                 intent_digest=intent_digest, heartbeat_freshness=heartbeat_freshness)
    guard = record['external_guard']
    grant = {'grant_id':str(uuid.uuid4()), 'owner_id':owner_id, 'generation':generation,
             'operation_key':guard['operation_key'], 'attempt_id':guard['intent']['attempt_id'],
             'intent_digest':intent_digest, 'claimed_at_utc':at}
    record['external_guard']['submission_claim'] = grant
    record['submission_claims'].append(copy.deepcopy(grant))
    revision = store.compare_and_swap(expected_revision, record)
    return {'revision':revision, 'grant':copy.deepcopy(grant)}


def check_designated_executor(config, owner_id):
    """Policy fallback only: this neither acquires nor proves exclusive ownership."""
    _uuid(owner_id)
    if config.get('backend') != 'single_writer' or config.get('designated_executor_id') != owner_id:
        raise ValueError('observer-only: executor is not explicitly designated')
    op._text(config.get('assignment_ref'), 'verified single-writer assignment reference')
    return {'owner_id':owner_id, 'assignment_ref':config['assignment_ref'], 'conditional_storage':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['read', 'init', 'acquire', 'renew', 'release', 'guard', 'check', 'claim-submission'])
    parser.add_argument('--repo', required=True)
    parser.add_argument('--remote', required=True)
    parser.add_argument('--coordination-ref', required=True)
    parser.add_argument('--request', help='JSON command arguments; expected_revision required for mutations/check')
    args = parser.parse_args(argv)
    try:
        from git_lease_store import GitLeaseStore
        store = GitLeaseStore(args.repo, args.remote, args.coordination_ref)
        request = op._load(args.request) if args.request else {}
        if args.command == 'read':
            revision, record = store.read()
        else:
            expected = request.pop('expected_revision')
            repository, source_ref = request.pop('repository'), request.pop('source_ref')
            if args.command in {'check', 'claim-submission'}:
                function = check if args.command == 'check' else claim_submission
                print(json.dumps(function(store, expected, repository, source_ref, **request), sort_keys=True))
                return 0
            revision, record = store.read()
            if revision != expected:
                raise ValueError('stale expected revision')
            if args.command == 'init':
                if record is not None or request:
                    raise ValueError('initialization requires absent store and no extra arguments')
                record = initialize(repository, source_ref)
            else:
                if record is None or record['repository'] != repository or record['source_ref'] != source_ref:
                    raise ValueError('exact repository/source-ref binding mismatch')
                if args.command == 'acquire':
                    if 'owner_id' in request:
                        raise ValueError('CLI acquisition generates a new executor UUID')
                    request['owner_id'] = str(uuid.uuid4())
                command = args.command
                if command == 'guard':
                    command = 'clear_guard' if 'observation' in request else 'set_guard'
                record = globals()[command](record, **request)
            revision = store.compare_and_swap(expected, record)
        print(json.dumps({'revision':revision, 'record':record}, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f'execution lease: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
