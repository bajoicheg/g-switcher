#!/usr/bin/env python3
"""Behavioral integration tests; commands run in disposable real Git worktrees."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_checks.py"
VALIDATOR = ROOT / "scripts/validate_evidence.py"
CONFIG_SHA = "a" * 64
GOOD_XML = '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase name="a"/><testcase name="b"/></testsuite></testsuites>'
BAD_XML = '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase name="a"><failure>expected assertion</failure></testcase></testsuite>'


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Evidence Tests")
        self.git("config", "user.email", "evidence@example.invalid")
        (self.repo / "source.txt").write_text("candidate\n")
        self.git("add", "source.txt")
        self.git("commit", "-qm", "candidate")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.plan_path = self.base / "plan.json"
        self.out = self.base / "evidence"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def check(self, check_id="build", code="print('ok')", kind="build", **kw):
        return dict(id=check_id, kind=kind, required=True,
                    argv=[sys.executable, "-c", code], timeout_seconds=5, **kw)

    def junit_check(self, xml=GOOD_XML, exit_code=0, **kw):
        code = ("import os,pathlib,sys; "
                f"pathlib.Path(os.environ['EVIDENCE_JUNIT_XML']).write_text({xml!r}); "
                f"print('expected assertion'); sys.exit({exit_code})")
        return self.check("tests", code, "test", **kw)

    def run_plan(self, checks, sha=None, output=None, cwd=None):
        self.plan_path.write_text(json.dumps({"schema": "command-check-plan/v1", "checks": checks}))
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--worktree", str(self.repo),
             "--candidate-sha", sha or self.sha, "--plan", str(self.plan_path),
             "--output-dir", str(output or self.out), "--environment-id", "test-environment",
             "--environment-config-sha256", CONFIG_SHA],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, cwd=cwd)
        return result

    def evidence(self):
        self.assertTrue((self.out / "evidence.json").is_file(), "runner must persist evidence.json")
        return json.loads((self.out / "evidence.json").read_text())

    def validate(self, sha=None, config_sha=CONFIG_SHA):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--evidence", str(self.out / "evidence.json"),
             "--plan", str(self.plan_path), "--candidate-sha", sha or self.sha,
             "--environment-id", "test-environment", "--environment-config-sha256", config_sha],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)

    def rewrite(self, evidence):
        (self.out / "evidence.json").write_text(json.dumps(evidence))

    # Removing per-command exit capture would wrongly let the final command decide.
    def test_failed_build_cannot_be_erased_by_later_success(self):
        result = self.run_plan([self.check(code="raise SystemExit(7)"), self.check("lint")])
        self.assertEqual(result.returncode, 1, result.stderr)
        evidence = self.evidence()
        self.assertEqual([c["status"] for c in evidence["checks"]], ["FAIL", "PASS"])
        self.assertEqual([c["exit_code"] for c in evidence["checks"]], [7, 0])
        self.assertEqual(evidence["runner_status"], "COMPLETE")
        self.assertEqual(evidence["gate_status"], "FAIL")
        self.assertFalse(evidence["final_green"])
        self.assertEqual(self.validate().returncode, 1)

    def test_passing_commands_and_real_test_counts_validate(self):
        result = self.run_plan([self.check(), self.junit_check()])
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.evidence()
        self.assertEqual(evidence["gate_status"], "GREEN")
        self.assertTrue(evidence["final_green"])
        self.assertEqual(evidence["checks"][1]["test_report"]["counts"],
                         {"tests": 2, "failures": 0, "errors": 0, "skipped": 0})
        self.assertEqual(evidence["environment"]["id"], "test-environment")
        self.assertEqual(len(evidence["environment"]["fingerprint"]), 64)
        for check in evidence["checks"]:
            self.assertEqual(check["before"]["sha"], self.sha)
            self.assertEqual(check["after"]["sha"], self.sha)
            self.assertTrue(check["before"]["clean"])
            self.assertTrue(check["after"]["clean"])
            self.assertLessEqual(check["started_at_utc"], check["ended_at_utc"])
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.validate().returncode, 0)

    def test_environment_configuration_digest_must_match_independent_expectation(self):
        result = self.run_plan([self.check()])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.evidence()["environment"]["configuration_sha256"], CONFIG_SHA)
        self.assertEqual(self.validate().returncode, 0)
        mismatch = self.validate(config_sha="b" * 64)
        self.assertEqual(mismatch.returncode, 2)
        self.assertIn("configuration", mismatch.stderr)

    # Zero process exit must not fabricate passing tests from absent/empty reports.
    def test_test_report_required_with_nonzero_real_test_count(self):
        cases = [None, '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
                 '<testsuite tests="2" failures="0" errors="0" skipped="2"/>',
                 'not XML', '<testsuite tests="one" failures="0" errors="0"/>', BAD_XML,
                 '<testsuites tests="0"><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>',
                 '<testsuite tests="2" failures="0" errors="1"><testcase name="setup"><error>setup failed</error></testcase><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuite>']
        for i, xml in enumerate(cases):
            with self.subTest(xml=xml):
                self.out = self.base / f"evidence-{i}"
                check = self.check("tests", kind="test") if xml is None else self.junit_check(xml)
                result = self.run_plan([check])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.evidence()["checks"][0]["status"], "FAIL")
                self.assertNotEqual(self.validate().returncode, 0)

    def test_expected_red_is_predeclared_exact_exit_and_signature_not_green(self):
        expected = {"exit_code": 3, "signature": "expected assertion", "reason": "New regression must fail before implementation"}
        result = self.run_plan([self.junit_check(BAD_XML, 3, expected_red=expected)])
        self.assertEqual(result.returncode, 1, result.stderr)
        evidence = self.evidence()
        self.assertEqual(evidence["checks"][0]["status"], "EXPECTED_RED")
        self.assertEqual(evidence["gate_status"], "EXPECTED_RED")
        self.assertFalse(evidence["final_green"])
        self.assertEqual(self.validate().returncode, 1)
        for i, (exit_code, signature) in enumerate([(4, "expected assertion"), (3, "unrelated text")]):
            self.out = self.base / f"wrong-red-{i}"
            expected = dict(expected, exit_code=exit_code, signature=signature)
            self.assertEqual(self.run_plan([self.junit_check(BAD_XML, 3, expected_red=expected)]).returncode, 1)
            self.assertEqual(self.evidence()["checks"][0]["status"], "FAIL")

    def test_wrong_sha_does_not_run_command(self):
        sentinel = self.base / "must-not-run"
        result = self.run_plan([self.check(code=f"open({str(sentinel)!r}, 'w').write('bad')")], sha="f" * 40)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.evidence()["checks"][0]["status"], "NOT_RUN")
        self.assertFalse(sentinel.exists())

    def test_dirty_source_does_not_run_command(self):
        (self.repo / "source.txt").write_text("changed\n")
        result = self.run_plan([self.check()])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.evidence()["checks"][0]["status"], "NOT_RUN")

    def test_source_mutation_fails_check_and_blocks_remaining_commands(self):
        result = self.run_plan([self.check(code="open('source.txt', 'w').write('changed')"), self.check("next")])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual([c["status"] for c in self.evidence()["checks"]], ["FAIL", "NOT_RUN"])

    def test_missing_empty_and_unexecutable_commands_are_not_run(self):
        blocked = self.base / "not-executable"
        blocked.write_text("#!/bin/sh\nexit 0\n")
        checks = [dict(self.check("missing"), argv=["this-command-must-not-exist-2341234"]),
                  dict(self.check("empty"), argv=[]), dict(self.check("unexecutable"), argv=[str(blocked)])]
        result = self.run_plan(checks)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual([c["status"] for c in self.evidence()["checks"]], ["NOT_RUN"] * 3)
        self.assertTrue(all(c["exit_code"] is None for c in self.evidence()["checks"]))

    def test_timeout_is_failure_and_retains_termination_evidence(self):
        check = dict(self.check(code="import time; time.sleep(5)"), timeout_seconds=0.05)
        result = self.run_plan([check])
        self.assertEqual(result.returncode, 1, result.stderr)
        evidence = self.evidence()["checks"][0]
        self.assertEqual(evidence["status"], "FAIL")
        self.assertEqual(evidence["termination"], "timeout")
        self.assertIsInstance(evidence["exit_code"], int)

    def test_output_must_be_new_and_outside_entire_worktree(self):
        for output in [self.repo / "results", self.repo / "source-subdir" / "results"]:
            result = self.run_plan([self.check()], output=output)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(output.exists())
        self.out.mkdir()
        (self.out / "keep").write_text("old evidence")
        self.assertEqual(self.run_plan([self.check()]).returncode, 2)
        self.assertEqual((self.out / "keep").read_text(), "old evidence")

    def test_relative_output_can_resolve_outside_worktree(self):
        result = self.run_plan([self.check()], output=Path("..") / "evidence", cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.evidence()["gate_status"], "GREEN")

    def test_argv_is_not_interpreted_by_a_shell(self):
        literal = "literal ; $(touch must-not-exist) && false"
        check = dict(self.check(), argv=[sys.executable, "-c", "import sys; print(sys.argv[1])", literal])
        self.assertEqual(self.run_plan([check]).returncode, 0)
        evidence = self.evidence()["checks"][0]
        self.assertIn(literal, (self.out / evidence["log"]["path"]).read_text())
        self.assertFalse((self.repo / "must-not-exist").exists())

    # Trusting a self-asserted status/summary would let these modified files pass.
    def test_validator_rejects_tampering_missing_results_and_wrong_expected_inputs(self):
        self.assertEqual(self.run_plan([self.junit_check()]).returncode, 0)
        original = self.evidence()
        self.assertNotEqual(self.validate(sha="e" * 40).returncode, 0)
        for mutate in [lambda e: e.update(checks=[]),
                       lambda e: e["checks"][0].update(exit_code=8),
                       lambda e: e["checks"][0]["after"].update(sha="e" * 40),
                       lambda e: e.update(runner_status="RUNNING"),
                       lambda e: e["environment"].update(fingerprint="0" * 64)]:
            evidence = json.loads(json.dumps(original))
            mutate(evidence)
            self.rewrite(evidence)
            self.assertNotEqual(self.validate().returncode, 0)
        self.rewrite(original)
        report = self.out / original["checks"][0]["test_report"]["path"]
        report.write_text(BAD_XML)
        self.assertNotEqual(self.validate().returncode, 0)
        report.write_text(GOOD_XML)
        plan = json.loads(self.plan_path.read_text())
        plan["checks"][0]["argv"] = [sys.executable, "-c", "print('different')"]
        self.plan_path.write_text(json.dumps(plan))
        self.assertNotEqual(self.validate().returncode, 0)

    def test_invalid_plan_cannot_make_a_vacuous_green(self):
        for checks in [[], [dict(self.check(), required=False)],
                       [dict(self.check(), expected_red={"exit_code": 0, "signature": "x", "reason": "bad"})],
                       [self.check(), self.check()], [dict(self.check(), kind=[])],
                       [dict(self.check(), timeout_seconds=True)], [dict(self.check(), argv="echo ok")]]:
            self.assertEqual(self.run_plan(checks).returncode, 2)
            self.assertFalse(self.out.exists())

    def test_changed_head_is_rejected_even_when_worktree_remains_clean(self):
        code = ("import subprocess; "
                "subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'unexpected HEAD'], check=True)")
        self.assertEqual(self.run_plan([self.check(code=code)]).returncode, 1)
        result = self.evidence()["checks"][0]
        self.assertEqual(result["before"]["sha"], self.sha)
        self.assertNotEqual(result["after"]["sha"], self.sha)
        self.assertTrue(result["after"]["clean"])
        self.assertEqual(result["status"], "FAIL")

    def test_validator_recomputes_status_even_if_both_json_copies_claim_pass(self):
        self.assertEqual(self.run_plan([self.check(code="raise SystemExit(9)")]).returncode, 1)
        evidence = self.evidence()
        evidence.update(gate_status="GREEN", final_green=True)
        result = evidence["checks"][0]
        result.update(status="PASS", reason="command and required evidence passed")
        (self.out / result["result_path"]).write_text(json.dumps(result))
        self.rewrite(evidence)
        self.assertEqual(self.validate().returncode, 2)

    def test_junit_nested_suites_are_counted_once_and_inconsistent_cases_rejected(self):
        nested = ('<testsuites tests="3"><testsuite name="parent" tests="3" failures="0" errors="0" skipped="0">'
                  '<testsuite name="one" tests="1" failures="0" errors="0" skipped="0"><testcase name="a"/></testsuite>'
                  '<testsuite name="two" tests="2" failures="0" errors="0" skipped="0"><testcase name="b"/><testcase name="c"/></testsuite>'
                  '</testsuite></testsuites>')
        self.assertEqual(self.run_plan([self.junit_check(nested)]).returncode, 0)
        self.assertEqual(self.evidence()["checks"][0]["test_report"]["counts"]["tests"], 3)
        self.out = self.base / "inconsistent"
        misleading = '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="a"><failure>failed</failure></testcase></testsuite>'
        self.assertEqual(self.run_plan([self.junit_check(misleading)]).returncode, 1)

    def test_junit_namespace_qualified_outcomes_cannot_hide_failures(self):
        xml = '<testsuite tests="1" failures="0" errors="0"><testcase name="a"><failure xmlns="urn:junit">failed</failure></testcase></testsuite>'
        result = self.run_plan([self.junit_check(xml)])
        self.assertEqual(result.returncode, 1, result.stderr)
        check = self.evidence()["checks"][0]
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("namespaces", check["test_report"]["error"])
        self.assertEqual(self.validate().returncode, 1)

    def test_symlinked_external_output_cannot_write_inside_source(self):
        link = self.base / "source-link"
        link.symlink_to(self.repo, target_is_directory=True)
        output = link / "evidence"
        self.assertEqual(self.run_plan([self.check()], output=output).returncode, 2)
        self.assertFalse(output.exists())

    def test_report_symlink_is_not_accepted_as_fresh_test_evidence(self):
        existing = self.base / "old-junit.xml"
        existing.write_text(GOOD_XML)
        code = ("import pathlib,os; "
                f"pathlib.Path(os.environ['EVIDENCE_JUNIT_XML']).symlink_to({str(existing)!r})")
        self.assertEqual(self.run_plan([self.check("tests", code, "test")]).returncode, 1)
        self.assertEqual(self.evidence()["checks"][0]["status"], "FAIL")

    def test_report_placeholder_is_rendered_as_one_argv_item(self):
        code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])"
        check = dict(self.check("tests", kind="test"), argv=[sys.executable, "-c", code, "{junit_xml}", GOOD_XML])
        self.assertEqual(self.run_plan([check]).returncode, 0)
        self.assertEqual(self.validate().returncode, 0)


if __name__ == "__main__":
    unittest.main()
