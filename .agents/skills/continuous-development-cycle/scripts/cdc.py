#!/usr/bin/env python3
"""One read-only CDC observation and recommendation entry point."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import resume_capsule


def _utc(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('timestamp must be UTC Z text')
    return datetime.fromisoformat(value[:-1] + '+00:00')


def resume(capsule, probe, *, now_utc=None, max_age_seconds=7200,
           max_probe_age_seconds=90):
    """Route one next action, preserving the existing capsule and authority gates.

    now_utc is an injected runtime clock for deterministic embedded callers;
    the command line always observes its own current clock.
    """
    if type(max_probe_age_seconds) is not int or max_probe_age_seconds <= 0:
        raise ValueError('max_probe_age_seconds must be positive integer')
    assessment = resume_capsule.assess(capsule, probe, max_age_seconds)
    now = _utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    probe_age = (now - _utc(probe['observed_at_utc'])).total_seconds()
    reasons = list(assessment['reasons'])
    if probe_age < -5:
        reasons.append('probe_from_future')
    elif probe_age > max_probe_age_seconds:
        reasons.append('probe_stale')
    # Keep the validated original operation as reconciliation context even
    # when fresh source/ownership observations are still missing or changed.
    # This carries identity, never current execution or replay authority.
    operation = dict(capsule['external']) if capsule['external'] is not None else None
    if reasons:
        kind = 'RECONCILE'
    elif capsule['external'] is not None:
        kind = 'RECONCILE_EXTERNAL'
        reasons.append('existing_external_operation')
    elif capsule['task']['blocker'] is not None or capsule['health']['state'] == 'BLOCKED':
        kind = 'WAIT'
        reasons.append(capsule['task']['blocker'] or 'health_blocked')
    elif capsule['health']['state'] != 'HEALTHY':
        kind = 'RECONCILE'
        reasons.append('health_' + capsule['health']['state'].lower())
    else:
        kind = 'RESUME'
    return {
        'schema': 'cdc-resume-result/v1',
        'next_action': {'kind': kind, 'checkpoint_ref': capsule['checkpoint_ref'],
                        'task': capsule['task']['next_action'], 'operation': operation,
                        'reasons': reasons},
        'capsule_assessment': assessment,
        'authorizes_product_write': False, 'authorizes_external_start': False,
        'authorizes_lease_mutation': False, 'authorizes_release': False,
        'authorizes_adoption': False,
    }


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field: ' + key)
        result[key] = value
    return result


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    entry = sub.add_parser('resume', help='Assess existing capsule and current probe')
    entry.add_argument('--capsule', required=True)
    entry.add_argument('--probe', required=True)
    entry.add_argument('--max-age-seconds', type=int, default=7200)
    entry.add_argument('--max-probe-age-seconds', type=int, default=90)
    for name in ('assess', 'report', 'strategy', 'allocate', 'init', 'migrate', 'delivery'):
        command = sub.add_parser(name)
        command.add_argument('input')
    args = parser.parse_args(argv)
    try:
        if args.command == 'resume':
            result = resume(_load(args.capsule), _load(args.probe),
                            max_age_seconds=args.max_age_seconds,
                            max_probe_age_seconds=args.max_probe_age_seconds)
        elif args.command == 'init':
            from project_setup import initialize
            result = initialize(_load(args.input))
        elif args.command == 'migrate':
            from project_setup import migrate
            result = migrate(_load(args.input))
        elif args.command == 'assess':
            from development_contract import evaluate
            result = evaluate(_load(args.input))
        elif args.command == 'strategy':
            from execution_strategy import evaluate
            result = evaluate(_load(args.input))
        elif args.command == 'allocate':
            from adaptive_allocation import evaluate
            result = evaluate(_load(args.input))
        elif args.command == 'delivery':
            from release_delivery import plan
            result = plan(_load(args.input))
        else:
            from operation_report import measure, render
            observation = _load(args.input)
            result = {'observation': measure(observation), 'suffix': render(observation)}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
