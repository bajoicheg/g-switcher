import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import project_lanes as lanes
import project_lane_runtime as runtime

SHA = "a" * 40


def claim(name, writes=(), kind=lanes.LaneKind.WORKER, branch=None, worktree=None, invocation=None, role=None):
    if role is None:
        role = "review" if kind == lanes.LaneKind.REVIEW else ("integrator" if kind == lanes.LaneKind.INTEGRATOR else "writer")
    return lanes.LaneClaim(
        lane_id=name, invocation_id=invocation or name, kind=kind, source_head=SHA,
        worktree=worktree or f"/tmp/{name}", branch=branch or f"cdc/{name}",
        write_paths=frozenset(writes), executor_id=name, role=role)


class MemoryStore:
    ref = "refs/heads/cdc/project-lanes"
    store_id = "sha256:" + "c" * 64

    def __init__(self):
        self.rev = 0
        self.value = None

    def read(self):
        return self.rev, copy.deepcopy(self.value)

    def compare_and_swap(self, expected, value):
        if expected != self.rev:
            raise ValueError("stale")
        self.rev += 1
        self.value = copy.deepcopy(value)
        return str(self.rev)


def registry_config(store):
    return runtime.LaneRegistryConfig(
        canonical_repository="example/g-cdc",
        product_source_ref="refs/heads/main",
        coordination_ref=store.ref,
        coordination_store_id=store.store_id,
        policy_authority="sha256:" + "d" * 64,
    )


def migration_verifier(observation):
    return {"safe": True, "legacy_lease": "absent", "external_guard": "none",
            "legacy_mode_disabled": True, "evidence_ref": "legacy:none"}


def coordinator(store=None, **kwargs):
    store = store or MemoryStore()
    kwargs.setdefault("migration_verifier", migration_verifier)
    value = runtime.ProjectLaneCoordinator(store, registry_config(store), **kwargs)
    value.establish_migration_gate({"legacy": "observed"})
    return value


def quiescent(lane, checkpoint):
    return {"quiescent": True, "evidence_ref": "process:stopped:" + checkpoint}


def verifier(observed_base=SHA, ancestor=True, touched=None):
    return lambda claim_value, result: {
        "observed_base": observed_base,
        "base_ancestor": ancestor,
        "touched_paths": set(touched if touched is not None else {"src/a/x.py"}),
    }


def stopped_quiescent(lane, checkpoint):
    return {"quiescent": True, "executor_stopped": True,
            "evidence_ref": "process:executor-stopped:" + checkpoint}


def activity_verifier(lane, activity_ref):
    return {"observed": True, "activity_ref": activity_ref,
            "evidence_ref": "process:activity:" + activity_ref}


class IntegrationVerifier:
    remote_id = "sha256:" + "e" * 64
    attempt_ref = "refs/heads/cdc/test-publication-attempts"

    def __init__(self):
        self.attempts = {}

    def publication_binding(self):
        return {
            "shared_ref": "refs/heads/main",
            "remote_id": self.remote_id,
            "durable_attempts": True,
            "attempt_store_ref": self.attempt_ref,
            "attempt_store_id": self.remote_id,
        }

    def publication_attempt(self, operation_id):
        return copy.deepcopy(self.attempts.get(operation_id))

    def __call__(self, item, integrator, intent):
        attempt = {
            "attempt_id": "attempt:" + intent["operation_id"],
            "operation_id": intent["operation_id"],
            "lane_id": item["lane_id"],
            "result_commit": item["result_commit"],
            "observed_shared_head": intent["observed_shared_head"],
            "intended_integrated_head": intent["intended_integrated_head"],
            "remote_id": self.remote_id,
            "shared_ref": "refs/heads/main",
            "status": "confirmed",
            "prepared_at_utc": "2026-09-30T15:00:00Z",
            "submitted_at_utc": "2026-09-30T15:00:01Z",
            "resolved_at_utc": "2026-09-30T15:00:02Z",
        }
        self.attempts[intent["operation_id"]] = copy.deepcopy(attempt)
        return {
            "integrated": True,
            "operation_id": intent["operation_id"],
            "result_commit": item["result_commit"],
            "observed_shared_head": intent["observed_shared_head"],
            "integrated_head": intent["intended_integrated_head"],
            "conditional_update": True,
            "force_push": False,
            "publication_attempt_id": attempt["attempt_id"],
            "publication_attempt_state": "confirmed",
            "publication_remote_id": self.remote_id,
            "publication_shared_ref": "refs/heads/main",
            "publication_attempt_store_ref": self.attempt_ref,
            "evidence_ref": "git:conditional-integration",
        }


