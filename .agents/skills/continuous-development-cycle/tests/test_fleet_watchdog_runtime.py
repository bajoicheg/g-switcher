import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from test_watchdog_liveness import NOW, PROJECT, probe
from git_remote_identity import endpoint_identity

if importlib.util.find_spec("fleet_watchdog_runtime"):
    import fleet_watchdog_runtime as fleet
    from git_document_store import GitDocumentStore
else:
    fleet = None
    GitDocumentStore = None


class RecordingSurvivability:
    def __init__(self, effects_attempted=1, continuation_required=False):
        self.effects_attempted = effects_attempted
        self.continuation_required = continuation_required
        self.calls = []

    def reconcile_registered(self, *, max_effects):
        self.calls.append(max_effects)
        return {
            "schema": "watchdog-survivability-batch/v1",
            "registered_count": 1,
            "results": [],
            "effects_attempted": min(self.effects_attempted, max_effects),
            "max_effects": max_effects,
            "continuation_required": self.continuation_required,
            "authorizes_scheduler_mutation": False,
        }


class RecordingScheduler:
    """Instrumented local scheduler: mutation changes live state and writes a receipt."""
    def __init__(self, root, projects):
        self.root = root
        self.live = {p["project_id"]: probe(p) for p in projects}
        self.effects = []
        self.before_observe = None
        self.after_enable = None
        self.lost_response = False
        self.bad_readback = False
        self.reads = 0
        self.lock = threading.Lock()

    def observe(self, project):
        with self.lock:
            self.reads += 1
            if self.before_observe:
                self.before_observe(self, project)
            return copy.deepcopy(self.live[project["project_id"]])

    def enable(self, project, *, binding, operation_id, expected_schedule, expected_prompt):
        with self.lock:
            live = self.live[project["project_id"]]
            assert binding == live["binding"]
            assert expected_schedule == live["signals"]["scheduler"]["schedule"]
            assert expected_prompt == live["signals"]["scheduler"]["prompt"]
            live["signals"]["scheduler"]["state"] = "enabled"
            self._receipt(project, "enable", operation_id)
            if self.bad_readback:
                live["signals"]["scheduler"]["schedule"] = "RRULE:FREQ=DAILY"
            if self.after_enable:
                self.after_enable(self, project)
            return {"binding": copy.deepcopy(binding), "status": "accepted"}

    def run(self, project, *, binding, operation_id):
        with self.lock:
            live = self.live[project["project_id"]]
            assert binding == live["binding"]
            invocation_id = "started:" + operation_id
            live["signals"]["invocation"].update(state="running", invocation_id=invocation_id)
            self._receipt(project, "run", operation_id)
            if self.lost_response:
                raise TimeoutError("the scheduler accepted the request but the reply was lost")
            return {"binding": copy.deepcopy(binding), "status": "accepted", "invocation_id": invocation_id}

    def _receipt(self, project, effect, operation_id):
        self.effects.append((project["project_id"], effect))
        (self.root / operation_id).write_text(json.dumps({"project": project, "effect": effect}))


class FleetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(fleet, "executable Fleet recovery is not implemented")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        self.git("init", "--bare", "-q", str(self.remote))
        self.ref = "refs/heads/cdc/fleet-state"
        self.store_id = endpoint_identity(str(self.remote))
        self.projects = [copy.deepcopy(PROJECT)]
        self.store = self.make_store("controller-a")
        self.backend = RecordingScheduler(self.root, self.projects)

    def git(self, *args, cwd=None, input=None):
        r = subprocess.run(["git", *args], cwd=cwd, input=input, text=True, capture_output=True, check=True)
        return r.stdout.strip()

    def make_store(self, name, cls=None):
        repo = self.root / name
        repo.mkdir()
        self.git("init", "-q", str(repo))
        self.git("remote", "add", "origin", str(self.remote), cwd=repo)
        return (cls or GitDocumentStore)(repo, "origin", self.ref, self.store_id, protected_refs=["refs/heads/main"])

    def runtime(self, store=None, survivability=None):
        return fleet.FleetRuntime(store or self.store, self.backend, clock=lambda: NOW,
                                  survivability_runtime=survivability)

    def batch(self, runtime=None, budget=20, invocation="controller-invocation-1"):
        return (runtime or self.runtime()).run_batch(self.projects, max_effects=budget, invocation_id=invocation)

    def test_survivability_repairs_share_the_same_bounded_fleet_effect_budget(self):
        survivability = RecordingSurvivability(effects_attempted=1)
        result = self.batch(runtime=self.runtime(survivability=survivability), budget=1)
        self.assertEqual(survivability.calls, [1])
        self.assertEqual(result["effects_attempted"], 1)
        self.assertEqual(self.backend.effects, [])
        self.assertEqual(len(result["assessments"]), 1)
        self.assertTrue(result["continuation_required"])
        self.assertEqual(result["survivability"]["effects_attempted"], 1)

    def test_survivability_continuation_is_preserved_even_when_liveness_is_settled(self):
        self.backend.live["alpha"]["signals"]["work"].update(state="terminal", terminal_proof={
            "project_id": "alpha", "source_ref": "refs/heads/main",
            "source_revision": "a" * 40, "evidence_ref": "git:complete"})
        survivability = RecordingSurvivability(effects_attempted=0, continuation_required=True)
        result = self.batch(runtime=self.runtime(survivability=survivability), budget=0)
        self.assertTrue(result["continuation_required"])

    def test_runtime_executes_enable_and_run_with_exact_readback_and_preserves_configuration(self):
        result = self.batch()
        self.assertEqual(self.backend.effects, [("alpha", "enable"), ("alpha", "run")])
        self.assertEqual(result["effects_attempted"], 2)
        self.assertEqual(self.backend.live["alpha"]["signals"]["scheduler"]["schedule"], "RRULE:FREQ=HOURLY")
        _, state = self.store.read()
        self.assertEqual({entry["status"] for entry in state["operations"].values()}, {"succeeded"})
        self.assertTrue(all(entry["binding"] == probe()["binding"] for entry in state["operations"].values()))
        self.assertEqual(len(list(self.root.glob("operation-*"))), 2)

    def test_every_registered_project_is_assessed_and_budget_remainder_survives_restart(self):
        self.projects = [{**PROJECT, "project_id": x, "watchdog_id": "watchdog-" + x} for x in ["alpha", "beta", "gamma"]]
        self.backend = RecordingScheduler(self.root, self.projects)
        first = self.batch(budget=1)
        self.assertEqual(len(first["assessments"]), 3)
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        self.assertTrue(first["continuation_required"])
        _, state = self.store.read()
        self.assertEqual(len(state["pending"]), 3)
        second = self.batch(self.runtime(self.make_store("restart")), budget=20, invocation="new-controller")
        self.assertEqual(len(second["assessments"]), 3)
        self.assertEqual(self.backend.effects, [("alpha", "enable"), ("alpha", "run"), ("beta", "enable"), ("beta", "run"), ("gamma", "enable"), ("gamma", "run")])
        self.assertTrue(second["continuation_required"])
        self.assertEqual(len(second["pending"]), 3)  # Exact accepted invocations still require monitoring.

    def test_zero_budget_still_assesses_and_persists_all_projects(self):
        result = self.batch(budget=0)
        self.assertEqual(len(result["assessments"]), 1)
        self.assertEqual(self.backend.effects, [])
        self.assertTrue(self.store.read()[1]["pending"])

    def test_idle_enable_retains_unclaimed_run_across_budget_exhaustion_and_zero_budget_restart(self):
        self.backend.live["alpha"]["signals"]["invocation"].update(state="idle", invocation_id=None)
        first = self.batch(budget=1)
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        self.assertTrue(first["continuation_required"])
        self.assertEqual(len(first["pending"]), 1)
        second = self.batch(self.runtime(self.make_store("zero-budget-restart")), budget=0, invocation="second-wake")
        self.assertTrue(second["continuation_required"])
        self.assertEqual(len(second["pending"]), 1)
        self.batch(budget=1, invocation="third-wake")
        self.assertEqual(self.backend.effects, [("alpha", "enable"), ("alpha", "run")])

    def test_idle_enable_retains_unclaimed_run_after_deadline_exhaustion(self):
        self.backend.live["alpha"]["signals"]["invocation"].update(state="idle", invocation_id=None)
        instant = [NOW]
        self.backend.after_enable = lambda backend, project: instant.__setitem__(0, "2026-09-28T12:00:02Z")
        runtime = fleet.FleetRuntime(self.store, self.backend, clock=lambda: instant[0])
        result = runtime.run_batch(self.projects, max_effects=2, invocation_id="deadline-wake", deadline_utc="2026-09-28T12:00:01Z")
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        self.assertTrue(result["continuation_required"])
        second = runtime.run_batch(self.projects, max_effects=0, invocation_id="zero-budget-next-wake")
        self.assertTrue(second["continuation_required"])

    def test_pause_or_exact_terminal_suppresses_unclaimed_run_continuation(self):
        self.backend.live["alpha"]["signals"]["invocation"].update(state="idle", invocation_id=None)
        self.batch(budget=1)
        self.backend.live["alpha"]["signals"]["pause"].update(state="paused", owner_evidence="owner:pause")
        paused = self.batch(budget=0, invocation="paused-wake")
        self.assertFalse(paused["continuation_required"])
        self.backend.live["alpha"]["signals"]["pause"].update(state="running", owner_evidence=None)
        self.backend.live["alpha"]["signals"]["work"].update(state="terminal", terminal_proof={
            "project_id": "alpha", "source_ref": "refs/heads/main", "source_revision": "a" * 40, "evidence_ref": "git:complete"})
        terminal = self.batch(budget=1, invocation="terminal-wake")
        self.assertFalse(terminal["continuation_required"])
        self.assertEqual(self.backend.effects, [("alpha", "enable")])

    def test_expired_wake_deadline_still_persists_continuation_without_effects(self):
        result = self.runtime().run_batch(self.projects, max_effects=20, invocation_id="deadline-wake", deadline_utc="2026-09-28T11:59:59Z")
        self.assertEqual(len(result["assessments"]), 1)
        self.assertEqual(self.backend.effects, [])
        self.assertTrue(result["continuation_required"])

    def test_wake_deadline_exhaustion_between_enable_and_run_preserves_schedule_and_remainder(self):
        instant = [NOW]
        self.backend.after_enable = lambda backend, project: instant.__setitem__(0, "2026-09-28T12:00:02Z")
        runtime = fleet.FleetRuntime(self.store, self.backend, clock=lambda: instant[0])
        result = runtime.run_batch(self.projects, max_effects=20, invocation_id="deadline-wake", deadline_utc="2026-09-28T12:00:01Z")
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        self.assertTrue(result["continuation_required"])

    def test_current_owner_pause_produces_zero_effects(self):
        self.backend.live["alpha"] = probe(pause={"state": "paused", "owner_evidence": "owner:pause"})
        result = self.batch()
        self.assertEqual(self.backend.effects, [])
        self.assertEqual(result["assessments"][0]["overall"], "PAUSED")

    def test_pause_between_enable_and_run_denies_run(self):
        def pause(backend, project):
            backend.live[project["project_id"]]["signals"]["pause"].update(state="paused", owner_evidence="owner:pause")
        self.backend.after_enable = pause
        self.batch()
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        self.assertEqual(self.backend.live["alpha"]["signals"]["scheduler"]["state"], "enabled")

    def test_pause_after_claim_before_effect_denies_enable_and_claim_is_not_replayed(self):
        original = self.store.compare_and_swap
        def pause_after_claim(revision, state):
            updated = original(revision, state)
            if any(op["status"] == "claimed" for op in state["operations"].values()):
                self.backend.live["alpha"]["signals"]["pause"].update(state="paused", owner_evidence="owner:pause")
            return updated
        self.store.compare_and_swap = pause_after_claim
        self.batch()
        self.assertEqual(self.backend.effects, [])
        self.backend.live["alpha"]["signals"]["pause"].update(state="running", owner_evidence=None)
        self.batch(self.runtime(self.make_store("restart")), invocation="new-controller")
        self.assertEqual(self.backend.effects, [])

    def test_policy_owner_guard_external_invocation_and_budget_are_reread_before_each_effect(self):
        cases = [("policy", {"recovery_allowed": False}), ("policy", {"effects_remaining": 0}), ("owner", {"state": "active"}), ("guard", {"state": "active"}), ("external", {"state": "unknown"}), ("invocation", {"state": "running", "invocation_id": "other-worker"})]
        for index, (signal, patch) in enumerate(cases):
            with self.subTest(signal=signal, patch=patch):
                store = self.make_store("gate-" + str(index))
                store.ref = "refs/heads/cdc/gate-" + str(index)
                self.backend = RecordingScheduler(self.root, self.projects)
                def change(backend, project):
                    backend.live[project["project_id"]]["signals"][signal].update(patch)
                self.backend.after_enable = change
                self.batch(self.runtime(store))
                self.assertEqual(self.backend.effects, [("alpha", "enable")])

    def test_unknown_owner_external_and_invocation_never_start_duplicates(self):
        for signal in ["owner", "guard", "external", "invocation"]:
            with self.subTest(signal=signal):
                self.backend.live["alpha"] = probe(**{signal: "unknown"})
                self.batch()
                self.assertEqual(self.backend.effects, [])

    def test_binding_change_after_enable_prevents_run(self):
        self.backend.after_enable = lambda backend, project: backend.live["alpha"]["binding"].update(incident_id="other-incident")
        self.batch()
        self.assertEqual(self.backend.effects, [("alpha", "enable")])

    def test_unknown_provider_reply_is_durable_and_never_replayed_even_when_idle_again(self):
        self.backend.lost_response = True
        self.batch()
        self.backend.live["alpha"]["signals"]["invocation"].update(state="completed", invocation_id="previous-invocation")
        self.batch(self.runtime(self.make_store("restart")), invocation="another-invocation")
        self.assertEqual(self.backend.effects, [("alpha", "enable"), ("alpha", "run")])
        _, state = self.store.read()
        self.assertIn("unknown", [entry["status"] for entry in state["operations"].values()])
        self.assertTrue(state["pending"])

    def test_renaming_incident_cannot_bypass_unknown_run_claim(self):
        self.backend.lost_response = True
        self.batch()
        self.backend.live["alpha"]["binding"]["incident_id"] = "renamed-incident"
        self.backend.live["alpha"]["signals"]["invocation"].update(state="completed", invocation_id="old")
        self.batch(self.runtime(self.make_store("restart")), invocation="next-controller")
        self.assertEqual(len(self.backend.effects), 2)
        self.assertTrue(self.store.read()[1]["pending"])

    def test_accepted_run_remains_pending_when_changed_incident_looks_idle_or_unrelated_completed(self):
        self.batch()
        for state, invocation_id in [("idle", None), ("completed", "other-completed-invocation")]:
            self.backend.live["alpha"]["binding"]["incident_id"] = "next-incident"
            self.backend.live["alpha"]["signals"]["invocation"].update(state=state, invocation_id=invocation_id)
            result = self.batch(invocation="next-controller")
            self.assertEqual(len(self.backend.effects), 2)
            self.assertTrue(result["continuation_required"])

    def test_exact_accepted_invocation_terminal_proof_allows_next_authorized_incident(self):
        self.batch()
        self.backend.live["alpha"]["binding"]["incident_id"] = "next-incident"
        self.backend.live["alpha"]["signals"]["invocation"]["state"] = "completed"
        self.batch(invocation="next-controller")
        self.assertEqual(self.backend.effects, [("alpha", "enable"), ("alpha", "run"), ("alpha", "run")])
        runs = [op for op in self.store.read()[1]["operations"].values() if op["effect"] == "run"]
        self.assertEqual(sum(op.get("invocation_terminal") is True for op in runs), 1)

    def test_zero_budget_retains_unknown_claim_even_when_next_probe_looks_healthy(self):
        self.backend.lost_response = True
        self.batch()
        result = self.batch(budget=0, invocation="next-controller")
        self.assertTrue(result["continuation_required"])

    def test_same_invocation_cannot_reset_durable_budget_by_starting_a_new_incident(self):
        self.batch(budget=2)
        self.backend.live["alpha"]["binding"]["incident_id"] = "next-confirmed-incident"
        self.backend.live["alpha"]["signals"]["invocation"]["state"] = "completed"
        result = self.batch(budget=2)
        self.assertEqual(len(self.backend.effects), 2)
        self.assertTrue(result["continuation_required"])

    def test_same_invocation_cannot_raise_its_durable_budget(self):
        self.batch(budget=0)
        with self.assertRaises(ValueError):
            self.batch(budget=2)
        self.assertEqual(self.backend.effects, [])

    def test_completed_checkpoint_loss_cannot_reset_effect_budget_for_next_project(self):
        self.projects.append({**PROJECT, "project_id": "beta", "watchdog_id": "watchdog-beta"})
        self.backend = RecordingScheduler(self.root, self.projects)
        original = self.store.compare_and_swap
        def lose_completion(revision, state):
            if any(op["effect"] == "run" and op["status"] == "succeeded" for op in state["operations"].values()):
                raise TimeoutError("completion checkpoint unavailable")
            return original(revision, state)
        self.store.compare_and_swap = lose_completion
        result = self.batch(budget=2)
        self.assertEqual(self.backend.effects, [("alpha", "enable"), ("alpha", "run")])
        self.assertEqual(result["effects_attempted"], 2)

    def test_changed_exact_invocation_after_claim_denies_effect(self):
        original = self.store.compare_and_swap
        def change_invocation(revision, state):
            result = original(revision, state)
            if any(op["status"] == "claimed" for op in state["operations"].values()):
                self.backend.live["alpha"]["signals"]["invocation"]["invocation_id"] = "different-completed-invocation"
            return result
        self.store.compare_and_swap = change_invocation
        self.batch()
        self.assertEqual(self.backend.effects, [])

    def test_stale_scheduler_readback_cannot_confirm_enable(self):
        def make_stale(backend, project):
            backend.live["alpha"]["signals"]["scheduler"]["observed_at_utc"] = "2026-09-28T11:00:00Z"
        self.backend.after_enable = make_stale
        self.batch()
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        self.assertIn("unknown", [op["status"] for op in self.store.read()[1]["operations"].values()])

    def test_run_must_read_back_a_new_exact_invocation(self):
        def stale_run(project, *, binding, operation_id):
            self.backend._receipt(project, "run", operation_id)
            return {"status": "accepted", "binding": binding, "invocation_id": "previous-invocation"}
        self.backend.run = stale_run
        self.batch()
        self.assertIn("unknown", [op["status"] for op in self.store.read()[1]["operations"].values()])

    def test_lost_cas_response_never_permits_scheduler_effect_or_restart_replay(self):
        original = self.store.compare_and_swap
        def lose_claim_reply(revision, state):
            result = original(revision, state)
            if any(op["status"] == "claimed" for op in state["operations"].values()):
                raise TimeoutError("committed claim reply lost")
            return result
        self.store.compare_and_swap = lose_claim_reply
        self.batch()
        self.assertEqual(self.backend.effects, [])
        self.batch(self.runtime(self.make_store("restart")), invocation="restart")
        self.assertEqual(self.backend.effects, [])

    def test_schedule_drift_in_readback_blocks_run(self):
        self.backend.bad_readback = True
        self.batch()
        self.assertEqual(self.backend.effects, [("alpha", "enable")])
        statuses = [op["status"] for op in self.store.read()[1]["operations"].values()]
        self.assertIn("unknown", statuses)

    def test_premature_completion_retains_continuation_without_reusing_run_claim(self):
        self.batch()
        self.backend.live["alpha"]["signals"]["invocation"]["state"] = "completed"
        result = self.batch(invocation="next-controller")
        self.assertTrue(result["continuation_required"])
        self.assertEqual(result["assessments"][0]["overall"], "CRITICAL")
        self.assertEqual(len(self.backend.effects), 2)

    def test_observation_failure_does_not_skip_other_registered_projects(self):
        self.projects.append({**PROJECT, "project_id": "beta", "watchdog_id": "watchdog-beta"})
        self.backend = RecordingScheduler(self.root, self.projects)
        observe = self.backend.observe
        def partial_failure(project):
            if project["project_id"] == "alpha":
                raise TimeoutError("unavailable observation")
            return observe(project)
        self.backend.observe = partial_failure
        result = self.batch()
        self.assertEqual(len(result["assessments"]), 2)
        self.assertEqual(self.backend.effects, [("beta", "enable"), ("beta", "run")])

    def test_separate_controllers_cannot_both_execute_same_incident(self):
        barrier = threading.Barrier(2, timeout=10)
        first_reads = set()
        original_observe = self.backend.observe
        def observe(project):
            value = original_observe(project)
            thread = threading.get_ident()
            if thread not in first_reads:
                first_reads.add(thread)
                barrier.wait()
            return value
        self.backend.observe = observe
        runtimes = [self.runtime(), self.runtime(self.make_store("controller-b"))]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.batch, runtime, 20, "controller-" + str(i)) for i, runtime in enumerate(runtimes)]
            for future in futures:
                future.result(timeout=30)
        self.assertEqual(self.backend.effects.count(("alpha", "enable")), 1)
        self.assertEqual(self.backend.effects.count(("alpha", "run")), 1)

    def test_git_cas_identical_proposals_have_one_winner_and_unique_commit_ids(self):
        initial = {"value": 1}
        revision = self.store.compare_and_swap(None, initial)
        barrier = threading.Barrier(2, timeout=10)
        proposals = []
        class Contender(GitDocumentStore):
            def read(inner):
                value = super().read()
                barrier.wait()
                return value
            def _git(inner, *args, **kwargs):
                value = super()._git(*args, **kwargs)
                if args[0] == "commit-tree":
                    proposals.append(value)
                return value
        stores = [self.make_store("race-" + str(i), Contender) for i in range(2)]
        def attempt(store):
            try:
                return store.compare_and_swap(revision, {"value": 2})
            except ValueError:
                return None
        clock = {"GIT_AUTHOR_DATE": "2026-09-28T12:00:00+00:00", "GIT_COMMITTER_DATE": "2026-09-28T12:00:00+00:00"}
        with mock.patch.dict(os.environ, clock), ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt, stores))
        self.assertEqual(len({p for p in proposals}), 2)
        self.assertEqual(sum(value is not None for value in outcomes), 1)
        self.assertEqual(self.store.read()[1], {"value": 2})

    def test_git_remote_identity_drift_and_product_ref_aliases_fail_closed(self):
        self.store.compare_and_swap(None, {"value": 1})
        other = self.root / "other.git"
        self.git("init", "--bare", "-q", str(other))
        self.git("remote", "set-url", "origin", str(other), cwd=self.store.repo)
        with self.assertRaises(ValueError):
            self.store.read()
        with self.assertRaises(ValueError):
            GitDocumentStore(self.store.repo, "origin", "refs/heads/MAIN", self.store_id, protected_refs=["refs/heads/main"])

    def seed_product_refs(self):
        blob = self.git("hash-object", "-w", "--stdin", cwd=self.store.repo, input="product content\n")
        tree = self.git("mktree", cwd=self.store.repo, input=f"100644 blob {blob}\tproduct.txt\n")
        commit = self.store._git("commit-tree", tree, input_text="product commit\n")
        for ref in ["refs/heads/main", "refs/heads/integration", "refs/heads/worker-a"]:
            self.git("update-ref", ref, commit, cwd=self.store.repo)
        self.git("config", "--replace-all", "remote.origin.fetch", "+" + self.ref + ":refs/heads/main", cwd=self.store.repo)
        self.git("config", "--add", "remote.origin.fetch", "+" + self.ref + ":refs/heads/integration", cwd=self.store.repo)
        self.git("config", "--add", "remote.origin.fetch", "+" + self.ref + ":refs/heads/worker-a", cwd=self.store.repo)
        return self.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.store.repo)

    def test_git_read_cannot_apply_configured_fetch_mapping_to_local_product_refs(self):
        revision = self.store.compare_and_swap(None, {"value": 1})
        before = self.seed_product_refs()
        self.assertEqual(self.store.read(), (revision, {"value": 1}))
        self.assertEqual(self.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.store.repo), before)

    def test_git_push_cannot_apply_configured_tracking_mapping_to_local_product_refs(self):
        before = self.seed_product_refs()
        # Empty remote means CAS reads no ref and does no fetch: this isolates the
        # push's incidental local tracking updates from fetch's separate behavior.
        revision = self.store.compare_and_swap(None, {"value": 1})
        self.assertEqual(self.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.store.repo), before)
        self.assertEqual(self.store.read(), (revision, {"value": 1}))
        newer = self.store.compare_and_swap(revision, {"value": 2})
        self.assertEqual(self.store.read(), (newer, {"value": 2}))
        self.assertEqual(self.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.store.repo), before)

    def test_git_document_store_refuses_shared_root_files_instead_of_erasing_them(self):
        revision = self.store.compare_and_swap(None, {"value": 1})
        blob = self.git("hash-object", "-w", "--stdin", cwd=self.store.repo, input="keep me\n")
        document = self.git("rev-parse", revision + ":document.json", cwd=self.store.repo)
        tree = self.git("mktree", cwd=self.store.repo, input=f"100644 blob {document}\tdocument.json\n100644 blob {blob}\tother.json\n")
        commit = self.store._git("commit-tree", tree, "-p", revision, input_text="add another root file\n")
        self.git("push", "-q", "origin", commit + ":" + self.ref, cwd=self.store.repo)
        with self.assertRaisesRegex(ValueError, "only document.json"):
            self.store.compare_and_swap(commit, {"value": 2})
        self.assertEqual(self.git("ls-remote", "--refs", "origin", self.ref, cwd=self.store.repo).split()[0], commit)

    def cli_fixture(self, *, crash=False):
        adapter = self.root / "local_scheduler_adapter.py"
        adapter.write_text('''from pathlib import Path
import os
from test_fleet_watchdog_runtime import RecordingScheduler
from watchdog_liveness import now_utc
def build(config):
    backend = RecordingScheduler(Path(config["root"]), config["projects"])
    original = backend.observe
    def fresh(project):
        for signal in backend.live[project["project_id"]]["signals"].values():
            signal["observed_at_utc"] = now_utc()
        return original(project)
    backend.observe = fresh
    if config.get("crash"):
        backend.enable = lambda *args, **kwargs: os._exit(19)
    return backend
''')
        config = self.root / "fleet.json"
        config.write_text(json.dumps({"store": {"repo": str(self.store.repo), "remote": "origin", "coordination_ref": self.ref,
                                                "coordination_store_id": self.store_id, "protected_refs": ["refs/heads/main"]},
                                      "projects": self.projects, "max_effects": 2, "invocation_id": "cli-invocation",
                                      "backend_config": {"root": str(self.root), "projects": self.projects, "crash": crash}}))
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(self.root), str(Path(__file__).parent), str(scripts)]))
        command = [sys.executable, "-B", str(scripts / "fleet_watchdog_runtime.py"), str(config), "--backend", "local_scheduler_adapter:build"]
        return command, env

    def test_cli_loads_an_explicit_local_backend_and_executes_actual_effects(self):
        command, env = self.cli_fixture()
        result = subprocess.run(command, text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["effects_attempted"], 2)
        self.assertEqual(len(list(self.root.glob("operation-*"))), 2)

    def test_actual_process_crash_after_claim_and_restart_cannot_replay(self):
        command, env = self.cli_fixture(crash=True)
        first = subprocess.run(command, text=True, capture_output=True, env=env)
        self.assertEqual(first.returncode, 19, first.stderr)
        self.assertEqual([op["status"] for op in self.store.read()[1]["operations"].values()], ["claimed"])
        second = subprocess.run(command, text=True, capture_output=True, env=env)
        self.assertEqual(second.returncode, 0, second.stderr)
        result = json.loads(second.stdout)
        self.assertTrue(result["continuation_required"])
        self.assertEqual(result["effects_attempted"], 0)
        self.assertEqual(list(self.root.glob("operation-*")), [])

    def test_invalid_registry_duplicate_and_noncanonical_ref_are_rejected(self):
        for projects in [[PROJECT, PROJECT], [{**PROJECT, "source_ref": "main"}]]:
            with self.subTest(projects=projects), self.assertRaises(ValueError):
                self.runtime().run_batch(projects, max_effects=1, invocation_id="controller")
        self.assertEqual(self.backend.effects, [])


if __name__ == "__main__":
    unittest.main()
