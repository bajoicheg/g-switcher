import copy, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import managed_executor_attempt as m

BASE = "a" * 40
T0 = "2026-01-01T00:00:00Z"
T1 = "2026-01-01T00:00:01Z"
T2 = "2026-01-01T00:00:02Z"
T3 = "2026-01-01T00:00:03Z"
T4 = "2026-01-01T00:00:04Z"

def writer(task="writer-a", attempt="a1", path="src/UI"):
    return m.new_attempt(
        pool_id="pool-1", change_id="change-1", task_id=task, attempt_id=attempt,
        parent_invocation_id="parent-1", executor_id="exec-1", backend="codex_compute",
        role="writer", base_sha=BASE, at_utc=T0, write_paths=[path],
        branch=f"refs/heads/cdc/{task}-{attempt}", worktree=f"worktrees/{task}-{attempt}",
    )

def succeeded(a):
    a = m.transition(a, "queued", T1)
    a = m.transition(a, "running", T2, activity_ref="provider:started")
    return m.transition(a, "succeeded", T3, activity_ref="git:result")

def result_for(a, changed="src/ui/file.txt"):
    return {
        "schema": "managed-executor-result/v1",
        "pool_id": a["pool_id"], "change_id": a["change_id"], "task_id": a["task_id"],
        "attempt_id": a["attempt_id"], "parent_invocation_id": a["parent_invocation_id"],
        "role": a["role"], "base_sha": a["base_sha"], "result_commit": "b" * 40,
        "changed_paths": [changed], "evidence_refs": ["tests:green"],
        "completed_at_utc": T4, "integrated": False,
        "authorizes_shared_branch_write": False, "authorizes_merge": False,
        "authorizes_release": False, "authorizes_scope_expansion": False,
        "authorizes_scheduler_mutation": False, "authorizes_user_approval": False,
    }

class ManagedExecutorAttemptTests(unittest.TestCase):
    def test_writer_requires_isolated_branch_worktree_and_write_set(self):
        with self.assertRaisesRegex(ValueError, "writer attempt requires write_paths"):
            m.new_attempt(pool_id="p", change_id="c", task_id="t", attempt_id="a",
                parent_invocation_id="i", executor_id="e", backend="local", role="writer",
                base_sha=BASE, at_utc=T0, write_paths=[], branch="refs/heads/x", worktree="w")

    def test_read_only_cannot_claim_writes(self):
        with self.assertRaisesRegex(ValueError, "cannot claim"):
            m.new_attempt(pool_id="p", change_id="c", task_id="t", attempt_id="a",
                parent_invocation_id="i", executor_id="e", backend="local", role="read_only",
                base_sha=BASE, at_utc=T0, write_paths=["src/a"])

    def test_illegal_transition_rejected(self):
        with self.assertRaisesRegex(ValueError, "illegal attempt transition"):
            m.transition(writer(), "succeeded", T1, activity_ref="git:x")

    def test_running_requires_new_activity_and_duplicate_heartbeat_rejected(self):
        a=m.transition(writer(),"queued",T1)
        a=m.transition(a,"running",T2,activity_ref="provider:started")
        with self.assertRaisesRegex(ValueError,"unique observable activity"):
            m.heartbeat(a,T3,activity_ref="provider:started")

    def test_retry_preserves_lineage_and_identity(self):
        a=m.transition(writer(),"queued",T1)
        a=m.transition(a,"failed",T2,failure="setup failed")
        b=m.retry(a,attempt_id="a2",executor_id="exec-2",backend="local",at_utc=T3,
                  branch="refs/heads/cdc/writer-a-a2",worktree="worktrees/writer-a-a2")
        self.assertEqual(b["predecessor_attempt_id"],"a1")
        self.assertEqual(b["base_sha"],a["base_sha"])
        self.assertEqual(b["write_paths"],a["write_paths"])
        self.assertEqual(b["status"],"planned")

    def test_duplicate_active_launch_same_task_rejected(self):
        a=writer(attempt="a1"); b=writer(attempt="a2")
        with self.assertRaisesRegex(ValueError,"duplicate active launch"):
            m.assert_no_duplicate_active([a,b])

    def test_unrelated_active_tasks_do_not_conflict(self):
        self.assertTrue(m.assert_no_duplicate_active([writer("a","a1"),writer("b","b1")]))

    def test_casefold_path_alias_is_within_claim(self):
        a=succeeded(writer(path="src/UI"))
        self.assertTrue(m.acceptance(result_for(a,"src/ui/file.txt"),a)["accepted"])

    def test_unicode_normalized_path_alias_is_within_claim(self):
        a=succeeded(writer(path="src/caf\u00e9"))
        self.assertTrue(m.acceptance(result_for(a,"src/cafe\u0301/file.txt"),a)["accepted"])

    def test_out_of_scope_writer_result_is_rejected(self):
        a=succeeded(writer(path="src/ui"))
        with self.assertRaisesRegex(ValueError,"escapes declared write set"):
            m.validate_result(result_for(a,"src/server/file.txt"),a)

    def test_result_identity_mismatch_is_rejected(self):
        a=succeeded(writer())
        r=result_for(a); r["attempt_id"]="other"
        with self.assertRaisesRegex(ValueError,"does not match"):
            m.validate_result(r,a)

    def test_worker_result_never_grants_authority(self):
        a=succeeded(writer()); r=result_for(a)
        accepted=m.acceptance(r,a)
        for name in m.AUTHORITY_FIELDS:
            self.assertFalse(accepted[name])
        r["authorizes_merge"]=True
        with self.assertRaisesRegex(ValueError,"must be false"):
            m.validate_result(r,a)

    def test_read_only_success_has_no_commit_or_changed_paths(self):
        a=m.new_attempt(pool_id="p",change_id="c",task_id="review",attempt_id="r1",
            parent_invocation_id="i",executor_id="e",backend="work",role="review",
            base_sha=BASE,at_utc=T0)
        a=m.transition(a,"queued",T1)
        a=m.transition(a,"running",T2,activity_ref="review:started")
        a=m.transition(a,"succeeded",T3,activity_ref="review:done")
        r=result_for(a); r["result_commit"]=None; r["changed_paths"]=[]
        self.assertTrue(m.validate_result(r,a))

if __name__ == "__main__":
    unittest.main()
