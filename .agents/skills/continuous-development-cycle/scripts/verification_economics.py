"""Dependency-bound reuse enforced by the command runner before spawning."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import evidence_reuse
from quality_levels import fields, text, texts


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def definition(check):
    return hashlib.sha256(canonical({k:v for k,v in check.items() if k != 'id'})).hexdigest()


def verify_dependencies(root, dependencies):
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError('dependency coverage required')
    root = Path(root).resolve()
    for name, expected in dependencies.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('dependency path must be relative and contained')
        target = root / path
        if target.resolve() != target.absolute() or not target.is_file():
            raise ValueError('dependency missing or symlinked: ' + name)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('dependency bytes changed: ' + name)


def validate_aggregate_repeats(plan):
    config = plan['economics']
    fields(config, ('check_inputs', 'aggregate_check_ids', 'prior_evidence',
                    'repeat_exceptions'), 'verification economics')
    texts(config['aggregate_check_ids'], 'aggregate IDs', allow_empty=True)
    ids = {c['id'] for c in plan['checks']}
    if not set(config['aggregate_check_ids']) <= ids:
        raise ValueError('aggregate ID not declared')
    exceptions = {}
    if not isinstance(config['repeat_exceptions'], list):
        raise ValueError('repeat exceptions must be list')
    for item in config['repeat_exceptions']:
        fields(item, ('check_id', 'reason', 'coverage_ref'), 'repeat exception')
        for k in item:text(item[k], k)
        if item['check_id'] not in ids or item['check_id'] in exceptions:
            raise ValueError('repeat exception ID invalid')
        exceptions[item['check_id']] = item
    # A second aggregate in the same runner/environment always needs a
    # separately reviewed coverage justification, even if argv differs.
    reasons=set()
    coverage=set()
    for check_id in config['aggregate_check_ids'][1:]:
        if check_id not in exceptions:
            raise ValueError('additional aggregate requires reviewed coverage reason')
        item=exceptions[check_id]
        if item['reason'] in reasons or item['coverage_ref'] in coverage:
            raise ValueError('additional aggregates require distinct reasons and coverage references')
        reasons.add(item['reason'])
        coverage.add(item['coverage_ref'])
    return exceptions


def current_inputs(plan, check, root, environment):
    mapping = plan['economics']['check_inputs']
    if not isinstance(mapping, dict) or set(mapping) != {c['id'] for c in plan['checks']}:
        raise ValueError('every check needs exactly one input coverage record')
    item = mapping[check['id']]
    fields(item, ('dependency_fingerprints', 'parameters', 'coverage_refs',
                  'exact_candidate_required'), 'check coverage')
    verify_dependencies(root, item['dependency_fingerprints'])
    texts(item['coverage_refs'], 'coverage_refs')
    if type(item['exact_candidate_required']) is not bool:
        raise ValueError('exact_candidate_required must be boolean')
    inputs = {'dependency_fingerprints':item['dependency_fingerprints'],
              'parameters':item['parameters'], 'argv':check['argv'],
              'environment_fingerprint':environment['fingerprint'],
              'check_definition_fingerprint':definition(check)}
    evidence_reuse._inputs(inputs)
    return inputs


def prior_records(config):
    if not isinstance(config['prior_evidence'], list):
        raise ValueError('prior_evidence must be list')
    records = []
    seen = set()
    for item in config['prior_evidence']:
        fields(item, ('path', 'sha256'), 'prior evidence')
        text(item['path'], 'evidence path')
        path = Path(item['path'])
        if not path.is_absolute() or path.resolve() != path or not path.is_file():
            raise ValueError('prior evidence must be absolute regular nonsymlink file')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('prior evidence digest mismatch')
        if item['sha256'] in seen:raise ValueError('duplicate prior evidence')
        seen.add(item['sha256'])
        def unique(pairs):
            result = {}
            for k,v in pairs:
                if k in result:raise ValueError('duplicate prior evidence field')
                result[k]=v
            return result
        data = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(data, dict) or data.get('schema') != 'command-evidence/v1'
                or data.get('runner_status') != 'COMPLETE'
                or not isinstance(data.get('checks'), list)):
            raise ValueError('prior evidence is not a complete command receipt')
        from run_checks import load_plan, file_digest, artifact, junit_report, source_matches, digest
        original_plan=load_plan(path.parent/'plan.json')
        if digest(canonical(original_plan))!=data.get('plan_sha256'):
            raise ValueError('prior evidence plan digest mismatch')
        original_checks={c['id']:c for c in original_plan['checks']}
        for check in data['checks']:
            if check.get('executed') is not True or check.get('status')!='PASS':continue
            declaration=original_checks.get(check.get('id'))
            if declaration is None or definition(declaration)!=check.get('validation_inputs',{}).get('check_definition_fingerprint'):
                raise ValueError('prior check definition mismatch')
            log=check.get('log',{})
            if file_digest(artifact(path.parent,log.get('path','')))!=log.get('sha256'):
                raise ValueError('prior command log digest mismatch')
            if declaration['kind']=='test':
                report=check.get('test_report',{})
                actual=junit_report(path.parent,report.get('path',''))
                if actual!=report:raise ValueError('prior test report changed')
            if not all(source_matches(data.get(side),data.get('candidate_sha'))
                       for side in ('source_before','source_after')):
                raise ValueError('prior command source was not frozen and clean')
            if declaration.get('expected_red') is not None:
                raise ValueError('expected RED is not reusable success')
        records.append((item, data))
    return records


def select(plan, check, root, environment, candidate, records):
    inputs = current_inputs(plan, check, root, environment)
    coverage = plan['economics']['check_inputs'][check['id']]
    exceptions = validate_aggregate_repeats(plan)
    unchanged_aggregate = False
    for ref, receipt in records:
        for previous in receipt['checks']:
            if previous.get('id') != check['id'] or previous.get('validation_inputs') is None:
                continue
            old = previous['validation_inputs']
            unchanged_aggregate |= canonical(old) == canonical(inputs)
            source = receipt.get('candidate_sha')
            observation_ok = all(isinstance(previous.get(side), dict)
                and previous[side].get('sha') == source
                and previous[side].get('clean') is True
                and previous[side].get('status_porcelain') == ''
                and previous[side].get('error') is None for side in ('before','after'))
            success = (receipt.get('final_green') is True and receipt.get('gate_status') == 'GREEN'
                and previous.get('executed') is True and previous.get('exit_code') == 0
                and previous.get('status') == 'PASS' and previous.get('termination') == 'completed'
                and observation_ok and previous.get('candidate_sha') == source
                and previous.get('environment', {}).get('fingerprint') == old.get('environment_fingerprint'))
            request = {'schema':'evidence-reuse/v1','check_id':check['id'],
                'source_candidate_sha':source,'target_candidate_sha':candidate,
                'source_evidence_ref':str(ref['path'])+'#sha256:'+ref['sha256'],
                'source_state':'success' if success else 'failed',
                'original_inputs':old,'current_inputs':inputs,
                'coverage_refs':coverage['coverage_refs'],
                'exact_candidate_required':coverage['exact_candidate_required']}
            result = evidence_reuse.evaluate(request)
            if result['reusable']:
                return {'action':'REUSE','inputs':inputs,'reuse':result}
    if (check['id'] in plan['economics']['aggregate_check_ids'] and unchanged_aggregate
            and check['id'] not in exceptions):
        raise ValueError('unchanged aggregate requires sufficient prior proof or reviewed repeat reason')
    return {'action':'RUN','inputs':inputs,'repeat_exception':exceptions.get(check['id'])}
