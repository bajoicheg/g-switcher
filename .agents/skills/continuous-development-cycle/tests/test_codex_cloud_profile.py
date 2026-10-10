"""Synthetic qualification fixtures; no provider observation or release proof."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import codex_cloud_profile as m
except ModuleNotFoundError:
    m = None
MODES = ('native_runtime', 'official_ui', 'official_cli')
NAMESPACES = ('managed_cloud_runtime', 'codex_cloud_ui', 'codex_cloud_cli')
NOW = '2026-10-09T02:00:00Z'
DIGEST = 'sha256:' + 'a' * 64


def profile():
    return {'schema': 'codex-cloud-project-profile/v1', 'repository': 'owner/project',
            'source_ref': 'refs/heads/main',
            'environments': {mode: {'provider_namespace': ns, 'id': mode + '-1',
                                  'url': 'https://chatgpt.com/codex/environments/' + mode,
                                  'label': mode} for mode, ns in zip(MODES, NAMESPACES)},
            'control_host': {'kind': 'native_cloud', 'provider_namespace': 'managed_cloud_runtime',
                             'binding_ref': 'fixture:native-host'},
            'access_modes': {mode: {'configured': True, 'capability_ref': 'fixture:' + mode}
                             for mode in MODES},
            'toolchain': {'cli_executable': 'codex', 'cli_version': '1.0.0'},
            'setup': {'fingerprint': DIGEST, 'commands': [['python', '-c', 'print("two words")']]},
            'policy_digest': DIGEST, 'provenance': []}


def probe(p):
    return {'schema': 'cloud-profile-probe/v1', 'observed_at_utc': NOW,
            'inventory_complete': False, 'repository': p['repository'], 'source_ref': p['source_ref'],
            'environments': copy.deepcopy(p['environments']), 'setup_fingerprint': p['setup']['fingerprint'],
            'policy_digest': p['policy_digest'], 'cli_version': p['toolchain']['cli_version'],
            'access_modes': {mode: {'complete': True, 'status': 'ready', 'reason': 'fixture:authenticated',
                                    'evidence_ref': 'fixture:observation:' + mode,
                                    'binding_digest': m.profile_binding_digest(p, mode),
                                    'observed_at_utc': NOW} for mode in MODES}}


class Qualification(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(m, 'codex_cloud_profile interface is missing')
        self.p = profile()
        self.q = probe(self.p)

    def assess(self, p=None, q=None, **kw):
        return m.assess_profile(p or self.p, q or self.q, NOW, **kw)

    def test_native_survives_cli_401_and_unknown_inventory(self):
        self.q['access_modes']['official_cli'].update(status='unavailable', reason='CLI401')
        r = self.assess()
        self.assertEqual(r['status'], 'PARTIAL')
        self.assertEqual(r['modes']['native_runtime']['status'], 'READY')
        self.assertEqual(r['modes']['official_cli']['status'], 'UNAVAILABLE')
        self.assertFalse(r['authorizes_external_start'])
        self.assertEqual(set(r), {'status', 'modes', 'reasons', 'profile_digest', 'authorizes_external_start'})
        self.assertNotIn('codespace', json.dumps(r).lower())

    def test_all_modes_ready_without_global_inventory(self):
        self.assertEqual(self.assess()['status'], 'READY')

    def test_shared_changes_invalidate_each_mode(self):
        for change in ('repository', 'source_ref', 'setup', 'policy_digest'):
            with self.subTest(change=change):
                p = copy.deepcopy(self.p)
                if change == 'setup': p['setup']['fingerprint'] = 'sha256:' + 'b' * 64
                elif change == 'repository': p[change] = 'owner/other'
                elif change == 'source_ref': p[change] = 'refs/heads/other'
                else: p[change] = 'sha256:' + 'b' * 64
                self.assertEqual({v['status'] for v in self.assess(p=p)['modes'].values()}, {'UNKNOWN'})

    def test_cli_version_and_executable_change_only_invalidate_cli(self):
        for key, value in [('cli_version', '2.0.0'), ('cli_executable', '/tools/codex')]:
            p = copy.deepcopy(self.p); p['toolchain'][key] = value
            r = self.assess(p=p)
            self.assertEqual(r['modes']['official_cli']['status'], 'UNKNOWN')
            self.assertEqual(r['modes']['native_runtime']['status'], 'READY')
            self.assertEqual(r['modes']['official_ui']['status'], 'READY')

    def test_environment_changes_only_invalidate_affected_mode(self):
        for mode in MODES:
            p = copy.deepcopy(self.p); p['environments'][mode]['id'] += '-changed'
            r = self.assess(p=p)
            self.assertEqual(r['modes'][mode]['status'], 'UNKNOWN')
            for other in set(MODES) - {mode}:
                self.assertEqual(r['modes'][other]['status'], 'READY')

    def test_cross_namespace_probe_rejects_only_that_qualification(self):
        self.q['environments']['official_cli']['provider_namespace'] = 'managed_cloud_runtime'
        self.assertEqual(self.assess()['modes']['official_cli']['status'], 'UNKNOWN')
        self.assertEqual(self.assess()['modes']['native_runtime']['status'], 'READY')

    def test_control_host_change_only_invalidates_native(self):
        p = copy.deepcopy(self.p); p['control_host']['binding_ref'] = 'fixture:another'
        self.assertEqual(self.assess(p=p)['modes']['native_runtime']['status'], 'UNKNOWN')
        self.assertEqual(self.assess(p=p)['modes']['official_cli']['status'], 'READY')

    def test_freshness_boundary_future_incomplete_and_missing_evidence(self):
        for updates, expected in [({'observed_at_utc': '2026-10-09T01:55:00Z'}, 'READY'),
                                  ({'observed_at_utc': '2026-10-09T01:54:59Z'}, 'STALE'),
                                  ({'observed_at_utc': '2026-10-09T02:00:01Z'}, 'UNKNOWN'),
                                  ({'complete': False}, 'UNKNOWN'),
                                  ({'evidence_ref': None}, 'UNKNOWN'),
                                  ({'binding_digest': None}, 'UNKNOWN')]:
            with self.subTest(updates=updates):
                q = copy.deepcopy(self.q); q['access_modes']['native_runtime'].update(updates)
                self.assertEqual(self.assess(q=q)['modes']['native_runtime']['status'], expected)
                self.assertEqual(self.assess(q=q)['modes']['official_cli']['status'], 'READY')

    def test_stale_unavailable_is_not_current_unavailability(self):
        for obs in self.q['access_modes'].values():
            obs.update(status='unavailable', observed_at_utc='2026-10-09T01:00:00Z')
        self.assertEqual(self.assess()['status'], 'STALE')
        self.assertEqual({v['status'] for v in self.assess()['modes'].values()}, {'STALE'})

    def test_new_genuine_observation_supersedes_unavailable(self):
        self.q['access_modes']['official_cli']['status'] = 'unavailable'
        self.assertEqual(self.assess()['modes']['official_cli']['status'], 'UNAVAILABLE')
        self.q['access_modes']['official_cli'].update(status='ready', evidence_ref='fixture:new-proof')
        self.assertEqual(self.assess()['modes']['official_cli']['status'], 'READY')

    def test_unknown_template_is_valid_and_unqualified(self):
        template = json.loads((ROOT / 'templates' / 'codex-cloud-profile.json').read_text())
        m.validate_profile(template)
        q = probe(template)
        self.assertEqual(m.assess_profile(template, q, NOW)['status'], 'UNKNOWN')
        for mode in MODES:
            self.assertFalse(template['access_modes'][mode]['configured'])
            self.assertIsNone(template['environments'][mode]['id'])
            self.assertIsNone(template['access_modes'][mode]['capability_ref'])

    def test_null_cli_fields_do_not_erase_native(self):
        p = copy.deepcopy(self.p)
        p['toolchain'].update(cli_version=None, cli_executable=None)
        p['environments']['official_cli'].update(id=None, url=None, label=None)
        p['access_modes']['official_cli'].update(configured=False, capability_ref=None)
        m.validate_profile(p)
        self.assertEqual(self.assess(p=p)['modes']['native_runtime']['status'], 'READY')
        self.assertEqual(self.assess(p=p)['modes']['official_cli']['status'], 'UNKNOWN')

    def test_exact_argv_roundtrip_and_no_input_mutation(self):
        p = copy.deepcopy(self.p)
        p['setup']['commands'] = [['python', '-c', 'print("привет two words")', '--path=x y']]
        original = copy.deepcopy(p)
        self.assertIs(m.validate_profile(p), p)
        self.assess(p=p)
        self.assertEqual(p, original)
        for bad in ['', ' padded', 'padded ', 'a\0b']:
            p = copy.deepcopy(original); p['setup']['commands'][0].append(bad)
            with self.assertRaises(ValueError): m.validate_profile(p)

    def test_digest_is_canonical_utf8_and_mode_only(self):
        p = copy.deepcopy(self.p); p['environments']['official_ui']['label'] = 'Окно'
        self.assertEqual(m.profile_binding_digest(p, 'native_runtime'),
                         m.profile_binding_digest(self.p, 'native_runtime'))
        self.assertNotEqual(m.profile_binding_digest(p, 'official_ui'),
                            m.profile_binding_digest(self.p, 'official_ui'))
        whole = 'sha256:' + hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':'),
                                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        self.assertEqual(self.assess(p=p)['profile_digest'], whole)
        with self.assertRaises(ValueError): m.profile_binding_digest(p, 'invented')

    def test_strict_unknown_keys_types_credentials_and_public_hosts(self):
        mutators = [lambda p: p.update(token='secret'),
                    lambda p: p['environments']['native_runtime'].update(password='secret'),
                    lambda p: p['control_host'].update(binding_ref=True),
                    lambda p: p['access_modes']['native_runtime'].update(configured=1),
                    lambda p: p.update(source_ref='main'),
                    lambda p: p.update(policy_digest='a' * 64),
                    lambda p: p.update(repository='https://u:p@github.com/owner/project'),
                    lambda p: p['environments']['official_cli'].update(url='https://u:p@chatgpt.com/x'),
                    lambda p: p['environments']['official_cli'].update(url='https://chatgpt.com.evil/x'),
                    lambda p: p['environments']['official_cli'].update(url='https://chatgpt.com/x?token=secret'),
                    lambda p: p['environments']['official_cli'].update(provider_namespace='managed_cloud_runtime'),
                    lambda p: p.update(provenance=[{'field': 'repository', 'evidence_ref': 'fixture:r',
                                                   'evidence_sha256': 'a' * 64,
                                                   'qualified_at_utc': '2026-10-09T02:00:00'}])]
        for mutate in mutators:
            p = copy.deepcopy(self.p); mutate(p)
            with self.subTest(p=p), self.assertRaises(ValueError): m.validate_profile(p)

    def test_native_deconfigured_even_with_matching_evidence_is_unknown(self):
        for update in ({'configured': False}, {'capability_ref': None}):
            p = copy.deepcopy(self.p); p['access_modes']['native_runtime'].update(update)
            self.assertEqual(self.assess(p=p)['modes']['native_runtime']['status'], 'UNKNOWN')
            self.assertEqual(self.assess(p=p)['modes']['official_cli']['status'], 'READY')

    def test_shared_unknown_cannot_qualify_even_matching_digest(self):
        for group, key in [('setup', 'fingerprint'), (None, 'policy_digest')]:
            p = copy.deepcopy(self.p)
            (p[group] if group else p)[key] = None
            q = probe(p)
            self.assertEqual({v['status'] for v in self.assess(p=p, q=q)['modes'].values()}, {'UNKNOWN'})

    def test_provenance_is_strict_and_not_reusable_mode_authority(self):
        entry = {'field': 'repository', 'evidence_ref': 'fixture:r',
                 'evidence_sha256': 'b' * 64, 'qualified_at_utc': NOW}
        self.p['provenance'] = [entry]
        self.assertIs(m.validate_profile(self.p), self.p)
        self.q['access_modes']['native_runtime']['complete'] = False
        self.assertEqual(self.assess()['modes']['native_runtime']['status'], 'UNKNOWN')
        for entries in [[entry, entry], [dict(entry, field='arbitrary')],
                        [dict(entry, evidence_sha256=DIGEST)], [dict(entry, secret='x')]]:
            p = copy.deepcopy(self.p); p['provenance'] = entries
            with self.assertRaises(ValueError): m.validate_profile(p)

    def test_mode_binding_exact_native_canonical_projection(self):
        expected = {'shared': {'repository': self.p['repository'], 'source_ref': self.p['source_ref'],
                               'setup_fingerprint': self.p['setup']['fingerprint'],
                               'policy_digest': self.p['policy_digest']},
                    'access_mode': 'native_runtime',
                    'mode_projection': {'environment': self.p['environments']['native_runtime'],
                                        'control_host': self.p['control_host']}}
        digest = 'sha256:' + hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(',', ':'),
                                                      ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        self.assertEqual(m.profile_binding_digest(self.p, 'native_runtime'), digest)

    def test_structural_non_json_values_raise_value_error(self):
        for field, value in [('repository', []), ('source_ref', None), ('policy_digest', {}),
                             ('provenance', None), ('access_modes', [])]:
            p = copy.deepcopy(self.p); p[field] = value
            with self.assertRaises(ValueError): m.validate_profile(p)
        for status in [[], {}, None, 1]:
            q = copy.deepcopy(self.q); q['access_modes']['native_runtime']['status'] = status
            with self.assertRaises(ValueError): self.assess(q=q)

    def test_strict_probe_and_clock_validation(self):
        mutators = [lambda q: q.update(secret='x'),
                    lambda q: q['access_modes']['official_cli'].update(complete=1),
                    lambda q: q['access_modes']['official_cli'].update(status='READY'),
                    lambda q: q['access_modes']['official_cli'].update(observed_at_utc='yesterday'),
                    lambda q: q['environments']['native_runtime'].update(extra=None)]
        for mutate in mutators:
            q = copy.deepcopy(self.q); mutate(q)
            with self.assertRaises(ValueError): self.assess(q=q)
        for age in [True, 0, -1, 1.5]:
            with self.assertRaises(ValueError): self.assess(max_age_seconds=age)
        with self.assertRaises(ValueError): m.assess_profile(self.p, self.q, '2026-10-09T02:00:00')


if __name__ == '__main__':
    unittest.main()
