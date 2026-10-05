import importlib.util
import concurrent.futures
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from git_document_store import GitDocumentStore
from project_lanes import LaneClaim, LaneKind

if importlib.util.find_spec("project_lane_git"):
    import project_lane_git
else:
    project_lane_git = None


def git(repo, *args, input_text=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


class GitLaneResultVerifierTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(project_lane_git, "Git lane result verifier is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "src/a").mkdir(parents=True)
        (self.repo / "src/b").mkdir(parents=True)
        (self.repo / "src/a/base.txt").write_text("a\n")
        (self.repo / "src/b/outside.txt").write_text("original\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.primary = git(self.repo, "branch", "--show-current")
        self.claim = LaneClaim(
            "lane", "inv", LaneKind.WORKER, self.base, str(self.repo), "worker",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        self.verifier = project_lane_git.GitLaneResultVerifier(self.repo)

    def commit(self, path, text, message):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(self.repo, "add", str(path))
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def test_descendant_result_reports_all_touched_paths(self):
        head = self.commit(Path("src/a/new.py"), "print(1)\n", "inside")
        result = self.verifier(self.claim, head)
        self.assertTrue(result["base_ancestor"])
        self.assertEqual(result["observed_base"], self.base)
        self.assertEqual(result["touched_paths"], {"src/a/new.py"})

    def test_non_descendant_result_is_not_accepted_as_ancestry(self):
        git(self.repo, "checkout", "-qb", "other", self.base)
        other = self.commit(Path("src/a/other.py"), "x\n", "other")
        git(self.repo, "checkout", "-q", self.primary)
        master = self.commit(Path("src/a/master.py"), "m\n", "master")
        self.assertTrue(self.verifier(self.claim, master)["base_ancestor"])
        unrelated = LaneClaim(
            "lane2", "inv2", LaneKind.WORKER, other, str(self.repo), "worker2",
            write_paths=frozenset({"src/a"}), executor_id="e", role="writer")
        self.assertFalse(self.verifier(unrelated, master)["base_ancestor"])

    def test_touched_and_restored_escape_is_still_reported(self):
        original = (self.repo / "src/b/outside.txt").read_text()
        self.commit(Path("src/b/outside.txt"), "changed\n", "outside")
        head = self.commit(Path("src/b/outside.txt"), original, "restore")
        self.assertEqual(git(self.repo, "diff", "--name-only", self.base + ".." + head), "")
        result = self.verifier(self.claim, head)
        self.assertIn("src/b/outside.txt", result["touched_paths"])

    def test_integration_verifier_proves_result_and_observed_head_ancestry(self):
        git(self.repo, "checkout", "-qb", "worker-result", self.base)
        result_commit = self.commit(Path("src/a/integrated.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        git(self.repo, "merge", "--ff-only", "worker-result")
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        verifier = project_lane_git.GitLaneIntegrationVerifier(
            self.repo, "refs/heads/" + self.primary)
        evidence = verifier(
            {"lane_id": "lane", "result_commit": result_commit},
            integrator,
            {"lane_id": "lane", "result_commit": result_commit,
             "observed_shared_head": self.base,
             "intended_integrated_head": result_commit,
             "operation_id": "op-1"})
        self.assertTrue(evidence["integrated"])
        self.assertEqual(evidence["integrated_head"], result_commit)
        self.assertFalse(evidence["conditional_update"])
        self.assertFalse(evidence["force_push"])

    def test_integration_verifier_rejects_result_not_present_on_shared_head(self):
        git(self.repo, "checkout", "-qb", "worker-result", self.base)
        result_commit = self.commit(Path("src/a/not-integrated.py"), "no\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        verifier = project_lane_git.GitLaneIntegrationVerifier(
            self.repo, "refs/heads/" + self.primary)
        with self.assertRaisesRegex(ValueError, "ancestry"):
            verifier(
                {"lane_id": "lane", "result_commit": result_commit},
                integrator,
                {"lane_id": "lane", "result_commit": result_commit,
                 "observed_shared_head": self.base,
                 "intended_integrated_head": result_commit,
                 "operation_id": "op-1"})

    def test_integration_publisher_performs_exact_head_conditional_fast_forward(self):
        remote = self.repo / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "origin", str(remote))
        git(self.repo, "push", "-q", "origin", self.base + ":refs/heads/integration")

        git(self.repo, "checkout", "-qb", "worker-publish", self.base)
        result_commit = self.commit(Path("src/a/published.py"), "ok\n", "published result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "origin")
        attempt_store = GitDocumentStore(
            self.repo, "origin", "refs/heads/cdc/publication-attempts",
            remote_id, protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "origin", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        item = {"lane_id": "lane", "result_commit": result_commit}
        intent = {
            "lane_id": "lane", "result_commit": result_commit,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-cas",
        }
        evidence = publisher(item, integrator, intent)
        self.assertTrue(evidence["conditional_update"])
        self.assertFalse(evidence["force_push"])
        self.assertEqual(evidence["integrated_head"], result_commit)
        remote_head = subprocess.check_output(
            ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/integration"],
            text=True).strip()
        self.assertEqual(remote_head, result_commit)
        # Lost-reply/retry reconciliation is idempotent once exact readback matches.
        self.assertEqual(publisher(item, integrator, intent), evidence)

    def test_racing_publishers_submit_one_transport_for_the_same_attempt(self):
        remote = self.repo / "remote-race.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "origin", str(remote))
        git(self.repo, "push", "-q", "origin", self.base + ":refs/heads/integration")
        result = self.commit(Path("src/a/race.py"), "ok\n", "race result")
        other = self.repo / "other"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(other)], check=True)
        git(other, "remote", "set-url", "origin", str(remote))
        remote_id = project_lane_git.remote_identity(self.repo, "origin")
        publishers = []
        for checkout in (self.repo, other):
            store = GitDocumentStore(checkout, "origin", "refs/heads/cdc/race-attempts",
                                     remote_id, protected_refs=("refs/heads/integration",))
            publishers.append(project_lane_git.GitLaneIntegrationPublisher(
                checkout, "origin", "refs/heads/integration", remote_id, attempt_store=store))
        integrator = LaneClaim("integrator", "inv", LaneKind.INTEGRATOR, self.base,
                               str(self.repo), self.primary, executor_id="e", role="integrator")
        item = {"lane_id": "lane", "result_commit": result}
        intent = dict(item, observed_shared_head=self.base, intended_integrated_head=result,
                      operation_id="race-operation")
        ready = threading.Barrier(2)
        calls = []
        transition = project_lane_git.GitLaneIntegrationPublisher._transition_attempt
        push = project_lane_git.GitLaneIntegrationPublisher._push_cas

        def synchronized_transition(publisher, item, intent, target, allowed):
            if target == "submitted":
                ready.wait(timeout=20)
            return transition(publisher, item, intent, target, allowed)

        def observed_push(publisher, observed, intended):
            calls.append((observed, intended))
            return push(publisher, observed, intended)

        def publish(publisher):
            try:
                return publisher(item, integrator, intent)
            except ValueError as exc:
                return str(exc)

        with mock.patch.object(project_lane_git.GitLaneIntegrationPublisher,
                               "_transition_attempt", synchronized_transition), \
             mock.patch.object(project_lane_git.GitLaneIntegrationPublisher,
                               "_push_cas", observed_push):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(publish, publishers))
        self.assertEqual(calls, [(self.base, result)],
                         "one durable attempt must authorize one provider transport")
        successes = [value for value in results if isinstance(value, dict)]
        self.assertEqual(len(successes), 1, results)
        self.assertTrue(successes[0]["conditional_update"])
        self.assertEqual(git(remote, "rev-parse", "refs/heads/integration"), result)
        self.assertEqual(publishers[1](item, integrator, intent), successes[0])
        self.assertEqual(publishers[0].publication_attempt("race-operation")["status"], "confirmed")

    def test_preexisting_intended_remote_head_is_readback_only_without_this_intents_cas(self):
        remote = self.repo / "remote-preexisting.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "preexisting", str(remote))
        git(self.repo, "push", "-q", "preexisting", self.base + ":refs/heads/integration")

        git(self.repo, "checkout", "-qb", "worker-preexisting", self.base)
        result_commit = self.commit(Path("src/a/preexisting.py"), "ok\n", "worker result")
        git(self.repo, "push", "-q", "preexisting", result_commit + ":refs/heads/integration")
        git(self.repo, "checkout", "-q", self.primary)

        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "preexisting")
        attempt_store = GitDocumentStore(
            self.repo, "preexisting", "refs/heads/cdc/preexisting-attempts",
            remote_id, protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "preexisting", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        evidence = publisher(
            {"lane_id": "lane", "result_commit": result_commit},
            integrator,
            {"lane_id": "lane", "result_commit": result_commit,
             "observed_shared_head": self.base,
             "intended_integrated_head": result_commit,
             "operation_id": "op-preexisting"})
        self.assertFalse(evidence["conditional_update"])

    def test_integration_publisher_requires_durable_attempt_state_before_push(self):
        remote = self.repo / "remote-no-attempt.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "noattempt", str(remote))
        git(self.repo, "push", "-q", "noattempt", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-no-attempt", self.base)
        result_commit = self.commit(Path("src/a/noattempt.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "noattempt", "refs/heads/integration",
            project_lane_git.remote_identity(self.repo, "noattempt"))
        with self.assertRaisesRegex(ValueError, "attempt|durable"):
            publisher(
                {"lane_id": "lane", "result_commit": result_commit},
                integrator,
                {"lane_id": "lane", "result_commit": result_commit,
                 "observed_shared_head": self.base,
                 "intended_integrated_head": result_commit,
                 "operation_id": "op-no-attempt"})

    def test_lost_push_reply_reconciles_from_durable_attempt_after_restart_without_replay(self):
        remote = self.repo / "remote-lost.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "lost", str(remote))
        git(self.repo, "push", "-q", "lost", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-lost", self.base)
        result_commit = self.commit(Path("src/a/lost.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "lost")
        attempt_store = GitDocumentStore(
            self.repo, "lost", "refs/heads/cdc/lost-attempts", remote_id,
            protected_refs=("refs/heads/integration",))
        item = {"lane_id": "lane", "result_commit": result_commit}
        intent = {
            "lane_id": "lane", "result_commit": result_commit,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-lost",
        }

        class LostReply(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(self, observed, intended):
                super()._push_cas(observed, intended)
                raise project_lane_git._PublicationUnknown("lost reply")

        first = LostReply(
            self.repo, "lost", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        with self.assertRaisesRegex(ValueError, "unknown"):
            first(item, integrator, intent)
        self.assertEqual(
            subprocess.check_output(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/integration"],
                text=True).strip(),
            result_commit)

        class NoReplay(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(self, observed, intended):
                raise AssertionError("publication push replayed")

        restarted = NoReplay(
            self.repo, "lost", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        evidence = restarted(item, integrator, intent)
        self.assertTrue(evidence["conditional_update"])
        self.assertEqual(evidence["publication_attempt_state"], "confirmed")

    def test_remote_failure_porcelain_is_unknown_and_reconciles_without_replay(self):
        remote = self.repo / "remote-failure.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "remotefailure", str(remote))
        git(self.repo, "push", "-q", "remotefailure", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-remote-failure", self.base)
        result_commit = self.commit(Path("src/a/remote_failure.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "remotefailure")
        attempt_store = GitDocumentStore(
            self.repo, "remotefailure", "refs/heads/cdc/remote-failure-attempts",
            remote_id, protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "remotefailure", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        item = {"lane_id": "lane", "result_commit": result_commit}
        intent = {
            "lane_id": "lane", "result_commit": result_commit,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-remote-failure",
        }

        real_run = subprocess.run
        def remote_failure(args, *positional, **kwargs):
            is_publication_push = (
                isinstance(args, list)
                and "push" in args
                and "--porcelain" in args
                and any(
                    isinstance(arg, str)
                    and arg.startswith("--force-with-lease=refs/heads/integration:")
                    for arg in args
                )
            )
            if is_publication_push:
                return subprocess.CompletedProcess(
                    args, 1,
                    stdout=(
                        "!\t" + result_commit + ":refs/heads/integration"
                        + "\t[remote failure] (remote failed to report status)\n"
                    ),
                    stderr="error: failed to push some refs to 'remotefailure'\n",
                )
            return real_run(args, *positional, **kwargs)

        with mock.patch.object(project_lane_git.subprocess, "run", side_effect=remote_failure):
            with self.assertRaisesRegex(ValueError, "unknown"):
                publisher(item, integrator, intent)

        _, state = attempt_store.read()
        attempt = state["attempts"]["op-remote-failure"]
        self.assertEqual(attempt["status"], "unknown")

        # Simulate the ambiguous transport having actually made B authoritative.
        git(self.repo, "push", "-q", "remotefailure",
            result_commit + ":refs/heads/test-only-object-seed")
        subprocess.run(
            ["git", "--git-dir", str(remote), "update-ref",
             "refs/heads/integration", result_commit], check=True)

        class NoReplay(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(self, observed, intended):
                raise AssertionError("unknown publication must reconcile without replay")

        restarted = NoReplay(
            self.repo, "remotefailure", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        evidence = restarted(item, integrator, intent)
        self.assertTrue(evidence["conditional_update"])
        self.assertEqual(evidence["publication_attempt_state"], "confirmed")
        self.assertEqual(evidence["publication_attempt_id"], attempt["attempt_id"])

    def test_prepared_but_unsent_attempt_does_not_become_proof_from_matching_head(self):
        remote = self.repo / "remote-unsent.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "unsent", str(remote))
        git(self.repo, "push", "-q", "unsent", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-unsent", self.base)
        result_commit = self.commit(Path("src/a/unsent.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "unsent")
        attempt_store = GitDocumentStore(
            self.repo, "unsent", "refs/heads/cdc/unsent-attempts", remote_id,
            protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "unsent", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        item = {"lane_id": "lane", "result_commit": result_commit}
        intent = {
            "lane_id": "lane", "result_commit": result_commit,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-unsent",
        }
        attempt = publisher._prepare_attempt(item, intent)
        self.assertEqual(attempt["status"], "prepared")
        git(self.repo, "push", "-q", "unsent", result_commit + ":refs/heads/integration")
        evidence = publisher(item, integrator, intent)
        self.assertFalse(evidence["conditional_update"])
        self.assertEqual(evidence["publication_attempt_state"], "prepared")

    def test_submitted_marker_without_push_outcome_does_not_become_conditional_proof(self):
        remote = self.repo / "remote-submitted-unsent.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "submittedunsent", str(remote))
        git(self.repo, "push", "-q", "submittedunsent", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-submitted-unsent", self.base)
        result_commit = self.commit(
            Path("src/a/submitted_unsent.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "submittedunsent")
        attempt_store = GitDocumentStore(
            self.repo, "submittedunsent",
            "refs/heads/cdc/submitted-unsent-attempts", remote_id,
            protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "submittedunsent", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        item = {"lane_id": "lane", "result_commit": result_commit}
        intent = {
            "lane_id": "lane", "result_commit": result_commit,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-submitted-unsent",
        }

        attempt = publisher._prepare_attempt(item, intent)
        attempt = publisher._transition_attempt(
            item, intent, "submitted", {"prepared"})
        self.assertEqual(attempt["status"], "submitted")

        # Model a controller crash after the durable submitted marker but before
        # _push_cas() is invoked. Another actor then moves the authoritative ref
        # to the same intended bytes. The marker alone is not transport proof.
        git(self.repo, "push", "-q", "submittedunsent",
            result_commit + ":refs/heads/integration")

        evidence = publisher(item, integrator, intent)
        self.assertFalse(evidence["conditional_update"])
        self.assertEqual(evidence["publication_attempt_state"], "submitted")
        self.assertEqual(
            attempt_store.read()[1]["attempts"]["op-submitted-unsent"]["status"],
            "submitted")

    def test_attempt_from_other_operation_or_result_is_not_reused(self):
        remote = self.repo / "remote-mismatch.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "mismatch", str(remote))
        git(self.repo, "push", "-q", "mismatch", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-mismatch", self.base)
        result_commit = self.commit(Path("src/a/mismatch.py"), "ok\n", "worker result")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "mismatch")
        attempt_store = GitDocumentStore(
            self.repo, "mismatch", "refs/heads/cdc/mismatch-attempts", remote_id,
            protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "mismatch", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        item = {"lane_id": "lane", "result_commit": result_commit}
        other_intent = {
            "lane_id": "lane", "result_commit": result_commit,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-other",
        }
        publisher._prepare_attempt(item, other_intent)
        git(self.repo, "push", "-q", "mismatch", result_commit + ":refs/heads/integration")
        current_intent = dict(other_intent, operation_id="op-current")
        self.assertFalse(publisher(item, integrator, current_intent)["conditional_update"])

        mismatched_item = {"lane_id": "lane", "result_commit": self.base}
        mismatched_intent = {
            "lane_id": "lane", "result_commit": self.base,
            "observed_shared_head": self.base,
            "intended_integrated_head": result_commit,
            "operation_id": "op-other",
        }
        with self.assertRaisesRegex(ValueError, "does not match"):
            publisher(mismatched_item, integrator, mismatched_intent)

    def test_concurrent_remote_move_during_cas_is_rejected_without_overwrite(self):
        remote = self.repo / "remote-cas-race.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "casrace", str(remote))
        git(self.repo, "push", "-q", "casrace", self.base + ":refs/heads/integration")
        git(self.repo, "checkout", "-qb", "worker-casrace", self.base)
        result_commit = self.commit(Path("src/a/casrace.py"), "worker\n", "worker result")
        git(self.repo, "checkout", "-qb", "concurrent-casrace", self.base)
        concurrent = self.commit(Path("src/b/casrace.py"), "other\n", "concurrent")
        git(self.repo, "checkout", "-q", self.primary)
        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "casrace")
        attempt_store = GitDocumentStore(
            self.repo, "casrace", "refs/heads/cdc/casrace-attempts", remote_id,
            protected_refs=("refs/heads/integration",))

        class RacingPublisher(project_lane_git.GitLaneIntegrationPublisher):
            def _push_cas(inner_self, observed, intended):
                git(self.repo, "push", "-q", "casrace", concurrent + ":refs/heads/integration")
                return super(RacingPublisher, inner_self)._push_cas(observed, intended)

        publisher = RacingPublisher(
            self.repo, "casrace", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        with self.assertRaisesRegex(ValueError, "rejected"):
            publisher(
                {"lane_id": "lane", "result_commit": result_commit},
                integrator,
                {"lane_id": "lane", "result_commit": result_commit,
                 "observed_shared_head": self.base,
                 "intended_integrated_head": result_commit,
                 "operation_id": "op-casrace"})
        self.assertEqual(
            subprocess.check_output(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/integration"],
                text=True).strip(),
            concurrent)
        _, attempt_state = attempt_store.read()
        self.assertEqual(attempt_state["attempts"]["op-casrace"]["status"], "rejected")
        git(self.repo, "push", "-q", "casrace",
            result_commit + ":refs/heads/test-only-object-seed")
        subprocess.run(
            ["git", "--git-dir", str(remote), "update-ref",
             "refs/heads/integration", result_commit], check=True)
        retry = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "casrace", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        evidence = retry(
            {"lane_id": "lane", "result_commit": result_commit},
            integrator,
            {"lane_id": "lane", "result_commit": result_commit,
             "observed_shared_head": self.base,
             "intended_integrated_head": result_commit,
             "operation_id": "op-casrace"})
        self.assertFalse(evidence["conditional_update"])
        self.assertEqual(evidence["publication_attempt_state"], "rejected")

    def test_integration_publisher_rejects_remote_head_movement_without_overwrite(self):
        remote = self.repo / "remote-race.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.repo, "remote", "add", "race", str(remote))
        git(self.repo, "push", "-q", "race", self.base + ":refs/heads/integration")

        git(self.repo, "checkout", "-qb", "worker-race", self.base)
        result_commit = self.commit(Path("src/a/race.py"), "worker\n", "worker result")
        git(self.repo, "checkout", "-qb", "concurrent", self.base)
        concurrent = self.commit(Path("src/b/concurrent.py"), "other\n", "concurrent")
        git(self.repo, "push", "-q", "race", concurrent + ":refs/heads/integration")
        git(self.repo, "checkout", "-q", self.primary)

        integrator = LaneClaim(
            "integrator", "integrator-inv", LaneKind.INTEGRATOR, self.base,
            str(self.repo), self.primary, executor_id="integrator", role="integrator")
        remote_id = project_lane_git.remote_identity(self.repo, "race")
        attempt_store = GitDocumentStore(
            self.repo, "race", "refs/heads/cdc/race-attempts", remote_id,
            protected_refs=("refs/heads/integration",))
        publisher = project_lane_git.GitLaneIntegrationPublisher(
            self.repo, "race", "refs/heads/integration", remote_id,
            attempt_store=attempt_store)
        with self.assertRaisesRegex(ValueError, "moved"):
            publisher(
                {"lane_id": "lane", "result_commit": result_commit},
                integrator,
                {"lane_id": "lane", "result_commit": result_commit,
                 "observed_shared_head": self.base,
                 "intended_integrated_head": result_commit,
                 "operation_id": "op-race"})
        remote_head = subprocess.check_output(
            ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/integration"],
            text=True).strip()
        self.assertEqual(remote_head, concurrent)

    def test_invalid_or_missing_commit_fails_closed(self):
        for value in ("main", "f" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verifier(self.claim, value)


if __name__ == "__main__":
    unittest.main()
