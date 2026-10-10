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
SCRIPT = ROOT / 'scripts/cdc.py'
sys.path.insert(0, str(ROOT / 'scripts'))
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('cdc_entrypoint', SCRIPT)
    cdc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cdc)
else:
    cdc = None


class ResumeEntryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cdc, 'unified CDC entry point must exist')
        self.cap = json.loads((ROOT / 'templates/resume-capsule.json').read_text())
        self.cap['task']['blocker'] = None
        self.cap['health']['state'] = 'HEALTHY'
        self.probe = dict(schema='resume-probe/v1', observed_at_utc='2026-01-01T00:01:00Z',
                          complete=True, lease_revision=self.cap['ownership']['revision'])
        for key in ('repository', 'source_ref', 'head_sha', 'policy_version',
                    'policy_revision', 'policy_digest', 'checkpoint_digest'):
            self.probe[key] = self.cap[key]
        self.now = '2026-01-01T00:01:00Z'

    def assess(self, **kwargs):
        return cdc.resume(self.cap, self.probe, now_utc=self.now, **kwargs)

    def test_fresh_matching_probe_returns_one_resume_action_without_authority(self):
        result = self.assess()
        self.assertEqual(result['next_action']['kind'], 'RESUME')
        self.assertEqual(result['next_action']['task'], self.cap['task']['next_action'])
        self.assertNotIn('actions', result)
        self.assertFalse(result['authorizes_external_start'])
        self.assertFalse(result['authorizes_product_write'])
        self.assertFalse(result['authorizes_lease_mutation'])

    def test_source_or_lease_change_requires_reconciliation(self):
        for field, value in [('head_sha', '1' * 40), ('lease_revision', 'other')]:
            with self.subTest(field=field):
                probe = copy.deepcopy(self.probe); probe[field] = value
                result = cdc.resume(self.cap, probe, now_utc=self.now)
                self.assertEqual(result['next_action']['kind'], 'RECONCILE')
                self.assertIn(field + '_changed', result['next_action']['reasons'])

    def test_old_probe_cannot_make_an_old_capsule_look_fresh(self):
        result = cdc.resume(self.cap, self.probe, now_utc='2026-01-01T04:00:00Z')
        self.assertEqual(result['next_action']['kind'], 'RECONCILE')
        self.assertIn('probe_stale', result['next_action']['reasons'])

    def test_incomplete_or_future_probe_reconciles(self):
        self.probe['complete'] = False
        self.assertEqual(self.assess()['next_action']['kind'], 'RECONCILE')
        self.probe['complete'] = True
        self.probe['observed_at_utc'] = '2026-01-01T00:02:00Z'
        self.assertIn('probe_from_future', self.assess()['next_action']['reasons'])

    def test_existing_external_identity_is_reconciled_before_continuation(self):
        self.cap['external'] = dict(kind='compute', id='existing-task', sha='0' * 40,
                                    operation_key='preserved-key', state='UNKNOWN')
        result = self.assess()
        self.assertEqual(result['next_action']['kind'], 'RECONCILE_EXTERNAL')
        self.assertEqual(result['next_action']['operation'], self.cap['external'])

    def test_stale_or_changed_probe_preserves_existing_external_identity(self):
        self.cap['external'] = dict(kind='compute', id='existing-task', sha='0' * 40,
                                    operation_key='preserved-key', state='UNKNOWN')
        original = copy.deepcopy(self.cap)
        for field, value, now in [('head_sha', '1' * 40, self.now),
                                  ('lease_revision', 'changed', self.now),
                                  ('complete', True, '2026-01-01T04:00:00Z')]:
            with self.subTest(field=field, now=now):
                probe = copy.deepcopy(self.probe)
                probe[field] = value
                result = cdc.resume(self.cap, probe, now_utc=now)
                self.assertEqual(result['next_action']['kind'], 'RECONCILE')
                self.assertEqual(result['next_action']['operation'], original['external'])
                self.assertTrue(result['next_action']['reasons'])
                self.assertFalse(result['authorizes_external_start'])
                self.assertFalse(result['authorizes_product_write'])
                self.assertFalse(result['authorizes_lease_mutation'])
        self.assertEqual(self.cap, original)

    def test_recorded_blocker_waits_and_recovery_health_reconciles(self):
        self.cap['task']['blocker'] = 'owner pause'
        self.assertEqual(self.assess()['next_action']['kind'], 'WAIT')
        self.cap['task']['blocker'] = None
        self.cap['health']['state'] = 'RECOVERY_REQUIRED'
        self.assertEqual(self.assess()['next_action']['kind'], 'RECONCILE')

    def test_cli_never_executes_free_text_and_rejects_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'unwanted-effect'
            self.cap['task']['next_action'] = f'touch {marker}'
            cap_path = Path(tmp) / 'capsule.json'; probe_path = Path(tmp) / 'probe.json'
            cap_path.write_text(json.dumps(self.cap)); probe_path.write_text(json.dumps(self.probe))
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'resume',
                                     '--capsule', str(cap_path), '--probe', str(probe_path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['next_action']['kind'], 'RECONCILE')
            self.assertFalse(marker.exists())
            cap_path.write_text('{"schema": "resume-capsule/v1", "schema": "other"}')
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'resume',
                                     '--capsule', str(cap_path), '--probe', str(probe_path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('duplicate', result.stderr)

    def test_cli_dispatches_real_contract_templates_without_side_effects(self):
        examples = [('assess', 'development-assessment.json', 'development-assessment-result/v1'),
                    ('strategy', 'execution-strategy.json', 'execution-strategy-result/v1'),
                    ('report', 'operation-observation.json', None)]
        for command, fixture, schema in examples:
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, '-B', str(SCRIPT), command,
                                         str(ROOT / 'templates' / fixture)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout)
                if schema:
                    self.assertEqual(parsed['schema'], schema)
                    self.assertFalse(parsed['authorizes_product_write'])
                else:
                    self.assertEqual(parsed['suffix'], '(4 мин)')

    def test_cli_uses_its_runtime_clock_for_current_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            self.cap['updated_at_utc'] = now
            self.probe['observed_at_utc'] = now
            cap_path = Path(tmp) / 'capsule.json'; probe_path = Path(tmp) / 'probe.json'
            cap_path.write_text(json.dumps(self.cap)); probe_path.write_text(json.dumps(self.probe))
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'resume',
                                     '--capsule', str(cap_path), '--probe', str(probe_path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['next_action']['kind'], 'RESUME')


if __name__ == '__main__':
    unittest.main()
