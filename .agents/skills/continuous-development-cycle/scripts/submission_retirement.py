#!/usr/bin/env python3
"""Owner disposition of UNKNOWN isolated create-only Git effects; never replay.

The controller must authenticate and persist/read back the referenced owner,
caller and physical-runtime evidence before calling. Parsing is not authority.
This administrative transition supplies no provider outcome or launch authority.
"""
from __future__ import annotations
import copy
import re
import operation_intent as op
import execution_lease_v2 as lease
from submission_recovery import _reference, _fresh, SHA

PILOT = re.compile(r'^refs/heads/pilot/[A-Za-z0-9][A-Za-z0-9._/-]*$')

def _validate_proof(proof, guard, repository, source_ref, release, at):
    op._object(proof, {'schema','lease_revision','lease_digest','guard_digest','repository',
        'source_ref','observed_at_utc','owner_decision','effect','runtime'}, 'retirement proof')
    if proof['schema'] != 'unknown-submission-retirement/v1':
        raise ValueError('unsupported retirement proof')
    if not isinstance(proof['lease_revision'],str) or not SHA.fullmatch(proof['lease_revision']):
        raise ValueError('immutable current lease revision required')
    op._digest(proof['lease_digest'],'retirement lease digest')
    if (proof['guard_digest'] != op._hash(guard) or proof['repository'] != repository
            or proof['source_ref'] != source_ref):
        raise ValueError('retirement must bind exact guard and repository/source')
    claim=guard['submission_claim']; intent=guard['intent']
    if (claim is None or intent['state'] not in {'submitting','unknown'} or intent['task'] is not None
            or release is None or release['owner_id'] != claim['owner_id']
            or release['generation'] != claim['generation'] or not release['invocation_id']
            or release['external_reconciliation'] != 'unknown_preserved'):
        raise ValueError('exact released UNKNOWN claim required; accepted/taskful operations unsupported')
    released=op._timestamp(release['at_utc'],'release time')
    claimed=op._timestamp(claim['claimed_at_utc'],'claim time')
    if claimed > released:
        raise ValueError('release cannot precede original claim')
    _fresh(proof['observed_at_utc'],at,released)
    decision=proof['owner_decision']
    op._object(decision,{'action','reference'},'owner decision')
    if decision['action'] != 'retire_unknown_without_replay':
        raise ValueError('explicit owner UNKNOWN retirement decision required')
    _reference(decision['reference'])
    effect=proof['effect']
    op._object(effect,{'backend','target_ref','candidate_sha','expected_target','receive_pack_calls',
        'subprocess_returned','caller_reference','caller_digest','observation_reference'},'original effect')
    target=effect['target_ref']
    if (effect['backend'] != 'git-conditional-create' or intent['binding']['backend'] != effect['backend']
            or effect['candidate_sha'] != intent['binding']['candidate_sha']
            or not isinstance(target,str) or not PILOT.fullmatch(target)
            or any(x in target for x in ('..','//','@{')) or target.endswith(('/','.','.lock'))
            or any(x.endswith('.lock') or x.startswith('.') for x in target.split('/'))
            or target == source_ref or effect['expected_target'] is not None
            or type(effect['receive_pack_calls']) is not int or effect['receive_pack_calls'] != 1
            or effect['subprocess_returned'] is not True):
        raise ValueError('only original returned single create-only isolated pilot Git push supported')
    for name in ('caller_reference','observation_reference'): _reference(effect[name])
    op._digest(effect['caller_digest'],'original caller digest')
    runtime=proof['runtime']
    op._object(runtime,{'invocation_id','owner_id','generation','status','quiescent',
        'pending_shared_writes','observed_at_utc','reference'},'stopped original runtime')
    if (runtime['invocation_id'] != release['invocation_id'] or runtime['owner_id'] != claim['owner_id']
            or type(runtime['generation']) is not int or runtime['generation'] != claim['generation']
            or runtime['status'] != 'stopped' or runtime['quiescent'] is not True
            or runtime['pending_shared_writes'] is not False):
        raise ValueError('exact original physically stopped/quiescent runtime required')
    _fresh(runtime['observed_at_utc'],at,released); _reference(runtime['reference'])

