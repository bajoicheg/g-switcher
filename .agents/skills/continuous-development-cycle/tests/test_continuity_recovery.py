"""Exercise the real lease boundary, not response text or fabricated traces."""
import copy
import sys
import unittest
from unittest import mock
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import execution_continuity as continuity
import execution_lease_v2 as lease
from continuity_fixtures import with_terminal_evidence

OWNER = "11111111-1111-4111-8111-111111111111"
AT = "2026-09-28T05:30:00Z"


def state(outcome="progress", runnable=True):
    return dict(schema="execution-continuity/v1", invocation_id="recovery",
                current_state="CHECKPOINT", requested_terminal_outcome=outcome,
                runnable_next_action=runnable, meaningful_progress_refs=["git:step-1"],
                primitive_steps=[], external_binding=None, blocker=None,
                checkpoint_ref="checkpoint:recovery", next_action="verify and integrate",
                lease_release_required=False, lease_released=False)


def owned():
    with mock.patch.object(lease.terminal_capability_api,"validate_verified",return_value={}):
        return lease.acquire(lease.initialize("example/project", "refs/heads/main"),
                             OWNER, AT, invocation=dict(invocation_id="recovery",
                             automation_id=None, conversation_id=None,
                             execution_surface="managed", started_at_utc=AT),
                             terminal_capability=object())


def reconciled():
    record = lease.begin_finalization(owned(), OWNER, 1, "recovery", AT,
                                      pending_shared_writes=False)
    record = lease.record_checkpoint(record, OWNER, 1, "recovery", AT,
                                      checkpoint_ref="checkpoint:recovery", pending_shared_writes=False)
    return lease.reconcile_finalization(record, OWNER, 1, "recovery", AT,
                                         external_reconciliation="none")


class ContinuityRecoveryTests(unittest.TestCase):
    def test_runnable_work_rejects_every_terminal_claim(self):
        for outcome in ("progress", "waiting_external", "blocked", "task_complete", "scope_complete"):
            with self.subTest(outcome=outcome):
                s = state(outcome)
                s["external_binding"] = dict(kind="ci", id="run-1", operation_key="op-1") if outcome == "waiting_external" else None
                s["blocker"] = "one dependency unavailable" if outcome == "blocked" else None
                self.assertFalse(continuity.evaluate(s)["allowed"])
                record = reconciled()
                with self.assertRaises(ValueError):
                    lease.mark_ready(record, OWNER, 1, "recovery", AT, continuity_state=s)
                self.assertEqual(record["owner_id"], OWNER)

    def test_progress_without_queue_is_still_not_scope_completion(self):
        self.assertFalse(continuity.evaluate(state(runnable=False))["allowed"])

    def test_continue_is_valid_but_never_final(self):
        result = continuity.evaluate(state("continue"))
        self.assertTrue(result["allowed"])
        self.assertIs(result.get("final_response_allowed"), False)

    def test_two_tasks_run_before_one_finalization(self):
        record = owned()
        actions = ["implement", "verify"]
        performed = []
        while actions:
            performed.append(actions.pop(0))
            assessment = state("progress" if actions else "scope_complete", bool(actions))
            if not actions:
                assessment = with_terminal_evidence(assessment)
            result = continuity.evaluate(assessment)
            if actions:
                self.assertFalse(result["allowed"])
                lease.check_record(record, OWNER, 1, "recovery", AT, action="product_write")
            else:
                self.assertIs(result.get("final_response_allowed"), True)
        record = reconciled()
        record = lease.mark_ready(record, OWNER, 1, "recovery", AT, continuity_state=assessment)
        record = lease.release(record, OWNER, 1, "recovery", AT)
        self.assertEqual(performed, ["implement", "verify"])
        self.assertIsNone(record["owner_id"])

    def test_real_wait_and_blocker_without_runnable_work_remain_valid(self):
        for outcome in ("waiting_external", "blocked", "scope_complete", "task_complete"):
            with self.subTest(outcome=outcome):
                s = state(outcome, False)
                if outcome == "waiting_external":
                    s["external_binding"] = dict(kind="ci", id="run-1", operation_key="op-1")
                if outcome == "blocked":
                    s["blocker"] = "required credential unavailable"
                s = with_terminal_evidence(s, AT)
                record = lease.mark_ready(reconciled(), OWNER, 1, "recovery", AT, continuity_state=s)
                self.assertIsNone(lease.release(record, OWNER, 1, "recovery", AT)["owner_id"])

    def test_finalization_must_use_the_persisted_checkpoint(self):
        s = state("scope_complete", False)
        s["checkpoint_ref"] = "checkpoint:unrelated"
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            lease.mark_ready(reconciled(), OWNER, 1, "recovery", AT, continuity_state=s)

    def test_milestone_cannot_be_relabelled_as_scope_complete(self):
        self.assertFalse(continuity.evaluate(state("scope_complete", False))["allowed"])

    def test_free_form_blocker_is_not_proof(self):
        s = state("blocked", False)
        s["blocker"] = "guess: credential missing"
        self.assertFalse(continuity.evaluate(s)["allowed"])

    def test_wait_cannot_discard_next_action(self):
        s = state("waiting_external", False)
        s["external_binding"] = dict(kind="ci", id="run-1", operation_key="op-1")
        s["next_action"] = None
        self.assertFalse(continuity.evaluate(s)["allowed"])


if __name__ == "__main__":
    unittest.main()
