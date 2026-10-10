"""Read-only project initialization and conservative migration previews."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import yaml
from contracts import StrictLoader, semver
from codex_cloud_profile import validate_profile
from policy_migration import plan as policy_plan
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24

ROOT = Path(__file__).resolve().parents[1]
PRESETS = {'portable': ('MEDIUM', 'any'), 'windows': ('MEDIUM', 'windows'),
           'android': ('MEDIUM', 'android'), 'critical': ('FULL', 'any')}
LEVELS = {'FAST': 0, 'MEDIUM': 1, 'FULL': 2}
AUTHORITY = {name: False for name in ('authorizes_product_write',
             'authorizes_external_start', 'authorizes_lease_mutation',
             'authorizes_release', 'authorizes_adoption')}


def _fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(label + ' fields mismatch')


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(label + ' must be text')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('source_head must be exact Git SHA')
    return value


def _preset(value):
    if not isinstance(value, str) or value not in PRESETS:
        raise ValueError('unknown project preset')
    return PRESETS[value]


def _yaml(text):
    _text(text, 'YAML')
    if len(text) > 262144:
        raise ValueError('configuration exceeds 256 KiB')
    try:
        value = yaml.load(text, Loader=StrictLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError('invalid strict YAML') from exc
    if not isinstance(value, dict):
        raise ValueError('configuration must be mapping')
    return value


def _checkpoint(text):
    _text(text, 'checkpoint')
    match = re.match(r'\A---\n(.*?)\n---(?P<body>\n.*|\Z)', text, re.S)
    if match is None:
        raise ValueError('checkpoint requires YAML frontmatter')
    return _yaml(match.group(1)), match.group('body')


def _render_checkpoint(value, body):
    return '---\n' + yaml.safe_dump(value, sort_keys=False, allow_unicode=True) + '---' + body


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field: ' + key)
        value[key] = item
    return value


def _cloud(text, repository, branch, digest):
    if text is None:
        value = json.loads((ROOT / 'templates/codex-cloud-profile.json').read_text())
        value.update(repository=repository, source_ref='refs/heads/' + branch,
                     policy_digest='sha256:' + digest)
        validate_profile(value)
        return json.dumps(value, indent=2) + '\n', {'status': 'UNCONFIGURED', 'reused': False}
    _text(text, 'cloud_profile_json')
    value = json.loads(text, object_pairs_hook=_unique)
    validate_profile(value)
    if value['repository'] != repository or value['source_ref'] != 'refs/heads/' + branch:
        raise ValueError('Cloud profile project/source identity mismatch')
    status = ('REUSE_PENDING_FRESH_PROBE' if digest is not None and value['policy_digest'] == 'sha256:' + digest
              else 'REQUALIFY')
    return text, {'status': status, 'reused': True}


def _file(path, content, before=None):
    h = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
    return dict(path=path, content=content, before_sha256=None if before is None else h(before),
                after_sha256=h(content))


def _result(action, preset, source_head, digest, files, cloud, reason,
            *, operation=None, compatibility=None):
    return dict(schema='cdc-project-plan/v1', action=action, preset=preset,
                source_head=source_head, policy_digest=digest, files=files,
                changed_paths=[f['path'] for f in files if f['before_sha256'] != f['after_sha256']],
                cloud_reuse=cloud, reason=reason, existing_operation=operation,
                original_compatibility=compatibility, **AUTHORITY)


def initialize(request):
    _fields(request, {'schema', 'repository', 'branch', 'source_head', 'preset',
                      'validation', 'cloud_profile_json'}, 'init request')
    if request['schema'] != 'cdc-init-request/v1':
        raise ValueError('unsupported init schema')
    repository, branch = request['repository'], request['branch']
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or '..' in repository:
        raise ValueError('repository must be canonical owner/name')
    if not isinstance(branch, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', branch) or any(part in {'', '.', '..'} or part.endswith(('.', '.lock')) or part.startswith('.') for part in branch.split('/')) or '..' in branch:
        raise ValueError('branch must be safe refs/heads suffix')
    source = _sha(request['source_head'])
    quality, platform = _preset(request['preset'])
    validation = request['validation']
    _fields(validation, {'quick', 'full', 'release'}, 'validation')
    for name in validation:
        _text(validation[name], name, empty=name == 'quick')
    adapter = _yaml((ROOT / 'templates/development-cycle.yaml').read_text())
    adapter['repository'].update(name=repository.split('/')[1], remote=repository)
    adapter['quality']['default_level'] = quality
    adapter['validation'].update(validation, final_platform=platform)
    adapter['checkpoint']['path'] = 'docs/work-status/current.md'
    binding = validate_adapter(adapter)
    cp, body = _checkpoint((ROOT / 'templates/work-status-v4.md').read_text())
    cp.update(repository=repository, branch=branch, candidate_sha=source,
              policy_revision=binding['policy_revision'], policy_digest=binding['policy_digest'])
    validate_checkpoint_24(cp, adapter)
    cloud_text, cloud = _cloud(request['cloud_profile_json'], repository, branch, binding['policy_digest'])
    scaffold = dict(schema='cloud-entry-inputs-template/v1', configuration_status='UNCONFIGURED',
                    input_schema='cloud-entry-inputs/v1',
                    required_snapshots=['context', 'probe', 'registry', 'routing_policy', 'routing_context'])
    files = [_file('docs/development-cycle.yaml', yaml.safe_dump(adapter, sort_keys=False, allow_unicode=True)),
             _file('docs/work-status/current.md', _render_checkpoint(cp, body)),
             _file('docs/cdc-cloud-profile.json', cloud_text),
             _file('docs/cdc-cloud-entry-inputs.template.json', json.dumps(scaffold, indent=2) + '\n')]
    return _result('INIT', request['preset'], source, binding['policy_digest'], files,
                   cloud, 'review_generated_files_then_use_existing_managed_writer')


def _parse_utc(text):
    if not isinstance(text, str) or not text.endswith('Z') or 'T' not in text:
        raise ValueError('observation must be UTC Z text')
    value = datetime.fromisoformat(text[:-1] + '+00:00')
    if value.utcoffset().total_seconds() != 0:
        raise ValueError('observation must be UTC')
    return value


def _original_documents(request):
    adapter = _yaml(request['current_adapter_yaml'])
    checkpoint, body = _checkpoint(request['current_checkpoint_markdown'])
    policy = adapter['policy']
    diagnostic_version = max(semver(policy['skill_min_version']), (2, 11, 3))
    ceiling = semver(policy['skill_max_version_exclusive'])
    if diagnostic_version >= ceiling:
        raise ValueError('original policy has no supported diagnostic version')
    diagnostic_text = '.'.join(str(part) for part in diagnostic_version)
    validate_checkpoint_24(checkpoint, adapter, skill_version=diagnostic_text)
    if adapter['checkpoint']['path'] != 'docs/work-status/current.md':
        raise ValueError('custom checkpoint path requires separately reviewed migration')
    target_text = (ROOT / 'VERSION').read_text().strip()
    compatibility = dict(diagnostic_version=diagnostic_text, target_version=target_text,
                         original_target_compatible=diagnostic_version <= semver(target_text) < ceiling)
    return adapter, checkpoint, body, compatibility


def _existing_operation(checkpoint):
    saved = ('operation_key', 'operation_intent_ref', 'waiting_external_kind',
             'waiting_external_id', 'waiting_external_sha')
    if all(checkpoint[key] is None for key in saved) and checkpoint['lease_state'] != 'waiting_external':
        return None
    return dict(kind=checkpoint['waiting_external_kind'], id=checkpoint['waiting_external_id'],
                sha=checkpoint['waiting_external_sha'], intent_ref=checkpoint['operation_intent_ref'],
                operation_key=checkpoint['operation_key'])


def _desired_sections(adapter, preset, compatibility):
    quality, platform = _preset(preset)
    old_platform = adapter['validation']['final_platform']
    if old_platform != 'any' and platform not in {'any', old_platform}:
        return None
    sections = {}
    old_quality = adapter.get('quality', {'default_level': 'FULL', 'max_validation_cycles': 2})
    new_quality = copy.deepcopy(old_quality)
    new_quality['default_level'] = max([old_quality['default_level'], quality], key=lambda key: LEVELS[key])
    if adapter.get('quality') != new_quality:
        sections['quality'] = new_quality
    if old_platform == 'any' and platform != 'any':
        sections['validation'] = {**adapter['validation'], 'final_platform': platform}
    new_policy = copy.deepcopy(adapter['policy'])
    if not compatibility['original_target_compatible']:
        target = semver(compatibility['target_version'])
        if (new_policy['skill_max_version_exclusive'] != '3.0.0' or target[0] != 3
                or target < semver(new_policy['skill_min_version'])):
            raise ValueError('version range requires separately reviewed migration')
        new_policy['skill_max_version_exclusive'] = '4.0.0'
        sections['policy'] = new_policy
    if sections:
        revision = new_policy['revision']
        if not re.fullmatch(r'[0-9]+', revision):
            raise ValueError('nondecimal revision requires reviewed revision choice')
        new_policy['revision'] = str(int(revision) + 1)
        sections['policy'] = new_policy
    return sections


def migrate(request, *, now_utc=None):
    _fields(request, {'schema', 'current_adapter_yaml', 'current_checkpoint_markdown',
                      'cloud_profile_json', 'preset', 'expected_source_head', 'probe'}, 'migrate request')
    if request['schema'] != 'cdc-migrate-request/v1':
        raise ValueError('unsupported migrate schema')
    _preset(request['preset'])
    expected = _sha(request['expected_source_head'])
    probe = request['probe']
    _fields(probe, {'source_head', 'observed_at_utc', 'lease_released', 'guard_reconciled'}, 'probe')
    observed = _sha(probe['source_head'])
    for key in ('lease_released', 'guard_reconciled'):
        if type(probe[key]) is not bool:
            raise ValueError(key + ' must be boolean')
    now = _parse_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    age = (now - _parse_utc(probe['observed_at_utc'])).total_seconds()
    adapter, checkpoint, body, compatibility = _original_documents(request)
    operation = _existing_operation(checkpoint)
    # Incomplete original binding is reconciliation work, never a silent rebind.
    if checkpoint['policy_digest'] is None:
        if request['cloud_profile_json'] is not None:
            _, cloud = _cloud(request['cloud_profile_json'], checkpoint['repository'],
                              checkpoint['branch'], None)
        else:
            cloud = {'status': 'UNCONFIGURED', 'reused': False}
    else:
        _, cloud = _cloud(request['cloud_profile_json'], checkpoint['repository'],
                          checkpoint['branch'], checkpoint['policy_digest'])
    def result(action, reason, files=None, digest=None, cloud_result=None):
        return _result(action, request['preset'], observed,
                       checkpoint['policy_digest'] if digest is None else digest,
                       files or [], cloud if cloud_result is None else cloud_result, reason,
                       operation=operation, compatibility=compatibility)
    if expected != observed or not -5 <= age <= 90 or checkpoint['policy_digest'] is None:
        return result('RECONCILE', 'source_probe_or_original_binding_requires_reconciliation')
    if (not probe['lease_released'] or not probe['guard_reconciled']
            or checkpoint['lease_state'] != 'released' or operation is not None):
        return result('WAIT', 'ownership_or_existing_operation_requires_reconciliation')
    desired = _desired_sections(adapter, request['preset'], compatibility)
    if desired is None:
        return result('CONFLICT', 'incompatible_platform_requires_reviewed_migration')
    if desired:
        proposal = policy_plan(dict(schema='policy-migration-request/v1',
                                    expected_source_head=expected, observed_source_head=observed,
                                    current_policy_yaml=request['current_adapter_yaml'], desired_sections=desired))
        adapter_text = proposal['rendered_policy_yaml']
        proposed_adapter = _yaml(adapter_text)
        binding = validate_adapter(proposed_adapter)
        proposed_checkpoint = copy.deepcopy(checkpoint)
        proposed_checkpoint.update(policy_revision=binding['policy_revision'], policy_digest=binding['policy_digest'])
        validate_checkpoint_24(proposed_checkpoint, proposed_adapter)
        checkpoint_text = _render_checkpoint(proposed_checkpoint, body)
        action = 'APPLY'
    else:
        adapter_text = request['current_adapter_yaml']
        checkpoint_text = request['current_checkpoint_markdown']
        binding = validate_adapter(adapter)
        action = 'NOOP'
    files = [_file('docs/development-cycle.yaml', adapter_text, request['current_adapter_yaml']),
             _file('docs/work-status/current.md', checkpoint_text, request['current_checkpoint_markdown'])]
    if request['cloud_profile_json'] is not None:
        cloud_text, cloud = _cloud(request['cloud_profile_json'], checkpoint['repository'],
                                  checkpoint['branch'], binding['policy_digest'])
        files.append(_file('docs/cdc-cloud-profile.json', cloud_text, request['cloud_profile_json']))
    return result(action, 'review_preview_then_use_existing_managed_writer', files,
                  binding['policy_digest'], cloud)

