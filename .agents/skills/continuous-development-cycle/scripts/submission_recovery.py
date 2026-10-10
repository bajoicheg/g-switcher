#!/usr/bin/env python3
"""Resolve positively proved taskless outcomes on an explicitly released lease.

Proofs must come from authenticated provider/dispatcher observations, persisted
and read back before this call. Validation does not authenticate their producer.
This path grants no ownership, submission, replay, merge or release authority.
"""
from __future__ import annotations
import copy
import re
import execution_lease_v2 as lease
import operation_intent as op

SHA = re.compile(r'^[0-9a-f]{40}$')
REF = re.compile(r'^(?:git:[0-9a-f]{40}|sha256:[0-9a-f]{64})$')
MAX_AGE_SECONDS = 300

def _reference(value):
    if not isinstance(value, str) or not REF.fullmatch(value):
        raise ValueError('immutable recovery evidence reference required')

def _fresh(value, at, floor):
    observed = op._timestamp(value, 'recovery observation')
    current = op._timestamp(at, 'recovery time')
    if observed < floor or not 0 <= (current - observed).total_seconds() <= MAX_AGE_SECONDS:
        raise ValueError('recovery observation is stale, future or predates release')

def resolve_released_guard(record, proof, evidence_reference, at):
    """Pure canonical transition; only three coordination fields can change."""
    lease.validate(record)
    op._timestamp(at, 'recovery time')
    _reference(evidence_reference)
    if record.get('schema') != 'execution-lease/v2' or record['owner_id'] is not None:
        raise ValueError('taskless recovery requires an explicitly released v2 lease')
    if record['invocation'] is not None or record['finalization'] is not None:
        raise ValueError('released recovery cannot retain a live executor')
    guard = record['external_guard']
    if guard is None or guard['submission_claim'] is None:
        raise ValueError('exact unresolved guarded submission required')
    intent = guard['intent']; claim = guard['submission_claim']; release = record['last_release']
    if intent['state'] != 'submitting' or intent['task'] is not None:
        raise ValueError('accepted, taskful or unknown operation requires provider reconciliation')
    if release is None or not release['invocation_id']:
        raise ValueError('exact released invocation required')
    if (release['generation'] != record['generation'] or claim['generation'] != record['generation']
            or release['owner_id'] != claim['owner_id'] or claim['intent_digest'] != guard['intent_digest']
            or claim['grant_id'] in lease._resolved_grant_ids(record)):
        raise ValueError('released generation, owner or claim binding mismatch')
    fields = {'schema', 'lease_revision', 'lease_digest', 'claim', 'repository', 'source_ref',
              'observed_at_utc', 'provider_observation', 'provider_reference', 'runtime', 'dispatch', 'dispatcher'}
    op._object(proof, fields, 'taskless recovery proof')
    if proof['schema'] != 'taskless-submission-proof/v1':
        raise ValueError('unsupported taskless proof schema')
    if not isinstance(proof['lease_revision'], str) or not SHA.fullmatch(proof['lease_revision']):
        raise ValueError('exact immutable lease revision required')
    if proof['lease_digest'] != op._hash(record) or op._hash(proof['claim']) != op._hash(claim):
        raise ValueError('proof must bind exact current lease and original claim')
    if any(proof[k] != record[k] for k in ('repository', 'source_ref')):
        raise ValueError('recovery repository/source mismatch')
    released = op._timestamp(release['at_utc'], 'release time')
    _fresh(proof['observed_at_utc'], at, released)
    observation = proof['provider_observation']
    decision = op.decide(intent, observation)
    if (observation['lookup_complete'] is not True or observation['tasks'] != []
            or decision['action'] != 'reconcile' or decision['operation_key'] != claim['operation_key']):
        raise ValueError('fresh complete exact provider absence required; tasks are never invented')
    _fresh(observation['observed_at_utc'], at, released)
    _reference(proof['provider_reference'])
    runtime = proof['runtime']
    op._object(runtime, {'invocation_id', 'owner_id', 'generation', 'status', 'quiescent',
                         'pending_shared_writes', 'observed_at_utc', 'reference'}, 'runtime evidence')
    if (runtime['invocation_id'] != release['invocation_id'] or runtime['owner_id'] != claim['owner_id']
            or type(runtime['generation']) is not int or runtime['generation'] != claim['generation'] or runtime['status'] != 'stopped'
            or runtime['quiescent'] is not True or runtime['pending_shared_writes'] is not False):
        raise ValueError('exact independently stopped and quiescent runtime required')
    _fresh(runtime['observed_at_utc'], at, released); _reference(runtime['reference'])
    dispatch = proof['dispatch']
    op._object(dispatch, {'outcome', 'grant_id', 'claim_digest', 'intent_digest', 'dispatcher_id',
                          'in_flight', 'terminal_at_utc', 'method', 'target', 'candidate_sha',
                          'http_status', 'barrier_state', 'reference'}, 'dispatch evidence')
    if (dispatch['grant_id'] != claim['grant_id'] or dispatch['claim_digest'] != op._hash(claim)
            or dispatch['intent_digest'] != guard['intent_digest'] or dispatch['in_flight'] is not False
            or dispatch['candidate_sha'] != intent['binding']['candidate_sha']):
        raise ValueError('exact non-in-flight dispatch/claim binding required')
    op._text(dispatch['dispatcher_id'], 'dispatcher identity'); _reference(dispatch['reference'])
    terminal = op._timestamp(dispatch['terminal_at_utc'], 'dispatch terminal time')
    if not op._timestamp(claim['claimed_at_utc'], 'claim time') <= terminal <= released:
        raise ValueError('dispatch outcome must follow claim and precede release')
    prefix = 'repos/' + record['repository'] + '/pulls'
    if (intent['binding']['mode'] == 'PR_VALIDATION'
            or (intent['binding']['mode'] == 'required_pr_validation'
                and intent['binding']['backend'] == 'github_create_pull_request'
                and dispatch['outcome'] == 'not_submitted'
                and dispatch['barrier_state'] == 'cancelled_before_send')):
        target_ok = dispatch['method'] == 'POST' and dispatch['target'] == prefix
    elif intent['binding']['mode'] == 'MERGE_VALIDATION':
        target_ok = (dispatch['method'] == 'PUT' and isinstance(dispatch['target'], str)
                     and re.fullmatch(re.escape(prefix) + r'/[1-9][0-9]*/merge', dispatch['target']) is not None)
    elif (intent['binding']['mode'] == 'COMPUTE_ONLY'
            and intent['binding']['backend'] == 'codex_cloud_cli'):
        # Bind every immutable execution field, not a mutable environment label.
        target_ok = (dispatch['method'] == 'EXEC'
                     and dispatch['target'] == 'codex-cloud-cli:' + op._canonical(intent['binding']).decode('utf-8')
                     and dispatch['outcome'] == 'not_submitted')
    else:
        target_ok = False
    if not target_ok:
        raise ValueError('dispatch target/method does not match exact supported operation')
    if dispatch['outcome'] == 'rejected':
        if type(dispatch['http_status']) is not int or dispatch['http_status'] != 403 or dispatch['barrier_state'] is not None:
            raise ValueError('only positively observed pre-acceptance GitHub 403 is supported')
    elif dispatch['outcome'] == 'not_submitted':
        if dispatch['http_status'] is not None or dispatch['barrier_state'] != 'cancelled_before_send':
            raise ValueError('immutable cancellation-before-send barrier required')
    else:
        raise ValueError('unknown/lost/accepted dispatch result must retain guard')
    dispatcher = proof['dispatcher']
    op._object(dispatcher, {'dispatcher_id', 'status', 'quiescent', 'observed_at_utc', 'reference'}, 'dispatcher evidence')
    if (dispatcher['dispatcher_id'] != dispatch['dispatcher_id'] or dispatcher['status'] != 'stopped'
            or dispatcher['quiescent'] is not True):
        raise ValueError('parent dispatcher must independently be stopped and quiescent')
    _fresh(dispatcher['observed_at_utc'], at, released); _reference(dispatcher['reference'])
    result = copy.deepcopy(record)
    result['external_guard'] = None
    result['last_terminal'] = {'operation_key': guard['operation_key'], 'intent_digest': guard['intent_digest'],
                               'intent_reference': guard['intent_reference'], 'observation': copy.deepcopy(proof),
                               'evidence_reference': evidence_reference, 'at_utc': at}
    result.setdefault('submission_resolutions', []).append({
        'grant_id': claim['grant_id'], 'owner_id': claim['owner_id'], 'generation': claim['generation'],
        'operation_key': claim['operation_key'], 'attempt_id': claim['attempt_id'], 'intent_digest': claim['intent_digest'],
        'resolved_at_utc': at, 'evidence_reference': evidence_reference, 'observation_digest': op._hash(proof)})
    return lease.validate(result)

def reconcile_submission_cas(store, expected_revision, proof, evidence_reference, at):
    """Consume one exact evidence-bound transition, then read its result back.

    A lost reply is observed through the store; it never authorizes a second CAS
    or provider submission. This helper calls no provider.
    """
    revision, previous = store.read()
    if revision != expected_revision or proof.get('lease_revision') != expected_revision:
        raise ValueError('stale lease revision; re-observe without replay')
    result = resolve_released_guard(previous, proof, evidence_reference, at)
    revision = store.compare_and_swap(expected_revision, result)
    observed_revision, observed = store.read()
    if observed_revision != revision or observed != result:
        raise ValueError('recovery CAS readback changed; reconcile without replay')
    return {'revision': revision, 'record': result, 'authorizes_submission': False,
            'authorizes_takeover': False, 'authorizes_merge': False, 'authorizes_release': False}
