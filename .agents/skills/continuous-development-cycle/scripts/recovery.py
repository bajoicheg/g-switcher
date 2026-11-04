#!/usr/bin/env python3
"""Pure bounded-wait and minimal-context recommendations; never authorize effects."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys

PHASES = {'unknown', 'queued', 'setup', 'running', 'terminal'}
RANK = {'unknown': -1, 'queued': 0, 'setup': 1, 'running': 2, 'terminal': 3}
WAIT_POLICY_FIELDS = {'queued_seconds', 'setup_seconds', 'running_seconds', 'unknown_seconds',
                      'observation_max_age_seconds', 'poll_initial_seconds', 'poll_cap_seconds'}
IDENTITY = {'operation_key', 'attempt_id', 'task_id', 'candidate_sha'}
OBSERVATION_FIELDS = IDENTITY | {'schema', 'phase', 'observed_at_utc', 'source', 'source_valid',
                                'observation_valid', 'lookup_complete', 'conclusion',
                                'evidence_refs', 'retry_after_seconds'}
STATE_FIELDS = IDENTITY | {'schema', 'phase', 'phase_started_at_utc', 'last_successful_observation',
                          'last_poll_at_utc', 'observation_valid', 'source_valid',
                          'unchanged_polls', 'error_polls'}
BINDING_FIELDS = {'repository', 'default_branch', 'working_branch', 'head_sha', 'policy_revision',
                  'policy_digest', 'skill_version', 'instructions', 'task_state_fingerprint',
                  'checkpoint_version', 'checkpoint_digest', 'lease_owner', 'lease_generation',
                  'lease_store_revision', 'external_operations', 'pr_revision', 'ci_revision',
                  'release_revision'}
CORE_READS = ['SKILL.md', 'VERSION', 'AGENTS.md', 'docs/development-cycle.yaml', 'docs/work-status/current.md']
PHASE_READS = {
    'waiting_external': ['references/bounded-recovery.md', 'references/external-operations.md'],
    'recovery': ['references/bounded-recovery.md', 'references/watchdog-recovery-and-migration.md'],
    'red': ['references/task-lifecycle.md', 'references/command-evidence.md'],
    'implementation': ['references/task-lifecycle.md'],
    'validation': ['references/command-evidence.md', 'references/validation-compute-and-ci.md'],
    'final_gate': ['references/command-evidence.md', 'references/validation-compute-and-ci.md',
                   'references/release-management.md'],
    'blocked': ['references/bounded-recovery.md', 'references/watchdog-recovery-and-migration.md',
                'references/budget-ledger.md'],
    'review': ['references/task-lifecycle.md'],
    'release': ['references/release-management.md'],
    'complete': ['references/release-management.md'],
}


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f'{label} must contain exactly {sorted(fields)}')


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label} must be nonempty text')


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum or value > 2**53 - 1:
        raise ValueError(f'{label} must be an integer from {minimum} through 2**53-1')


def _bool(value, label):
    if type(value) is not bool:
        raise ValueError(f'{label} must be boolean')


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value):
        raise ValueError('timestamp must be UTC ending in Z')
    return datetime.fromisoformat(value[:-1] + '+00:00')


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
        raise ValueError('digest must be sha256: plus 64 lowercase hex characters')


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value):
        raise ValueError('candidate must be a full lowercase Git SHA')


def validate_wait_policy(policy):
    _object(policy, WAIT_POLICY_FIELDS, 'wait policy')
    for field in WAIT_POLICY_FIELDS:
        _integer(policy[field], field, 1)
    if policy['poll_initial_seconds'] > policy['poll_cap_seconds']:
        raise ValueError('poll_initial_seconds exceeds poll_cap_seconds')
    return policy


def _identity(value):
    _digest(value['operation_key'])
    _sha(value['candidate_sha'])
    _text(value['attempt_id'], 'attempt_id')
    if value['task_id'] is not None:
        _text(value['task_id'], 'task_id')


def _observation(value):
    _object(value, OBSERVATION_FIELDS, 'observation')
    _identity(value)
    if value['schema'] != 'wait-observation/v1' or value['phase'] not in PHASES:
        raise ValueError('invalid observation schema or phase')
    _time(value['observed_at_utc'])
    _text(value['source'], 'source')
    for field in ('source_valid', 'observation_valid', 'lookup_complete'):
        _bool(value[field], field)
    if value['retry_after_seconds'] is not None:
        _integer(value['retry_after_seconds'], 'retry_after_seconds')
    if not isinstance(value['evidence_refs'], list) or len(value['evidence_refs']) > 256:
        raise ValueError('evidence_refs must be a bounded list')
    for ref in value['evidence_refs']:
        _text(ref, 'evidence ref')
    if value['phase'] == 'terminal':
        if value['conclusion'] not in {'succeeded', 'failed', 'cancelled', 'timed_out', 'setup_failed'}:
            raise ValueError('terminal requires provider conclusion')
    elif value['conclusion'] is not None:
        raise ValueError('nonterminal cannot have conclusion')


def validate_wait_state(state):
    optional = {'trusted_retry_after'} if isinstance(state, dict) and 'trusted_retry_after' in state else set()
    _object(state, STATE_FIELDS | optional, 'wait state')
    _identity(state)
    if state['schema'] != 'external-wait/v1' or state['phase'] not in PHASES:
        raise ValueError('invalid wait schema or phase')
    if state['phase'] != 'unknown' and state['task_id'] is None:
        raise ValueError('known provider phase requires exact task identity; reconcile as unknown')
    started = _time(state['phase_started_at_utc'])
    for field in ('unchanged_polls', 'error_polls'):
        _integer(state[field], field)
    for field in ('source_valid', 'observation_valid'):
        _bool(state[field], field)
    last_poll = _time(state['last_poll_at_utc']) if state['last_poll_at_utc'] else None
    if last_poll and last_poll < started:
        raise ValueError('last poll predates phase start')
    retry = state.get('trusted_retry_after')
    if retry is not None:
        _object(retry, {'source', 'observed_at_utc', 'retry_after_seconds'}, 'trusted retry timing')
        _text(retry['source'], 'retry source')
        _integer(retry['retry_after_seconds'], 'retry_after_seconds')
        if not last_poll or _time(retry['observed_at_utc']) > last_poll:
            raise ValueError('retry timing is newer than the last poll')
    prior = state['last_successful_observation']
    if prior is not None:
        _observation(prior)
        if not all(prior[f] == state[f] for f in IDENTITY | {'phase'}):
            raise ValueError('last successful observation contradicts wait binding')
        if not all(prior[f] for f in ('source_valid', 'observation_valid', 'lookup_complete')):
            raise ValueError('last successful observation was not valid')
        if not last_poll or not started <= _time(prior['observed_at_utc']) <= last_poll:
            raise ValueError('last successful observation timestamp contradicts state')
    return state


def supervise_wait(state, observation, policy, now):
    """Consume one attempted poll. Caller enforces per-wake budget and persistence."""
    validate_wait_policy(policy)
    validate_wait_state(state)
    current = _time(now)
    if current < _time(state['phase_started_at_utc']) or (state['last_poll_at_utc'] and current < _time(state['last_poll_at_utc'])):
        raise ValueError('backward poll timestamp')
    result = copy.deepcopy(state)
    result.update(last_poll_at_utc=now, observation_valid=False, source_valid=False)
    result.setdefault('trusted_retry_after', None)
    reasons = []
    valid = False
    prior = state['last_successful_observation']
    if observation is None:
        reasons.append('poll unavailable or timed out; provider outcome remains unknown')
    else:
        try:
            _observation(observation)
            observed = _time(observation['observed_at_utc'])
            if not 0 <= (current - observed).total_seconds() <= policy['observation_max_age_seconds']:
                raise ValueError('stale or future observation')
            if observed < _time(state['phase_started_at_utc']):
                raise ValueError('observation predates current phase')
            if any(observation[f] != state[f] for f in IDENTITY - {'task_id'}):
                raise ValueError('observation binding mismatch')
            if not observation['source_valid']:
                raise ValueError('untrusted observation source')
            if state['task_id'] is not None and observation['task_id'] not in (None, state['task_id']):
                raise ValueError('task identity mismatch')
            result['source_valid'] = True
            if observation['retry_after_seconds'] is not None:
                retry = {key: observation[key] for key in ('source', 'observed_at_utc', 'retry_after_seconds')}
                existing = result['trusted_retry_after']
                deadline = observed.timestamp() + retry['retry_after_seconds']
                if existing is None or deadline > _time(existing['observed_at_utc']).timestamp() + existing['retry_after_seconds']:
                    result['trusted_retry_after'] = retry
            if not observation['observation_valid'] or not observation['lookup_complete']:
                raise ValueError('incomplete or invalid task observation; trusted retry timing retained')
            if state['task_id'] is not None and observation['task_id'] != state['task_id']:
                raise ValueError('task identity mismatch')
            if observation['phase'] != 'unknown' and observation['task_id'] is None:
                raise ValueError('known provider phase requires exact task identity')
            if RANK[observation['phase']] < RANK[state['phase']]:
                raise ValueError('backward phase observation')
            if prior:
                if observed < _time(prior['observed_at_utc']):
                    raise ValueError('backward observation timestamp')
                if observed == _time(prior['observed_at_utc']) and observation != prior:
                    raise ValueError('contradictory observations at the same timestamp')
                if state['phase'] == 'terminal' and observation['conclusion'] != prior['conclusion']:
                    raise ValueError('contradictory terminal conclusion')
            valid = True
        except (ValueError, TypeError) as exc:
            reasons.append(str(exc))
    if valid:
        changed = observation['phase'] != state['phase']
        result.update(phase=observation['phase'], task_id=observation['task_id'],
                      last_successful_observation=copy.deepcopy(observation),
                      observation_valid=True, source_valid=True, error_polls=0,
                      unchanged_polls=0 if changed else min(state['unchanged_polls'] + 1, 2**53 - 1))
        if changed:
            result['phase_started_at_utc'] = observation['observed_at_utc']
    else:
        result['error_polls'] = min(state['error_polls'] + 1, 2**53 - 1)
        result['unchanged_polls'] = 0
    exponent = min(max(result['unchanged_polls'], result['error_polls']), 53)
    delay = min(policy['poll_cap_seconds'], policy['poll_initial_seconds'] * 2**exponent)
    # Accept authenticated transport timing independently of task-state validity.
    # Retain legacy successful-observation timing when upgrading an older v1 record.
    for timing in (result['trusted_retry_after'], result['last_successful_observation']):
        if timing and timing['retry_after_seconds'] is not None:
            remaining = timing['retry_after_seconds'] - (current - _time(timing['observed_at_utc'])).total_seconds()
            delay = max(delay, math.ceil(remaining))
    action = 'observe' if valid and result['phase'] != 'unknown' else 'reconcile'
    guarded = True
    if valid and result['phase'] == 'terminal':
        if observation['evidence_refs']:
            action, guarded, delay = 'reuse_terminal', False, None
            reasons.append('trusted provider terminal; exact candidate evidence still requires validation')
        else:
            action = 'reconcile'
            reasons.append('terminal observation lacks evidence references')
    elif result['phase'] != 'terminal':
        elapsed = (current - _time(result['phase_started_at_utc'])).total_seconds()
        if elapsed >= policy[result['phase'] + '_seconds']:
            reasons.append('phase diagnostic threshold reached; retain guard and inspect provider evidence')
            if valid and result['phase'] != 'unknown':
                action = 'diagnose'
    return dict(state=result, action=action, reasons=reasons, next_poll_seconds=delay,
                external_guard=guarded, allow_submission=False, completion_claim_allowed=False)


def _bindings(value):
    _object(value, BINDING_FIELDS, 'recovery bindings')
    for field in ('repository', 'default_branch', 'working_branch', 'policy_revision', 'skill_version',
                  'lease_store_revision', 'pr_revision', 'ci_revision', 'release_revision'):
        _text(value[field], field)
    if not re.fullmatch(r'\d+\.\d+\.\d+', value['skill_version']):
        raise ValueError('skill_version must be an exact semantic version')
    _sha(value['head_sha'])
    for field in ('policy_digest', 'task_state_fingerprint', 'checkpoint_digest'):
        _digest(value[field])
    _integer(value['checkpoint_version'], 'checkpoint_version', 1)
    _integer(value['lease_generation'], 'lease_generation')
    if value['lease_owner'] is not None:
        _text(value['lease_owner'], 'lease_owner')
    instructions = value['instructions']
    if not isinstance(instructions, list) or not 1 <= len(instructions) <= 256:
        raise ValueError('instructions must be a nonempty bounded manifest')
    paths = set()
    for entry in instructions:
        _object(entry, {'path', 'kind', 'digest', 'durable_verified'}, 'instruction entry')
        _text(entry['path'], 'instruction path')
        if entry['kind'] not in {'instruction', 'specification', 'task_list', 'log'}:
            raise ValueError('unsupported instruction manifest kind')
        _digest(entry['digest'])
        if entry['durable_verified'] is not True:
            raise ValueError('instruction hash lacks durable verification')
        if entry['path'] in paths:
            raise ValueError('duplicate instruction path')
        paths.add(entry['path'])
    operations = value['external_operations']
    if not isinstance(operations, list) or len(operations) > 256:
        raise ValueError('external_operations must be a complete bounded list')
    identities = set()
    for entry in operations:
        _object(entry, {'operation_key', 'attempt_id', 'task_id', 'state', 'revision'}, 'external operation')
        _digest(entry['operation_key'])
        for field in ('attempt_id', 'revision'):
            _text(entry[field], field)
        if entry['task_id'] is not None:
            _text(entry['task_id'], 'task_id')
        if entry['state'] not in PHASES | {'prepared', 'submitting', 'accepted'}:
            raise ValueError('invalid external operation state')
        identity = (entry['operation_key'], entry['attempt_id'])
        if identity in identities:
            raise ValueError('duplicate external operation')
        identities.add(identity)


def decide_recovery(snapshot, live_probe, now, max_age_seconds=300):
    """Recommend context reads only; caller must collect/authenticate live facts."""
    current = _time(now)
    _integer(max_age_seconds, 'max_age_seconds', 1)
    reasons = []
    phase = snapshot.get('phase') if isinstance(snapshot, dict) else None
    try:
        _object(snapshot, {'schema', 'observed_at_utc', 'phase', 'bindings'}, 'snapshot')
        if snapshot['schema'] != 'recovery-snapshot/v1' or phase not in PHASE_READS:
            raise ValueError('unsupported snapshot schema or phase')
        _bindings(snapshot['bindings'])
        snap_at = _time(snapshot['observed_at_utc'])
        if not 0 <= (current - snap_at).total_seconds() <= max_age_seconds:
            raise ValueError('snapshot stale or future')
        _object(live_probe, {'schema', 'observed_at_utc', 'complete', 'source_valid', 'phase', 'bindings'}, 'live probe')
        if live_probe['schema'] != 'recovery-probe/v1' or live_probe['complete'] is not True or live_probe['source_valid'] is not True:
            raise ValueError('live probe is incomplete or untrusted')
        probe_at = _time(live_probe['observed_at_utc'])
        if probe_at < snap_at or not 0 <= (current - probe_at).total_seconds() <= max_age_seconds:
            raise ValueError('live probe stale, backward or future')
        _bindings(live_probe['bindings'])
        for field in sorted(BINDING_FIELDS):
            if snapshot['bindings'][field] != live_probe['bindings'][field]:
                reasons.append(f'changed {field}')
        if phase != live_probe['phase']:
            reasons.append('changed phase')
    except (ValueError, TypeError) as exc:
        reasons.append(str(exc))
    fast = not reasons
    reads = list(CORE_READS)
    # Instructions always load anew; only unchanged long specs/logs are skippable.
    for source in (snapshot, live_probe):
        if isinstance(source, dict) and isinstance(source.get('bindings'), dict):
            entries = source['bindings'].get('instructions', [])
            if isinstance(entries, list):
                for entry in entries[:256]:
                    if isinstance(entry, dict) and isinstance(entry.get('path'), str):
                        path = entry['path']
                        if not fast or entry.get('kind') == 'instruction' or Path(path).name == 'AGENTS.md':
                            reads.append(path)
    if fast:
        reads.extend(PHASE_READS[phase])
        reasons.append('fresh complete live bindings match; reread core, adapter, current instructions and checkpoint')
    else:
        reads.extend(path for paths in PHASE_READS.values() for path in paths)
        reads.extend(['active specification and task list', 'changed instruction bodies', 'operation records and relevant logs'])
    return dict(fast_path=fast, action='read_phase_context' if fast else 'expanded_reconciliation',
                read_set=list(dict.fromkeys(reads)), reasons=reasons, allow_write=False,
                allow_submission=False, completion_claim_allowed=False)


def _load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    wait = commands.add_parser('wait')
    for field in ('state', 'policy', 'now'):
        wait.add_argument('--' + field, required=True)
    wait.add_argument('--observation', help='omit for an unsuccessful poll')
    recover = commands.add_parser('recover')
    for field in ('snapshot', 'now'):
        recover.add_argument('--' + field, required=True)
    recover.add_argument('--live-probe')
    recover.add_argument('--max-age-seconds', type=int, default=300)
    args = parser.parse_args(argv)
    try:
        if args.command == 'wait':
            result = supervise_wait(_load(args.state), _load(args.observation) if args.observation else None,
                                    _load(args.policy), args.now)
        else:
            result = decide_recovery(_load(args.snapshot), _load(args.live_probe) if args.live_probe else None,
                                     args.now, args.max_age_seconds)
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
