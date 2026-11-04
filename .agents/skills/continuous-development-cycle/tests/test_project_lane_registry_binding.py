from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import project_lane_runtime as runtime


class MemoryStore:
    ref = "refs/heads/cdc/project-lanes"
    store_id = "sha256:" + "c" * 64

    def __init__(self):
        self.rev = 0
        self.value = None

    def read(self):
        import copy
        return self.rev, copy.deepcopy(self.value)

    def compare_and_swap(self, expected, value):
        import copy
        if expected != self.rev:
            raise ValueError("stale")
        self.rev += 1
        self.value = copy.deepcopy(value)
        return str(self.rev)


def config(**patch):
    value = {
        "canonical_repository": "example/g-cdc",
        "product_source_ref": "refs/heads/main",
        "coordination_ref": "refs/heads/cdc/project-lanes",
        "coordination_store_id": "sha256:" + "c" * 64,
        "policy_authority": "sha256:" + "d" * 64,
    }
    value.update(patch)
    return runtime.LaneRegistryConfig(**value)


class ProjectLaneRegistryBindingTests(unittest.TestCase):
    def test_state_is_content_bound_to_exact_registry_configuration(self):
        store = MemoryStore()
        first = runtime.ProjectLaneCoordinator(store, config())
        snapshot = first.snapshot()
        self.assertEqual(snapshot["config"]["canonical_repository"], "example/g-cdc")
        self.assertRegex(snapshot["config_digest"], r"^sha256:[0-9a-f]{64}$")

        with self.assertRaisesRegex(ValueError, "configuration"):
            runtime.ProjectLaneCoordinator(
                store, config(policy_authority="sha256:" + "e" * 64))

    def test_coordination_endpoint_must_match_store_identity(self):
        for value in (
            config(coordination_ref="refs/heads/cdc/other"),
            config(coordination_store_id="sha256:" + "f" * 64),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime.ProjectLaneCoordinator(MemoryStore(), value)

    def test_source_ref_and_repository_identity_are_canonical(self):
        for source_ref in ("main", "refs/heads/bad ref", "refs/heads/bad:ref", "refs/heads/a..b"):
            with self.subTest(source_ref=source_ref), self.assertRaises(ValueError):
                config(product_source_ref=source_ref)
        for coordination_ref in ("refs/heads/cdc/bad ref", "refs/heads/cdc/a..b", "refs/heads/other"):
            with self.subTest(coordination_ref=coordination_ref), self.assertRaises(ValueError):
                config(coordination_ref=coordination_ref)
        with self.assertRaises(ValueError):
            config(canonical_repository="not-a-repository")

    def test_lane_admission_requires_verified_legacy_migration_gate(self):
        from project_lanes import LaneClaim, LaneKind
        store = MemoryStore()
        coordinator = runtime.ProjectLaneCoordinator(store, config())
        claim = LaneClaim(
            "lane", "inv", LaneKind.WORKER, "a" * 40, "/tmp/lane", "cdc/lane",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        with self.assertRaisesRegex(ValueError, "safe legacy boundary"):
            coordinator.admit(claim, generation=1)

    def test_legacy_gate_requires_independent_safe_evidence_and_is_immutable(self):
        store = MemoryStore()
        unsafe = runtime.ProjectLaneCoordinator(
            store, config(), migration_verifier=lambda observation: {
                "safe": False, "legacy_lease": "released", "external_guard": "none",
                "legacy_mode_disabled": True, "evidence_ref": "legacy:unsafe"})
        with self.assertRaisesRegex(ValueError, "not independently proven"):
            unsafe.establish_migration_gate({"legacy": "observed"})

        store = MemoryStore()
        safe_evidence = {
            "safe": True, "legacy_lease": "released", "external_guard": "reconciled",
            "legacy_mode_disabled": True, "evidence_ref": "legacy:safe"}
        coordinator = runtime.ProjectLaneCoordinator(
            store, config(), migration_verifier=lambda observation: dict(safe_evidence))
        self.assertEqual(coordinator.establish_migration_gate({"legacy": "observed"}), safe_evidence)
        self.assertEqual(coordinator.establish_migration_gate({"legacy": "observed"}), safe_evidence)

        with self.assertRaisesRegex(ValueError, "migration|revalidation|binding"):
            runtime.ProjectLaneCoordinator(
                store, config(), migration_verifier=lambda observation: {
                    **safe_evidence, "evidence_ref": "legacy:different"})

    def test_new_coordinator_without_migration_verifier_fails_closed_after_gate(self):
        store = MemoryStore()
        safe_evidence = {
            "safe": True, "legacy_lease": "released", "external_guard": "none",
            "legacy_mode_disabled": True, "evidence_ref": "legacy:safe"}
        coordinator = runtime.ProjectLaneCoordinator(
            store, config(), migration_verifier=lambda observation: dict(safe_evidence))
        coordinator.establish_migration_gate({"legacy": "observed"})
        with self.assertRaisesRegex(ValueError, "migration|verifier|revalid"):
            runtime.ProjectLaneCoordinator(store, config())

    def test_live_migration_authority_drift_blocks_admission(self):
        from project_lanes import LaneClaim, LaneKind
        store = MemoryStore()
        authority = {"lease": "released", "enabled": False}
        def verify(_observation):
            return {
                "safe": authority["lease"] == "released" and authority["enabled"] is False,
                "legacy_lease": authority["lease"],
                "external_guard": "none",
                "legacy_mode_disabled": authority["enabled"] is False,
                "evidence_ref": "legacy:epoch-1",
            }
        coordinator = runtime.ProjectLaneCoordinator(store, config(), migration_verifier=verify)
        coordinator.establish_migration_gate({"legacy": "observed"})
        authority["lease"] = "active"
        claim = LaneClaim(
            "lane", "inv", LaneKind.WORKER, "a" * 40, "/tmp/lane", "cdc/lane",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        with self.assertRaisesRegex(ValueError, "legacy|migration|revalid"):
            coordinator.admit(claim, generation=1)

    def test_live_legacy_acquisition_reenabled_blocks_authority(self):
        from project_lanes import LaneClaim, LaneKind
        store = MemoryStore()
        authority = {"enabled": False}
        def verify(_observation):
            return {
                "safe": authority["enabled"] is False,
                "legacy_lease": "released",
                "external_guard": "none",
                "legacy_mode_disabled": authority["enabled"] is False,
                "evidence_ref": "legacy:epoch-1",
            }
        coordinator = runtime.ProjectLaneCoordinator(store, config(), migration_verifier=verify)
        coordinator.establish_migration_gate({"legacy": "observed"})
        authority["enabled"] = True
        claim = LaneClaim(
            "lane", "inv", LaneKind.WORKER, "a" * 40, "/tmp/lane", "cdc/lane",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        with self.assertRaisesRegex(ValueError, "legacy|migration|proven"):
            coordinator.admit(claim, generation=1)

    def test_live_migration_evidence_epoch_mismatch_blocks_authority(self):
        store = MemoryStore()
        evidence_ref = {"value": "legacy:epoch-1"}
        def verify(_observation):
            return {
                "safe": True, "legacy_lease": "released", "external_guard": "none",
                "legacy_mode_disabled": True, "evidence_ref": evidence_ref["value"]}
        coordinator = runtime.ProjectLaneCoordinator(store, config(), migration_verifier=verify)
        coordinator.establish_migration_gate({"legacy": "observed"})
        evidence_ref["value"] = "legacy:epoch-2"
        with self.assertRaisesRegex(ValueError, "migration|evidence|binding"):
            coordinator.snapshot()

    def test_malformed_live_lane_state_fails_closed_on_read(self):
        from project_lanes import LaneClaim, LaneKind
        store = MemoryStore()
        safe_evidence = {
            "safe": True, "legacy_lease": "released", "external_guard": "none",
            "legacy_mode_disabled": True, "evidence_ref": "legacy:safe"}
        coordinator = runtime.ProjectLaneCoordinator(
            store, config(), migration_verifier=lambda observation: dict(safe_evidence))
        coordinator.establish_migration_gate({"legacy": "observed"})
        claim = LaneClaim(
            "lane", "inv", LaneKind.WORKER, "a" * 40, "/tmp/lane", "cdc/lane",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        coordinator.admit(claim, generation=1)
        store.value["lanes"]["lane"]["state"] = "corrupt"
        with self.assertRaisesRegex(ValueError, "lane registry lane"):
            coordinator.snapshot()

    def test_malformed_integration_queue_fails_before_claim_mutation(self):
        from project_lanes import LaneClaim, LaneKind

        store = MemoryStore()
        safe_evidence = {
            "safe": True, "legacy_lease": "released", "external_guard": "none",
            "legacy_mode_disabled": True, "evidence_ref": "legacy:safe"}
        coordinator = runtime.ProjectLaneCoordinator(
            store, config(), migration_verifier=lambda observation: dict(safe_evidence))
        coordinator.establish_migration_gate({"legacy": "observed"})

        worker = LaneClaim(
            "worker", "worker-inv", LaneKind.WORKER, "a" * 40,
            "/tmp/worker", "cdc/worker", write_paths=frozenset({"src/a"}),
            executor_id="worker-executor", role="writer")
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, "a" * 40,
            "/tmp/integrator", "main", executor_id="integrator-executor",
            role="integrator")
        self.assertTrue(coordinator.admit(worker, generation=1)["admitted"])
        self.assertTrue(coordinator.admit(integrator, generation=1)["admitted"])

        # A durable queue item that could never be produced by record_result()
        # must be rejected at the read boundary, before claim_integration() can
        # turn malformed persisted state into a new authoritative mutation.
        store.value["integration_queue"] = [{
            "lane_id": "worker",
            "result_commit": "b" * 40,
        }]
        with self.assertRaisesRegex(ValueError, "integration|queue|registry"):
            coordinator.claim_integration(
                "worker", result_commit="b" * 40,
                integrator_lane_id="integrator",
                integrator_invocation_id="integrator-inv",
                integrator_generation=1,
                integrator_executor_id="integrator-executor",
                observed_shared_head="a" * 40,
                intended_integrated_head="b" * 40,
            )
        self.assertEqual(store.value["integration_intents"], {})
        self.assertFalse(store.value["lanes"]["integrator"]["pending_effects"])

    def test_configuration_digest_is_deterministic(self):
        left = config()
        right = config()
        self.assertEqual(left.digest(), right.digest())


if __name__ == "__main__":
    unittest.main()
