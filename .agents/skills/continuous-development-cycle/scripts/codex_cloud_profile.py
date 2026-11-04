#!/usr/bin/env python3
"""Strict, pure Codex Cloud profile validation and per-mode qualification.

A READY result describes supplied bound evidence. It grants no execution authority,
performs no provider discovery and never replaces live lease/intent/budget gates.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

MODES = ('native_runtime', 'official_ui', 'official_cli')
NAMESPACES = dict(zip(MODES, ('managed_cloud_runtime', 'codex_cloud_ui', 'codex_cloud_cli')))
PROFILE_FIELDS = {'schema', 'repository', 'source_ref', 'environments', 'control_host',
                  'access_modes', 'toolchain', 'setup', 'policy_digest', 'provenance'}
PROBE_FIELDS = {'schema', 'observed_at_utc', 'inventory_complete', 'repository',
                'source_ref', 'environments', 'setup_fingerprint', 'policy_digest',
                'cli_version', 'access_modes'}
ENV_FIELDS = {'provider_namespace', 'id', 'url', 'label'}
OBS_FIELDS = {'complete', 'status', 'reason', 'evidence_ref', 'binding_digest', 'observed_at_utc'}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')
UTC = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z')
PUBLIC_HOSTS = {'chatgpt.com', 'chat.openai.com', 'platform.openai.com', 'github.com'}


def _fields(value, expected, name):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(name + ' fields mismatch')


def _text(value, name, *, nullable=False):
    if value is None and nullable:
        return value
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(name + ' must be nonempty trimmed text without control characters')
    return value


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(name + ' must be boolean')


def _digest_value(value, name, *, nullable=False, plain=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not (HEX if plain else DIGEST).fullmatch(value):
        raise ValueError(name + ' must be SHA256')


def _utc(value, name):
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise ValueError(name + ' must be UTC timestamp')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(name + ' must be valid UTC timestamp') from exc


def _repository(value):
    if (not isinstance(value, str) or not REPOSITORY.fullmatch(value)
            or any(part in {'.', '..'} for part in value.split('/'))):
        raise ValueError('repository must be owner/name public GitHub identity')


def _source_ref(value):
    _text(value, 'source_ref')
    if (not value.startswith('refs/heads/') or len(value) == len('refs/heads/')
            or any(c in value for c in ' ~^:?*[\\') or '..' in value
            or '@{' in value or '//' in value or value.endswith(('/', '.', '.lock'))
            or any(part.startswith('.') or part.endswith('.lock') for part in value.split('/'))):
        raise ValueError('source_ref must be full portable refs/heads/*')


def _url(value, name):
    if value is None:
        return
    _text(value, name)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(name + ' invalid URL') from exc
    if (parsed.scheme != 'https' or parsed.hostname not in PUBLIC_HOSTS
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 443) or parsed.query or parsed.fragment
            or '%' in parsed.netloc or '\\' in value):
        raise ValueError(name + ' must be credential-free approved public HTTPS URL')


def _reference(value, name, *, nullable=False):
    _text(value, name, nullable=nullable)
    if isinstance(value, str) and '://' in value:
        _url(value, name)


def _environments(value, *, profile):
    _fields(value, set(MODES), 'environments')
    for mode in MODES:
        env = value[mode]
        _fields(env, ENV_FIELDS, 'environment.' + mode)
        _text(env['provider_namespace'], 'provider_namespace')
        if profile and env['provider_namespace'] != NAMESPACES[mode]:
            raise ValueError('profile environment namespace mismatch: ' + mode)
        for key in ('id', 'label'):
            _text(env[key], 'environment.' + key, nullable=True)
        _url(env['url'], 'environment.url')


def _hash(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                               ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def validate_profile(profile):
    """Return the input after strict validation, without copying or normalizing argv."""
    _fields(profile, PROFILE_FIELDS, 'profile')
    if profile['schema'] != 'codex-cloud-project-profile/v1':
        raise ValueError('unsupported profile schema')
    _repository(profile['repository'])
    _source_ref(profile['source_ref'])
    _environments(profile['environments'], profile=True)
    host = profile['control_host']
    _fields(host, {'kind', 'provider_namespace', 'binding_ref'}, 'control_host')
    _text(host['kind'], 'control_host.kind')
    _text(host['provider_namespace'], 'control_host.provider_namespace')
    _reference(host['binding_ref'], 'control_host.binding_ref', nullable=True)
    _fields(profile['access_modes'], set(MODES), 'access_modes')
    for mode, access in profile['access_modes'].items():
        _fields(access, {'configured', 'capability_ref'}, 'access_mode.' + mode)
        _boolean(access['configured'], 'configured')
        _reference(access['capability_ref'], 'capability_ref', nullable=True)
    _fields(profile['toolchain'], {'cli_executable', 'cli_version'}, 'toolchain')
    for name, value in profile['toolchain'].items():
        _text(value, name, nullable=True)
    setup = profile['setup']
    _fields(setup, {'fingerprint', 'commands'}, 'setup')
    _digest_value(setup['fingerprint'], 'setup.fingerprint', nullable=True)
    if not isinstance(setup['commands'], list):
        raise ValueError('setup.commands must be argv list')
    for argv in setup['commands']:
        if not isinstance(argv, list) or not argv:
            raise ValueError('setup command must be nonempty argv')
        for arg in argv:
            _text(arg, 'setup argv')
    _digest_value(profile['policy_digest'], 'policy_digest', nullable=True)
    provenance = profile['provenance']
    if not isinstance(provenance, list):
        raise ValueError('provenance must be list')
    allowed_fields = PROFILE_FIELDS - {'schema', 'provenance'}
    allowed_fields |= {'environments.' + mode for mode in MODES}
    allowed_fields |= {'access_modes.' + mode for mode in MODES}
    allowed_fields |= {'toolchain.cli_executable', 'toolchain.cli_version',
                       'setup.fingerprint', 'setup.commands'}
    allowed_fields |= {'environments.' + mode + '.' + key for mode in MODES for key in ENV_FIELDS}
    allowed_fields |= {'access_modes.' + mode + '.' + key for mode in MODES
                       for key in ('configured', 'capability_ref')}
    allowed_fields |= {'control_host.' + key for key in ('kind', 'provider_namespace', 'binding_ref')}
    seen = set()
    for entry in provenance:
        _fields(entry, {'field', 'evidence_ref', 'evidence_sha256', 'qualified_at_utc'}, 'provenance')
        if not isinstance(entry['field'], str) or entry['field'] not in allowed_fields:
            raise ValueError('provenance field not recognized')
        if entry['field'] in seen:
            raise ValueError('duplicate provenance field')
        seen.add(entry['field'])
        _reference(entry['evidence_ref'], 'provenance.evidence_ref')
        _digest_value(entry['evidence_sha256'], 'evidence_sha256', plain=True)
        _utc(entry['qualified_at_utc'], 'qualified_at_utc')
    return profile


def validate_probe(probe):
    """Validate dynamic observations; a namespace mismatch remains mode-local."""
    _fields(probe, PROBE_FIELDS, 'probe')
    if probe['schema'] != 'cloud-profile-probe/v1':
        raise ValueError('unsupported probe schema')
    _utc(probe['observed_at_utc'], 'probe.observed_at_utc')
    _boolean(probe['inventory_complete'], 'inventory_complete')
    _repository(probe['repository'])
    _source_ref(probe['source_ref'])
    _environments(probe['environments'], profile=False)
    _digest_value(probe['setup_fingerprint'], 'setup_fingerprint', nullable=True)
    _digest_value(probe['policy_digest'], 'policy_digest', nullable=True)
    _text(probe['cli_version'], 'probe.cli_version', nullable=True)
    _fields(probe['access_modes'], set(MODES), 'probe.access_modes')
    for mode, obs in probe['access_modes'].items():
        _fields(obs, OBS_FIELDS, 'observation.' + mode)
        _boolean(obs['complete'], 'observation.complete')
        if obs['status'] not in ('ready', 'unavailable', 'unknown'):
            raise ValueError('unsupported observation status')
        _text(obs['reason'], 'observation.reason')
        _reference(obs['evidence_ref'], 'observation.evidence_ref', nullable=True)
        _digest_value(obs['binding_digest'], 'observation.binding_digest', nullable=True)
        _utc(obs['observed_at_utc'], 'observation.observed_at_utc')
    return probe


def _projection(profile, access_mode):
    shared = {'repository': profile['repository'], 'source_ref': profile['source_ref'],
              'setup_fingerprint': profile['setup']['fingerprint'], 'policy_digest': profile['policy_digest']}
    env = profile['environments'][access_mode]
    if access_mode == 'native_runtime':
        mode_projection = {'environment': env, 'control_host': profile['control_host']}
    else:
        mode_projection = {'environment': env, 'access': profile['access_modes'][access_mode]}
        if access_mode == 'official_cli':
            mode_projection['toolchain'] = profile['toolchain']
    return {'shared': shared, 'access_mode': access_mode, 'mode_projection': mode_projection}


def profile_binding_digest(profile, access_mode):
    """Canonical UTF-8 digest of shared and strictly mode-specific qualification."""
    validate_profile(profile)
    if not isinstance(access_mode, str) or access_mode not in MODES:
        raise ValueError('unsupported access mode')
    return _hash(_projection(profile, access_mode))


def assess_profile(profile, probe, now_utc, *, max_age_seconds=300):
    """Assess detached supplied observations, retaining global inventory uncertainty."""
    validate_profile(profile)
    validate_probe(probe)
    now = _utc(now_utc, 'now_utc')
    if type(max_age_seconds) is not int or max_age_seconds < 1:
        raise ValueError('max_age_seconds must be positive integer')
    shared_match = (profile['repository'] == probe['repository']
                    and profile['source_ref'] == probe['source_ref']
                    and profile['setup']['fingerprint'] == probe['setup_fingerprint']
                    and profile['policy_digest'] == probe['policy_digest'])
    shared_known = profile['setup']['fingerprint'] is not None and profile['policy_digest'] is not None
    modes = {}
    reasons = [] if probe['inventory_complete'] else ['inventory_unknown']
    for mode in MODES:
        binding = _hash(_projection(profile, mode))
        obs = probe['access_modes'][mode]
        env = profile['environments'][mode]
        access = profile['access_modes'][mode]
        why = []
        status = 'UNKNOWN'
        if not access['configured'] or access['capability_ref'] is None:
            why.append('mode_not_configured_or_qualified')
        if not shared_known:
            why.append('shared_binding_unknown')
        if not shared_match:
            why.append('shared_binding_mismatch')
        if (probe['environments'][mode] != env
                or probe['environments'][mode]['provider_namespace'] != NAMESPACES[mode]):
            why.append('environment_binding_mismatch')
        if env['id'] is None or (mode != 'native_runtime' and env['label'] is None):
            why.append('environment_binding_unknown')
        if mode == 'native_runtime' and profile['control_host']['binding_ref'] is None:
            why.append('native_control_host_binding_unknown')
        if mode == 'official_cli':
            if any(profile['toolchain'][key] is None for key in ('cli_executable', 'cli_version')):
                why.append('cli_toolchain_unknown')
            if profile['toolchain']['cli_version'] != probe['cli_version']:
                why.append('cli_version_mismatch')
        if not obs['complete']:
            why.append('observation_incomplete')
        if obs['evidence_ref'] is None:
            why.append('observation_evidence_missing')
        if obs['binding_digest'] != binding:
            why.append('observation_binding_mismatch')
        age = (now - _utc(obs['observed_at_utc'], 'observation.observed_at_utc')).total_seconds()
        if age < 0:
            why.append('observation_future')
        if not why and age > max_age_seconds:
            status = 'STALE'
            why.append('observation_stale')
        elif not why:
            status = {'ready': 'READY', 'unavailable': 'UNAVAILABLE', 'unknown': 'UNKNOWN'}[obs['status']]
            if status != 'READY':
                why.append('observation_' + obs['status'])
        if obs['reason'] not in why:
            why.append(obs['reason'])
        modes[mode] = {'status': status, 'reasons': why, 'binding_digest': binding,
                       'evidence_ref': obs['evidence_ref']}
        reasons.extend(mode + ':' + reason for reason in why)
    statuses = [result['status'] for result in modes.values()]
    if all(status == 'READY' for status in statuses):
        aggregate = 'READY'
    elif 'READY' in statuses:
        aggregate = 'PARTIAL'
    elif 'STALE' in statuses:
        aggregate = 'STALE'
    else:
        aggregate = 'UNKNOWN'
    return {'status': aggregate, 'modes': modes, 'reasons': reasons,
            'profile_digest': _hash(profile), 'authorizes_external_start': False}
