#!/usr/bin/env python3
"""Durable desired-state reconciliation for replaceable watchdog scheduler objects.

The scheduler backend is an explicit capability boundary. Every scheduler effect
is preceded by a durable CAS claim and a fresh safety read. Unknown effects are
never replayed; a later inventory may reconcile them by exact generation/readback.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import secrets

from watchdog_survivability import assess, validate_desired

SCHEMA = "watchdog-survivability-runtime/v1"


def binding_key(binding):
    raw = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def operation_key(binding, action, generation, object_id=None, basis=None):
    payload = {"binding": binding, "action": action, "generation": generation,
               "object_id": object_id, "basis": basis}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class WatchdogSurvivabilityRuntime:
    def __init__(self, store, backend, *, clock, max_age_seconds=120, leader_guard=None):
        self.store = store
        self.backend = backend
        self.clock = clock
        self.max_age_seconds = max_age_seconds
        self.leader_guard = leader_guard

    def _initial(self):
        return {"schema": SCHEMA, "coordination_ref": self.store.ref,
                "coordination_store_id": self.store.store_id, "entries": {}}

    def _read(self):
        revision, state = self.store.read()
        if state is None:
            return revision, self._initial()
        if (not isinstance(state, dict) or set(state) != set(self._initial()) or state.get("schema") != SCHEMA
                or state.get("coordination_ref") != self.store.ref
                or state.get("coordination_store_id") != self.store.store_id or not isinstance(state.get("entries"), dict)):
            raise ValueError("watchdog survivability runtime state mismatch")
        for key, entry in state["entries"].items():
            if not isinstance(entry, dict) or set(entry) != {"desired", "operations"} or not isinstance(entry["operations"], dict):
                raise ValueError("watchdog survivability entry invalid")
            validate_desired(entry["desired"])
            if key != binding_key(entry["desired"]["binding"]):
                raise ValueError("watchdog survivability entry binding mismatch")
            for op_key, operation in entry["operations"].items():
                if (not isinstance(operation, dict) or operation.get("status") not in {"claimed", "succeeded", "blocked", "unknown"}
                        or operation.get("action") not in {"create", "enable", "run", "disable"}
                        or not isinstance(operation.get("operation_id"), str) or not operation["operation_id"]):
                    raise ValueError("watchdog survivability operation invalid")
                leader=operation.get("leader")
                if leader is not None:
                    expected_leader={"schema","fleet_repository","fleet_ref","owner_id","generation","invocation_id","observed_fleet_head"}
                    if (not isinstance(leader,dict) or set(leader)!=expected_leader
                            or leader.get("schema")!="fleet-leader-binding/v1"):
                        raise ValueError("watchdog survivability leader binding invalid")
                expected = operation_key(entry["desired"]["binding"], operation["action"],
                                         operation["generation"], operation.get("object_id"),
                                         operation.get("basis"))
                if op_key != expected:
                    raise ValueError("watchdog survivability operation key mismatch")
        return revision, state

    def _change(self, transform):
        for _ in range(6):
            revision, state = self._read()
            changed = copy.deepcopy(state)
            result = transform(changed)
            if result is False:
                return False
            try:
                self.store.compare_and_swap(revision, changed)
                return result
            except ValueError:
                continue
        raise ValueError("watchdog survivability coordination contention")

    def snapshot(self):
        return copy.deepcopy(self._read()[1])

    def register(self, desired):
        validate_desired(desired)
        key = binding_key(desired["binding"])
        incoming = copy.deepcopy(desired)

        def transform(state):
            current = state["entries"].get(key)
            if current is None:
                state["entries"][key] = {"desired": incoming, "operations": {}}
                return True
            existing = current["desired"]
            if incoming["generation"] < existing["generation"]:
                raise ValueError("cannot roll back watchdog desired generation")
            if incoming == existing:
                return False
            if incoming["generation"] == existing["generation"]:
                raise ValueError("desired-state mutation requires an explicit newer generation")
            unresolved = any(op["status"] in {"claimed", "unknown"} for op in current["operations"].values())
            if unresolved:
                stop_only = (incoming["desired_state"] == "paused"
                             or incoming["owner_stop_evidence"] is not None
                             or not incoming["required"])
                stable_materialization = (
                    incoming["schedule"] == existing["schedule"]
                    and incoming["template_digest"] == existing["template_digest"]
                    and incoming["canonical_object_id"] == existing["canonical_object_id"])
                if not stop_only or not stable_materialization:
                    raise ValueError("cannot replace watchdog desired state while an effect is unresolved")
                # Owner stop/fencing is authoritative, but never erase the uncertain effect journal.
                current["desired"] = incoming
                return True
            current["desired"] = incoming
            current["operations"] = {}
            return True

        self._change(transform)
        return key

    def _entry(self, binding):
        key = binding_key(binding)
        _, state = self._read()
        if key not in state["entries"] or state["entries"][key]["desired"]["binding"] != binding:
            raise ValueError("watchdog desired state is not registered")
        return key, state["entries"][key]

    def _observe(self, desired):
        inventory = self.backend.observe(copy.deepcopy(desired["binding"]))
        result = assess(desired, inventory, now=self.clock(), max_age_seconds=self.max_age_seconds)
        return inventory, result

    def _leader_binding(self, invocation_id=None, expected=None):
        if self.leader_guard is None:
            raise ValueError("Fleet leader guard required for watchdog scheduler effects")
        if invocation_id is None:
            invocation_id=getattr(self.leader_guard,"invocation_id",None)
        if not isinstance(invocation_id,str) or not invocation_id:
            raise ValueError("watchdog scheduler effect requires exact leader invocation")
        value=self.leader_guard.binding(invocation_id)
        fields={"schema","fleet_repository","fleet_ref","owner_id","generation","invocation_id","observed_fleet_head"}
        if not isinstance(value,dict) or set(value)!=fields or value.get("schema")!="fleet-leader-binding/v1":
            raise ValueError("Fleet leader binding invalid")
        if value["invocation_id"]!=invocation_id:
            raise ValueError("Fleet leader invocation mismatch")
        if expected is not None and value!=expected:
            raise ValueError("Fleet head or leader changed")
        return copy.deepcopy(value)

    def _set_operation(self, key, action, generation, object_id=None, *, basis=None, leader=None):
        op_key = operation_key(self._entry_by_key(key)["desired"]["binding"],
                               action, generation, object_id, basis)
        operation_id = "watchdog-operation-" + secrets.token_hex(24)

        def transform(state):
            entry = state["entries"][key]
            if op_key in entry["operations"]:
                return False
            if any(op["status"] in {"claimed", "unknown"} for op in entry["operations"].values()):
                return False
            entry["operations"][op_key] = {
                "action": action, "generation": generation, "object_id": object_id,
                "basis": basis, "operation_id": operation_id,
                "status": "claimed", "claimed_at_utc": self.clock(),
                "leader": copy.deepcopy(leader),
            }
            return True

        if not self._change(transform):
            return None, op_key
        return operation_id, op_key

    def _entry_by_key(self, key):
        _, state = self._read()
        return state["entries"][key]

    def _fence_replacement(self, key, op_key, operation_id, expected_desired, target_generation):
        def transform(state):
            entry = state["entries"][key]
            op = entry["operations"].get(op_key)
            if (op is None or op["operation_id"] != operation_id or op["status"] != "claimed"
                    or entry["desired"] != expected_desired
                    or entry["desired"]["generation"] >= target_generation):
                return False
            entry["desired"]["generation"] = target_generation
            entry["desired"]["canonical_object_id"] = None
            return True
        return bool(self._change(transform))

    def _finish(self, key, op_key, operation_id, status, detail):
        def transform(state):
            op = state["entries"][key]["operations"].get(op_key)
            if not op or op["operation_id"] != operation_id or op["status"] != "claimed":
                return False
            op.update(status=status, detail=detail, finished_at_utc=self.clock())
            return True
        self._change(transform)

    def _adopt(self, key, object_id, *, op_key=None, operation_id=None):
        def transform(state):
            entry = state["entries"][key]
            entry["desired"]["canonical_object_id"] = object_id
            if op_key is not None:
                op = entry["operations"].get(op_key)
                if op and op["operation_id"] == operation_id and op["status"] in {"claimed", "unknown"}:
                    op.update(status="succeeded", detail="exact generation materialization adopted", finished_at_utc=self.clock())
            return True
        self._change(transform)

    @staticmethod
    def _at_or_after(value, lower_bound):
        try:
            left = datetime.fromisoformat(value.replace("Z", "+00:00"))
            right = datetime.fromisoformat(lower_bound.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return False
        return left >= right

    def _reconcile_uncertain(self, key, entry):
        uncertain = [(op_key, op) for op_key, op in entry["operations"].items() if op["status"] in {"claimed", "unknown"}]
        if not uncertain:
            return None
        desired = entry["desired"]
        inventory, result = self._observe(desired)
        for op_key, op in uncertain:
            if op["action"] == "create":
                matching = [
                    item for item in inventory["objects"]
                    if item["generation"] == op["generation"]
                    and item["schedule"] == desired["schedule"]
                    and item["template_digest"] == desired["template_digest"]
                ]
                object_id = (result["canonical_object_id"]
                             if result["action"] == "ADOPT" and result["canonical_object_id"]
                             else matching[0]["object_id"] if len(matching) == 1 else None)
                if object_id:
                    self._adopt(key, object_id, op_key=op_key, operation_id=op["operation_id"])
                    return {"outcome": "adopted", "assessment": result}
            if op["action"] == "enable":
                item = next((x for x in inventory["objects"] if x["object_id"] == op["object_id"]), None)
                if item is not None and item["enabled"]:
                    self._finish_unknown(key, op_key, op["operation_id"], "enabled readback")
                    return {"outcome": "enabled", "assessment": result}
            if op["action"] == "disable":
                item = next((x for x in inventory["objects"] if x["object_id"] == op["object_id"]), None)
                if (item is None
                        or (not item["enabled"] and item["execution_state"] in {"idle", "failed"})):
                    self._finish_unknown(key, op_key, op["operation_id"], "disabled and quiescent readback")
                    return {"outcome": "duplicates_quiesced", "assessment": result}
            if op["action"] == "run":
                item = next((x for x in inventory["objects"] if x["object_id"] == op["object_id"]), None)
                if (item is not None and item["last_run_at_utc"] is not None
                        and item["execution_state"] in {"running", "idle", "failed"}
                        and self._at_or_after(item["last_run_at_utc"], op["claimed_at_utc"])):
                    self._finish_unknown(key, op_key, op["operation_id"], "run readback after durable claim")
                    return {"outcome": "run_requested", "assessment": result}
        return {"outcome": "unreconciled_operation", "assessment": result}

    def _finish_unknown(self, key, op_key, operation_id, detail):
        def transform(state):
            op = state["entries"][key]["operations"].get(op_key)
            if not op or op["operation_id"] != operation_id or op["status"] not in {"claimed", "unknown"}:
                return False
            op.update(status="succeeded", detail=detail, finished_at_utc=self.clock())
            return True
        self._change(transform)

    def _post_claim_assessment(self, desired):
        _, assessment = self._observe(desired)
        return assessment

    def reconcile_registered(self, *, max_effects=100, invocation_id=None, leader_binding=None):
        """Assess every registered watchdog and apply a bounded number of scheduler effects."""
        if type(max_effects) is not int or not 0 <= max_effects <= 2000:
            raise ValueError("watchdog survivability max_effects must be 0..2000")
        batch_leader=None
        if max_effects>0:
            batch_leader=(self._leader_binding(invocation_id)
                          if leader_binding is None
                          else self._leader_binding(invocation_id, expected=leader_binding))
        _, state = self._read()
        results = []
        effects_attempted = 0
        effect_actions = {"RECREATE", "ENABLE", "RUN", "QUIESCE_DUPLICATES"}
        effect_outcomes = {"recreated", "enabled", "run_requested", "duplicates_quiesced",
                           "provider_outcome_unknown"}
        for key in sorted(state["entries"]):
            binding = copy.deepcopy(state["entries"][key]["desired"]["binding"])
            try:
                entry = self._entry_by_key(key)
                unresolved = any(op["status"] in {"claimed", "unknown"} for op in entry["operations"].values())
                if unresolved:
                    result = self.reconcile(binding)
                else:
                    _, assessment = self._observe(entry["desired"])
                    if assessment["action"] in effect_actions and effects_attempted >= max_effects:
                        result = {"outcome": "effect_budget_deferred", "assessment": assessment}
                    else:
                        result = self.reconcile(binding, invocation_id=invocation_id, leader_binding=batch_leader)
                        if result["outcome"] in effect_outcomes:
                            effects_attempted += 1
            except Exception as exc:
                result = {
                    "outcome": "coordination_or_observation_unavailable",
                    "error_class": type(exc).__name__,
                }
            results.append({"binding": binding, **result})

        def needs_continuation(item):
            assessment = item.get("assessment", {})
            if item["outcome"] == "no_effect":
                return assessment.get("overall") not in {"HEALTHY", "OWNER_PAUSED", "PROJECT_TERMINAL"}
            if assessment.get("action") in {"ADOPT", "RECREATE", "ENABLE", "RUN", "QUIESCE_DUPLICATES"}:
                return True
            if item["outcome"] in {"adopted", "enabled", "run_requested", "recreated", "duplicates_quiesced"}:
                return False
            return True

        return {
            "schema": "watchdog-survivability-batch/v1",
            "registered_count": len(state["entries"]),
            "results": results,
            "effects_attempted": effects_attempted,
            "max_effects": max_effects,
            "continuation_required": any(needs_continuation(item) for item in results),
            "authorizes_scheduler_mutation": False,
        }

    def reconcile(self, binding, *, invocation_id=None, leader_binding=None):
        key, entry = self._entry(binding)
        uncertain = self._reconcile_uncertain(key, entry)
        if uncertain is not None:
            return uncertain
        desired = self._entry_by_key(key)["desired"]
        inventory, assessment = self._observe(desired)
        action = assessment["action"]
        if action in {"NONE", "OBSERVE"}:
            return {"outcome": "no_effect", "assessment": assessment}
        if action == "ADOPT":
            self._adopt(key, assessment["canonical_object_id"])
            return {"outcome": "adopted", "assessment": assessment}
        if not assessment["recovery_eligible"]:
            return {"outcome": "no_effect", "assessment": assessment}
        if action == "RECREATE":
            target_generation = assessment["next_generation"]
            leader=(self._leader_binding(invocation_id)
                    if leader_binding is None
                    else self._leader_binding(invocation_id, expected=leader_binding))
            operation_id, op_key = self._set_operation(
                key, "create", target_generation,
                basis="generation:" + str(target_generation), leader=leader)
            if operation_id is None:
                return {"outcome": "unreconciled_operation", "assessment": assessment}

            # Claim first, but do not advance the generation fence until a fresh
            # execution-safety observation still proves replacement is allowed.
            pre_fence_desired = copy.deepcopy(self._entry_by_key(key)["desired"])
            _, after_claim = self._observe(pre_fence_desired)
            if after_claim["action"] == "ADOPT":
                self._finish(key, op_key, operation_id, "blocked",
                             "current generation materialization appeared before replacement fence")
                self._adopt(key, after_claim["canonical_object_id"])
                return {"outcome": "adopted", "assessment": after_claim}
            if (after_claim["action"] != "RECREATE"
                    or not after_claim["recovery_eligible"]
                    or after_claim["next_generation"] != target_generation):
                self._finish(key, op_key, operation_id, "blocked",
                             "post-claim replacement safety changed")
                return {"outcome": "post_claim_gate_denied", "assessment": after_claim}

            if not self._fence_replacement(
                    key, op_key, operation_id, pre_fence_desired, target_generation):
                self._finish(key, op_key, operation_id, "blocked",
                             "desired state changed before replacement fence")
                return {"outcome": "post_claim_gate_denied", "assessment": after_claim}

            # Re-observe after the durable generation fence and immediately
            # before scheduler I/O. The fence alone never proves quiescence.
            desired = self._entry_by_key(key)["desired"]
            _, before_io = self._observe(desired)
            if before_io["action"] == "ADOPT":
                self._adopt(key, before_io["canonical_object_id"],
                            op_key=op_key, operation_id=operation_id)
                return {"outcome": "adopted", "assessment": before_io}
            if before_io["action"] != "RECREATE" or not before_io["recovery_eligible"]:
                self._finish(key, op_key, operation_id, "blocked",
                             "pre-I/O replacement safety changed")
                return {"outcome": "post_claim_gate_denied", "assessment": before_io}
            try:
                self._leader_binding(invocation_id, expected=leader)
            except ValueError:
                self._finish(key, op_key, operation_id, "blocked", "fleet head or leader changed before provider I/O")
                return {"outcome": "fleet_head_or_leader_changed", "assessment": before_io}
            try:
                reply = self.backend.create(copy.deepcopy(binding), generation=target_generation,
                                            schedule=desired["schedule"], template_digest=desired["template_digest"],
                                            operation_id=operation_id)
                _, readback = self._observe(desired)
                valid = (isinstance(reply, dict) and reply.get("status") == "accepted"
                         and reply.get("operation_id") == operation_id and reply.get("generation") == target_generation
                         and readback["action"] == "ADOPT" and readback["canonical_object_id"] == reply.get("object_id"))
                if not valid:
                    raise ValueError("create exact readback disagrees")
            except Exception:
                self._finish(key, op_key, operation_id, "unknown", "provider create outcome unconfirmed")
                return {"outcome": "provider_outcome_unknown", "assessment": assessment}
            self._adopt(key, reply["object_id"], op_key=op_key, operation_id=operation_id)
            return {"outcome": "recreated", "assessment": readback}
        if action in {"ENABLE", "RUN"}:
            verb = action.lower()
            object_id = assessment["canonical_object_id"]
            generation = desired["generation"]
            before = next((x for x in inventory["objects"] if x["object_id"] == object_id), None)
            if before is None:
                return {"outcome": "observation_changed", "assessment": assessment}
            basis = ("disabled@" + inventory["observed_at_utc"] if verb == "enable"
                     else "run-after:" + str(before["last_run_at_utc"] or "never")
                     + ":failures:" + str(before["consecutive_failures"]))
            leader=(self._leader_binding(invocation_id)
                    if leader_binding is None
                    else self._leader_binding(invocation_id, expected=leader_binding))
            operation_id, op_key = self._set_operation(
                key, verb, generation, object_id, basis=basis, leader=leader)
            if operation_id is None:
                return {"outcome": "unreconciled_operation", "assessment": assessment}
            current = self._entry_by_key(key)["desired"]
            post_claim = self._post_claim_assessment(current)
            if post_claim["action"] != action or not post_claim["recovery_eligible"]:
                self._finish(key, op_key, operation_id, "blocked", "post-claim recovery action changed")
                return {"outcome": "post_claim_gate_denied", "assessment": post_claim}
            try:
                self._leader_binding(invocation_id, expected=leader)
            except ValueError:
                self._finish(key, op_key, operation_id, "blocked", "fleet head or leader changed before provider I/O")
                return {"outcome": "fleet_head_or_leader_changed", "assessment": post_claim}
            try:
                method = getattr(self.backend, verb)
                claimed_at = self._entry_by_key(key)["operations"][op_key]["claimed_at_utc"]
                reply = method(copy.deepcopy(binding), object_id=object_id, operation_id=operation_id)
                inv, readback = self._observe(current)
                item = next((x for x in inv["objects"] if x["object_id"] == object_id), None)
                valid = isinstance(reply, dict) and reply.get("status") == "accepted" and reply.get("operation_id") == operation_id and item is not None
                if verb == "enable":
                    valid = valid and item["enabled"]
                else:
                    valid = (valid and item["last_run_at_utc"] is not None
                             and item["execution_state"] in {"running", "idle", "failed"}
                             and self._at_or_after(item["last_run_at_utc"], claimed_at))
                if not valid:
                    raise ValueError("scheduler exact readback disagrees")
            except Exception:
                self._finish(key, op_key, operation_id, "unknown", "provider effect outcome unconfirmed")
                return {"outcome": "provider_outcome_unknown", "assessment": assessment}
            self._finish(key, op_key, operation_id, "succeeded", "exact scheduler readback confirmed")
            return {"outcome": "enabled" if verb == "enable" else "run_requested", "assessment": readback}
        if action == "QUIESCE_DUPLICATES":
            object_id = assessment["stale_object_ids"][0]
            stale = next((x for x in inventory["objects"] if x["object_id"] == object_id), None)
            if stale is None:
                return {"outcome": "observation_changed", "assessment": assessment}
            basis = ("duplicate:" + str(stale["generation"]) + "@"
                     + inventory["observed_at_utc"])
            leader=(self._leader_binding(invocation_id)
                    if leader_binding is None
                    else self._leader_binding(invocation_id, expected=leader_binding))
            operation_id, op_key = self._set_operation(
                key, "disable", desired["generation"], object_id, basis=basis, leader=leader)
            if operation_id is None:
                return {"outcome": "unreconciled_operation", "assessment": assessment}
            current = self._entry_by_key(key)["desired"]
            post_claim = self._post_claim_assessment(current)
            if (post_claim["action"] != "QUIESCE_DUPLICATES"
                    or object_id not in post_claim["stale_object_ids"]
                    or not post_claim["recovery_eligible"]):
                self._finish(key, op_key, operation_id, "blocked", "post-claim duplicate action changed")
                return {"outcome": "post_claim_gate_denied", "assessment": post_claim}
            try:
                self._leader_binding(invocation_id, expected=leader)
            except ValueError:
                self._finish(key, op_key, operation_id, "blocked", "fleet head or leader changed before provider I/O")
                return {"outcome": "fleet_head_or_leader_changed", "assessment": post_claim}
            try:
                reply = self.backend.disable(copy.deepcopy(binding), object_id=object_id, operation_id=operation_id)
                inv, readback = self._observe(current)
                item = next((x for x in inv["objects"] if x["object_id"] == object_id), None)
                if not (isinstance(reply, dict) and reply.get("status") == "accepted"
                        and reply.get("operation_id") == operation_id
                        and (item is None
                             or (not item["enabled"] and item["execution_state"] in {"idle", "failed"}))):
                    raise ValueError("disable exact readback has not proven duplicate quiescence")
            except Exception:
                self._finish(key, op_key, operation_id, "unknown", "provider disable outcome unconfirmed")
                return {"outcome": "provider_outcome_unknown", "assessment": assessment}
            self._finish(key, op_key, operation_id, "succeeded", "stale watchdog quiesced")
            return {"outcome": "duplicates_quiesced", "assessment": readback}
        raise ValueError("unsupported survivability action")
