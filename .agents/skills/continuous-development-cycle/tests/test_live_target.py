"""Live target authority uses real Git objects and exact remote revisions."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import git_remote_identity
try:
    import live_target
except ModuleNotFoundError:
    live_target = None

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
PACKAGE = "src/continuous-development-cycle"


class LiveTargetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(live_target, "live target resolver has not been implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.canonical = self.make_repo("canonical")
        self.registry = self.make_repo("registry")
        self.cache = self.make_repo("cache")
        self.write(self.canonical, PACKAGE + "/VERSION", "3.2.1\n")
        self.candidate = self.commit(self.canonical)
        self.tree = self.git(self.canonical, "rev-parse", "HEAD:" + PACKAGE)
        self.evidence = {
            "schema": "cdc-release-evidence/v1", "version": "3.2.1",
            "canonical_repository": "owner/canonical", "status": "released",
            "candidate_source_commit": self.candidate, "package_tree": self.tree,
            "release_ref": "refs/heads/release/v3.2.1",
        }
        self.write(self.canonical, "release/evidence-3.2.1.json", self.evidence)
        self.release = self.commit(self.canonical)
        self.git(self.canonical, "update-ref", self.evidence["release_ref"], self.release)
        self.target = {
            "schema": "version-convergence-target/v1", "target_version": "3.2.1",
            "target_package_fingerprint": "git-tree:" + self.tree,
            "checkpoint_schema": "development-work-status/v4", "safe_boundary_required": True,
        }
        self.provenance = {
            "schema": "live-target-release/v1", "version": "3.2.1",
            "canonical_repository": "owner/canonical", "release_ref": self.evidence["release_ref"],
            "release_commit": self.release, "package_tree": self.tree,
        }
        self.registry_data = {
            "schema": "fleet-registry/v1", "target": self.target,
            "slo_policy": {"schema": "progress-slo-policy/v1", "degraded_after_seconds": 1200,
                           "stalled_after_seconds": 3600, "blocked_pauses_clock": True,
                           "waiting_external_pauses_clock": True, "primitive_activity_is_progress": False},
            "assessment_max_age_seconds": 900,
            "projects": [{"repository": "owner/product", "source_ref": "refs/heads/main",
                          "watchdog_id": "project-watchdog", "required": True}],
        }
        self.publish_registry()
        for remote, repo in (("fleet", self.registry), ("canonical", self.canonical)):
            self.git(self.cache, "remote", "add", remote, str(repo))

    def make_repo(self, name):
        path = self.root / name
        path.mkdir()
        self.git(path, "init", "-q", "-b", "main")
        self.git(path, "config", "user.name", "Fixture")
        self.git(path, "config", "user.email", "fixture@example.invalid")
        return path

    @staticmethod
    def git(repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                       stderr=subprocess.PIPE).strip()

    @staticmethod
    def write(repo, path, content):
        dest = repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(content) if isinstance(content, dict) else content)

    def commit(self, repo):
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-q", "--allow-empty", "-m", "fixture")
        return self.git(repo, "rev-parse", "HEAD")

    def publish_registry(self):
        self.write(self.registry, "fleet/registry.json", self.registry_data)
        self.write(self.registry, "fleet/target.json", self.target)
        self.write(self.registry, "fleet/target-release.json", self.provenance)
        self.registry_revision = self.commit(self.registry)

    def source(self, remote, cls=None):
        return (cls or live_target.GitSource)(
            self.cache, remote, git_remote_identity.remote_identity(self.cache, remote),
            clock=lambda: NOW,
        )

    def resolve(self, **kwargs):
        return live_target.resolve_live_target(
            kwargs.pop("registry_source", self.source("fleet")),
            kwargs.pop("canonical_source", self.source("canonical")),
            registry_ref="refs/heads/main", canonical_repository="owner/canonical",
            clock=lambda: NOW, **kwargs,
        )

    def test_resolves_same_live_revision_and_canonical_release_provenance(self):
        # A resolver using local HEAD, version equality or a remote alias fails here.
        self.write(self.registry, "fleet/target.json", {"uncommitted": "must not be read"})
        before_refs = self.git(self.cache, "show-ref") if self.git(self.cache, "for-each-ref") else ""
        result = self.resolve(target_path="fleet/target.json")
        self.assertEqual(result["registry_revision"], self.registry_revision)
        self.assertEqual(result["registry"], self.registry_data)
        self.assertEqual(result["target"], self.target)
        self.assertEqual(result["release"]["release_commit"], self.release)
        self.assertEqual(result["release"]["package_tree"], self.tree)
        self.assertFalse(result["authorizes_adoption"])
        self.assertFalse(result["authorizes_scheduler_write"])
        after_refs = self.git(self.cache, "show-ref") if self.git(self.cache, "for-each-ref") else ""
        self.assertEqual(before_refs, after_refs)

    def test_embedded_v1_target_remains_supported(self):
        (self.registry / "fleet/target.json").unlink()
        self.commit(self.registry)
        self.assertEqual(self.resolve()["target"], self.target)

    def test_configured_standalone_target_is_required_and_must_agree(self):
        self.write(self.registry, "fleet/target.json", {**self.target, "target_version": "3.2.2"})
        self.commit(self.registry)
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.resolve(target_path="fleet/target.json")
        (self.registry / "fleet/target.json").unlink()
        self.commit(self.registry)
        with self.assertRaises(ValueError):
            self.resolve(target_path="fleet/target.json")

    def test_untrusted_endpoint_and_changed_remote_alias_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            live_target.GitSource(self.cache, "canonical", "sha256:" + "0" * 64)
        source = self.source("fleet")
        self.git(self.cache, "remote", "set-url", "fleet", str(self.canonical))
        with self.assertRaisesRegex(ValueError, "identity"):
            self.resolve(registry_source=source)

    def test_narrow_adapter_cannot_supply_unknown_endpoint_identity(self):
        for identity in (None, "", "owner/registry"):
            class UnknownSource(live_target.GitSource):
                def identity(self):
                    return identity
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, "identity"):
                self.resolve(registry_source=self.source("fleet", UnknownSource))

    def test_ref_movement_during_registry_read_is_rejected(self):
        test = self
        class MovingSource(live_target.GitSource):
            def read_file(self, snapshot, path):
                content = super().read_file(snapshot, path)
                if path == "fleet/registry.json":
                    test.commit(test.registry)
                return content
        with self.assertRaisesRegex(ValueError, "moved"):
            self.resolve(registry_source=self.source("fleet", MovingSource))

    def test_release_ref_moved_before_or_during_resolution_is_rejected(self):
        changed = self.commit(self.canonical)
        self.git(self.canonical, "update-ref", self.evidence["release_ref"], changed)
        with self.assertRaisesRegex(ValueError, "release_commit"):
            self.resolve()
        self.git(self.canonical, "update-ref", self.evidence["release_ref"], self.release)
        test = self
        class MovingSource(live_target.GitSource):
            def read_file(self, snapshot, path):
                content = super().read_file(snapshot, path)
                if path.endswith("VERSION"):
                    test.git(test.canonical, "update-ref", test.evidence["release_ref"], changed)
                return content
        with self.assertRaisesRegex(ValueError, "moved"):
            self.resolve(canonical_source=self.source("canonical", MovingSource))

    def test_stale_and_future_transport_observations_are_rejected(self):
        for when in ("2026-09-28T11:00:00Z", "2026-09-28T12:00:01Z"):
            class DatedSource(live_target.GitSource):
                def pin(self, ref):
                    return replace(super().pin(ref), observed_at_utc=when)
            with self.subTest(when=when), self.assertRaisesRegex(ValueError, "stale|future"):
                self.resolve(registry_source=self.source("fleet", DatedSource), max_age_seconds=60)

    def test_canonical_observation_must_also_be_fresh(self):
        class OldSource(live_target.GitSource):
            def pin(self, ref):
                return replace(super().pin(ref), observed_at_utc="2026-09-27T12:00:00Z")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.resolve(canonical_source=self.source("canonical", OldSource))

    def test_malformed_observation_fails_closed_as_validation_error(self):
        class MalformedSource(live_target.GitSource):
            def pin(self, ref):
                return replace(super().pin(ref), observed_at_utc="2026-09-28Z")
        with self.assertRaises(ValueError):
            self.resolve(registry_source=self.source("fleet", MalformedSource))

    def test_registry_and_release_document_bindings_cannot_disagree(self):
        for key, value in (("canonical_repository", "attacker/canonical"),
                           ("version", "3.2.2"), ("package_tree", "0" * 40),
                           ("release_ref", "refs/heads/main")):
            original = self.provenance[key]
            self.provenance[key] = value
            self.publish_registry()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.resolve()
            self.provenance[key] = original

    def republish_release(self):
        self.write(self.canonical, "release/evidence-3.2.1.json", self.evidence)
        self.release = self.commit(self.canonical)
        self.git(self.canonical, "update-ref", self.evidence["release_ref"], self.release)
        self.provenance["release_commit"] = self.release
        self.publish_registry()

    def test_canonical_release_evidence_must_be_released_and_agree(self):
        for key, value in (("status", "candidate"), ("canonical_repository", "other/repo"),
                           ("version", "3.2.2"), ("package_tree", "0" * 40),
                           ("release_commit", "0" * 40)):
            original = dict(self.evidence)
            self.evidence[key] = value
            self.republish_release()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.resolve()
            self.evidence = original

    def test_git_package_tree_and_version_must_match_provenance(self):
        self.write(self.canonical, PACKAGE + "/VERSION", "3.2.2\n")
        self.republish_release()
        with self.assertRaises(ValueError):
            self.resolve()
        self.tree = self.git(self.canonical, "rev-parse", "HEAD:" + PACKAGE)
        self.target["target_package_fingerprint"] = "git-tree:" + self.tree
        self.provenance["package_tree"] = self.tree
        self.evidence["package_tree"] = self.tree
        self.republish_release()
        with self.assertRaisesRegex(ValueError, "VERSION"):
            self.resolve()

    def test_candidate_provenance_must_be_ancestor_with_same_package(self):
        self.evidence["candidate_source_commit"] = "0" * 40
        self.republish_release()
        with self.assertRaises(ValueError):
            self.resolve()

    def test_duplicate_json_keys_and_unsafe_paths_are_rejected(self):
        self.write(self.registry, "fleet/target.json",
                   json.dumps(self.target)[:-1] + ', "target_version": "3.2.1"}')
        self.commit(self.registry)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.resolve(target_path="fleet/target.json")
        for path in ("../target.json", "/target.json", "fleet/../target.json", "fleet//target.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.resolve(target_path=path)

    def test_missing_release_provenance_cannot_fall_back_to_version_only(self):
        (self.registry / "fleet/target-release.json").unlink()
        self.commit(self.registry)
        with self.assertRaises(ValueError):
            self.resolve()

    def test_watchdog_prompt_resolves_live_policy_and_version_authority(self):
        prompt = (ROOT / "templates/watchdog-prompt.md").read_text()
        self.assertNotRegex(prompt, r"(?:CDC|Cycle) v?\d+\.\d+")
        for term in ("live_target.py", "target-release.json", "consumer lock", "AGENTS.md",
                     "coordination ref", "checkpoint", "same exact registry revision"):
            self.assertIn(term, prompt)

    def split_metadata(self):
        # Model actual8: immutable tested package, released evidence on descendant metadata.
        self.release = self.candidate
        self.evidence["release_commit"] = self.release
        self.write(self.canonical, "release/evidence-3.2.1.json", self.evidence)
        self.metadata = self.commit(self.canonical)
        self.evidence_ref = "refs/heads/cdc/release-evidence/v3.2.1"
        self.git(self.canonical, "update-ref", self.evidence["release_ref"], self.release)
        self.git(self.canonical, "update-ref", self.evidence_ref, self.metadata)
        self.provenance.update(schema="live-target-release/v2", release_commit=self.release,
                               evidence_binding={"schema": "canonical-release-evidence-binding/v1",
                                   "source_identity": git_remote_identity.remote_identity(self.cache, "canonical"),
                                   "ref": self.evidence_ref, "commit": self.metadata,
                                   "path": "release/evidence-3.2.1.json"})
        self.publish_registry()

    def repin_metadata(self):
        self.metadata = self.commit(self.canonical)
        self.git(self.canonical, "update-ref", self.evidence_ref, self.metadata)
        self.provenance["evidence_binding"]["commit"] = self.metadata
        self.publish_registry()

    def test_split_metadata_explicit_binding_resolves_real_git(self):
        self.split_metadata()
        before = self.git(self.cache, "for-each-ref")
        result = self.resolve(target_path="fleet/target.json")
        self.assertEqual(result["release"]["release_commit"], self.candidate)
        self.assertEqual(result["evidence_observation"]["revision"], self.metadata)
        self.assertEqual(result["evidence_observation"]["ref"], self.evidence_ref)
        self.assertEqual(result["evidence_observation"]["source_identity"], self.source("canonical").identity())
        self.assertFalse(result["authorizes_adoption"])
        self.assertFalse(result["authorizes_scheduler_write"])
        self.assertEqual(before, self.git(self.cache, "for-each-ref"))

    def test_split_metadata_legacy_without_binding_still_rejects(self):
        self.split_metadata()
        self.provenance["schema"] = "live-target-release/v1"
        del self.provenance["evidence_binding"]
        self.publish_registry()
        with self.assertRaisesRegex(ValueError, "Git source operation failed"):
            self.resolve()

    def test_split_evidence_foreign_endpoint_rejected(self):
        self.split_metadata()
        self.provenance["evidence_binding"]["source_identity"] = "sha256:" + "0" * 64
        self.publish_registry()
        with self.assertRaisesRegex(ValueError, "evidence.*identity"):
            self.resolve()

    def test_split_evidence_binding_schema_fields_and_path_rejected(self):
        for field, value in (("schema", "unsupported"), ("ref", "main"),
                             ("commit", "short"), ("path", "../secret"),
                             ("path", "release/other.json")):
            self.split_metadata()
            self.provenance["evidence_binding"][field] = value
            self.publish_registry()
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.resolve()
        self.split_metadata()
        self.provenance["evidence_binding"]["extra"] = True
        self.publish_registry()
        with self.assertRaises(ValueError):
            self.resolve()

    def test_split_evidence_commit_mismatch_rejected(self):
        self.split_metadata()
        self.provenance["evidence_binding"]["commit"] = self.release
        self.publish_registry()
        with self.assertRaisesRegex(ValueError, "evidence.*commit"):
            self.resolve()

    def test_split_evidence_ref_moved_before_read_rejected(self):
        self.split_metadata()
        moved = self.commit(self.canonical)
        self.git(self.canonical, "update-ref", self.evidence_ref, moved)
        with self.assertRaisesRegex(ValueError, "evidence.*commit"):
            self.resolve()

    def test_split_evidence_ref_moved_during_read_rejected(self):
        self.split_metadata()
        test = self
        class MovingEvidence(live_target.GitSource):
            def read_file(self, snapshot, path):
                value = super().read_file(snapshot, path)
                if snapshot.ref == test.evidence_ref:
                    test.git(test.canonical, "update-ref", test.evidence_ref, test.commit(test.canonical))
                return value
        with self.assertRaisesRegex(ValueError, "moved"):
            self.resolve(canonical_source=self.source("canonical", MovingEvidence))

    def test_split_evidence_stale_or_future_pin_rejected(self):
        self.split_metadata()
        test = self
        for stamp in ("2026-09-28T11:00:00Z", "2026-09-28T12:00:01Z"):
            class DatedEvidence(live_target.GitSource):
                def pin(self, ref):
                    observed = super().pin(ref)
                    return replace(observed, observed_at_utc=stamp) if ref == test.evidence_ref else observed
            with self.subTest(stamp=stamp), self.assertRaisesRegex(ValueError, "stale|future"):
                self.resolve(canonical_source=self.source("canonical", DatedEvidence), max_age_seconds=60)

    def test_split_evidence_must_descend_from_release(self):
        self.split_metadata()
        self.git(self.canonical, "checkout", "--orphan", "unrelated")
        self.git(self.canonical, "rm", "-r", "--cached", ".")
        self.repin_metadata()
        with self.assertRaisesRegex(ValueError, "ancestor"):
            self.resolve()

    def test_split_evidence_package_tree_mismatch_rejected(self):
        self.split_metadata()
        self.write(self.canonical, PACKAGE + "/VERSION", "3.2.2\n")
        self.repin_metadata()
        with self.assertRaisesRegex(ValueError, "evidence.*package tree"):
            self.resolve()

    def test_split_evidence_release_fields_and_status_rejected(self):
        for field, value in (("status", "candidate"), ("release_commit", "0" * 40),
                             ("version", "3.2.2"), ("package_tree", "0" * 40),
                             ("candidate_source_commit", "0" * 40)):
            self.split_metadata()
            original = dict(self.evidence)
            self.evidence[field] = value
            self.write(self.canonical, "release/evidence-3.2.1.json", self.evidence)
            self.repin_metadata()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.resolve()
            self.evidence = original

    def test_split_evidence_requires_explicit_release_commit(self):
        self.split_metadata()
        del self.evidence["release_commit"]
        self.write(self.canonical, "release/evidence-3.2.1.json", self.evidence)
        self.repin_metadata()
        with self.assertRaisesRegex(ValueError, "release_commit"):
            self.resolve()

    def test_split_evidence_missing_document_rejected(self):
        self.split_metadata()
        (self.canonical / "release/evidence-3.2.1.json").unlink()
        self.repin_metadata()
        with self.assertRaisesRegex(ValueError, "Git source operation failed"):
            self.resolve()

    def test_split_evidence_explicit_pin_needed_even_for_colocated_evidence(self):
        self.provenance["schema"] = "live-target-release/v2"
        self.publish_registry()
        with self.assertRaises(ValueError):
            self.resolve()

    def test_split_evidence_stable_ref_survives_main_advancement(self):
        self.split_metadata()
        pinned = self.metadata
        self.write(self.canonical, "later-development.md", "unrelated later canonical main development\n")
        moved_main = self.commit(self.canonical)
        self.assertNotEqual(moved_main, pinned)
        result = self.resolve()
        self.assertEqual(result["evidence_observation"]["revision"], pinned)
        self.assertEqual(result["evidence_observation"]["ref"], self.evidence_ref)
        self.assertEqual(result["release"]["release_commit"], self.candidate)


if __name__ == "__main__":
    unittest.main()
