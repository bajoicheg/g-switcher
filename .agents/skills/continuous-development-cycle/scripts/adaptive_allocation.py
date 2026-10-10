#!/usr/bin/env python3
"""Measured allocation recommendations; existing budget and launch gates remain authoritative."""
from __future__ import annotations

import argparse
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
import sys

import execution_strategy
import operation_report

EFFORT = {'low': 0, 'medium': 1, 'high': 2, 'xhigh': 3}
MIN_SAMPLES = 2


def _fields(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(label + ' fields mismatch')


def _text(value, label):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 for c in value)):
        raise ValueError(label + ' must be nonempty unpadded text')


def _strategy(value):
    try:
        return execution_strategy.evaluate(value)
    except (TypeError, KeyError, OverflowError) as exc:
        raise ValueError('invalid strategy or prospective budget input') from exc


def evaluate(request: dict) -> dict:
    """Select from caller-authenticated compatible evidence without consuming reservations."""
    _fields(request, ('schema', 'comparison_group', 'strategy', 'default_profile_id',
                      'profiles', 'observations'), 'allocation')
    if request['schema'] != 'adaptive-allocation/v1':
        raise ValueError('allocation schema mismatch')
    _text(request['comparison_group'], 'comparison_group')
    baseline = _strategy(request['strategy'])
    floor = 2 if any(q['effective_level'] == 'FULL'
                     for q in baseline['task_quality'].values()) else 1
    raw_profiles = request['profiles']
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError('profiles must be a nonempty list')
    profiles, strategies = {}, {}
    for profile in raw_profiles:
        _fields(profile, ('id', 'reasoning_effort', 'max_agents', 'agent_reservations'), 'profile')
        _text(profile['id'], 'profile.id')
        effort = profile['reasoning_effort']
        if not isinstance(effort, str) or effort not in EFFORT:
            raise ValueError('unsupported reasoning effort')
        if type(profile['max_agents']) is not int or profile['max_agents'] < 0:
            raise ValueError('max_agents must be a nonnegative integer')
        if profile['id'] in profiles:
            raise ValueError('duplicate profile id')
        strategy = copy.deepcopy(request['strategy'])
        strategy['agent_reservations'] = profile['agent_reservations']
        strategies[profile['id']] = _strategy(strategy)
        profiles[profile['id']] = profile
    default_id = request['default_profile_id']
    _text(default_id, 'default_profile_id')
    if default_id not in profiles or EFFORT[profiles[default_id]['reasoning_effort']] < floor:
        raise ValueError('default profile must satisfy the effective quality effort floor')
    observations = request['observations']
    if not isinstance(observations, list):
        raise ValueError('observations must be a list')
    seen, defective = set(), set()
    samples = {name: [] for name in profiles}
    for item in observations:
        _fields(item, ('profile_id', 'operation'), 'allocation observation')
        _text(item['profile_id'], 'observation.profile_id')
        if item['profile_id'] not in profiles:
            raise ValueError('observation profile is unknown')
        try:
            measured = operation_report.measure(item['operation'])
        except OverflowError as exc:
            raise ValueError('observation number exceeds finite measurement range') from exc
        reference = measured['observation_ref']
        _text(reference, 'observation_ref')
        if reference in seen:
            raise ValueError('duplicate observation reference')
        seen.add(reference)
        if measured['comparison_group'] != request['comparison_group']:
            raise ValueError('observations belong to different comparison groups')
        defects = measured['delivery']['escaped_defects']['value']
        delivered = measured['delivery']['delivered']['value']
        if defects is not None and defects > 0:
            defective.add(item['profile_id'])
        if (defects == 0 and delivered is not None and delivered > 0
                and measured['tokens']['provenance'] == 'measured'):
            samples[item['profile_id']].append(measured)
    rankings, measurements = [], {}
    for name, eligible in samples.items():
        profile = profiles[name]
        if name in defective or EFFORT[profile['reasoning_effort']] < floor or len(eligible) < MIN_SAMPLES:
            continue
        try:
            elapsed = math.fsum(item['elapsed_seconds'] for item in eligible)
        except (OverflowError, ValueError) as exc:
            raise ValueError('aggregate elapsed measurement exceeds finite range') from exc
        if not math.isfinite(elapsed):
            raise ValueError('aggregate elapsed measurement must be finite')
        tokens = sum(item['tokens']['value'] for item in eligible)
        delivered = sum(item['delivery']['delivered']['value'] for item in eligible)
        try:
            finite_totals = math.isfinite(tokens) and math.isfinite(delivered)
        except OverflowError as exc:
            raise ValueError('aggregate token or delivery measurement exceeds finite range') from exc
        if not finite_totals:
            raise ValueError('aggregate token and delivery measurements must be finite')
        cost = Fraction(tokens, delivered)
        duration = elapsed / delivered
        try:
            cost_float = float(cost)
        except OverflowError as exc:
            raise ValueError('aggregate token rate exceeds finite range') from exc
        if not math.isfinite(cost_float) or not math.isfinite(duration):
            raise ValueError('aggregate measurement rates must be finite')
        measurements[name] = {'observation_refs': [item['observation_ref'] for item in eligible],
                              'sample_count': len(eligible), 'tokens': tokens,
                              'elapsed_seconds': elapsed, 'delivered': delivered,
                              'tokens_per_delivered': cost_float,
                              'seconds_per_delivered': duration}
        rankings.append((cost, duration, EFFORT[profile['reasoning_effort']], profile['max_agents'], name))
    selected_id = min(rankings)[-1] if rankings else default_id
    selected, strategy = profiles[selected_id], strategies[selected_id]
    reasons = list(strategy['reasons'])
    action = strategy['action']
    if baseline['action'] == 'WAIT':
        action, reasons = 'WAIT', list(baseline['reasons'])
    elif not rankings and default_id in defective:
        action = 'WAIT'
        reasons.append('default profile has an observed defect; corrected safe evidence required')
    elif action == 'PARALLEL' and selected['max_agents'] < len(strategy['agent_task_ids']):
        action = 'SINGLE'
        reasons.append('selected profile agent cap cannot cover the independent task set')
    if not rankings:
        reasons.append('insufficient compatible measured samples; no measured savings claimed')
    return {'schema': 'adaptive-allocation-result/v1', 'comparison_group': request['comparison_group'],
            'profile_id': selected_id, 'reasoning_effort': selected['reasoning_effort'],
            'max_agents': selected['max_agents'], 'selection': 'measured' if rankings else 'default',
            'measurement': measurements.get(selected_id), 'excluded_profile_ids': sorted(defective),
            'action': action, 'reasons': reasons, 'integrator': 'single',
            'task_quality': strategy['task_quality'], 'batch_candidate': strategy['batch_candidate'],
            'agent_task_ids': strategy['agent_task_ids'] if action == 'PARALLEL' else [],
            'reservation_event_ids': [item['event']['event_id'] for item in selected['agent_reservations']],
            'authorizes_external_start': False, 'authorizes_product_write': False,
            'authorizes_release': False, 'authorizes_takeover': False,
            'authorizes_scheduler_mutation': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request')
    args = parser.parse_args(argv)
    try:
        from cdc import _load
        result = evaluate(_load(args.request))
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
