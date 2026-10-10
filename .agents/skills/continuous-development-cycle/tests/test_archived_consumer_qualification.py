"""Offline major compatibility must preserve the archived adoption boundary."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from contracts import ContractError, load_yaml
from validate_adapter import validate_adapter
from archived_consumer_qualification import qualify, qualify_snapshots


class ArchivedConsumerQualificationTests(unittest.TestCase):
    def setUp(self):
        self.source_lock = dict(schema='cdc-source-lock/v1',
            canonical_repository='owner/cdc', base_validation_repository='owner/cdc',
            target_version=(ROOT / 'VERSION').read_text().strip(),
            development_driver_version='3.0.0',
            base_validation_commit='a' * 40, base_package_tree='b' * 40,
            bootstrap_contract='cdc-bootstrap/v1', direct_product_repo_development=False,
            base_validation_run_id=1, base_validation_evidence_ref=None)
        self.baseline = self.source_lock['development_driver_version']
        self.adapter = load_yaml(ROOT / 'templates/development-cycle.yaml')
        self.adapter['policy']['skill_max_version_exclusive'] = '3.0.0'
        self.checkpoint = load_yaml(ROOT / 'templates/work-status-v4.md', frontmatter=True)
        self.checkpoint['policy_digest'] = validate_adapter(
            self.adapter, skill_version='2.12.1')['policy_digest']

    def check(self, adapter=None, checkpoint=None):
        return qualify(adapter or self.adapter, checkpoint or self.checkpoint,
                       baseline_version=self.baseline, source_lock=self.source_lock)

    def test_major_ceiling_is_rejected_and_copy_is_qualified_without_mutation(self):
        original = copy.deepcopy((self.adapter, self.checkpoint))
        result = self.check()
        self.assertEqual(result['installation_compatible'], False)
        self.assertEqual(result['qualification'], 'migration_fixture_compatible')
        self.assertEqual(result['migration_changes'],
                         ['policy.skill_max_version_exclusive', 'checkpoint.policy_digest'])
        self.assertEqual((self.adapter, self.checkpoint), original)
        self.assertFalse(result['authorizes_adoption'])
        self.assertFalse(result['authorizes_policy_write'])

    def test_already_compatible_archive_uses_real_checkpoint_validation(self):
        self.adapter['policy']['skill_max_version_exclusive'] = '4.0.0'
        self.checkpoint['policy_digest'] = validate_adapter(self.adapter)['policy_digest']
        result = self.check()
        self.assertTrue(result['installation_compatible'])
        self.assertEqual(result['qualification'], 'compatible')
        self.assertEqual(result['migration_changes'], [])

    def test_stale_checkpoint_binding_cannot_be_repaired_by_qualification(self):
        self.checkpoint['policy_digest'] = '0' * 64
        with self.assertRaisesRegex(ContractError, 'archived policy binding'):
            self.check()

    def test_other_adapter_defects_cannot_be_treated_as_expected_rejection(self):
        self.adapter['validation']['final_remote_required'] = False
        with self.assertRaises(ContractError):
            self.check()

    def test_copy_preserves_invalid_ownership_and_fails(self):
        self.checkpoint['lease_state'] = 'active'
        with self.assertRaises(ContractError):
            self.check()

    def test_different_ceiling_is_not_automatically_widened(self):
        self.adapter['policy']['skill_max_version_exclusive'] = '2.13.0'
        self.checkpoint['policy_digest'] = validate_adapter(
            self.adapter, skill_version='2.12.1')['policy_digest']
        with self.assertRaises(ContractError):
            self.check()

    def test_unknown_runtime_baseline_is_rejected(self):
        with self.assertRaises(ContractError):
            qualify(self.adapter, self.checkpoint, baseline_version='2.11.2')

    def test_same_major_driver_incompatibility_is_reported_without_revision_change(self):
        self.adapter['policy']['revision'] = 'original-review-v2'
        self.checkpoint['policy_revision'] = 'original-review-v2'
        self.checkpoint['policy_digest'] = validate_adapter(
            self.adapter, skill_version='2.12.1')['policy_digest']
        before = copy.deepcopy((self.adapter, self.checkpoint))
        result = self.check()
        self.assertFalse(result['baseline_installation_compatible'])
        self.assertEqual(result['diagnostic_version'], '2.11.3')
        self.assertFalse(result['installation_compatible'])
        self.assertEqual((self.adapter, self.checkpoint), before)

    def test_same_major_extension_requires_exact_source_lock_binding(self):
        for lock in (None, dict(self.source_lock, target_version='3.9.0'),
                     dict(self.source_lock, development_driver_version='2.12.1'),
                     dict(self.source_lock, base_package_tree='wrong')):
            with self.subTest(lock=lock), self.assertRaises(ContractError):
                qualify(self.adapter, self.checkpoint, baseline_version=self.baseline,
                        source_lock=lock)

    def snapshots(self, root):
        for name in ('one', 'two', 'three'):
            folder = root / name
            folder.mkdir()
            (folder / 'development-cycle.yaml').write_text(yaml.safe_dump(self.adapter))
            (folder / 'work-status.md').write_text('---\n' +
                yaml.safe_dump(self.checkpoint) + '---\nOriginal history.\n')
            (folder / 'source.json').write_text(json.dumps({
                'schema': 'cdc-consumer-validation-source/v1',
                'repository': self.adapter['repository']['remote'],
                'source_commit': 'b' * 40, 'vendored_cdc_version': '2.12.1',
                'candidate_version': (ROOT / 'VERSION').read_text().strip(),
                'candidate_package_tree': 'a' * 40}))

    def qualify_files(self, root, **changes):
        args = dict(consumers=['one', 'two', 'three'], baseline_version=self.baseline, source_lock=self.source_lock,
                    package_tree='a' * 40)
        args.update(changes)
        return qualify_snapshots(root, **args)

    def test_all_three_snapshots_and_original_history_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.snapshots(root)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = self.qualify_files(root)
            self.assertEqual(len(result['consumers']), 3)
            self.assertTrue(result['archives_unchanged'])
            self.assertTrue(all(not r['installation_compatible'] for r in result['consumers']))
            self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_mismatched_package_cannot_qualify_the_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.snapshots(root)
            with self.assertRaisesRegex(ValueError, 'source binding mismatch'):
                self.qualify_files(root, package_tree='c' * 40)

    def test_missing_consumer_and_repeated_directory_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.snapshots(root)
            with self.assertRaises(OSError):
                self.qualify_files(root, consumers=['one', 'two', 'absent'])
            with self.assertRaisesRegex(ValueError, 'three distinct'):
                self.qualify_files(root, consumers=['one', 'one', 'three'])

    def test_metadata_repository_substitution_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.snapshots(root)
            path = root / 'one' / 'source.json'
            data = json.loads(path.read_text())
            data['repository'] = 'other/project'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'repository identity mismatch'):
                self.qualify_files(root)

    def test_duplicate_metadata_field_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.snapshots(root)
            path = root / 'one' / 'source.json'
            path.write_text(path.read_text()[:-1] + ', "candidate_version": "3.0.0"}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON field'):
                self.qualify_files(root)


if __name__ == '__main__':
    unittest.main()