integration_verifier = IntegrationVerifier()


class CooperativeLaneExtendedTests(unittest.TestCase):
    def test_integrator_is_singleton_but_does_not_block_isolated_writer(self):
        integrator = claim("i", (), lanes.LaneKind.INTEGRATOR)
        self.assertTrue(lanes.admit_writer([integrator], claim("w", {"src/a"})))
        self.assertFalse(lanes.admit_writer([integrator], claim("i2", (), lanes.LaneKind.INTEGRATOR)))

    def test_integrator_and_writer_may_coexist_only_with_distinct_branch_and_worktree(self):
        integrator = claim("i", (), lanes.LaneKind.INTEGRATOR,
                           branch="cdc/integration", worktree="/tmp/integration")
        self.assertFalse(lanes.admit_writer(
            [integrator], claim("w1", {"src/a"}, branch="cdc/integration", worktree="/tmp/w1")))
        self.assertFalse(lanes.admit_writer(
            [integrator], claim("w2", {"src/a"}, branch="cdc/w2",
                                worktree="/tmp/integration/../integration")))
        self.assertTrue(lanes.admit_writer(
            [integrator], claim("w3", {"src/a"}, branch="cdc/w3", worktree="/tmp/w3")))

    def test_short_and_full_ref_branch_aliases_cannot_share_writer_branch(self):
        a = claim("a", {"src/a"}, branch="refs/heads/cdc/shared", worktree="/tmp/a")
        b = claim("b", {"src/b"}, branch="cdc/shared", worktree="/tmp/b")
        self.assertFalse(lanes.admit_writer([a], b))

    def test_duplicate_branch_or_worktree_blocks_writer_even_when_paths_are_disjoint(self):
        a = claim("a", {"src/a"}, branch="cdc/shared", worktree="/tmp/a")
        self.assertFalse(lanes.admit_writer([a], claim("b", {"src/b"}, branch="cdc/shared", worktree="/tmp/b")))
        self.assertFalse(lanes.admit_writer([a], claim("b", {"src/b"}, branch="cdc/b", worktree="/tmp/a")))

    def test_unsafe_or_nonportable_claim_paths_fail_closed(self):
        for path in ("../escape", "/absolute", "src//double", "src/../escape", "CON/file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                lanes.validate_claim(claim("bad", {path}))

    def test_result_touched_paths_must_stay_within_original_write_claim(self):
        lane = claim("a", {"src/a", "docs/readme.md"})
        self.assertTrue(lanes.result_within_claim(lane, {"src/a/x.py", "docs/readme.md"}))
        self.assertFalse(lanes.result_within_claim(lane, {"src/a/x.py", "src/b/y.py"}))

    def test_project_completion_aggregates_lanes_queue_results_and_unknown_effects(self):
        self.assertTrue(lanes.project_can_finalize(
            active_lane_count=0, runnable_task_count=0, pending_result_count=0, unknown_effect_count=0))
        for kwargs in (
            {"active_lane_count": 1, "runnable_task_count": 0, "pending_result_count": 0, "unknown_effect_count": 0},
            {"active_lane_count": 0, "runnable_task_count": 1, "pending_result_count": 0, "unknown_effect_count": 0},
            {"active_lane_count": 0, "runnable_task_count": 0, "pending_result_count": 1, "unknown_effect_count": 0},
            {"active_lane_count": 0, "runnable_task_count": 0, "pending_result_count": 0, "unknown_effect_count": 1},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(lanes.project_can_finalize(**kwargs))

    def test_durable_coordinator_admits_disjoint_foreground_and_watchdog_lanes(self):
        coord = coordinator()
        self.assertTrue(coord.admit(
            claim("fg", {"src/ui"}, lanes.LaneKind.FOREGROUND), generation=1)["admitted"])
        self.assertTrue(coord.admit(
            claim("wd", {"src/backend"}, lanes.LaneKind.WATCHDOG), generation=1)["admitted"])
        self.assertEqual(len(coord.snapshot()["lanes"]), 2)

    def test_shared_product_branch_is_reserved_for_integrator(self):
        for kind in (lanes.LaneKind.WORKER, lanes.LaneKind.FOREGROUND, lanes.LaneKind.WATCHDOG):
            with self.subTest(kind=kind):
                coord = coordinator()
                decision = coord.admit(
                    claim("ordinary-" + kind.value, {"src/" + kind.value}, kind,
                          branch="refs/heads/main"), generation=1)
                self.assertFalse(decision["admitted"])
                self.assertEqual(decision["reason"], "shared_product_ref_reserved")
                self.assertEqual(coord.snapshot()["lanes"], {})

        coord = coordinator()
        decision = coord.admit(
            claim("integrator-shared", (), lanes.LaneKind.INTEGRATOR,
                  branch="refs/heads/main"), generation=1)
        self.assertTrue(decision["admitted"])

    def test_shared_product_branch_aliases_are_portably_equivalent(self):
        for branch in ("main", "refs/heads/MAIN", "MaIn"):
            with self.subTest(branch=branch):
                coord = coordinator()
                decision = coord.admit(
                    claim("writer-" + branch.replace("/", "-"), {"src/a"},
                          lanes.LaneKind.WORKER, branch=branch), generation=1)
                self.assertFalse(decision["admitted"])
                self.assertEqual(decision["reason"], "shared_product_ref_reserved")

    def test_shared_product_branch_unicode_normalization_alias_is_rejected(self):
        store = MemoryStore()
        config = runtime.LaneRegistryConfig(
            canonical_repository="example/g-cdc",
            product_source_ref="refs/heads/caf\u00e9",
            coordination_ref=store.ref,
            coordination_store_id=store.store_id,
            policy_authority="sha256:" + "d" * 64,
        )
        coord = runtime.ProjectLaneCoordinator(
            store, config, migration_verifier=migration_verifier)
        coord.establish_migration_gate({"legacy": "observed"})
        decision = coord.admit(
            claim("unicode-writer", {"src/a"}, lanes.LaneKind.WORKER,
                  branch="refs/heads/cafe\u0301"), generation=1)
        self.assertFalse(decision["admitted"])
        self.assertEqual(decision["reason"], "shared_product_ref_reserved")

    def test_coordinator_blocks_overlap_before_mutation_and_release_is_identity_bound(self):
        coord = coordinator()
        coord.admit(claim("a", {"src"}), generation=1)
        blocked = coord.admit(claim("b", {"src/b"}), generation=1)
        self.assertFalse(blocked["admitted"])
        self.assertEqual(blocked["reason"], "write_claim_conflict")
        with self.assertRaises(ValueError):
            coord.release("a", invocation_id="other", generation=1, executor_id="a", checkpoint_ref="cp-a")
        coord.release("a", invocation_id="a", generation=1, executor_id="a", checkpoint_ref="cp-a")
        self.assertEqual(coord.snapshot()["lanes"]["a"]["state"], "released")

    def test_handoff_requires_checkpoint_and_independent_quiescence(self):
        store = MemoryStore()
        coordinator = globals()["coordinator"](store)
        coordinator.admit(claim("a", {"src/a"}), generation=1)
        with self.assertRaises(ValueError):
            coordinator.handoff("a", invocation_id="a", generation=1, executor_id="a", checkpoint_ref=None)
        with self.assertRaises(ValueError):
            coordinator.handoff("a", invocation_id="a", generation=1, executor_id="a", checkpoint_ref="cp-1")
        coordinator = globals()["coordinator"](store, quiescence_verifier=quiescent)
        coordinator.handoff("a", invocation_id="a", generation=1, executor_id="a", checkpoint_ref="cp-1")
        self.assertEqual(coordinator.snapshot()["lanes"]["a"]["state"], "handoff_ready")

    def test_recovery_release_requires_executor_stopped_quiescence_not_ttl_or_silence(self):
        store = MemoryStore()
        coord = coordinator(store, quiescence_verifier=quiescent)
        coord.admit(claim("dead", {"src/a"}), generation=1)
        with self.assertRaisesRegex(ValueError, "executor_stopped"):
            coord.recovery_release("dead", checkpoint_ref="cp-dead")
        recovered = coordinator(store, quiescence_verifier=stopped_quiescent)
        recovered.recovery_release("dead", checkpoint_ref="cp-dead")
        lane = recovered.snapshot()["lanes"]["dead"]
        self.assertEqual(lane["state"], "released")
        self.assertTrue(lane["quiescence_evidence"]["executor_stopped"])

    def test_heartbeat_requires_independent_observable_activity(self):
        coord = coordinator()
        coord.admit(claim("a", {"src/a"}), generation=1)
        with self.assertRaisesRegex(ValueError, "activity verifier"):
            coord.heartbeat("a", invocation_id="a", generation=1, executor_id="a", activity_ref="commit:a")
        coord = coordinator(activity_verifier=activity_verifier)
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.heartbeat("a", invocation_id="a", generation=1, executor_id="a", activity_ref="commit:a")
        with self.assertRaises(ValueError):
            coord.heartbeat("a", invocation_id="a", generation=1, executor_id="a", activity_ref="commit:a")

    def test_release_requires_bound_executor_and_checkpoint(self):
        coord = coordinator()
        coord.admit(claim("a", {"src/a"}), generation=1)
        with self.assertRaises(ValueError):
            coord.release("a", invocation_id="a", generation=1, executor_id="other", checkpoint_ref="cp-a")
        with self.assertRaises(ValueError):
            coord.release("a", invocation_id="a", generation=1, executor_id="a", checkpoint_ref=None)

    def test_successful_writer_result_survives_lane_release_until_integrated(self):
        coord = coordinator(result_verifier=verifier(), integration_verifier=integration_verifier)
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.record_result(
            "a", invocation_id="a", generation=1, executor_id="a", result_commit="b" * 40,
            evidence_refs=["test:green"])
        coord.release("a", invocation_id="a", generation=1, executor_id="a", checkpoint_ref="cp-a")
        self.assertEqual(len(coord.snapshot()["integration_queue"]), 1)
        self.assertFalse(coord.can_finalize(runnable_task_count=0, unknown_effect_count=0))
        coord.admit(claim("integrator", (), lanes.LaneKind.INTEGRATOR), generation=1)
        intent = coord.claim_integration(
            "a", result_commit="b" * 40, integrator_lane_id="integrator",
            integrator_invocation_id="integrator", integrator_generation=1,
            integrator_executor_id="integrator", observed_shared_head="c" * 40,
            intended_integrated_head="d" * 40)
        self.assertTrue(intent["claimed"])
        coord.mark_integrated(
            "a", result_commit="b" * 40, operation_id=intent["operation_id"],
            integrator_lane_id="integrator", integrator_invocation_id="integrator",
            integrator_generation=1, integrator_executor_id="integrator")
        coord.release("integrator", invocation_id="integrator", generation=1, executor_id="integrator", checkpoint_ref="cp-integrator")
        self.assertTrue(coord.can_finalize(runnable_task_count=0, unknown_effect_count=0))

    def test_integration_intent_keeps_integrator_lane_nonreleasable_until_reconciled(self):
        coord = coordinator(result_verifier=verifier(), integration_verifier=integration_verifier)
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.record_result("a", invocation_id="a", generation=1, executor_id="a",
                            result_commit="b" * 40, evidence_refs=["test:green"])
        coord.admit(claim("integrator", (), lanes.LaneKind.INTEGRATOR), generation=1)
        intent = coord.claim_integration(
            "a", result_commit="b" * 40, integrator_lane_id="integrator",
            integrator_invocation_id="integrator", integrator_generation=1,
            integrator_executor_id="integrator", observed_shared_head="c" * 40,
            intended_integrated_head="d" * 40)
        self.assertTrue(coord.snapshot()["lanes"]["integrator"]["pending_effects"])
        with self.assertRaisesRegex(ValueError, "drained effects"):
            coord.release(
                "integrator", invocation_id="integrator", generation=1,
                executor_id="integrator", checkpoint_ref="cp:int")
        coord.mark_integrated(
            "a", result_commit="b" * 40, operation_id=intent["operation_id"],
            integrator_lane_id="integrator", integrator_invocation_id="integrator",
            integrator_generation=1, integrator_executor_id="integrator")
        self.assertFalse(coord.snapshot()["lanes"]["integrator"]["pending_effects"])
        coord.release(
            "integrator", invocation_id="integrator", generation=1,
            executor_id="integrator", checkpoint_ref="cp:int")

    def test_integration_requires_durable_one_shot_intent_before_reconciliation(self):
        coord = coordinator(result_verifier=verifier(), integration_verifier=integration_verifier)
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.record_result("a", invocation_id="a", generation=1, executor_id="a",
                            result_commit="b" * 40, evidence_refs=["test:green"])
        coord.admit(claim("integrator", (), lanes.LaneKind.INTEGRATOR), generation=1)
        with self.assertRaisesRegex(ValueError, "intent"):
            coord.mark_integrated(
                "a", result_commit="b" * 40, operation_id="missing",
                integrator_lane_id="integrator", integrator_invocation_id="integrator",
                integrator_generation=1, integrator_executor_id="integrator")
        first = coord.claim_integration(
            "a", result_commit="b" * 40, integrator_lane_id="integrator",
            integrator_invocation_id="integrator", integrator_generation=1,
            integrator_executor_id="integrator", observed_shared_head="c" * 40,
            intended_integrated_head="d" * 40)
        second = coord.claim_integration(
            "a", result_commit="b" * 40, integrator_lane_id="integrator",
            integrator_invocation_id="integrator", integrator_generation=1,
            integrator_executor_id="integrator", observed_shared_head="c" * 40,
            intended_integrated_head="d" * 40)
        self.assertTrue(first["claimed"])
        self.assertFalse(second["claimed"])
        self.assertEqual(first["operation_id"], second["operation_id"])
        with self.assertRaisesRegex(ValueError, "durable intent"):
            coord.claim_integration(
                "a", result_commit="b" * 40, integrator_lane_id="integrator",
                integrator_invocation_id="integrator", integrator_generation=1,
                integrator_executor_id="integrator", observed_shared_head="c" * 40,
                intended_integrated_head="e" * 40)

    def test_readonly_integration_verifier_cannot_close_queue(self):
        class ReadOnly:
            def publication_binding(self):
                return {
                    "shared_ref": "refs/heads/main",
                    "remote_id": None,
                    "durable_attempts": False,
                    "attempt_store_ref": None,
                    "attempt_store_id": None,
                }

            def __call__(self, item, integrator, intent):
                raise AssertionError("read-only verifier must not receive publication authority")

        coord = coordinator(result_verifier=verifier(), integration_verifier=ReadOnly())
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.record_result(
            "a", invocation_id="a", generation=1, executor_id="a",
            result_commit="b" * 40, evidence_refs=["test:green"])
        coord.admit(claim("integrator", (), lanes.LaneKind.INTEGRATOR), generation=1)
        intent = coord.claim_integration(
            "a", result_commit="b" * 40, integrator_lane_id="integrator",
            integrator_invocation_id="integrator", integrator_generation=1,
            integrator_executor_id="integrator", observed_shared_head="c" * 40,
            intended_integrated_head="d" * 40)
        with self.assertRaisesRegex(ValueError, "durable publication"):
            coord.mark_integrated(
                "a", result_commit="b" * 40, operation_id=intent["operation_id"],
                integrator_lane_id="integrator", integrator_invocation_id="integrator",
                integrator_generation=1, integrator_executor_id="integrator")
        self.assertEqual(len(coord.snapshot()["integration_queue"]), 1)

    def test_mark_integrated_rejects_mismatched_trusted_attempt_binding(self):
        class MismatchedAttemptVerifier(IntegrationVerifier):
            def publication_attempt(self, operation_id):
                value = super().publication_attempt(operation_id)
                if value is not None:
                    value["result_commit"] = "f" * 40
                return value

        integration = MismatchedAttemptVerifier()
        coord = coordinator(result_verifier=verifier(), integration_verifier=integration)
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.record_result(
            "a", invocation_id="a", generation=1, executor_id="a",
            result_commit="b" * 40, evidence_refs=["test:green"])
        coord.admit(
            claim("integrator", (), lanes.LaneKind.INTEGRATOR,
                  branch="refs/heads/main"), generation=1)
        intent = coord.claim_integration(
            "a", result_commit="b" * 40, integrator_lane_id="integrator",
            integrator_invocation_id="integrator", integrator_generation=1,
            integrator_executor_id="integrator", observed_shared_head="c" * 40,
            intended_integrated_head="d" * 40)
        with self.assertRaisesRegex(ValueError, "trusted publication attempt"):
            coord.mark_integrated(
                "a", result_commit="b" * 40, operation_id=intent["operation_id"],
                integrator_lane_id="integrator", integrator_invocation_id="integrator",
                integrator_generation=1, integrator_executor_id="integrator")
        self.assertEqual(len(coord.snapshot()["integration_queue"]), 1)

    def test_lane_cannot_publish_multiple_accepted_results(self):
        coord = coordinator(result_verifier=verifier())
        coord.admit(claim("a", {"src/a"}), generation=1)
        coord.record_result("a", invocation_id="a", generation=1, executor_id="a",
                            result_commit="b" * 40, evidence_refs=["test:first"])
        with self.assertRaisesRegex(ValueError, "accepted writer result"):
            coord.record_result("a", invocation_id="a", generation=1, executor_id="a",
                                result_commit="c" * 40, evidence_refs=["test:second"])

    def test_result_rejects_stale_base_unverified_ancestry_or_path_escape(self):
        for check in (
            verifier("c" * 40, True, {"src/a/x.py"}),
            verifier(SHA, False, {"src/a/x.py"}),
            verifier(SHA, True, {"src/b/x.py"}),
        ):
            coord = coordinator(result_verifier=check)
            coord.admit(claim("a", {"src/a"}), generation=1)
            with self.assertRaises(ValueError):
                coord.record_result(
                    "a", invocation_id="a", generation=1, executor_id="a", result_commit="b" * 40,
                    evidence_refs=["test:green"])


if __name__ == "__main__":
    unittest.main()
