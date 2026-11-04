"""Supported Fleet projections never widen policy or grant adoption."""
import copy,json,sys,tempfile,unittest,hashlib
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from contracts import load_yaml,ContractError
from validate_adapter import validate_adapter
from supported_consumer_qualification import qualify,qualify_snapshots
class SupportedConsumerTests(unittest.TestCase):
    def setUp(self):
        self.adapter=load_yaml(ROOT/'templates/development-cycle.yaml')
        self.checkpoint=load_yaml(ROOT/'templates/work-status-v4.md',frontmatter=True)
        self.checkpoint['policy_digest']=validate_adapter(self.adapter,skill_version='3.3.0')['policy_digest']
    def check(self):
        return qualify(self.adapter,self.checkpoint,installed_version='3.3.0')
    def test_supported_policy_and_checkpoint_validate_without_mutation(self):
        before=copy.deepcopy((self.adapter,self.checkpoint));value=self.check()
        self.assertTrue(value['installation_compatible']);self.assertEqual(value['migration_changes'],[])
        self.assertFalse(value['authorizes_adoption']);self.assertEqual(before,(self.adapter,self.checkpoint))
    def test_stale_checkpoint_binding_cannot_be_repaired(self):
        self.checkpoint['policy_digest']='0'*64
        with self.assertRaisesRegex(ContractError,'policy'):self.check()
    def test_other_adapter_defects_cannot_be_expected_rejection(self):
        self.adapter['validation']['final_remote_required']=False
        with self.assertRaises(ContractError):self.check()
    def test_invalid_ownership_fails(self):
        self.checkpoint['lease_state']='active'
        with self.assertRaises(ContractError):self.check()
    def test_old_major_ceiling_is_rejected_without_widening(self):
        self.adapter['policy']['skill_max_version_exclusive']='3.0.0'
        before=copy.deepcopy(self.adapter)
        with self.assertRaises(ContractError):self.check()
        self.assertEqual(self.adapter,before)
    def test_below_floor_installed_runtime_is_rejected(self):
        with self.assertRaisesRegex(ContractError,'3.3.0'):
            qualify(self.adapter,self.checkpoint,installed_version='3.2.9')
    def snapshots(self,root):
        import shutil
        pins=json.loads((ROOT/'templates/supported-consumer-provenance.json').read_text())['consumers']
        for name,bindings in pins.items():
            p=root/name;shutil.copytree(ROOT/'templates/supported-consumer-fixtures'/name,p)
            source=dict(bindings,schema='cdc-supported-consumer-projection/v1',projection=True,candidate_version=(ROOT/'VERSION').read_text().strip(),candidate_package_tree='a'*40)
            (p/'source.json').write_text(json.dumps(source))
    def files(self,root,**changes):
        args=dict(consumers=['fleet-1','fleet-2','fleet-3'],package_tree='a'*40);args.update(changes)
        return qualify_snapshots(root,**args)
    def test_three_projection_files_and_history_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshots(root);before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            value=self.files(root);self.assertEqual(len(value['consumers']),3);self.assertTrue(value['snapshots_unchanged'])
            self.assertEqual(before,{p:p.read_bytes() for p in before})
    def test_package_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshots(root)
            with self.assertRaisesRegex(ValueError,'source binding'):self.files(root,package_tree='e'*40)
    def test_missing_or_repeated_consumer_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshots(root)
            with self.assertRaisesRegex(ValueError,'binding'):self.files(root,consumers=['fleet-1','fleet-2','absent'])
            with self.assertRaisesRegex(ValueError,'distinct'):self.files(root,consumers=['fleet-1','fleet-1','fleet-3'])
    def test_metadata_repository_substitution_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshots(root);p=root/'fleet-1/source.json';v=json.loads(p.read_text());v['repository']='other/project';p.write_text(json.dumps(v))
            with self.assertRaisesRegex(ValueError,'repository'):self.files(root)
    def test_duplicate_metadata_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshots(root);p=root/'fleet-1/source.json';p.write_text(p.read_text()[:-1]+',"candidate_version":"3.5.0"}')
            with self.assertRaisesRegex(ValueError,'duplicate'):self.files(root)
    def test_control_byte_substitution_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.snapshots(root);p=root/'fleet-1/work-status.md';p.write_text(p.read_text()+'tampered')
            with self.assertRaisesRegex(ValueError,'control hash'):self.files(root)

    def actual_snapshots(self,root):
        self.snapshots(root)
        return dict(consumers=['fleet-1','fleet-2','fleet-3'],package_tree='a'*40)
    def test_installed_package_binding_is_required_for_each_authentic_projection(self):
        for name in ('fleet-1','fleet-2','fleet-3'):
            with self.subTest(consumer=name),tempfile.TemporaryDirectory() as d:
                root=Path(d);args=self.actual_snapshots(root);p=root/name/'source.json';v=json.loads(p.read_text());del v['installed_package_tree'];p.write_text(json.dumps(v))
                with self.assertRaisesRegex(ValueError,'binding'):qualify_snapshots(root,**args)
    def test_substituted_authentic_provenance_is_rejected(self):
        for field,value in [('installed_package_tree','e'*40),('source_commit','e'*40),('installed_version','3.4.0'),('original_adapter_sha256','e'*64),('original_checkpoint_sha256','e'*64)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                root=Path(d);args=self.actual_snapshots(root);p=root/'fleet-1/source.json';v=json.loads(p.read_text());v[field]=value;p.write_text(json.dumps(v))
                with self.assertRaisesRegex(ValueError,'binding'):qualify_snapshots(root,**args)
    def test_replaced_provenance_manifest_cannot_supply_new_caller_pins(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);snapshots=root/'snapshots';snapshots.mkdir();args=self.actual_snapshots(snapshots)
            manifest=root/'templates/supported-consumer-provenance.json';manifest.parent.mkdir()
            pins=json.loads((ROOT/'templates/supported-consumer-provenance.json').read_text())
            pins['consumers']['fleet-1']['source_commit']='e'*40
            manifest.write_text(json.dumps(pins))
            with patch('supported_consumer_qualification.ROOT',root):
                with self.assertRaisesRegex(ValueError,'provenance binding changed'):
                    qualify_snapshots(snapshots,**args)
