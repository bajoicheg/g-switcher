import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import project_lane_executor as executor
from project_lanes import LaneClaim, LaneKind
from project_lane_runtime import LaneRegistryConfig, ProjectLaneCoordinator


class MemoryStore:
    ref = "refs/heads/cdc/project-lane-executor"
    store_id = "sha256:" + "a" * 64

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


class FakeBackend:
    def __init__(self, journal_root):
        self.journal_root = Path(journal_root)
        self.starts = 0
        self.requests = []
        self.before_start = None
        self.observation = None

    def start(self, request):
        self.starts += 1
        self.requests.append(copy.deepcopy(request))
        if self.before_start:
            self.before_start(request)
        if self.observation is None:
            raise TimeoutError("lost start reply")
        return copy.deepcopy(self.observation(request))

    def observe(self, request, receipt=None):
        if self.observation is None:
            return {
                "schema": "project-lane-observation/v1",
                "identity": request["identity"],
                "status": "unknown",
                "quiescent": False,
                "reason": "still unknown",
            }
        return copy.deepcopy(self.observation(request))


def terminal_receipt(request):
    ref = executor._digest(request)
    return {
        "schema": "managed-executor-observation/v1",
        "identity": request["identity"],
        "claim": request["claim"],
        "request_ref": ref,
        "launch_id": ref,
        "status": "succeeded",
        "quiescent": True,
    }


class ProjectLaneExecutionAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "CDC Test"], check=True)
        (self.repo / "README.md").write_text("base\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.base = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.store = MemoryStore()
        config = LaneRegistryConfig(
            canonical_repository="example/repo",
            product_source_ref="refs/heads/main",
            coordination_ref=self.store.ref,
            coordination_store_id=self.store.store_id,
            policy_authority="sha256:" + "b" * 64,
        )
        self.coordinator = ProjectLaneCoordinator(
            self.store, config, migration_verifier=lambda observation: {
                "safe": True, "legacy_lease": "absent", "external_guard": "none",
                "legacy_mode_disabled": True, "evidence_ref": "legacy:none"})
        self.coordinator.establish_migration_gate({"legacy": "observed"})
        self.worktrees = self.root / "worktrees"
        self.claim = LaneClaim(
            "lane-a", "inv-a", LaneKind.WORKER, self.base,
            str(self.worktrees / "lane-a"), "refs/heads/lane-a",
            write_paths=frozenset({"src/a"}), executor_id="exec-a", role="writer")
        self.coordinator.admit(self.claim, generation=1)
        self.backend = FakeBackend(self.root / "journal")
        self.adapter = executor.ProjectLaneExecutionAdapter(
            self.coordinator, self.repo, self.backend, worktree_root=self.worktrees,
            journal_root=self.root / "journal")

    def test_backend_start_observes_durable_claim_before_effect(self):
        observed = {}
        def inspect(request):
            state = self.coordinator.snapshot()
            observed["pending"] = state["lanes"]["lane-a"]["pending_effects"]
            observed["operation"] = state["start_operations"]["lane-a"]["status"]
            observed["request_exists"] = Path(request["journal_directory"], "request.json").exists()
        self.backend.before_start = inspect
        self.backend.observation = terminal_receipt
        result = self.adapter.start(
            "lane-a", invocation_id="inv-a", generation=1, executor_id="exec-a",
            argv=[sys.executable, "-c", "pass"], timeout_seconds=10)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(observed, {
            "pending": True, "operation": "claimed", "request_exists": True})
        self.assertFalse(self.coordinator.snapshot()["lanes"]["lane-a"]["pending_effects"])

    def test_unknown_start_is_never_replayed(self):
        first = self.adapter.start(
            "lane-a", invocation_id="inv-a", generation=1, executor_id="exec-a",
            argv=[sys.executable, "-c", "pass"], timeout_seconds=10)
        self.assertEqual(first["status"], "unknown")
        self.assertEqual(self.backend.starts, 1)
        second = self.adapter.start(
            "lane-a", invocation_id="inv-a", generation=1, executor_id="exec-a",
            argv=[sys.executable, "-c", "raise SystemExit(2)"], timeout_seconds=1)
        self.assertEqual(second["status"], "unknown")
        self.assertEqual(self.backend.starts, 1)
        self.assertTrue(self.coordinator.snapshot()["lanes"]["lane-a"]["pending_effects"])

    def test_claim_without_local_request_is_observed_unknown_not_replayed(self):
        claim = self.coordinator.claim_start(
            "lane-a", invocation_id="inv-a", generation=1, executor_id="exec-a")
        self.assertTrue(claim["claimed"])
        result = self.adapter.start(
            "lane-a", invocation_id="inv-a", generation=1, executor_id="exec-a",
            argv=[sys.executable, "-c", "pass"], timeout_seconds=10)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(self.backend.starts, 0)
        self.assertTrue(self.coordinator.snapshot()["lanes"]["lane-a"]["pending_effects"])

    def test_worktree_escape_is_rejected_before_backend_start(self):
        bad = LaneClaim(
            "escape", "escape-inv", LaneKind.WORKER, self.base,
            str(self.root.parent / "outside-lane"), "refs/heads/escape",
            write_paths=frozenset({"src/x"}), executor_id="escape", role="writer")
        self.coordinator.admit(bad, generation=1)
        with self.assertRaisesRegex(ValueError, "worktree"):
            self.adapter.start(
                "escape", invocation_id="escape-inv", generation=1, executor_id="escape",
                argv=[sys.executable, "-c", "pass"], timeout_seconds=10)
        self.assertEqual(self.backend.starts, 0)
        state = self.coordinator.snapshot()
        self.assertFalse(state["lanes"]["escape"]["pending_effects"])
        self.assertEqual(state["start_operations"]["escape"]["status"], "failed")

    def test_review_lane_keeps_read_only_executor_identity(self):
        review = LaneClaim(
            "review", "review-inv", LaneKind.REVIEW, self.base,
            str(self.worktrees / "review"), "refs/heads/review",
            executor_id="review-exec", role="review")
        decision = self.coordinator.admit(review, generation=1)
        self.assertTrue(decision["admitted"])
        self.backend.observation = terminal_receipt
        result = self.adapter.start(
            "review", invocation_id="review-inv", generation=1, executor_id="review-exec",
            argv=[sys.executable, "-c", "pass"], timeout_seconds=10)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.backend.requests[-1]["identity"]["role"], "review")

    def test_malformed_persisted_review_claim_never_reaches_writer_backend(self):
        self.store.value["lanes"]["lane-a"]["claim"]["kind"] = LaneKind.REVIEW.value
        self.store.value["lanes"]["lane-a"]["claim"]["role"] = "review"
        with self.assertRaisesRegex(ValueError, "lane registry lane"):
            self.adapter.start(
                "lane-a", invocation_id="inv-a", generation=1, executor_id="exec-a",
                argv=[sys.executable, "-c", "pass"], timeout_seconds=10)
        self.assertEqual(self.backend.starts, 0)

    def test_integrator_lane_cannot_launch_worker_backend(self):
        store = MemoryStore()
        config = LaneRegistryConfig(
            canonical_repository="example/repo",
            product_source_ref="refs/heads/main",
            coordination_ref=store.ref,
            coordination_store_id=store.store_id,
            policy_authority="sha256:" + "b" * 64,
        )
        coord = ProjectLaneCoordinator(
            store, config, migration_verifier=lambda observation: {
                "safe": True, "legacy_lease": "absent", "external_guard": "none",
                "legacy_mode_disabled": True, "evidence_ref": "legacy:none"})
        coord.establish_migration_gate({"legacy": "observed"})
        claim = LaneClaim(
            "integrator", "int-inv", LaneKind.INTEGRATOR, self.base,
            str(self.worktrees / "integrator"), "refs/heads/integration",
            executor_id="integrator", role="integrator")
        coord.admit(claim, generation=1)
        adapter = executor.ProjectLaneExecutionAdapter(
            coord, self.repo, self.backend, worktree_root=self.worktrees,
            journal_root=self.root / "journal-int")
        with self.assertRaisesRegex(ValueError, "integrator"):
            adapter.start(
                "integrator", invocation_id="int-inv", generation=1,
                executor_id="integrator", argv=[sys.executable, "-c", "pass"],
                timeout_seconds=10)


if __name__ == "__main__":
    unittest.main()
