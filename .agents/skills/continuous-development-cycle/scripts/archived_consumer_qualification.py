#!/usr/bin/env python3
"""Qualify archived data and detached major-migration copies without adoption.

An expected major ceiling rejection is separate from installation acceptance.
Only in-memory copies receive a new ceiling and matching policy digest; all
ownership, external-operation, budget pointers and checkpoint history survive.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re

from contracts import ContractError, load_yaml, semver
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24

ROOT = Path(__file__).resolve().parents[1]


def _same_major_lock(source_lock, candidate, baseline_version):
    return (isinstance(source_lock, dict) and
            source_lock.get('schema') == 'cdc-source-lock/v1' and
            isinstance(source_lock.get('canonical_repository'), str) and
            re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source_lock['canonical_repository']) and
            source_lock.get('base_validation_repository') == source_lock['canonical_repository'] and
            source_lock.get('bootstrap_contract') == 'cdc-bootstrap/v1' and
            source_lock.get('direct_product_repo_development') is False and
            source_lock.get('target_version') == candidate and
            source_lock.get('development_driver_version') == baseline_version and
            all(isinstance(source_lock.get(key), str) and
                re.fullmatch('[0-9a-f]{40}', source_lock[key])
                for key in ('base_validation_commit', 'base_package_tree')) and
            type(source_lock.get('base_validation_run_id')) is int and
            source_lock['base_validation_run_id'] >= 0 and
            ((source_lock['base_validation_run_id'] > 0 and
              source_lock.get('base_validation_evidence_ref') is None) or
             (source_lock['base_validation_run_id'] == 0 and
              isinstance(source_lock.get('base_validation_evidence_ref'), str) and
              bool(source_lock['base_validation_evidence_ref'].strip()))))


def qualify(adapter, checkpoint, *, baseline_version, source_lock=None):
    candidate = (ROOT / 'VERSION').read_text().strip()
    target, baseline = semver(candidate), semver(baseline_version)
    if baseline >= target:
        raise ContractError('baseline must precede the candidate runtime')
    ceiling = semver(adapter['policy']['skill_max_version_exclusive'])
    later_three = (target[0] == baseline[0] == 3 and ceiling == (3, 0, 0))
    if later_three and not _same_major_lock(source_lock, candidate, baseline_version):
        raise ContractError('later 3.x qualification requires exact source lock binding')
    baseline_compatible = semver(adapter['policy']['skill_min_version']) <= baseline < ceiling
    diagnostic = baseline_version
    if later_three and not baseline_compatible:
        floor = max(semver(adapter['policy']['skill_min_version']), (2, 11, 3))
        if floor >= ceiling:
            raise ContractError('original policy has no supported diagnostic version')
        diagnostic = '.'.join(map(str, floor))
    original_binding = validate_adapter(adapter, skill_version=diagnostic)
    if (checkpoint.get('policy_revision') != original_binding['policy_revision'] or
            checkpoint.get('policy_digest') != original_binding['policy_digest']):
        raise ContractError('archived policy binding must validate before migration')
    validate_checkpoint_24(checkpoint, adapter, skill_version=diagnostic)
    result = {'candidate_version': candidate, 'baseline_version': baseline_version,
              'baseline_installation_compatible': baseline_compatible,
              'diagnostic_version': diagnostic,
              'installation_compatible': True, 'qualification': 'compatible',
              'migration_changes': [], 'authorizes_adoption': False,
              'authorizes_policy_write': False}
    try:
        validate_adapter(adapter)
    except ContractError as exc:
        if str(exc) != 'policy skill version range is incompatible with installed skill':
            raise
        major_boundary = (target[1:] == (0, 0) and ceiling == target and
                          baseline[0] + 1 == target[0])
        if not (major_boundary or later_three):
            raise ContractError('qualification requires an explicit major boundary') from exc
        migrated_adapter = copy.deepcopy(adapter)
        migrated_adapter['policy']['skill_max_version_exclusive'] = f'{target[0] + 1}.0.0'
        binding = validate_adapter(migrated_adapter)
        migrated_checkpoint = copy.deepcopy(checkpoint)
        migrated_checkpoint['policy_digest'] = binding['policy_digest']
        validate_checkpoint_24(migrated_checkpoint, migrated_adapter)
        result.update(installation_compatible=False,
                      qualification='migration_fixture_compatible',
                      migration_changes=['policy.skill_max_version_exclusive',
                                         'checkpoint.policy_digest'])
    else:
        validate_checkpoint_24(checkpoint, adapter)
    return result


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field: ' + key)
        result[key] = value
    return result


def qualify_snapshots(snapshot_root, *, consumers, baseline_version, package_tree,
                      source_lock=None):
    if not isinstance(package_tree, str) or not re.fullmatch('[0-9a-f]{40}', package_tree):
        raise ValueError('package_tree must be an exact Git tree SHA')
    if (not isinstance(consumers, (list, tuple)) or len(consumers) != 3 or
            len(set(consumers)) != 3 or any(not isinstance(name, str) or
            not re.fullmatch('[A-Za-z0-9_-]+', name) for name in consumers)):
        raise ValueError('exactly three distinct consumer directory names required')
    results = []
    for name in consumers:
        root = Path(snapshot_root) / name
        paths = [root / 'source.json', root / 'development-cycle.yaml', root / 'work-status.md']
        before = [path.read_bytes() for path in paths]
        source = json.loads(before[0].decode('utf-8'), object_pairs_hook=_unique)
        if (source.get('schema') != 'cdc-consumer-validation-source/v1' or
                source.get('candidate_version') != (ROOT / 'VERSION').read_text().strip() or
                source.get('candidate_package_tree') != package_tree or
                not re.fullmatch('[0-9a-f]{40}', source.get('source_commit', ''))):
            raise ValueError(name + ' archived source binding mismatch')
        adapter = load_yaml(paths[1])
        if source.get('repository') != adapter['repository']['remote']:
            raise ValueError(name + ' archived repository identity mismatch')
        checkpoint = load_yaml(paths[2], frontmatter=True)
        result = qualify(adapter, checkpoint, baseline_version=baseline_version,
                         source_lock=source_lock)
        if [path.read_bytes() for path in paths] != before:
            raise ValueError(name + ' archive changed during qualification')
        results.append(dict(result, consumer=name, source_commit=source['source_commit']))
    return {'schema': 'archived-consumer-qualification/v1', 'consumers': results,
            'package_tree': package_tree, 'archives_unchanged': True,
            'authorizes_adoption': False, 'authorizes_policy_write': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-root', required=True)
    parser.add_argument('--consumers', nargs=3, required=True)
    parser.add_argument('--baseline-version', required=True)
    parser.add_argument('--package-tree', required=True)
    args = parser.parse_args(argv)
    try:
        result = qualify_snapshots(args.snapshot_root, consumers=args.consumers,
                                   baseline_version=args.baseline_version,
                                   package_tree=args.package_tree,
                                   source_lock=json.loads((ROOT.parents[1] /
                                       'release/source.lock.json').read_text(),
                                       object_pairs_hook=_unique))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('ARCHIVED_CONSUMERS_RED:', exc)
        return 1
    print(json.dumps(result, sort_keys=True))
    print('THREE_ARCHIVED_CONSUMERS_QUALIFIED package_tree=' + args.package_tree)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
