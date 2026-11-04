import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
if importlib.util.find_spec("watchdog_survivability"):
    import watchdog_survivability as survivability
else:
    survivability = None

NOW = "2026-09-29T12:30:00Z"
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def desired(**patch):
    value = {
        "schema": "watchdog-desired-state/v1",
        "binding": {"project_id": "alpha", "source_ref": "refs/heads/main", "role": "project-watchdog"},
        "required": True,
        "desired_state": "enabled",
        "generation": 7,
        "canonical_object_id": "wd-current",
        "schedule": "RRULE:FREQ=HOURLY",
        "template_digest": DIGEST,
        "owner_stop_evidence": None,
        "recovery_policy": {
            "allowed": True,
            "owner_authorization": "owner:cdc-2.11.2",
            "overdue_after_seconds": 7200,
            "flap_threshold": 3,
        },
    }
    value.update(patch)
    return value


def obj(object_id="wd-current", **patch):
    value = {
        "object_id": object_id,
        "generation": 7,
        "enabled": True,
        "schedule": "RRULE:FREQ=HOURLY",
        "template_digest": DIGEST,
        "last_run_at_utc": "2026-09-29T12:00:00Z",
        "consecutive_failures": 0,
        "execution_state": "idle",
        "quiescence_evidence": None,
    }
    value.update(patch)
    return value


def quiescence(object_id="wd-current", generation=7, evidence_ref=None):
    return {
        "object_id": object_id,
        "generation": generation,
        "quiescent": True,
        "evidence_ref": evidence_ref or f"process:quiescent:{object_id}:{generation}",
    }


def inventory(objects=None, **patch):
    value = {
        "schema": "watchdog-runtime-inventory/v1",
        "binding": {"project_id": "alpha", "source_ref": "refs/heads/main", "role": "project-watchdog"},
        "observed_at_utc": NOW,
        "project": {"state": "runnable", "source_revision": SHA, "terminal_proof": None},
        "safety": {
            "owner": "released",
            "guard": "released",
            "external": "none",
            "pause": "running",
            "owner_pause_evidence": None,
            "observed_at_utc": NOW,
        },
        "objects": [obj()] if objects is None else objects,
    }
    value.update(patch)
    return value


class WatchdogSurvivabilityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(survivability, "watchdog survivability contract is not implemented")

    def test_missing_canonical_waits_for_running_noncanonical_materialization(self):
        running_old = obj("wd-old", generation=6, execution_state="running")
        result = survivability.assess(desired(), inventory([running_old]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("DUPLICATE", "OBSERVE"))
        self.assertFalse(result["recovery_eligible"])
        self.assertEqual(result["stale_object_ids"], ["wd-old"])

    def test_missing_canonical_idle_label_without_quiescence_proof_blocks_replacement(self):
        idle_old = obj("wd-old", generation=6, execution_state="idle")
        result = survivability.assess(desired(), inventory([idle_old]), now=NOW)
        self.assertEqual(result["action"], "OBSERVE")
        self.assertFalse(result["recovery_eligible"])
        self.assertEqual(result["next_generation"], 7)

    def test_bound_quiescence_proof_allows_stale_object_replacement(self):
        idle_old = obj(
            "wd-old", generation=6, execution_state="idle",
            quiescence_evidence=quiescence("wd-old", 6))
        result = survivability.assess(desired(), inventory([idle_old]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("MISSING", "RECREATE"))
        self.assertTrue(result["recovery_eligible"])
        self.assertEqual(result["next_generation"], 8)

    def test_missing_stale_unknown_object_blocks_replacement(self):
        unknown_old = obj("wd-old", generation=6, execution_state="unknown")
        result = survivability.assess(desired(), inventory([unknown_old]), now=NOW)
        self.assertEqual(result["action"], "OBSERVE")
        self.assertFalse(result["recovery_eligible"])

    def test_quiescence_proof_must_bind_exact_object_and_generation(self):
        with self.assertRaisesRegex(ValueError, "quiescence"):
            survivability.assess(
                desired(),
                inventory([obj(
                    "wd-old", generation=6,
                    quiescence_evidence=quiescence("wd-old", 5))]),
                now=NOW)

    def test_missing_required_watchdog_requests_recreation_with_new_generation(self):
        result = survivability.assess(desired(canonical_object_id=None), inventory([]), now=NOW)
        self.assertEqual(result["overall"], "MISSING")
        self.assertEqual(result["action"], "RECREATE")
        self.assertEqual(result["next_generation"], 8)
        self.assertTrue(result["recovery_eligible"])
        self.assertFalse(result["authorizes_scheduler_mutation"])

    def test_explicit_owner_stop_tombstone_never_self_heals(self):
        result = survivability.assess(desired(owner_stop_evidence="owner-message:42"), inventory([]), now=NOW)
        self.assertEqual(result["overall"], "OWNER_PAUSED")
        self.assertEqual(result["action"], "NONE")
        self.assertFalse(result["recovery_eligible"])

    def test_fresh_project_terminal_proof_never_recreates_watchdog(self):
        proof = {"project_id": "alpha", "source_ref": "refs/heads/main", "source_revision": SHA,
                 "evidence_ref": "git:terminal-proof"}
        inv = inventory([], project={"state": "terminal", "source_revision": SHA, "terminal_proof": proof})
        result = survivability.assess(desired(canonical_object_id=None), inv, now=NOW)
        self.assertEqual(result["overall"], "PROJECT_TERMINAL")
        self.assertEqual(result["action"], "NONE")

    def test_disabled_current_object_is_enabled_without_generation_change(self):
        result = survivability.assess(desired(), inventory([obj(enabled=False)]), now=NOW)
        self.assertEqual((result["overall"], result["action"], result["next_generation"]),
                         ("DISABLED_DRIFT", "ENABLE", 7))

    def test_configuration_drift_requires_recreation_and_fences_old_generation(self):
        result = survivability.assess(
            desired(),
            inventory([obj(schedule="RRULE:FREQ=DAILY",
                           quiescence_evidence=quiescence())]),
            now=NOW)
        self.assertEqual((result["overall"], result["action"], result["next_generation"]),
                         ("CONFIG_DRIFT", "RECREATE", 8))

    def test_duplicate_or_stale_objects_are_quiesced_after_current_object_is_known(self):
        stale = obj("wd-old", generation=6)
        result = survivability.assess(desired(), inventory([obj(), stale]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("DUPLICATE", "QUIESCE_DUPLICATES"))
        self.assertEqual(result["stale_object_ids"], ["wd-old"])

    def test_unbound_matching_generation_can_be_adopted_without_scheduler_effect(self):
        result = survivability.assess(desired(canonical_object_id=None), inventory([obj("wd-new")]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("CONFIG_DRIFT", "ADOPT"))
        self.assertEqual(result["canonical_object_id"], "wd-new")
        self.assertFalse(result["authorizes_scheduler_mutation"])

    def test_old_generation_is_fenced_from_execution_even_if_it_wakes_late(self):
        self.assertTrue(survivability.execution_is_current(desired(), obj()))
        self.assertFalse(survivability.execution_is_current(desired(), obj("wd-old", generation=6)))
        self.assertFalse(survivability.execution_is_current(desired(), obj("other")))

    def test_overdue_object_is_kicked_before_replacement(self):
        old = obj(last_run_at_utc="2026-09-29T09:00:00Z")
        result = survivability.assess(desired(), inventory([old]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("OVERDUE", "RUN"))
        self.assertEqual(result["next_generation"], 7)

    def test_flapping_object_recreates_only_when_owner_authorized(self):
        flapping = obj(
            consecutive_failures=3, execution_state="failed",
            quiescence_evidence=quiescence())
        result = survivability.assess(desired(), inventory([flapping]), now=NOW)
        self.assertEqual((result["overall"], result["action"], result["next_generation"]),
                         ("FLAPPING", "RECREATE", 8))
        denied_policy = dict(desired()["recovery_policy"], allowed=False)
        denied = survivability.assess(desired(recovery_policy=denied_policy), inventory([flapping]), now=NOW)
        self.assertFalse(denied["recovery_eligible"])

    def test_safety_or_freshness_uncertainty_blocks_scheduler_recovery(self):
        for inv in (
            inventory(safety={**inventory()["safety"], "owner": "active"}),
            inventory(safety={**inventory()["safety"], "guard": "active"}),
            inventory(safety={**inventory()["safety"], "external": "running"}),
            inventory(observed_at_utc="2026-09-29T12:00:00Z"),
        ):
            with self.subTest(inv=inv):
                result = survivability.assess(desired(canonical_object_id=None), inv, now=NOW, max_age_seconds=120)
                self.assertFalse(result["recovery_eligible"])
                self.assertEqual(result["action"], "OBSERVE")

    def test_fresh_owner_pause_evidence_blocks_recovery_even_if_scheduler_reports_running(self):
        inv = inventory([], safety={**inventory()["safety"], "pause": "running",
                                    "owner_pause_evidence": "owner:pause"})
        result = survivability.assess(desired(canonical_object_id=None), inv, now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("OWNER_PAUSED", "NONE"))
        self.assertFalse(result["recovery_eligible"])

    def test_running_watchdog_is_never_kicked_again_even_when_last_run_is_old(self):
        running = obj(last_run_at_utc="2026-09-29T09:00:00Z", execution_state="running")
        result = survivability.assess(desired(), inventory([running]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("HEALTHY", "NONE"))

    def test_running_config_drift_or_flapping_waits_for_quiescence(self):
        for running in (
            obj(schedule="RRULE:FREQ=DAILY", execution_state="running"),
            obj(consecutive_failures=3, execution_state="running"),
        ):
            with self.subTest(running=running):
                result = survivability.assess(desired(), inventory([running]), now=NOW)
                self.assertEqual(result["action"], "OBSERVE")
                self.assertFalse(result["recovery_eligible"])

    def test_running_disabled_watchdog_enables_schedule_without_second_run(self):
        running = obj(enabled=False, execution_state="running")
        result = survivability.assess(desired(), inventory([running]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("DISABLED_DRIFT", "ENABLE"))
        self.assertTrue(result["recovery_eligible"])

    def test_recent_failed_watchdog_gets_bounded_retry_before_flap_threshold(self):
        failed = obj(execution_state="failed", consecutive_failures=1)
        result = survivability.assess(desired(), inventory([failed]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("OVERDUE", "RUN"))

    def test_current_execution_requires_enabled_exact_materialization(self):
        self.assertFalse(survivability.execution_is_current(desired(), obj(enabled=False)))
        self.assertFalse(survivability.execution_is_current(desired(), obj(schedule="RRULE:FREQ=DAILY")))
        self.assertFalse(survivability.execution_is_current(desired(required=False), obj()))

    def test_unknown_execution_is_not_assumed_dead(self):
        result = survivability.assess(desired(), inventory([obj(execution_state="unknown")]), now=NOW)
        self.assertEqual((result["overall"], result["action"]), ("EXECUTION_BROKEN", "OBSERVE"))
        self.assertFalse(result["recovery_eligible"])

    def test_invocation_fence_allows_only_exact_current_running_materialization(self):
        current = survivability.invocation_fence(
            desired(), inventory([obj(execution_state="running")]),
            object_id="wd-current", generation=7, now=NOW)
        self.assertTrue(current["may_enter_cdc"])
        self.assertFalse(current["authorizes_product_write"])
        self.assertFalse(current["authorizes_external_start"])
        self.assertFalse(current["authorizes_lease_acquire"])

        for object_id, generation in (
            ("wd-old", 6),
            ("wd-current", 6),
            (None, None),
        ):
            with self.subTest(object_id=object_id, generation=generation):
                result = survivability.invocation_fence(
                    desired(), inventory([
                        obj(execution_state="running"),
                        obj("wd-old", generation=6, execution_state="running"),
                    ]),
                    object_id=object_id, generation=generation, now=NOW)
                self.assertFalse(result["may_enter_cdc"])

    def test_invocation_fence_fails_closed_on_pause_terminal_or_stale_inventory(self):
        paused = inventory([obj(execution_state="running")],
                           safety={**inventory()["safety"], "pause": "paused",
                                   "owner_pause_evidence": "owner:pause"})
        terminal = inventory(
            [obj(execution_state="running")],
            project={"state": "terminal", "source_revision": SHA,
                     "terminal_proof": {"project_id": "alpha",
                                        "source_ref": "refs/heads/main",
                                        "source_revision": SHA,
                                        "evidence_ref": "git:terminal"}})
        stale = inventory([obj(execution_state="running")],
                          observed_at_utc="2026-09-29T12:00:00Z")
        for inv in (paused, terminal, stale):
            with self.subTest(inv=inv):
                result = survivability.invocation_fence(
                    desired(), inv, object_id="wd-current", generation=7,
                    now=NOW, max_age_seconds=120)
                self.assertFalse(result["may_enter_cdc"])

    def test_malformed_binding_or_duplicate_object_id_fails_closed(self):
        bad = inventory([obj(), obj()])
        with self.assertRaises(ValueError):
            survivability.assess(desired(), bad, now=NOW)
        mismatched = inventory([], binding={"project_id": "beta", "source_ref": "refs/heads/main", "role": "project-watchdog"})
        with self.assertRaises(ValueError):
            survivability.assess(desired(canonical_object_id=None), mismatched, now=NOW)


if __name__ == "__main__":
    unittest.main()
