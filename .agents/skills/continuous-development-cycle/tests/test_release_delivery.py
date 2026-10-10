"""Reusable canonical release verification uses the same real Git authority."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_live_target as fixtures
NOW = fixtures.NOW
import live_target

class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LiveTargetTests("test_embedded_v1_target_remains_supported")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def verify(self):
        f = self.fixture
        return live_target.verify_release_binding(f.source("canonical"), f.provenance,
            canonical_repository="owner/canonical", clock=lambda: NOW)

    def test_colocated_release_without_registry_returns_exact_objects(self):
        f=self.fixture
        result=self.verify()
        self.assertEqual(result["release_revision"].revision,f.release)
        self.assertEqual(result["evidence"]["candidate_source_commit"],f.candidate)
        self.assertFalse(result["authorizes_adoption"])

    def test_split_release_is_verified_without_fleet_registry(self):
        f=self.fixture; f.split_metadata()
        result=self.verify()
        self.assertEqual(result["evidence_revision"].revision,f.metadata)
        self.assertEqual(result["release_revision"].revision,f.candidate)

    def test_moved_release_ref_is_rejected(self):
        f=self.fixture
        f.git(f.canonical,"update-ref",f.provenance["release_ref"],f.commit(f.canonical))
        with self.assertRaises(ValueError): self.verify()

    def test_split_wrong_candidate_and_duplicate_evidence_are_rejected(self):
        f=self.fixture; f.split_metadata()
        f.evidence["candidate_source_commit"]="0"*40
        f.write(f.canonical,"release/evidence-3.2.1.json",f.evidence);f.repin_metadata()
        with self.assertRaises(ValueError): self.verify()
        import json
        f.evidence["candidate_source_commit"]=f.candidate
        f.write(f.canonical,"release/evidence-3.2.1.json",json.dumps(f.evidence)[:-1]+',"status":"released"}')
        f.repin_metadata()
        with self.assertRaisesRegex(ValueError,"duplicate"): self.verify()

    def test_malformed_version_cannot_form_a_git_path(self):
        f=self.fixture
        f.provenance["version"]="../3.2.1"
        with self.assertRaises(ValueError): self.verify()

if __name__ == "__main__": unittest.main()