def validate_retirement(entry, record):
    """Validate immutable history independently of the current generation/clock."""
    op._object(entry,{'schema','outcome','replay_forbidden','guard','original_release','proof',
        'evidence_reference','retired_at_utc'},'submission retirement')
    if (entry['schema'] != 'submission-retirement/v1' or entry['outcome'] != 'UNKNOWN'
            or entry['replay_forbidden'] is not True):
        raise ValueError('retirement must preserve UNKNOWN and permanent no replay')
    at=entry['retired_at_utc']; op._timestamp(at,'retirement time'); _reference(entry['evidence_reference'])
    # Reuse the original strict legacy guard validator without recursing into v2.
    projected=lease._legacy_projection(record,sanitize_migrated=True)
    projected['external_guard']=copy.deepcopy(entry['guard'])
    lease.legacy.validate(projected)
    lease._validate_release(entry['original_release'],record['generation'])
    _validate_proof(entry['proof'],entry['guard'],record['repository'],record['source_ref'],entry['original_release'],at)
    return entry

def _forbids_intent(entry,intent):
    old=entry['guard']['intent']; binding=intent['binding']; old_binding=old['binding']
    # Changing attempt, mode, environment, key or backend cannot disguise the
    # same retired candidate. Distinct source upgrade candidates remain eligible.
    return (intent['operation_key']==old['operation_key']
            or (binding['repository']==old_binding['repository']
                and binding['candidate_sha']==old_binding['candidate_sha']))

def retire_unknown_guard(record, proof, evidence_reference, at):
    """Pure transition; no ownership, provider terminal fact or budget refund."""
    lease.validate(record); _reference(evidence_reference)
    if (record.get('schema') != 'execution-lease/v2' or record['owner_id'] is not None
            or record['invocation'] is not None or record['finalization'] is not None
            or record['external_guard'] is None):
        raise ValueError('retirement requires a released v2 guarded lease')
    guard=record['external_guard']; claim=guard['submission_claim']
    if claim is None or claim['generation'] != record['generation']:
        raise ValueError('retirement must bind original released generation')
    if claim['grant_id'] in lease._resolved_grant_ids(record):
        raise ValueError('terminal-resolved claims cannot be retired')
    if proof.get('lease_digest') != op._hash(record):
        raise ValueError('retirement proof must bind exact current lease digest')
    _validate_proof(proof,guard,record['repository'],record['source_ref'],record['last_release'],at)
    result=copy.deepcopy(record)
    result['external_guard']=None
    result.setdefault('submission_retirements',[]).append(dict(schema='submission-retirement/v1',
        outcome='UNKNOWN',replay_forbidden=True,guard=copy.deepcopy(guard),
        original_release=copy.deepcopy(record['last_release']),proof=copy.deepcopy(proof),
        evidence_reference=evidence_reference,retired_at_utc=at))
    return lease.validate(result)

def retire_unknown_cas(store, expected_revision, proof, evidence_reference, at):
    """One conditional coordination write and independent readback; no replay."""
    revision,previous=store.read()
    if revision != expected_revision or proof.get('lease_revision') != expected_revision:
        raise ValueError('stale retirement revision; re-observe without replay')
    result=retire_unknown_guard(previous,proof,evidence_reference,at)
    revision=store.compare_and_swap(expected_revision,result)
    observed_revision,observed=store.read()
    if observed_revision != revision or observed != result:
        raise ValueError('retirement readback changed; re-observe without replay')
    return dict(revision=revision,record=result,outcome='UNKNOWN',authorizes_submission=False,
        authorizes_takeover=False,authorizes_merge=False,authorizes_release=False)
