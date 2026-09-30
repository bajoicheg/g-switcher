import copy
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
if importlib.util.find_spec("watchdog_survivability_runtime"):
    import watchdog_survivability_runtime as runtime_mod
else:
    runtime_mod = None

from test_watchdog_survivability import NOW, desired, inventory, obj, quiescence


class MemoryStore:
    ref = "refs/heads/cdc/watchdog-survivability"
    store_id = "sha256:" + "c" * 64

    def __init__(self):
        self.revision = 0
        self.value = None
        self.after_cas = None

    def read(self):
        return self.revision, copy.deepcopy(self.value)

    def compare_and_swap(self, expected, value):
        if expected != self.revision:
            raise ValueError("stale")
        self.revision += 1
        self.value = copy.deepcopy(value)
        if self.after_cas:
            self.after_cas(self)
        return str(self.revision)


class RecordingBackend:
    def __init__(self, inv=None):
        self.inventory = copy.deepcopy(inv or inventory([]))
        self.effects = []
        self.lose_create_reply = False
        self.lose_run_reply = False
        self.next_id = 1
        self.run_at_utc = NOW
        self.reads = 0
        self.before_observe = None

    def observe(self, binding):
        self.reads += 1
        if self.before_observe:
            self.before_observe(self, self.reads)
        self.inventory["binding"] = copy.deepcopy(binding)
        return copy.deepcopy(self.inventory)

    def create(self, binding, *, generation, schedule, template_digest, operation_id):
        object_id = f"wd-created-{self.next_id}"
        self.next_id += 1
        self.effects.append(("create", generation, operation_id))
        self.inventory["objects"].append(obj(object_id, generation=generation, schedule=schedule,
                                             template_digest=template_digest, last_run_at_utc=None))
        if self.lose_create_reply:
            raise TimeoutError("reply lost")
        return {"status": "accepted", "object_id": object_id, "generation": generation,
                "operation_id": operation_id}

    def enable(self, binding, *, object_id, operation_id):
        self.effects.append(("enable", object_id, operation_id))
        for item in self.inventory["objects"]:
            if item["object_id"] == object_id:
                item["enabled"] = True
        return {"status": "accepted", "object_id": object_id, "operation_id": operation_id}

    def run(self, binding, *, object_id, operation_id):
        self.effects.append(("run", object_id, operation_id))
        for item in self.inventory["objects"]:
            if item["object_id"] == object_id:
                item["last_run_at_utc"] = self.run_at_utc
                item["execution_state"] = "running"
        if self.lose_run_reply:
            raise TimeoutError("run reply lost")
        return {"status": "accepted", "object_id": object_id, "operation_id": operation_id}

    def disable(self, binding, *, object_id, operation_id):
        self.effects.append(("disable", object_id, operation_id))
        for item in self.inventory["objects"]:
            if item["object_id"] == object_id:
                item["enabled"] = False
        return {"status": "accepted", "object_id": object_id, "operation_id": operation_id}


class WatchdogSurvivabilityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime_mod, "watchdog survivability runtime is not implemented")
        self.store = MemoryStore()
        self.backend = RecordingBackend()
        self.runtime = runtime_mod.WatchdogSurvivabilityRuntime(self.store, self.backend, clock=lambda: NOW)
        self.runtime.register(desired(canonical_object_id=None))

    def test_missing_watchdog_fences_generation_before_create_and_adopts_readback(self):
        result = self.runtime.reconcile(desired()["binding"])
        self.assertEqual(result["outcome"], "recreated")
        state = self.runtime.snapshot()
        current = state["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]
        self.assertEqual(current["generation"], 8)
        self.assertEqual(current["canonical_object_id"], "wd-created-1")
        self.assertEqual([e[0] for e in self.backend.effects], ["create"])

    def test_stale_idle_object_without_quiescence_proof_does_not_bump_generation_or_create(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj("wd-old", generation=6, execution_state="idle")]))
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())
        result = runtime.reconcile(desired()["binding"])
        current = runtime.snapshot()["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]
        self.assertEqual(result["outcome"], "no_effect")
        self.assertEqual(current["generation"], 7)
        self.assertEqual(backend.effects, [])

    def test_recreate_race_does_not_bump_generation_before_fresh_execution_safety_recheck(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([]))
        def race(other, reads):
            if reads == 2:
                other.inventory["objects"] = [obj("wd-old", generation=6, execution_state="running")]
        backend.before_observe = race
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired(canonical_object_id=None))
        result = runtime.reconcile(desired()["binding"])
        current = runtime.snapshot()["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]
        self.assertEqual(result["outcome"], "post_claim_gate_denied")
        self.assertEqual(current["generation"], 7)
        self.assertEqual(backend.effects, [])

    def test_bound_quiescent_stale_object_is_recreated_after_two_fresh_safety_gates(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([
            obj("wd-old", generation=6, execution_state="idle",
                quiescence_evidence=quiescence("wd-old", 6))
        ]))
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())
        result = runtime.reconcile(desired()["binding"])
        self.assertEqual(result["outcome"], "recreated")
        current = runtime.snapshot()["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]
        self.assertEqual(current["generation"], 8)
        self.assertEqual(current["canonical_object_id"], "wd-created-1")
        self.assertEqual([e[0] for e in backend.effects], ["create"])

    def test_lost_create_reply_retains_generation_and_never_replays_create(self):
        self.backend.lose_create_reply = True
        first = self.runtime.reconcile(desired()["binding"])
        self.assertEqual(first["outcome"], "provider_outcome_unknown")
        state = self.runtime.snapshot()
        current = state["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]
        self.assertEqual(current["generation"], 8)
        self.assertIsNone(current["canonical_object_id"])
        self.backend.lose_create_reply = False
        second = self.runtime.reconcile(desired()["binding"])
        self.assertEqual(second["outcome"], "adopted")
        self.assertEqual([e[0] for e in self.backend.effects], ["create"])
        self.assertEqual(self.runtime.snapshot()["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]["canonical_object_id"], "wd-created-1")

    def test_unknown_create_without_materialization_is_not_replayed(self):
        self.backend.create = self._unknown_without_object
        first = self.runtime.reconcile(desired()["binding"])
        second = self.runtime.reconcile(desired()["binding"])
        self.assertEqual(first["outcome"], "provider_outcome_unknown")
        self.assertEqual(second["outcome"], "unreconciled_operation")
        self.assertEqual([e[0] for e in self.backend.effects], ["create"])

    def _unknown_without_object(self, binding, *, generation, schedule, template_digest, operation_id):
        self.backend.effects.append(("create", generation, operation_id))
        raise TimeoutError("unknown before readback")

    def test_lost_run_reply_reconciles_from_post_claim_run_timestamp_without_replay(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj(last_run_at_utc="2026-09-29T09:00:00Z")]))
        backend.lose_run_reply = True
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())
        first = runtime.reconcile(desired()["binding"])
        self.assertEqual(first["outcome"], "provider_outcome_unknown")
        backend.lose_run_reply = False
        second = runtime.reconcile(desired()["binding"])
        self.assertEqual(second["outcome"], "run_requested")
        self.assertEqual([effect[0] for effect in backend.effects], ["run"])

    def test_unresolved_effect_blocks_desired_generation_replacement(self):
        self.backend.create = self._unknown_without_object
        self.runtime.reconcile(desired()["binding"])
        newer = desired(canonical_object_id=None, generation=9)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.runtime.register(newer)

    def test_post_claim_run_is_blocked_if_another_actor_already_started_watchdog(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj(last_run_at_utc="2026-09-29T09:00:00Z")]))
        def race(other, reads):
            if reads == 2:
                other.inventory["objects"][0]["last_run_at_utc"] = NOW
                other.inventory["objects"][0]["execution_state"] = "running"
        backend.before_observe = race
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())
        result = runtime.reconcile(desired()["binding"])
        self.assertEqual(result["outcome"], "post_claim_gate_denied")
        self.assertEqual(backend.effects, [])

    def test_owner_stop_can_fence_unknown_effect_without_erasing_journal(self):
        self.backend.create = self._unknown_without_object
        first = self.runtime.reconcile(desired()["binding"])
        self.assertEqual(first["outcome"], "provider_outcome_unknown")
        stopped = desired(
            canonical_object_id=None, generation=9, desired_state="paused",
            owner_stop_evidence="owner:pause")
        self.runtime.register(stopped)
        state = self.runtime.snapshot()
        entry = state["entries"][runtime_mod.binding_key(stopped["binding"])]
        self.assertEqual(entry["desired"]["desired_state"], "paused")
        self.assertTrue(any(op["status"] == "unknown" for op in entry["operations"].values()))
        second = self.runtime.reconcile(stopped["binding"])
        self.assertEqual(second["outcome"], "unreconciled_operation")
        self.assertEqual([e[0] for e in self.backend.effects], ["create"])
        self.backend.inventory["objects"].append(
            obj("wd-late", generation=8, last_run_at_utc=None))
        third = self.runtime.reconcile(stopped["binding"])
        self.assertEqual(third["outcome"], "adopted")
        self.assertEqual([e[0] for e in self.backend.effects], ["create"])
        current = self.runtime.snapshot()["entries"][runtime_mod.binding_key(stopped["binding"])]["desired"]
        self.assertEqual(current["desired_state"], "paused")
        self.assertEqual(current["canonical_object_id"], "wd-late")

    def test_running_duplicate_is_disabled_once_but_not_declared_quiescent_until_it_stops(self):
        d = desired()
        store = MemoryStore()
        backend = RecordingBackend(
            inventory([obj(), obj("wd-old", generation=6, execution_state="running")]))
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(d)
        first = runtime.reconcile(d["binding"])
        self.assertEqual(first["outcome"], "provider_outcome_unknown")
        self.assertEqual([(e[0], e[1]) for e in backend.effects], [("disable", "wd-old")])
        second = runtime.reconcile(d["binding"])
        self.assertEqual(second["outcome"], "unreconciled_operation")
        self.assertEqual([(e[0], e[1]) for e in backend.effects], [("disable", "wd-old")])
        next(item for item in backend.inventory["objects"] if item["object_id"] == "wd-old")["execution_state"] = "idle"
        third = runtime.reconcile(d["binding"])
        self.assertEqual(third["outcome"], "duplicates_quiesced")
        self.assertEqual([(e[0], e[1]) for e in backend.effects], [("disable", "wd-old")])

    def test_owner_stop_committed_after_claim_blocks_scheduler_io(self):
        fired = {"done": False}
        def pause_after_claim(store):
            if fired["done"] or not store.value:
                return
            entry = next(iter(store.value["entries"].values()))
            if any(op["status"] == "claimed" for op in entry["operations"].values()):
                entry["desired"]["owner_stop_evidence"] = "owner-message:99"
                fired["done"] = True
        self.store.after_cas = pause_after_claim
        result = self.runtime.reconcile(desired()["binding"])
        self.assertEqual(result["outcome"], "post_claim_gate_denied")
        self.assertEqual(self.backend.effects, [])

    def test_duplicate_stale_generation_is_quiesced_not_recreated(self):
        d = desired()
        self.store = MemoryStore()
        self.backend = RecordingBackend(inventory([obj(), obj("wd-old", generation=6)]))
        self.runtime = runtime_mod.WatchdogSurvivabilityRuntime(self.store, self.backend, clock=lambda: NOW)
        self.runtime.register(d)
        result = self.runtime.reconcile(d["binding"])
        self.assertEqual(result["outcome"], "duplicates_quiesced")
        self.assertEqual([(e[0], e[1]) for e in self.backend.effects], [("disable", "wd-old")])
        second = self.runtime.reconcile(d["binding"])
        self.assertEqual(second["outcome"], "no_effect")
        self.assertEqual([(e[0], e[1]) for e in self.backend.effects], [("disable", "wd-old")])

    def test_disabled_and_overdue_use_enable_and_run_without_generation_bump(self):
        for current, effect in ((obj(enabled=False), "enable"),
                                (obj(last_run_at_utc="2026-09-29T09:00:00Z"), "run")):
            with self.subTest(effect=effect):
                store = MemoryStore()
                backend = RecordingBackend(inventory([current]))
                runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
                runtime.register(desired())
                result = runtime.reconcile(desired()["binding"])
                self.assertEqual(result["outcome"], {"enable": "enabled", "run": "run_requested"}[effect])
                self.assertEqual(backend.effects[0][0], effect)
                self.assertEqual(runtime.snapshot()["entries"][runtime_mod.binding_key(desired()["binding"])]["desired"]["generation"], 7)

    def test_same_generation_can_repair_a_new_later_disable_incident(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj(enabled=False)]))
        instant = [NOW]
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: instant[0])
        runtime.register(desired())
        self.assertEqual(runtime.reconcile(desired()["binding"])["outcome"], "enabled")
        backend.inventory["objects"][0]["enabled"] = False
        instant[0] = "2026-09-29T12:31:00Z"
        backend.inventory["observed_at_utc"] = instant[0]
        backend.inventory["safety"]["observed_at_utc"] = instant[0]
        self.assertEqual(runtime.reconcile(desired()["binding"])["outcome"], "enabled")
        self.assertEqual([e[0] for e in backend.effects], ["enable", "enable"])

    def test_same_generation_can_request_a_new_later_periodic_run(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj(last_run_at_utc="2026-09-29T09:00:00Z")]))
        instant = [NOW]
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: instant[0])
        runtime.register(desired())
        self.assertEqual(runtime.reconcile(desired()["binding"])["outcome"], "run_requested")
        backend.inventory["objects"][0]["execution_state"] = "idle"
        instant[0] = "2026-09-29T15:00:00Z"
        backend.run_at_utc = instant[0]
        backend.inventory["observed_at_utc"] = instant[0]
        backend.inventory["safety"]["observed_at_utc"] = instant[0]
        self.assertEqual(runtime.reconcile(desired()["binding"])["outcome"], "run_requested")
        self.assertEqual([e[0] for e in backend.effects], ["run", "run"])

    def test_owner_paused_or_terminal_state_produces_no_scheduler_effect(self):
        for d, inv in (
            (desired(canonical_object_id=None, owner_stop_evidence="owner:stop"), inventory([])),
            (desired(canonical_object_id=None), inventory([], project={"state": "terminal", "source_revision": "a" * 40,
                "terminal_proof": {"project_id": "alpha", "source_ref": "refs/heads/main", "source_revision": "a" * 40,
                                   "evidence_ref": "git:terminal"}})),
        ):
            with self.subTest(d=d):
                store = MemoryStore()
                backend = RecordingBackend(inv)
                runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
                runtime.register(d)
                result = runtime.reconcile(d["binding"])
                self.assertEqual(result["outcome"], "no_effect")
                self.assertEqual(backend.effects, [])

    def test_reconcile_registered_processes_every_desired_watchdog(self):
        paused = desired(
            binding={"project_id": "beta", "source_ref": "refs/heads/main", "role": "project-watchdog"},
            canonical_object_id=None,
            owner_stop_evidence="owner:pause-beta",
        )
        self.runtime.register(paused)
        result = self.runtime.reconcile_registered()
        self.assertEqual(result["registered_count"], 2)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual({item["binding"]["project_id"] for item in result["results"]}, {"alpha", "beta"})
        self.assertFalse(result["authorizes_scheduler_mutation"])

    def test_batch_keeps_execution_broken_watchdog_for_continuation(self):
        store = MemoryStore()
        inv = inventory([obj(execution_state="unknown")])
        backend = RecordingBackend(inv)
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())
        result = runtime.reconcile_registered()
        self.assertTrue(result["continuation_required"])
        self.assertEqual(result["results"][0]["assessment"]["overall"], "EXECUTION_BROKEN")

    def test_recreation_keeps_batch_continuation_until_new_watchdog_is_woken(self):
        result = self.runtime.reconcile_registered(max_effects=1)
        self.assertEqual(result["effects_attempted"], 1)
        self.assertEqual(result["results"][0]["outcome"], "recreated")
        self.assertTrue(result["continuation_required"])

    def test_reconciled_unknown_does_not_consume_current_batch_effect_budget(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj(enabled=False)]))
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())

        def lost_enable_reply(binding, *, object_id, operation_id):
            backend.effects.append(("enable", object_id, operation_id))
            for item in backend.inventory["objects"]:
                if item["object_id"] == object_id:
                    item["enabled"] = True
            raise TimeoutError("enable reply lost after provider effect")

        backend.enable = lost_enable_reply
        first = runtime.reconcile_registered(max_effects=1)
        self.assertEqual(first["effects_attempted"], 1)
        self.assertEqual(first["results"][0]["outcome"], "provider_outcome_unknown")
        self.assertTrue(first["continuation_required"])
        self.assertEqual([effect[0] for effect in backend.effects], ["enable"])

        second = runtime.reconcile_registered(max_effects=0)
        self.assertEqual(second["results"][0]["outcome"], "enabled")
        self.assertEqual(second["effects_attempted"], 0)
        self.assertEqual(second["max_effects"], 0)
        self.assertFalse(second["continuation_required"])
        self.assertEqual([effect[0] for effect in backend.effects], ["enable"])

    def test_registered_reconciliation_assesses_all_but_bounds_scheduler_effects(self):
        store = MemoryStore()
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(
            store, RecordingBackend(inventory([])), clock=lambda: NOW)
        alpha = desired(canonical_object_id=None)
        beta = desired(
            binding={"project_id": "beta", "source_ref": "refs/heads/main", "role": "project-watchdog"},
            canonical_object_id=None,
        )
        runtime.register(alpha)
        runtime.register(beta)
        result = runtime.reconcile_registered(max_effects=0)
        self.assertEqual(result["registered_count"], 2)
        self.assertEqual(result["effects_attempted"], 0)
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["continuation_required"])
        self.assertEqual(
            {item["outcome"] for item in result["results"]},
            {"effect_budget_deferred"})

    def test_duplicate_quiescence_consumes_one_effect_per_reconcile(self):
        store = MemoryStore()
        backend = RecordingBackend(inventory([obj(), obj("wd-old-1", generation=6), obj("wd-old-2", generation=5)]))
        runtime = runtime_mod.WatchdogSurvivabilityRuntime(store, backend, clock=lambda: NOW)
        runtime.register(desired())
        first = runtime.reconcile_registered(max_effects=1)
        self.assertEqual(first["effects_attempted"], 1)
        self.assertTrue(first["continuation_required"])
        self.assertEqual(len([e for e in backend.effects if e[0] == "disable"]), 1)
        second = runtime.reconcile_registered(max_effects=1)
        self.assertEqual(second["effects_attempted"], 1)
        self.assertFalse(second["continuation_required"])
        self.assertEqual(len([e for e in backend.effects if e[0] == "disable"]), 2)

    def test_stale_registered_generation_cannot_overwrite_newer_runtime_generation(self):
        self.runtime.reconcile(desired()["binding"])
        with self.assertRaisesRegex(ValueError, "generation"):
            self.runtime.register(desired(canonical_object_id=None))


if __name__ == "__main__":
    unittest.main()
