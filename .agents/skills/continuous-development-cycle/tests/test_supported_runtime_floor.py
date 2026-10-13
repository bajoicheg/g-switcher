"""History parsing never restores executable authority below the Fleet floor."""
import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from live_target import verify_release_binding
from consumer_lock import validate as validate_lock
from consumer_adoption import assess

class SupportedFloorTests(unittest.TestCase):
    def test_below_floor_release_fails_before_native_remote_access(self):
        for version in ('2.12.1','3.0.0','3.2.9'):
            binding=dict(schema='live-target-release/v1', version=version,
                         canonical_repository='owner/cdc', release_ref='refs/heads/release/v'+version,
                         release_commit='a'*40, package_tree='b'*40)
            with self.subTest(version=version), self.assertRaisesRegex(ValueError,'3.3.0'):
                verify_release_binding(None,binding,canonical_repository='owner/cdc')
    def test_historical_lock_stays_readable_without_granting_execution(self):
        lock=dict(schema='cdc-consumer-lock/v1',canonical_repository='owner/cdc',version='2.12.1',
                  release_ref='refs/heads/release/v2.12.1',release_commit='a'*40,package_tree='b'*40,
                  checkpoint_schema='development-work-status/v4',safe_boundary_required=True,
                  local_core_modifications_allowed=False)
        self.assertIs(validate_lock(lock),lock)
