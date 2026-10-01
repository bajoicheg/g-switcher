"""Behavioral recovery tests; no provider calls or remote mutations."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/operation_intent.py"
CREATED = "2026-09-22T10:00:00Z"
READ_BACK = "2026-09-22T10:01:00Z"
SUBMITTING = "2026-09-22T10:02:00Z"
LOST = "2026-09-22T10:03:00Z"
OBSERVED = "2026-09-22T10:04:00Z"


def binding():
    return {
        "repository": "example/project",
        "candidate_sha": "a" * 40,
        "backend": "codex",
        "mode": "COMPUTE_ONLY",
        "check_suite_fingerprint": "sha256:" + "b" * 64,
        "environment_fingerprint": "sha256:" + "c" * 64,
        "check_plan_digest": "sha256:" + "d" * 64,
        "environment_id": "environment-1",
    }


class OperationIntentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "operation intent helper is missing")
        spec = importlib.util.spec_from_file_location("operation_intent", SCRIPT)
        self.op = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.op)

    def prepared(self, **kwargs):
        return self.op.prepare(binding(), "attempt-1", "refs/heads/candidate", CREATED, **kwargs)

    def submitting(self):
        intent = self.prepared()
        receipt = self.op.verify_readback(
            intent, copy.deepcopy(intent), "https://example.invalid/coordination/1", READ_BACK
        )
        return self.op.transition(intent, "submitting", SUBMITTING, receipt=receipt)

    def unknown(self):
        return self.op.transition(self.submitting(), "unknown", LOST)

    def task(self, intent, state="running", conclusion=None, evidence=None):
        return {
            "task_id": "task-17",
            "task_url": "https://example.invalid/tasks/17",
            "operation_key": intent["operation_key"],
            "attempt_id": intent["attempt_id"],
            "binding": copy.deepcopy(intent["binding"]),
            "state": state,
            "conclusion": conclusion,
            "evidence_refs": evidence or [],
        }

    def observation(self, intent, tasks, complete=True):
        return {
            "schema": "operation-observation/v1",
            "operation_key": intent["operation_key"],
            "lookup_complete": complete,
            "observed_at_utc": OBSERVED,
            "tasks": tasks,
        }

    def test_key_is_stable_across_mapping_order_and_attempts(self):
        first = self.prepared()
        second = self.op.prepare(dict(reversed(list(binding().items()))), "attempt-2", "other-ref", CREATED)
        self.assertEqual(first["operation_key"], second["operation_key"])
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])

    def test_changed_execution_contract_changes_operation_key(self):
        key = self.prepared()["operation_key"]
        changes = {
            "repository": "example/other",
            "candidate_sha": "f" * 40,
            "check_suite_fingerprint": "sha256:" + "e" * 64,
            "environment_fingerprint": "sha256:" + "e" * 64,
            "check_plan_digest": "sha256:" + "e" * 64,
            "backend": "approved-local-runner",
            "mode": "BUILD_ONLY",
            "environment_id": "environment-2",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = binding()
                changed[field] = value
                self.assertNotEqual(key, self.op.prepare(changed, "attempt-1", "candidate", CREATED)["operation_key"])

    def test_submit_requires_matching_durable_readback(self):
        intent = self.prepared()
        with self.assertRaisesRegex(ValueError, "readback|receipt"):
            self.op.transition(intent, "submitting", SUBMITTING)
        wrong = self.op.prepare(binding(), "attempt-2", "refs/heads/candidate", CREATED)
        with self.assertRaisesRegex(ValueError, "readback|match"):
            self.op.verify_readback(intent, wrong, "coordination/1", READ_BACK)
        receipt = self.op.verify_readback(intent, intent, "coordination/1", READ_BACK)
        receipt["record_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest|receipt"):
            self.op.transition(intent, "submitting", SUBMITTING, receipt=receipt)

    def test_lost_submit_response_reconciles_original_running_task(self):
        intent = self.unknown()
        decision = self.op.decide(intent, self.observation(intent, [self.task(intent)]))
        self.assertEqual(decision["action"], "observe")
        self.assertEqual(decision["task_id"], "task-17")
        self.assertFalse(decision["allow_submission"])
        self.assertTrue(decision["external_guard"])

    def test_repeat_wake_is_read_only_and_cannot_request_resubmission(self):
        intent = self.unknown()
        before = copy.deepcopy(intent)
        observation = self.observation(intent, [self.task(intent)])
        first = self.op.decide(intent, observation)
        self.assertEqual(first, self.op.decide(intent, observation))
        self.assertEqual(intent, before)
        self.assertFalse(first["allow_submission"])

    def test_missing_task_never_allows_replacement_even_after_complete_lookup(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                intent = self.unknown()
                decision = self.op.decide(intent, self.observation(intent, [], complete))
                self.assertEqual(decision["action"], "reconcile")
                self.assertFalse(decision["allow_submission"])
                self.assertTrue(decision["external_guard"])

    def test_incomplete_terminal_lookup_keeps_external_guard(self):
        intent = self.unknown()
        task = self.task(intent, "terminal", "succeeded", ["logs/17"])
        decision = self.op.decide(intent, self.observation(intent, [task], False))
        self.assertEqual(decision["action"], "reconcile")
        self.assertTrue(decision["external_guard"])

    def test_wrong_task_binding_blocks_recovery(self):
        intent = self.unknown()
        changes = {"candidate_sha": "e" * 40, "environment_id": "environment-2", "mode": "EDIT", "check_plan_digest": "sha256:" + "e" * 64}
        for field, value in changes.items():
            with self.subTest(field=field):
                task = self.task(intent)
                task["binding"][field] = value
                decision = self.op.decide(intent, self.observation(intent, [task]))
                self.assertEqual(decision["action"], "blocked")
                self.assertTrue(decision["external_guard"])
                self.assertFalse(decision["allow_submission"])

    def test_different_attempt_or_multiple_matches_fail_closed(self):
        intent = self.unknown()
        different = self.task(intent)
        different["attempt_id"] = "attempt-2"
        for tasks in ([different], [self.task(intent), self.task(intent)]):
            with self.subTest(tasks=tasks):
                decision = self.op.decide(intent, self.observation(intent, tasks))
                self.assertEqual(decision["action"], "blocked")
                self.assertTrue(decision["external_guard"])

    def test_terminal_timeout_reuses_outcome_without_claiming_completion(self):
        intent = self.unknown()
        task = self.task(intent, "terminal", "timed_out", ["logs/17"])
        decision = self.op.decide(intent, self.observation(intent, [task]))
        self.assertEqual(decision["action"], "reuse_terminal")
        self.assertEqual(decision["terminal_outcome"], "timed_out")
        self.assertFalse(decision["completion_claim_allowed"])
        self.assertFalse(decision["allow_submission"])

    def test_successful_provider_conclusion_still_requires_evidence_validation(self):
        intent = self.unknown()
        task = self.task(intent, "terminal", "succeeded", ["logs/17"])
        decision = self.op.decide(intent, self.observation(intent, [task]))
        self.assertEqual(decision["action"], "reuse_terminal")
        self.assertFalse(decision["completion_claim_allowed"])
        self.assertFalse(decision["external_guard"])

    def test_terminal_without_evidence_requires_reconciliation(self):
        intent = self.unknown()
        decision = self.op.decide(intent, self.observation(intent, [self.task(intent, "terminal", "failed")]))
        self.assertEqual(decision["action"], "reconcile")
        self.assertFalse(decision["completion_claim_allowed"])

    def test_unknown_cannot_be_reset_to_prepared_or_submitting(self):
        for state in ("prepared", "submitting"):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "transition"):
                self.op.transition(self.unknown(), state, OBSERVED)

    def test_known_task_cannot_be_rebound_during_acceptance_or_terminal_transition(self):
        intent = self.submitting()
        accepted = self.op.transition(intent, "accepted", LOST, task=self.task(intent))
        terminal = self.task(intent, "terminal", "failed", ["logs/17"])
        terminal["task_id"] = "task-18"
        with self.assertRaisesRegex(ValueError, "task|binding"):
            self.op.transition(accepted, "terminal", OBSERVED, task=terminal)

    def test_terminal_is_irreversible_and_repeated_acceptance_is_idempotent(self):
        intent = self.submitting()
        task = self.task(intent)
        accepted = self.op.transition(intent, "accepted", LOST, task=task)
        self.assertEqual(accepted, self.op.transition(accepted, "accepted", OBSERVED, task=task))
        terminal = self.op.transition(accepted, "terminal", OBSERVED, task=self.task(intent, "terminal", "cancelled", ["logs/17"]))
        with self.assertRaisesRegex(ValueError, "transition"):
            self.op.transition(terminal, "accepted", OBSERVED, task=task)

    def test_invalid_schema_types_sha_and_timestamps_are_rejected(self):
        invalid = [("schema", "operation-intent/v0"), ("attempt_id", 17), ("state", "running"), ("created_at_utc", "yesterday"), ("updated_at_utc", "2026-09-21T10:00:00Z")]
        for field, value in invalid:
            with self.subTest(field=field):
                intent = self.prepared()
                intent[field] = value
                with self.assertRaisesRegex(ValueError, field + "|timestamp"):
                    self.op.validate_intent(intent)
        wrong = binding()
        wrong["candidate_sha"] = "abc123"
        with self.assertRaisesRegex(ValueError, "candidate_sha"):
            self.op.prepare(wrong, "attempt-1", "candidate", CREATED)
        with self.assertRaisesRegex(ValueError, "timestamp|earlier"):
            self.op.transition(self.unknown(), "accepted", CREATED, task=self.task(self.unknown()))

    def test_tampered_key_and_malformed_lookup_are_rejected(self):
        intent = self.prepared()
        intent["operation_key"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "operation_key"):
            self.op.validate_intent(intent)
        intent = self.unknown()
        observation = self.observation(intent, [], complete="false")
        with self.assertRaisesRegex(ValueError, "lookup_complete"):
            self.op.decide(intent, observation)

    def test_atomic_write_protects_other_intent_and_stale_expected_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intent.json"
            original = self.prepared()
            self.op.write_intent(path, original)
            stored = path.read_bytes()
            other = self.op.prepare(binding(), "attempt-2", "candidate", CREATED)
            with self.assertRaisesRegex(ValueError, "exists|overwrite|intent"):
                self.op.write_intent(path, other)
            self.assertEqual(stored, path.read_bytes())
            submitted = self.submitting()
            self.op.write_intent(path, submitted, expected=original)
            with self.assertRaisesRegex(ValueError, "changed|stale|match"):
                self.op.write_intent(path, self.unknown(), expected=original)
            self.assertEqual(json.loads(path.read_text()), submitted)

    def test_file_writer_cannot_roll_back_an_existing_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intent.json"
            submitted = self.submitting()
            self.op.write_intent(path, submitted)
            with self.assertRaisesRegex(ValueError, "transition"):
                self.op.write_intent(path, self.prepared(), expected=submitted)
            self.assertEqual(json.loads(path.read_text()), submitted)

    def test_known_terminal_task_cannot_become_active_on_recovery(self):
        intent = self.submitting()
        intent = self.op.transition(intent, "terminal", LOST, task=self.task(intent, "terminal", "failed", ["logs/17"]))
        decision = self.op.decide(intent, self.observation(intent, [self.task(intent)]))
        self.assertEqual(decision["action"], "blocked")
        self.assertTrue(decision["external_guard"])

    def test_cli_round_trip_records_lost_response_and_decides_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / "intent.json"
            readback = directory / "readback.json"
            receipt = directory / "receipt.json"
            observation = directory / "observation.json"
            original = self.prepared()
            path.write_text(json.dumps(original))
            readback.write_text(json.dumps(original))

            def run(*args):
                result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            receipt.write_text(run("readback", "--intent", str(path), "--readback", str(readback), "--reference", "coordination/1", "--at", READ_BACK))
            run("transition", "--intent", str(path), "--state", "submitting", "--at", SUBMITTING, "--receipt", str(receipt))
            run("transition", "--intent", str(path), "--state", "unknown", "--at", LOST)
            intent = json.loads(path.read_text())
            observation.write_text(json.dumps(self.observation(intent, [self.task(intent)])))
            before = path.read_bytes()
            result = json.loads(run("decide", "--intent", str(path), "--observation", str(observation)))
            self.assertEqual(result["action"], "observe")
            self.assertFalse(result["allow_submission"])
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(json.loads(run("validate", "--intent", str(path)))["valid"])

    def test_prepare_cli_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "binding.json"
            target = Path(directory) / "intent.json"
            source.write_text(json.dumps(binding()))
            command = [sys.executable, "-B", str(SCRIPT), "prepare", "--binding", str(source), "--attempt-id", "attempt-1", "--source-ref", "candidate", "--at", CREATED, "--output", str(target)]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(target.read_text())["state"], "prepared")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exists", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_ambiguous_duplicate_json_binding_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "binding.json"
            target = Path(directory) / "intent.json"
            source.write_text(json.dumps(binding())[:-1] + ', "mode": "EDIT"}')
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), "prepare", "--binding", str(source),
                 "--attempt-id", "attempt-1", "--source-ref", "candidate", "--at", CREATED, "--output", str(target)],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate", result.stderr)
            self.assertFalse(target.exists())
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
