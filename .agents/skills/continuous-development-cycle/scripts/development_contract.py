#!/usr/bin/env python3
"""Read-only composition of development validation evidence and advice.

The v1 request names a candidate, existing quality/cycle contracts, declared
required checks, direct observations, reuse requests, and change context. This
module does not run checks or grant any effect authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import evidence_reuse
import quality_levels


CRITICAL_RISKS = frozenset(('cdc_core', 'executor_authority', 'authentication',
                            'ad_write', 'dangerous_migration'))
TDD_REASONS = frozenset(('complex_logic', 'critical_boundary', 'reproduced_bug'))
CHANGE_KINDS = frozenset(('feature', 'bugfix', 'refactor', 'text_layout'))


def _sha(value, name):
    if not isinstance(value, str) or not evidence_reuse.SHA.fullmatch(value):
        raise ValueError(name + ' invalid SHA')


def _list(value, name):
    if not isinstance(value, list):
        raise ValueError(name + ' must be a list')


def _unique_ids(entries, key, name):
    ids = [entry[key] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError(name + ' contains duplicates')


def _validate(request):
    quality_levels.fields(request, ('schema', 'candidate_sha', 'quality', 'cycle',
                                   'required_checks', 'completed_checks',
                                   'reuse_requests', 'change'), 'development assessment')
    if request['schema'] != 'development-assessment/v1':
        raise ValueError('development assessment schema mismatch')
    _sha(request['candidate_sha'], 'candidate_sha')
    quality = quality_levels.evaluate(request['quality'])
    cycle = quality_levels.evaluate_cycle(request['cycle'])

    required = request['required_checks']
    _list(required, 'required_checks')
    for item in required:
        quality_levels.fields(item, ('id', 'exact_candidate_required'), 'required check')
        quality_levels.text(item['id'], 'required check id')
        if type(item['exact_candidate_required']) is not bool:
            raise ValueError('exact_candidate_required must be bool')
    _unique_ids(required, 'id', 'required_checks')

    completed = request['completed_checks']
    _list(completed, 'completed_checks')
    for item in completed:
        quality_levels.fields(item, ('check_id', 'state', 'candidate_sha',
                                     'evidence_ref'), 'completed check')
        quality_levels.text(item['check_id'], 'completed check id')
        if item['state'] not in ('success', 'failed', 'not_run'):
            raise ValueError('completed check state invalid')
        _sha(item['candidate_sha'], 'completed candidate_sha')
        quality_levels.text(item['evidence_ref'], 'completed evidence_ref')
    _unique_ids(completed, 'check_id', 'completed_checks')

    reused = request['reuse_requests']
    _list(reused, 'reuse_requests')
    for item in reused:
        evidence_reuse.validate(item)
    _unique_ids(reused, 'check_id', 'reuse_requests')
    declared = {item['id'] for item in required}
    observed = {item['check_id'] for item in completed + reused}
    if not observed <= declared:
        raise ValueError('observed check not declared')
    if {item['check_id'] for item in completed} & {item['check_id'] for item in reused}:
        raise ValueError('direct and reused check overlap')
    if any(item['target_candidate_sha'] != request['candidate_sha'] for item in reused):
        raise ValueError('reuse target differs from candidate')

    change = request['change']
    quality_levels.fields(change, ('kind', 'tdd_risk_reasons',
                                   'compatible_change_ids', 'urgent'), 'change')
    if change['kind'] not in CHANGE_KINDS:
        raise ValueError('change kind invalid')
    quality_levels.texts(change['tdd_risk_reasons'], 'tdd_risk_reasons', allow_empty=True)
    if any(reason not in TDD_REASONS for reason in change['tdd_risk_reasons']):
        raise ValueError('tdd risk reason invalid')
    quality_levels.texts(change['compatible_change_ids'],
                         'compatible_change_ids', allow_empty=True)
    if type(change['urgent']) is not bool:
        raise ValueError('urgent must be bool')
    return quality, cycle


def evaluate(request: dict) -> dict:
    """Evaluate declared check evidence; a recommendation has no effect authority."""
    quality, cycle = _validate(request)
    required = {item['id']: item for item in request['required_checks']}
    completed = {item['check_id']: item for item in request['completed_checks']}
    reuse_results = []
    for item in request['reuse_requests']:
        # The declaration is authoritative. A source's assertion of a weaker
        # exact-candidate condition cannot relax this gate.
        effective = dict(item, exact_candidate_required=(
            item['exact_candidate_required'] or
            required[item['check_id']]['exact_candidate_required']))
        reuse_results.append(evidence_reuse.evaluate(effective))
    reused = {item['check_id']: item for item in reuse_results}

    blockers = list(cycle['blockers'])
    if not required:
        blockers.append('required_checks_missing')
    if (CRITICAL_RISKS.intersection(request['quality']['risk_categories']) and
            not quality['mandatory_check_ids']):
        blockers.append('critical_mandatory_checks_missing')
    check_results = []
    for check_id, declaration in required.items():
        direct = completed.get(check_id)
        reuse = reused.get(check_id)
        satisfied = bool(direct and direct['state'] == 'success' and
                         direct['candidate_sha'] == request['candidate_sha'])
        satisfied = satisfied or bool(reuse and reuse['reusable'])
        outcome = {'check_id': check_id, 'status': 'satisfied' if satisfied else 'unsatisfied',
                   'exact_candidate_required': declaration['exact_candidate_required']}
        if reuse is not None:
            outcome['source_candidate_sha'] = reuse['source_candidate_sha']
            outcome['evidence_ref'] = reuse['source_evidence_ref']
        elif direct is not None:
            outcome['source_candidate_sha'] = direct['candidate_sha']
            outcome['evidence_ref'] = direct['evidence_ref']
        check_results.append(outcome)
        if not satisfied:
            kind = 'mandatory' if check_id in quality['mandatory_check_ids'] else 'required'
            blockers.append(kind + '_check_unsatisfied:' + check_id)
    for check_id in quality['mandatory_check_ids']:
        if check_id not in required:
            blockers.append('mandatory_check_unsatisfied:' + check_id)

    change = request['change']
    tdd_reasons = list(change['tdd_risk_reasons'])
    tdd_reasons.extend('critical_risk:' + category for category in
                       request['quality']['risk_categories'] if category in CRITICAL_RISKS
                       and 'critical_boundary' not in tdd_reasons)
    batch_reasons = []
    if len(change['compatible_change_ids']) < 2:
        batch_reasons.append('fewer_than_two_compatible_changes')
    if change['urgent']:
        batch_reasons.append('urgent_change')
    if quality['effective_level'] == 'FULL':
        batch_reasons.append('full_risk_floor')
    if blockers:
        batch_reasons.append('validation_blocked')
    return {
        'schema': 'development-assessment-result/v1',
        'candidate_sha': request['candidate_sha'],
        'quality': quality, 'cycle': cycle,
        'reuse_results': reuse_results, 'check_results': check_results,
        'validation_recommended': not blockers, 'blockers': blockers,
        'tdd': {'recommended': bool(tdd_reasons), 'reasons': tdd_reasons},
        'batching': {'recommended': not batch_reasons,
                     'candidate_change_ids': list(change['compatible_change_ids']),
                     'reasons': batch_reasons},
        'authorizes_external_start': False, 'authorizes_product_write': False,
        'authorizes_merge': False, 'authorizes_release': False,
        'authorizes_adoption': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    args = parser.parse_args(argv)
    try:
        result = evaluate(json.loads(Path(args.input).read_text()))
    except (OSError, ValueError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result['validation_recommended'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
