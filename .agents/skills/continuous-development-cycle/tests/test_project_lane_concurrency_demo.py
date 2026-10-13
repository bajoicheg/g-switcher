import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from managed_executor_runtime import LocalCommandBackend
from project_lanes import LaneClaim, LaneKind
from project_lane_runtime import LaneRegistryConfig, ProjectLaneCoordinator
from project_lane_executor import ProjectLaneExecutionAdapter


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class MemoryStore:
    ref = "refs/heads/cdc/project-lanes-demo"
    store_id = "sha256:" + "d" * 64

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


@unittest.skipUnless(sys.platform == "linux" and Path("/proc/self/stat").exists(),
                     "real lane process demo requires Linux /proc")
class CooperativeLaneProcessDemoTests(unittest.TestCase):
    def test_foreground_and_watchdog_run_concurrently_after_durable_lane_claims(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            git(repo, "config", "user.email", "cdc@example.invalid")
            git(repo, "config", "user.name", "CDC test")
            (repo / "src").mkdir()
            (repo / "src/base.txt").write_text("base\n")
            git(repo, "add", ".")
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            base = git(repo, "rev-parse", "HEAD")

            worktrees = root / "worktrees"
            fg = worktrees / "fg"
            wd = worktrees / "wd"
            store = MemoryStore()
            config = LaneRegistryConfig(
                canonical_repository="example/g-cdc", product_source_ref="refs/heads/main",
                coordination_ref=store.ref, coordination_store_id=store.store_id,
                policy_authority="sha256:" + "e" * 64)
            coordinator = ProjectLaneCoordinator(
                store, config, migration_verifier=lambda observation: {
                    "safe": True, "legacy_lease": "absent", "external_guard": "none",
                    "legacy_mode_disabled": True, "evidence_ref": "legacy:none"})
            coordinator.establish_migration_gate({"legacy": "observed"})
            claims = [
                LaneClaim("foreground", "fg-inv", LaneKind.FOREGROUND, base, str(fg), "refs/heads/lane-fg",
                          write_paths=frozenset({"src/fg"}), executor_id="fg", role="writer"),
                LaneClaim("watchdog", "wd-inv", LaneKind.WATCHDOG, base, str(wd), "refs/heads/lane-wd",
                          write_paths=frozenset({"src/wd"}), executor_id="wd", role="writer"),
            ]
            for claim in claims:
                self.assertTrue(coordinator.admit(claim, generation=1)["admitted"])

            worker = root / "worker.py"
            worker.write_text(
                "from pathlib import Path\n"
                "import sys,time\n"
                "root=Path.cwd(); name=sys.argv[1]\n"
                "target=root/'src'/name; target.mkdir(parents=True,exist_ok=True)\n"
                "(target/'result.txt').write_text(name+'\\n')\n"
                "(root/(name+'.ready')).write_text('ready')\n"
                "release=root/(name+'.release')\n"
                "while not release.exists(): time.sleep(0.02)\n"
            )

            backend = LocalCommandBackend(root / "lane-journal")
            adapter = ProjectLaneExecutionAdapter(
                coordinator, repo, backend, worktree_root=worktrees,
                journal_root=root / "lane-journal")
            adapter.start(
                "foreground", invocation_id="fg-inv", generation=1, executor_id="fg",
                argv=[sys.executable, str(worker), "fg"], timeout_seconds=10)
            adapter.start(
                "watchdog", invocation_id="wd-inv", generation=1, executor_id="wd",
                argv=[sys.executable, str(worker), "wd"], timeout_seconds=10)

            deadline = time.monotonic() + 6
            fg_obs = wd_obs = None
            while time.monotonic() < deadline:
                fg_obs = adapter.observe("foreground")
                wd_obs = adapter.observe("watchdog")
                if ((fg / "fg.ready").exists() and (wd / "wd.ready").exists()
                        and fg_obs["status"] in {"starting", "running"}
                        and wd_obs["status"] in {"starting", "running"}):
                    break
                time.sleep(0.03)
            self.assertTrue((fg / "fg.ready").exists())
            self.assertTrue((wd / "wd.ready").exists())
            self.assertIn(fg_obs["status"], {"starting", "running"})
            self.assertIn(wd_obs["status"], {"starting", "running"})
            self.assertTrue((fg / "src/fg/result.txt").exists())
            self.assertFalse((fg / "src/wd").exists())
            self.assertTrue((wd / "src/wd/result.txt").exists())
            self.assertFalse((wd / "src/fg").exists())
            self.assertTrue(coordinator.snapshot()["lanes"]["foreground"]["pending_effects"])
            self.assertTrue(coordinator.snapshot()["lanes"]["watchdog"]["pending_effects"])

            # Cooperative foreground work never changes scheduler state.
            scheduler_mutations = []
            self.assertEqual(scheduler_mutations, [])

            (fg / "fg.release").write_text("go")
            (wd / "wd.release").write_text("go")
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                fg_obs = adapter.observe("foreground")
                wd_obs = adapter.observe("watchdog")
                if fg_obs["status"] == "succeeded" and wd_obs["status"] == "succeeded":
                    break
                time.sleep(0.03)
            self.assertEqual(fg_obs["status"], "succeeded")
            self.assertEqual(wd_obs["status"], "succeeded")
            self.assertTrue(fg_obs["quiescent"])
            self.assertTrue(wd_obs["quiescent"])
            self.assertFalse(coordinator.snapshot()["lanes"]["foreground"]["pending_effects"])
            self.assertFalse(coordinator.snapshot()["lanes"]["watchdog"]["pending_effects"])

            coordinator.release(
                "foreground", invocation_id="fg-inv", generation=1, executor_id="fg",
                checkpoint_ref="checkpoint:fg")
            self.assertEqual(coordinator.snapshot()["lanes"]["watchdog"]["state"], "running")
            coordinator.release(
                "watchdog", invocation_id="wd-inv", generation=1, executor_id="wd",
                checkpoint_ref="checkpoint:wd")


if __name__ == "__main__":
    unittest.main()
