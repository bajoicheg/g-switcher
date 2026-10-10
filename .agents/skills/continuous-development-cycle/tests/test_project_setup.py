"""User-visible planner contracts; changing platform/authority/preservation breaks these."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from contracts import load_yaml
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24
import yaml
import project_setup


def init_request(preset='portable'):
    return dict(schema='cdc-init-request/v1', repository='owner/project',
                branch='feature/setup', source_head='a' * 40, preset=preset,
                validation=dict(quick='python -B quick.py', full='python -B full.py',
                                release='python -B release.py'), cloud_profile_json=None)


def invoke(command, request):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'request.json'
        path.write_text(json.dumps(request))
        before = set(Path(directory).iterdir())
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/cdc.py'),
                                 command, str(path)], cwd=directory,
                                capture_output=True, text=True)
        if set(Path(directory).iterdir()) != before:
            raise AssertionError('planner wrote files in caller workspace')
        return result


class InitCLITests(unittest.TestCase):
    def initialize(self, request):
        result = invoke('init', request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_each_preset_generates_valid_adapter_and_checkpoint(self):
        for preset, quality, platform in [('portable', 'MEDIUM', 'any'),
                                          ('windows', 'MEDIUM', 'windows'),
                                          ('android', 'MEDIUM', 'android'),
                                          ('critical', 'FULL', 'any')]:
            with self.subTest(preset=preset):
                value = self.initialize(init_request(preset))
                files = {item['path']: item['content'] for item in value['files']}
                with tempfile.TemporaryDirectory() as directory:
                    adapter_file = Path(directory) / 'adapter.yaml'
                    checkpoint_file = Path(directory) / 'checkpoint.md'
                    adapter_file.write_text(files['docs/development-cycle.yaml'])
                    checkpoint_file.write_text(files['docs/work-status/current.md'])
                    adapter = load_yaml(adapter_file)
                    checkpoint = load_yaml(checkpoint_file, frontmatter=True)
                    binding = validate_adapter(adapter)
                    validate_checkpoint_24(checkpoint, adapter)
                self.assertEqual(adapter['quality']['default_level'], quality)
                self.assertEqual(adapter['validation']['final_platform'], platform)
                self.assertEqual(checkpoint['repository'], 'owner/project')
                self.assertEqual(checkpoint['branch'], 'feature/setup')
                self.assertEqual(checkpoint['candidate_sha'], 'a' * 40)
                self.assertEqual(checkpoint['policy_digest'], binding['policy_digest'])
                self.assertEqual(checkpoint['phase'], 'recovery')
                self.assertEqual(checkpoint['lease_state'], 'released')
                self.assertIsNone(checkpoint['operation_key'])
                self.assertEqual(checkpoint['last_green_evidence'], '')
                self.assertFalse(adapter['watchdog']['enabled'])
                self.assertEqual(adapter['ci']['actions_budget'], 'conserve')
                self.assertFalse(any(v for k, v in value.items() if k.startswith('authorizes_')))

    def test_validation_commands_are_literal_unexecuted_data(self):
        request = init_request()
        request['validation']['full'] = 'touch SENTINEL; $(touch OTHER); `touch THIRD`'
        result = self.initialize(request)
        self.assertIn(request['validation']['full'], str(result['files']))

    def test_invalid_preset_identity_or_missing_full_command_is_rejected(self):
        for field, bad in [('repository', '../project'), ('branch', '../main'),
                            ('source_head', 'abcd'), ('preset', 'unknown')]:
            with self.subTest(field=field):
                request = init_request(); request[field] = bad
                self.assertNotEqual(invoke('init', request).returncode, 0)
        request = init_request(); request['validation']['full'] = ''
        self.assertNotEqual(invoke('init', request).returncode, 0)

    def test_duplicate_json_keys_are_rejected_before_planning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text('{"schema":"cdc-init-request/v1","schema":"other"}')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/cdc.py'),
                                     'init', str(path)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate JSON field', result.stderr)


class ProjectMigrationTests(unittest.TestCase):
    def setUp(self):
        result = project_setup.initialize(init_request())
        self.files = {f['path']: f['content'] for f in result['files']}
        self.request = dict(schema='cdc-migrate-request/v1',
                            current_adapter_yaml=self.files['docs/development-cycle.yaml'],
                            current_checkpoint_markdown=self.files['docs/work-status/current.md'],
                            cloud_profile_json=None, preset='portable',
                            expected_source_head='a' * 40,
                            probe=dict(source_head='a' * 40, observed_at_utc='2026-10-10T00:00:00Z',
                                       lease_released=True, guard_reconciled=True))
        self.now = '2026-10-10T00:00:01Z'

    def migrate(self, request=None, now=None):
        self.assertTrue(callable(getattr(project_setup, 'migrate', None)), 'migration planner must exist')
        return project_setup.migrate(request or self.request, now_utc=now or self.now)

    def documents(self):
        adapter = yaml.safe_load(self.request['current_adapter_yaml'])
        cp = yaml.safe_load(self.request['current_checkpoint_markdown'].split('---\n', 2)[1])
        body = self.request['current_checkpoint_markdown'].split('\n---', 1)[1]
        return adapter, cp, body

    def update_documents(self, adapter, cp, body):
        cp['policy_revision'] = adapter['policy']['revision']
        cp['policy_digest'] = validate_adapter(adapter, skill_version='2.11.3')['policy_digest']
        self.request['current_adapter_yaml'] = yaml.safe_dump(adapter, sort_keys=False)
        self.request['current_checkpoint_markdown'] = '---\n' + yaml.safe_dump(cp, sort_keys=False) + '---' + body

    def result_documents(self, result):
        files = {f['path']: f['content'] for f in result['files']}
        adapter = yaml.safe_load(files['docs/development-cycle.yaml'])
        cp = yaml.safe_load(files['docs/work-status/current.md'].split('---\n', 2)[1])
        return files, adapter, cp

    def test_custom_checkpoint_path_is_rejected_before_fixed_path_proposal(self):
        adapter, cp, body = self.documents()
        adapter['checkpoint']['path'] = 'state/custom.md'
        self.update_documents(adapter, cp, body)
        self.request['preset'] = 'critical'
        with self.assertRaisesRegex(ValueError, 'checkpoint path'): self.migrate()

    def test_recovery_without_binding_still_validates_supplied_cloud_profile(self):
        adapter, cp, body = self.documents()
        cp['policy_digest'] = None
        self.request['current_checkpoint_markdown'] = '---\n' + yaml.safe_dump(cp) + '---' + body
        wrong = json.loads(self.files['docs/cdc-cloud-profile.json'])
        wrong['repository'] = 'other/project'
        for text in ('malformed', '{"schema":"one","schema":"two"}', json.dumps(wrong)):
            with self.subTest(text=text):
                self.request['cloud_profile_json'] = text
                with self.assertRaises(ValueError): self.migrate()
        self.request['cloud_profile_json'] = self.files['docs/cdc-cloud-profile.json']
        result = self.migrate()
        self.assertEqual(result['action'], 'RECONCILE')
        self.assertEqual(result['files'], [])
        self.assertEqual(result['cloud_reuse']['status'], 'REQUALIFY')

    def test_keyless_partial_external_markers_are_retained_and_block_files(self):
        for key, value in (('waiting_external_kind', 'compute'),
                           ('waiting_external_id', 'saved-task'),
                           ('waiting_external_sha', 'a' * 40),
                           ('operation_intent_ref', 'git:saved-intent')):
            with self.subTest(key=key):
                adapter, cp, body = self.documents()
                cp[key] = value
                self.update_documents(adapter, cp, body)
                self.request['preset'] = 'critical'
                result = self.migrate()
                self.assertEqual(result['action'], 'WAIT')
                self.assertEqual(result['files'], [])
                output_key = {'waiting_external_kind': 'kind', 'waiting_external_id': 'id',
                              'waiting_external_sha': 'sha', 'operation_intent_ref': 'intent_ref'}[key]
                self.assertEqual(result['existing_operation'][output_key], value)
                self.request['current_checkpoint_markdown'] = self.files['docs/work-status/current.md']
                self.request['current_adapter_yaml'] = self.files['docs/development-cycle.yaml']

    def test_migrate_cli_uses_its_own_fresh_clock(self):
        request = copy.deepcopy(self.request)
        request['probe']['observed_at_utc'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        result = invoke('migrate', request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['action'], 'NOOP')

    def test_wrong_probe_types_and_duplicate_yaml_cannot_produce_artifacts(self):
        request = copy.deepcopy(self.request)
        request['probe']['lease_released'] = 'true'
        with self.assertRaises(ValueError): self.migrate(request)
        request = copy.deepcopy(self.request)
        request['current_adapter_yaml'] += '\nrepository: {}\n'
        with self.assertRaises(ValueError): self.migrate(request)
        request['current_adapter_yaml'] = 'one: &shared {}\ntwo: *shared\n'
        with self.assertRaises(ValueError): self.migrate(request)

    def test_noop_preserves_exact_bytes_and_never_mutates_request(self):
        original = copy.deepcopy(self.request)
        result = self.migrate()
        self.assertEqual(result['action'], 'NOOP')
        self.assertEqual(result['changed_paths'], [])
        self.assertEqual(self.result_documents(result)[0]['docs/development-cycle.yaml'], original['current_adapter_yaml'])
        self.assertEqual(self.result_documents(result)[0]['docs/work-status/current.md'], original['current_checkpoint_markdown'])
        self.assertEqual(self.request, original)
        self.assertFalse(any(v for k, v in result.items() if k.startswith('authorizes_')))

    def test_change_preserves_neighbor_controls_history_and_markdown_body(self):
        adapter, cp, body = self.documents()
        adapter['watchdog']['enabled'] = False
        adapter['orchestration']['budget']['task_limits']['ci_starts'] = 0
        cp.update(last_ci_run_id='old-run', last_ci_status='unknown',
                  last_green_evidence='old-evidence', release_state='released',
                  release_version='2.12.1', release_candidate_sha='b' * 40)
        body += '\nHistorical owner pause, unresolved charged attempts, original report.\n'
        self.update_documents(adapter, cp, body)
        self.request['preset'] = 'critical'
        result = self.migrate()
        self.assertEqual(result['action'], 'APPLY')
        files, proposed, rebound = self.result_documents(result)
        for key in set(adapter) - {'quality', 'policy'}:
            self.assertEqual(proposed[key], adapter[key], key)
        for key in set(cp) - {'policy_revision', 'policy_digest'}:
            self.assertEqual(rebound[key], cp[key], key)
        self.assertTrue(files['docs/work-status/current.md'].endswith(body))
        validate_checkpoint_24(rebound, proposed)
        self.assertEqual(proposed['policy']['revision'], '2')
        self.request.update(current_adapter_yaml=files['docs/development-cycle.yaml'],
                            current_checkpoint_markdown=files['docs/work-status/current.md'])
        self.assertEqual(self.migrate()['action'], 'NOOP')

    def test_full_and_missing_legacy_quality_cannot_be_reduced(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                adapter, cp, body = self.documents()
                if missing: adapter.pop('quality', None)
                else: adapter['quality']['default_level'] = 'FULL'
                self.update_documents(adapter, cp, body)
                proposed = self.result_documents(self.migrate())[1]
                self.assertEqual(proposed['quality']['default_level'], 'FULL')

    def test_platform_cannot_be_downgraded_or_swapped(self):
        adapter, cp, body = self.documents()
        adapter['validation']['final_platform'] = 'windows'
        self.update_documents(adapter, cp, body)
        self.assertEqual(self.result_documents(self.migrate())[1]['validation']['final_platform'], 'windows')
        self.request['preset'] = 'android'
        result = self.migrate()
        self.assertEqual(result['action'], 'CONFLICT')
        self.assertEqual(result['files'], [])

    def test_stale_future_and_source_drift_generate_no_files(self):
        for source, now in [('b' * 40, self.now), ('a' * 40, '2026-10-10T00:02:00Z'),
                            ('a' * 40, '2026-10-09T23:59:00Z')]:
            with self.subTest(source=source, now=now):
                self.request['probe']['source_head'] = source
                result = self.migrate(now=now)
                self.assertEqual(result['action'], 'RECONCILE')
                self.assertEqual(result['files'], [])

    def test_guard_or_unreleased_probe_requires_wait(self):
        for key in ('guard_reconciled', 'lease_released'):
            request = copy.deepcopy(self.request); request['probe'][key] = False
            result = self.migrate(request)
            self.assertEqual(result['action'], 'WAIT')
            self.assertEqual(result['files'], [])

    def test_external_identity_survives_combined_stale_source_drift(self):
        adapter, cp, body = self.documents()
        cp.update(lease_state='waiting_external', phase='waiting_external',
                  observed_at_utc='2026-10-10T00:00:00Z',
                  waiting_external_kind='compute', waiting_external_id='existing-id',
                  waiting_external_sha='a' * 40, operation_intent_ref='git:old-intent',
                  operation_key='sha256:' + '1' * 64)
        cp['execution_continuity']['completion_gate'] = 'durable_external_binding'
        self.update_documents(adapter, cp, body)
        self.assertEqual(self.migrate()['action'], 'WAIT')
        self.request['probe']['source_head'] = 'b' * 40
        result = self.migrate(now='2026-10-10T00:05:00Z')
        self.assertEqual(result['action'], 'RECONCILE')
        self.assertEqual(result['existing_operation']['id'], 'existing-id')
        self.assertEqual(result['existing_operation']['operation_key'], cp['operation_key'])
        self.assertEqual(result['files'], [])

    def test_archived_ceiling_is_diagnostic_only_and_proposal_validates(self):
        adapter, cp, body = self.documents()
        adapter['policy']['skill_max_version_exclusive'] = '3.0.0'
        self.update_documents(adapter, cp, body)
        with self.assertRaises(ValueError): validate_checkpoint_24(cp, adapter)
        result = self.migrate()
        self.assertFalse(result['original_compatibility']['original_target_compatible'])
        self.assertEqual(result['original_compatibility']['diagnostic_version'], '2.11.3')
        files, proposed, rebound = self.result_documents(result)
        self.assertEqual(proposed['policy']['skill_max_version_exclusive'], '4.0.0')
        self.assertEqual(proposed['policy']['skill_min_version'], adapter['policy']['skill_min_version'])
        validate_checkpoint_24(rebound, proposed)
        with self.assertRaises(ValueError): validate_checkpoint_24(cp, adapter)

    def test_stale_checkpoint_binding_cannot_be_rebound_silently(self):
        self.request['current_adapter_yaml'] += '\n# comment\n'
        adapter, cp, body = self.documents()
        adapter['watchdog']['enabled'] = not adapter['watchdog']['enabled']
        self.request['current_adapter_yaml'] = yaml.safe_dump(adapter)
        with self.assertRaises(ValueError): self.migrate()

    def test_nondecimal_revision_requires_explicit_reviewed_choice(self):
        adapter, cp, body = self.documents()
        adapter['policy']['revision'] = 'owner-v7'
        self.update_documents(adapter, cp, body)
        self.assertEqual(self.migrate()['action'], 'NOOP')
        self.request['preset'] = 'critical'
        with self.assertRaisesRegex(ValueError, 'revision'): self.migrate()

    def test_reused_cloud_profile_bytes_survive_policy_change(self):
        text = self.files['docs/cdc-cloud-profile.json'] + '  \n'
        self.request['cloud_profile_json'] = text
        self.request['preset'] = 'critical'
        result = self.migrate()
        self.assertEqual(result['cloud_reuse']['status'], 'REQUALIFY')
        self.assertEqual(self.result_documents(result)[0]['docs/cdc-cloud-profile.json'], text)
        wrong = json.loads(text); wrong['repository'] = 'other/project'
        self.request['cloud_profile_json'] = json.dumps(wrong)
        with self.assertRaises(ValueError): self.migrate()

    def test_initializer_cloud_reuse_is_exact_and_not_current_capability(self):
        request = init_request()
        request['cloud_profile_json'] = self.files['docs/cdc-cloud-profile.json'] + '\n'
        result = project_setup.initialize(request)
        files = {f['path']: f['content'] for f in result['files']}
        self.assertEqual(files['docs/cdc-cloud-profile.json'], request['cloud_profile_json'])
        self.assertEqual(result['cloud_reuse']['status'], 'REUSE_PENDING_FRESH_PROBE')
        self.assertFalse(result['authorizes_external_start'])

    def test_inert_cloud_input_scaffold_cannot_start_prepare(self):
        text = self.files['docs/cdc-cloud-entry-inputs.template.json']
        value = json.loads(text)
        self.assertEqual(value['configuration_status'], 'UNCONFIGURED')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'profile.json'; profile.write_text(self.files['docs/cdc-cloud-profile.json'])
            inputs = root / 'inputs.json'; inputs.write_text(text)
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/codex_cloud_entrypoint.py'),
                                     'prepare', '--profile', str(profile), '--inputs', str(inputs),
                                     '--project-root', str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('READY_FOR_SUBMIT', result.stdout)

    def test_optional_diagnostic_version_preserves_default_rejection(self):
        adapter, cp, body = self.documents()
        adapter['policy']['skill_max_version_exclusive'] = '3.0.0'
        self.update_documents(adapter, cp, body)
        self.assertTrue(callable(getattr(project_setup, 'migrate', None)), 'migration planner must exist')
        validate_checkpoint_24(cp, adapter, skill_version='2.11.3')
        with self.assertRaises(ValueError): validate_checkpoint_24(cp, adapter)


if __name__ == '__main__': unittest.main()
