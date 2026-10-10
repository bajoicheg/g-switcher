"""Current policy controls, with valid positive baselines."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from contracts import ContractError,load_yaml
from validate_adapter import validate_adapter
VERSION=(ROOT/"VERSION").read_text().strip()
class PolicyControlsTests(unittest.TestCase):
    def template(self):
        data=load_yaml(ROOT/"templates/development-cycle.yaml")
        validate_adapter(data,VERSION)
        return data
    def test_duplicate_backend_preference_rejected(self):
        d = self.template()
        d['routing']['backend_kind_preference'] = ['codex_compute', 'codex_compute']
        with self.assertRaises(ContractError):
            validate_adapter(d, VERSION)

    def test_event_wake_cannot_be_authority(self):
        d = self.template()
        d['continuation']['event_wake_is_authority'] = True
        with self.assertRaises(ContractError):
            validate_adapter(d, VERSION)

    def test_fleet_cannot_gain_product_authority(self):
        d = self.template()
        d['fleet']['product_write_authority'] = True
        with self.assertRaises(ContractError):
            validate_adapter(d, VERSION)

    def test_primitive_activity_cannot_be_progress(self):
        d = self.template()
        d['progress_slo']['primitive_activity_is_progress'] = True
        with self.assertRaises(ContractError):
            validate_adapter(d, VERSION)

    def test_stalled_threshold_must_exceed_degraded(self):
        d = self.template()
        d['progress_slo']['stalled_after_seconds'] = d['progress_slo']['degraded_after_seconds']
        with self.assertRaises(ContractError):
            validate_adapter(d, VERSION)

    def test_runtime_floor_preserves_readable_older_policy(self):
        data = self.template()
        data['policy']['skill_min_version'] = '2.10.2'
        data['convergence']['target_version'] = '2.10.2'
        for version in ('2.11.3', VERSION):
            with self.subTest(version=version):
                validate_adapter(data, version)
        with self.assertRaisesRegex(ContractError, 'minimum supported CDC runtime is 2.11.3'):
            validate_adapter(data, '2.11.2')
