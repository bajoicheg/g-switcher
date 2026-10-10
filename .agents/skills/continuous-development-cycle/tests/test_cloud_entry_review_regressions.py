"""Synthetic read-only counterexamples found during independent release review."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_cloud_entrypoint as entry
import codex_cloud_profile as profile
import test_codex_cloud_entrypoint as fixture
from test_recovery_recipes_v2 import B, C, DIAG, H


def recovery_values():
    values = fixture.fixtures()
    p, c, _, _, _, _ = values
    bindings = copy.deepcopy(B)
    bindings.update(repository=c['repository'], environment_id=p['environments']['native_runtime']['id'],
                    policy_digest=p['policy_digest'], input_digests={
                        'cloud-profile:native_runtime': profile.profile_binding_digest(p, 'native_runtime')})
    history = copy.deepcopy(H)
    history['repository'] = c['repository']
    c['recovery'].update(catalog_ref='fixture:catalog', catalog=copy.deepcopy(C), diagnosis=copy.deepcopy(DIAG),
                         history_ref='fixture:history', history=history, bindings=bindings)
    return values


def remote_values():
    values = list(fixture.fixtures())
    p, c, q, registry, _, old_route = values
    c['access_mode'] = 'official_cli'
    q['access_modes']['official_cli']['status'] = 'ready'
    c['live_recovery']['provider'] = copy.deepcopy(c['live_recovery']['source'])
    c['intent'] = {'operation_key': fixture.KEY, 'attempt_id': 'synthetic-reviewed-ready',
                   'intent_ref': 'fixture:intent', 'intent_digest': 'sha256:' + '5' * 64,
                   'request_binding_digest': 'sha256:' + '6' * 64}
    c['intent']['request_binding_digest'] = entry._hash(entry._request(p, c))
    c['routing_request'] = {'schema': 'capability-request/v1', 'task_id': c['task_id'],
                            'candidate_sha': c['exact_sha'], 'required_capabilities': ['python:3'],
                            'preferred_kinds': ['codex_compute'], 'forbidden_backend_ids': [],
                            'required_backend_id': 'codex', 'max_registry_age_seconds': 300}
    backend = registry['backends'][0]
    env = p['environments']['official_cli']
    values[-1] = {'schema': 'compute-cost-context/v2', 'base_context': old_route,
                  'provider_bindings': {'schema': 'backend-provider-bindings/v1', 'bindings': [{
                      'backend_id': backend['backend_id'], 'provider_namespace': env['provider_namespace'],
                      'provider_kind': 'codex_cloud', 'environment_id': env['id'],
                      'configuration_digest': backend['configuration_digest'],
                      'evidence_ref': 'fixture:qualified-cli-backend', 'evidence_digest': 'sha256:' + '7' * 64}]},
                  'codespace_exception': None, 'provider_action': {
                      'backend_id': backend['backend_id'], 'provider_namespace': env['provider_namespace'],
                      'provider_kind': 'codex_cloud', 'environment_id': env['id'],
                      'consumption': 'compute_backend', 'action': 'create',
                      'control_host_ref': None, 'compute_backend_ref': 'fixture:qualified-cli-backend'}}
    return values


class RecoveryQualificationTests(unittest.TestCase):
    def test_current_profile_binding_allows_bounded_diagnostic(self):
        result = entry.prepare(*recovery_values(), fixture.NOW)
        self.assertEqual(result['action'], 'CONTINUE_NATIVE')
        self.assertEqual(result['recovery_decision']['action_plan']['handler'], 'inspect_exact_invocation')

    def test_requalified_setup_cannot_reuse_old_recovery_profile(self):
        values = recovery_values()
        p, _, q, *_ = values
        p['setup']['fingerprint'] = 'sha256:' + '8' * 64
        q['setup_fingerprint'] = p['setup']['fingerprint']
        q['access_modes']['native_runtime']['binding_digest'] = profile.profile_binding_digest(p, 'native_runtime')
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')

    def test_requalified_policy_cannot_reuse_old_recovery_subject(self):
        values = recovery_values()
        p, c, q, *_ = values
        p['policy_digest'] = q['policy_digest'] = 'sha256:' + '9' * 64
        q['access_modes']['native_runtime']['binding_digest'] = profile.profile_binding_digest(p, 'native_runtime')
        c['recovery']['bindings']['input_digests']['cloud-profile:native_runtime'] = profile.profile_binding_digest(p, 'native_runtime')
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')

    def test_missing_current_recovery_profile_proof_fails_closed(self):
        values = recovery_values()
        values[1]['recovery']['bindings']['input_digests'].pop('cloud-profile:native_runtime')
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')


class CapsuleEffectTests(unittest.TestCase):
    def values(self):
        values = fixture.fixtures()
        c = values[1]
        capsule = json.loads((Path(__file__).resolve().parents[1] / 'templates/resume-capsule.json').read_text())
        capsule.update(repository=c['repository'], source_ref=c['source_ref'], head_sha=c['exact_sha'], updated_at_utc=fixture.NOW)
        capsule['external'] = {'kind': 'codex_cloud', 'id': 'existing-task', 'sha': c['exact_sha'],
                               'operation_key': fixture.KEY, 'state': 'running'}
        c['resume_capsule'] = capsule
        return values

    def test_capsule_effect_precedes_fresh_absence_and_native_check(self):
        result = entry.prepare(*self.values(), fixture.NOW)
        self.assertEqual(result['action'], 'RECONCILE_EXISTING')
        self.assertEqual(result['operation_key'], fixture.KEY)
        self.assertEqual(result['task_id'], 'existing-task')
        self.assertIsNone(result['request'])

    def test_conflicting_capsule_and_journal_keys_cannot_observe_one_as_settled(self):
        values = self.values()
        r = values[1]['restored']
        other = 'sha256:' + 'b' * 64
        r.update(mode='COMPUTE_ONLY', operation_key=other, journal_state='running',
                 journal_ref='fixture:journal', journal_digest='sha256:' + 'c' * 64, task_id='other-task')
        r['lookup'].update(operation_key=other)
        result = entry.prepare(*values, fixture.NOW)
        self.assertEqual(result['action'], 'RECONCILE_EXISTING')
        self.assertEqual(result['operation_key'], other)
        self.assertIsNone(result['request'])


class RemoteRoutingTests(unittest.TestCase):
    def test_unqualified_executable_rejected_before_adapter_or_launch_callback(self):
        values = remote_values()
        prepared = entry.prepare(*values, fixture.NOW)
        calls = []
        class DifferentCLI(entry.cli.CodexCloudCLI):
            def submit(self, request, *, launch_authorized):
                calls.append('adapter')
                return {'unexpected': True}
        with tempfile.TemporaryDirectory() as root:
            adapter = DifferentCLI(root, executable='different-codex')
            fresh = dict(zip(('profile','context','probe','registry','routing_policy','routing_context'), values))
            fresh['schema'] = 'cloud-entrypoint-preflight/v1'
            with self.assertRaises(ValueError):
                entry.submit(prepared, adapter, read_preflight=lambda: fresh,
                             launch_authorized=lambda: calls.append('launch'), clock=lambda: fixture.NOW)
        self.assertEqual(calls, [])

    def test_qualified_exact_cli_backend_can_prepare_without_authority(self):
        result = entry.prepare(*remote_values(), fixture.NOW)
        self.assertEqual(result['action'], 'READY_FOR_SUBMIT')
        self.assertFalse(any(result['authorities'].values()))

    def test_empty_registry_blocks_remote_ready(self):
        values = remote_values()
        values[3]['backends'] = []
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')

    def test_stale_registry_blocks_remote_ready(self):
        values = remote_values()
        values[3]['observed_at_utc'] = '2026-10-08T02:00:00Z'
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')

    def test_product_failure_policy_blocks_remote_ready(self):
        values = remote_values()
        values[-1]['base_context']['primary_failure_class'] = 'product'
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')

    def test_legacy_routing_context_is_not_cli_provider_binding(self):
        values = remote_values()
        values[-1] = values[-1]['base_context']
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')

    def test_missing_explicit_routing_request_fails_closed(self):
        values = remote_values()
        values[1].pop('routing_request')
        self.assertEqual(entry.prepare(*values, fixture.NOW)['action'], 'BLOCKED')


class HandoffRecipeTests(unittest.TestCase):
    def handoff(self):
        from test_cloud_handoff_bindings import handoff
        from test_recovery_recipes_v2 import R
        recipe = copy.deepcopy(R)
        recipe['actions'] = ['resume_next_action']
        selected = entry.recipes._result('apply_recipe', 'verified_evidence_reused', recipe=recipe,
                                         steps=['resume_next_action'])
        diagnosis = dict(DIAG, code=recipe['diagnosis_code'])
        plan = entry.recipes.action_plan(selected, diagnosis, B, H,
                                         {'next_action_ref': 'fixture:check', 'evidence_ref': 'fixture:proof'})
        h = handoff()
        h['recovery_history_ref'] = 'fixture:history'
        h['next_action'].update(handler='execute_existing_recovery_plan', parameters={'decision': {
            'status': 'PLANNED', 'reason': selected['reason'], 'selection': selected, 'action_plan': plan,
            'history_ref': 'fixture:history', 'history_digest': entry._hash(H),
            'new_signal_ref': None, 'completed_correction_ref': None}})
        return h

    def test_verified_reuse_cannot_serialize_a_repeated_diagnostic(self):
        h = self.handoff()
        self.assertEqual(entry.validate_handoff(h), h)
        decision = h['next_action']['parameters']['decision']
        decision['selection']['steps'] = ['inspect_exact_invocation']
        decision['action_plan'].update(handler='inspect_exact_invocation', parameters={
            'invocation_ref': 'fixture:invocation', 'error_evidence_ref': 'fixture:error',
            'approved_read_argv': ['python', '-V'], 'diagnostic_limit': 1})
        with self.assertRaises(ValueError):
            entry.validate_handoff(h)

    def test_plan_verification_cannot_discard_recipe_required_facts(self):
        h = self.handoff()
        h['next_action']['parameters']['decision']['action_plan']['verification']['required_facts'] = []
        with self.assertRaises(ValueError):
            entry.validate_handoff(h)


if __name__ == '__main__':
    unittest.main()
