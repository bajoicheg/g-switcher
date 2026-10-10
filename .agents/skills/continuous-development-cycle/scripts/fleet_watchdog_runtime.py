#!/usr/bin/env python3
"""Cooperative Fleet recovery using supplied observation and scheduler capabilities.

No platform adapter is bundled. Every effect consumes an irreversible durable
claim, then checks live authority again. Ambiguous claims/replies require external
reconciliation and are never replayed, including under a renamed incident.
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
from pathlib import Path
import secrets
import sys

from git_document_store import GitDocumentStore
from git_remote_identity import isolated_remote_args
import fleet_supervisor_control as fleet_control
from parallel_task_planner import portable_path_key
from watchdog_liveness import assess, binding_key, now_utc, text, utc, validate_binding

SCHEMA = "fleet-watchdog-state/v1"
MAX_PROJECTS = 1000


def project_of(binding):
    return {key: value for key, value in binding.items() if key != "incident_id"}


def operation_key(binding, effect):
    return binding_key(binding) + ":" + effect


class GitFleetLeaderGuard:
    """Read-only verifier for an already-acquired Fleet Supervisor leader lease."""

    def __init__(self, store, *, owner_id, generation, invocation_id, clock=now_utc):
        if not isinstance(store, GitDocumentStore):
            raise ValueError("Fleet leader state requires GitDocumentStore")
        self.store=store
        self.owner_id=owner_id
        self.generation=generation
        self.invocation_id=invocation_id
        self.clock=clock

    def _live_fleet_head(self,state):
        self.store._assert_remote_identity()
        if portable_path_key(self.store.ref)==portable_path_key(state["fleet_ref"]):
            raise ValueError("Fleet leader state ref must be isolated from authoritative Fleet ref")
        # Reuse the coordination store's immutable remote identity, but read the
        # authoritative Fleet ref rather than trusting config bytes.
        config,alias=isolated_remote_args(self.store.repo,self.store.remote,self.store.store_id)
        output=self.store._git(*config,"ls-remote","--refs",alias,state["fleet_ref"])
        rows=[line for line in output.splitlines() if line.strip()]
        if len(rows)!=1:
            raise ValueError("authoritative Fleet ref must resolve exactly once")
        parts=rows[0].split("\t")
        if len(parts)!=2 or parts[1]!=state["fleet_ref"] or len(parts[0])!=40 or any(ch not in "0123456789abcdef" for ch in parts[0]):
            raise ValueError("authoritative Fleet ref response invalid")
        return parts[0]

    def binding(self, invocation_id):
        if invocation_id!=self.invocation_id:
            raise ValueError("Fleet runtime invocation does not match leader invocation")
        _,state=self.store.read()
        if state is None:
            raise ValueError("Fleet leader state is absent")
        live_head=self._live_fleet_head(state)
        return fleet_control.leader_binding(
            state,self.owner_id,self.generation,self.invocation_id,self.clock(),live_head)

    def claim_scheduler_effect(self, invocation_id, project, effect, recovery, policy_revision):
        if invocation_id!=self.invocation_id:
            raise ValueError("Fleet runtime invocation does not match leader invocation")
        target="watchdog:"+binding_key(project)
        intent={
            "effect":effect,
            "schedule":recovery["schedule"],
            "prompt":recovery["prompt"],
            "expected_invocation":copy.deepcopy(recovery["expected_invocation"]),
            "policy_revision":policy_revision,
            "leader_generation":self.generation,
            "leader_invocation_id":self.invocation_id,
        }
        for _ in range(6):
            revision,state=self.store.read()
            if state is None:
                raise ValueError("Fleet leader state is absent")
            live_head=self._live_fleet_head(state)
            leader=fleet_control.leader_binding(
                state,self.owner_id,self.generation,self.invocation_id,self.clock(),live_head)
            request={"kind":"scheduler_repair","target":target,"observed_fleet_head":live_head,"intent":intent}
            changed,decision=fleet_control.claim_effect_record(
                state,self.owner_id,self.generation,self.invocation_id,self.clock(),live_head,request)
            if decision["action"]!="SUBMIT_ONCE":
                return {**decision,"leader":leader}
            try:
                self.store.compare_and_swap(revision,changed)
                return {**decision,"leader":leader}
            except ValueError:
                continue
        raise ValueError("Fleet effect journal contention or unavailable CAS")

    def finish_scheduler_effect(self, invocation_id, effect_id, state_name, receipt_ref, outcome=None):
        if invocation_id!=self.invocation_id:
            raise ValueError("Fleet runtime invocation does not match leader invocation")
        for _ in range(6):
            revision,state=self.store.read()
            if state is None:
                raise ValueError("Fleet leader state is absent")
            try:
                changed=fleet_control.update_effect_record(
                    state,self.owner_id,self.generation,self.invocation_id,self.clock(),
                    effect_id,state_name,receipt_ref,outcome)
            except ValueError:
                raise
            try:
                self.store.compare_and_swap(revision,changed)
                return next(copy.deepcopy(e) for e in changed["effects"] if e["effect_id"]==effect_id)
            except ValueError:
                continue
        raise ValueError("Fleet effect completion contention or unavailable CAS")

class FleetRuntime:
    """backend.observe(project), enable(...), and run(...) are real capabilities.

    Callers must keep incident IDs stable until independently reconciled and
    collect fresh facts from authoritative sources. A completed controller/child
    invocation does not clear pending work or prove a project terminal.
    """

    def __init__(self, store, backend, *, clock=now_utc, max_age_seconds=120,
                 survivability_runtime=None, leader_guard=None):
        self.store = store
        self.backend = backend
        self.clock = clock
        self.max_age_seconds = max_age_seconds
        self.survivability_runtime = survivability_runtime
        self.leader_guard = leader_guard
        if (self.survivability_runtime is not None and self.leader_guard is not None
                and getattr(self.survivability_runtime, "leader_guard", None) is None):
            self.survivability_runtime.leader_guard = self.leader_guard

    def _initial_state(self):
        return {"schema": SCHEMA, "coordination_ref": self.store.ref,
                "coordination_store_id": self.store.store_id, "operations": {},
                "recoveries": {}, "assessments": {}, "wake_budgets": {}, "pending": [], "last_batch": None}

    def _read(self):
        for attempt in range(6):
            try:
                revision, state = self.store.read()
                break
            except ValueError:
                if attempt == 5:
                    raise
        if state is None:
            return revision, self._initial_state()
        expected = set(self._initial_state())
        if (set(state) != expected or state["schema"] != SCHEMA
                or state["coordination_ref"] != self.store.ref
                or state["coordination_store_id"] != self.store.store_id):
            raise ValueError("Fleet state schema or coordination identity mismatch")
        for name in ["operations", "recoveries", "assessments", "wake_budgets"]:
            if not isinstance(state[name], dict):
                raise ValueError("Fleet state mapping invalid")
        if not isinstance(state["pending"], list) or len(set(state["pending"])) != len(state["pending"]):
            raise ValueError("Fleet pending continuation invalid")
        for key, op in state["operations"].items():
            validate_binding(op["binding"])
            if (op.get("effect") not in {"enable", "run"} or key != operation_key(op["binding"],op["effect"])
                    or op.get("status") not in {"claimed", "succeeded", "blocked", "unknown"}):
                raise ValueError("Fleet operation identity or status invalid")
            leader=op.get("leader")
            if leader is not None:
                expected={"schema","fleet_repository","fleet_ref","owner_id","generation","invocation_id","observed_fleet_head"}
                if not isinstance(leader,dict) or set(leader)!=expected or leader.get("schema")!="fleet-leader-binding/v1":
                    raise ValueError("Fleet operation leader binding invalid")
                if leader["invocation_id"]!=op.get("controller_invocation_id"):
                    raise ValueError("Fleet operation leader/controller mismatch")
                if (not isinstance(leader["generation"],int) or leader["generation"]<1
                        or not isinstance(leader["owner_id"],str) or not leader["owner_id"]
                        or not isinstance(leader["fleet_repository"],str) or not leader["fleet_repository"]
                        or not isinstance(leader["fleet_ref"],str) or not leader["fleet_ref"].startswith("refs/heads/")
                        or not isinstance(leader["observed_fleet_head"],str) or len(leader["observed_fleet_head"])!=40
                        or any(ch not in "0123456789abcdef" for ch in leader["observed_fleet_head"])):
                    raise ValueError("Fleet operation leader binding values invalid")
            fleet_effect_id=op.get("fleet_effect_id")
            if fleet_effect_id is not None:
                if (leader is None or not isinstance(fleet_effect_id,str) or not fleet_effect_id.startswith("sha256:")
                        or len(fleet_effect_id)!=71 or any(ch not in "0123456789abcdef" for ch in fleet_effect_id[7:])):
                    raise ValueError("Fleet operation effect provenance invalid")
            text(op.get("operation_id"), "operation_id")
            text(op.get("controller_invocation_id"), "controller_invocation_id")
            if op["controller_invocation_id"] not in state["wake_budgets"]:
                raise ValueError("Fleet operation lacks its durable wake budget")
            if op["effect"] == "run" and op["status"] == "succeeded":
                text(op.get("provider_invocation_id"), "provider_invocation_id")
                if type(op.get("invocation_terminal")) is not bool:
                    raise ValueError("Fleet accepted run requires an independent invocation lifecycle")
        for invocation_id, budget in state["wake_budgets"].items():
            text(invocation_id, "wake invocation_id")
            if (not isinstance(budget, dict) or set(budget) != {"max_effects", "deadline_utc"}
                    or type(budget["max_effects"]) is not int or not 0 <= budget["max_effects"] <= 2000):
                raise ValueError("Fleet wake budget invalid")
            if budget["deadline_utc"] is not None:
                utc(budget["deadline_utc"])
            if sum(op["controller_invocation_id"] == invocation_id for op in state["operations"].values()) > budget["max_effects"]:
                raise ValueError("Fleet wake budget over-reserved")
        for key, recovery in state["recoveries"].items():
            validate_binding(recovery["binding"])
            if key != binding_key(recovery["binding"]) or recovery["steps"] not in [["enable", "run"], ["run"]]:
                raise ValueError("Fleet recovery binding or steps invalid")
            text(recovery["schedule"], "recovery.schedule")
            text(recovery["prompt"], "recovery.prompt")
            expected_invocation = recovery.get("expected_invocation")
            if (not isinstance(expected_invocation, dict) or set(expected_invocation) != {"state", "invocation_id"}
                    or expected_invocation["state"] not in {"idle", "completed"}):
                raise ValueError("Fleet recovery exact invocation invalid")
        return revision, state

    def _change(self, transform):
        # A lost successful CAS is safe to read again: the durable claim exists,
        # so the transform cannot return a second grant. A timeout stops outright.
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
        raise ValueError("Fleet coordination contention or unavailable CAS")

    def _observe(self, project, binding=None):
        value = self.backend.observe(copy.deepcopy(project))
        if project_of(value.get("binding", {})) != project:
            raise ValueError("observation project/ref/watchdog mismatch")
        result = assess(value, now=self.clock(), max_age_seconds=self.max_age_seconds, expected_binding=binding)
        return value, result

    def _leader_binding(self, invocation_id):
        if self.leader_guard is None:
            raise ValueError("Fleet leader guard required for side effects")
        value=self.leader_guard.binding(invocation_id)
        expected={"schema","fleet_repository","fleet_ref","owner_id","generation","invocation_id","observed_fleet_head"}
        if not isinstance(value,dict) or set(value)!=expected or value.get("schema")!="fleet-leader-binding/v1":
            raise ValueError("Fleet leader binding invalid")
        if value["invocation_id"]!=invocation_id:
            raise ValueError("Fleet leader binding invocation mismatch")
        return copy.deepcopy(value)

    def _uncertain(self, state, project):
        return any(op["binding"]["watchdog_id"] == project["watchdog_id"]
                   and (op["status"] in {"claimed", "unknown"}
                        or (op["status"] == "succeeded" and op["effect"] == "run" and not op["invocation_terminal"]))
                   for op in state["operations"].values())

    def _needs_continuation(self, state, project, assessment):
        if self._uncertain(state, project):
            return True
        if assessment["overall"] in {"PAUSED", "COMPLETE"}:
            return False
        unfinished = any(
            project_of(recovery["binding"]) == project
            and any(state["operations"].get(operation_key(recovery["binding"], step), {}).get("status") != "succeeded"
                    for step in recovery["steps"])
            for recovery in state["recoveries"].values()
        )
        return unfinished or assessment["overall"] in {"CRITICAL", "UNKNOWN", "STALLED"}

    def _finish(self, key, operation_id, status, detail, receipt=None):
        def transform(state):
            op = state["operations"].get(key)
            if not op or op["operation_id"] != operation_id or op["status"] != "claimed":
                return False
            op.update(status=status, detail=detail, finished_at_utc=self.clock())
            if receipt is not None:
                op.update(receipt)
            return True
        return self._change(transform)

    def _reconcile_invocation_terminal(self, project, observed):
        invocation = observed["signals"]["invocation"]
        age = (utc(self.clock()) - utc(invocation["observed_at_utc"])).total_seconds()
        if invocation["state"] != "completed" or not 0 <= age <= self.max_age_seconds:
            return
        def transform(state):
            changed = False
            for op in state["operations"].values():
                if (op["status"] == "succeeded" and op["effect"] == "run"
                        and project_of(op["binding"]) == project and not op["invocation_terminal"]
                        and op["provider_invocation_id"] == invocation["invocation_id"]):
                    op.update(invocation_terminal=True, terminal_observed_at_utc=invocation["observed_at_utc"])
                    changed = True
            return changed
        self._change(transform)

    def _recover(self, project, initial, remaining, invocation_id, batch_budget, batch_leader):
        binding = initial["binding"]
        recovery_key = binding_key(binding)
        value, assessment = self._observe(project, binding)
        self._reconcile_invocation_terminal(project, value)
        _, current = self._read()
        if self._uncertain(current, project):
            return 0, "unreconciled_operation"
        if not assessment["safe_to_recover"]:
            return 0, "fresh_gate_denied"
        recovery = current["recoveries"].get(recovery_key)
        if recovery is None:
            if not assessment["recovery_eligible"]:
                return 0, "no_recovery_needed"
            recovery = {"binding": binding, "schedule": value["signals"]["scheduler"]["schedule"],
                        "prompt": value["signals"]["scheduler"]["prompt"],
                        "expected_invocation": {key: value["signals"]["invocation"].get(key) for key in ["state", "invocation_id"]},
                        "steps": ["enable", "run"] if value["signals"]["scheduler"]["state"] == "disabled" else ["run"]}
            def plan(state):
                if recovery_key not in state["recoveries"]:
                    state["recoveries"][recovery_key] = recovery
                return True
            self._change(plan)
            _, current = self._read()
            recovery = current["recoveries"][recovery_key]
        attempted = 0
        for effect in recovery["steps"]:
            key = operation_key(binding, effect)
            _, state = self._read()
            previous = state["operations"].get(key)
            if previous:
                if previous["status"] == "succeeded":
                    continue
                return attempted, "operation_already_consumed"
            if attempted >= remaining or not self._time_available(batch_budget):
                return attempted, "batch_budget_exhausted"
            value, assessment = self._observe(project, binding)
            if not self._effect_gate(value, assessment, recovery, effect):
                return attempted, "fresh_gate_denied"
            if batch_leader is None or self._leader_binding(invocation_id)!=batch_leader:
                return attempted, "fleet_head_or_leader_changed"
            if self.leader_guard is None or not hasattr(self.leader_guard,"claim_scheduler_effect"):
                raise ValueError("Fleet leader guard lacks scheduler effect journal")
            outer=self.leader_guard.claim_scheduler_effect(
                invocation_id,project,effect,recovery,value["signals"]["policy"]["revision"])
            if outer["action"]!="SUBMIT_ONCE":
                return attempted, "fleet_effect_already_claimed"
            if outer["leader"]!=batch_leader:
                try:
                    self.leader_guard.finish_scheduler_effect(
                        invocation_id,outer["effect"]["effect_id"],"terminal","control:leader-binding-changed","not_submitted")
                except Exception:
                    pass
                return attempted, "fleet_head_or_leader_changed"
            leader_binding=copy.deepcopy(batch_leader)
            fleet_effect_id=outer["effect"]["effect_id"]
            operation_id = "operation-" + secrets.token_hex(24)
            def claim(state):
                if key in state["operations"] or self._uncertain(state, project):
                    return False
                reserved = sum(op["controller_invocation_id"] == invocation_id for op in state["operations"].values())
                if reserved >= state["wake_budgets"][invocation_id]["max_effects"]:
                    return False
                state["operations"][key] = {
                    "binding": binding, "effect": effect, "status": "claimed", "operation_id": operation_id,
                    "controller_invocation_id": invocation_id, "claimed_at_utc": self.clock(),
                    "policy_revision": value["signals"]["policy"]["revision"],
                    "leader": copy.deepcopy(leader_binding),
                    "fleet_effect_id": fleet_effect_id,
                }
                return True
            if not self._change(claim):
                try:
                    self.leader_guard.finish_scheduler_effect(
                        invocation_id,fleet_effect_id,"terminal","control:internal-claim-denied","not_submitted")
                except Exception:
                    pass
                return attempted, "claim_not_granted"
            # Pause, policy, owner, guard, external, exact invocation, and provider
            # budget are reread AFTER the durable claim and immediately before IO.
            try:
                live, gate = self._observe(project, binding)
                current_leader=self._leader_binding(invocation_id)
                allowed = (current_leader==leader_binding and self._effect_gate(live, gate, recovery, effect)
                           and self._time_available(batch_budget))
            except Exception:
                allowed = False
            if not allowed:
                try:
                    self.leader_guard.finish_scheduler_effect(
                        invocation_id,fleet_effect_id,"terminal","control:post-claim-gate-denied","not_submitted")
                except Exception:
                    pass
                self._finish(key, operation_id, "blocked", "post_claim_gate_denied")
                return attempted, "post_claim_gate_denied"
            attempted += 1
            # Charge before IO. Even failure to persist a completion receipt must
            # not reset this wake's effect budget for the next registered project.
            batch_budget["attempted"] += 1
            try:
                if effect == "enable":
                    reply = self.backend.enable(copy.deepcopy(project), binding=copy.deepcopy(binding),
                                                operation_id=operation_id, expected_schedule=recovery["schedule"],
                                                expected_prompt=recovery["prompt"])
                else:
                    reply = self.backend.run(copy.deepcopy(project), binding=copy.deepcopy(binding), operation_id=operation_id)
                readback, readback_assessment = self._observe(project, binding)
                scheduler = readback["signals"]["scheduler"]
                valid = (isinstance(reply, dict) and reply.get("status") == "accepted" and reply.get("binding") == binding
                         and not any(reason.startswith("stale_or_future:") for reason in readback_assessment["reasons"])
                         and scheduler["state"] in {"enabled", "overdue"}
                         and scheduler["schedule"] == recovery["schedule"] and scheduler["prompt"] == recovery["prompt"])
                if effect == "run":
                    invocation = readback["signals"]["invocation"]
                    valid = (valid and isinstance(reply.get("invocation_id"), str) and bool(reply["invocation_id"])
                             and reply["invocation_id"] != live["signals"]["invocation"].get("invocation_id")
                             and invocation["invocation_id"] == reply["invocation_id"] and invocation["state"] in {"running", "completed"})
                if not valid:
                    raise ValueError("scheduler exact readback disagrees")
            except Exception:
                try:
                    self.leader_guard.finish_scheduler_effect(
                        invocation_id,fleet_effect_id,"unknown","scheduler-attempt:"+operation_id)
                except Exception:
                    pass
                self._finish(key, operation_id, "unknown", "provider_reply_or_exact_readback_unconfirmed")
                return attempted, "provider_outcome_unknown"
            receipt = ({"provider_invocation_id": reply["invocation_id"],
                        "invocation_terminal": readback["signals"]["invocation"]["state"] == "completed"}
                       if effect == "run" else None)
            outer_receipt=("provider-invocation:"+reply["invocation_id"] if effect=="run"
                           else "scheduler-operation:"+operation_id)
            try:
                self.leader_guard.finish_scheduler_effect(
                    invocation_id,fleet_effect_id,"terminal",outer_receipt,"success")
            except Exception:
                self._finish(key, operation_id, "unknown", "fleet_effect_completion_unconfirmed")
                return attempted, "provider_outcome_unknown"
            if not self._finish(key, operation_id, "succeeded", "exact_readback_confirmed", receipt):
                return attempted, "claim_completion_unconfirmed"
        return attempted, "recovery_steps_consumed"

    def _effect_gate(self, probe, assessment, recovery, effect):
        scheduler = probe["signals"]["scheduler"]
        return (assessment["safe_to_recover"] and scheduler["schedule"] == recovery["schedule"]
                and scheduler["prompt"] == recovery["prompt"]
                and {key: probe["signals"]["invocation"].get(key) for key in ["state", "invocation_id"]} == recovery["expected_invocation"]
                and scheduler["state"] in ({"disabled"} if effect == "enable" else {"enabled", "overdue"}))

    def _time_available(self, batch_budget):
        deadline = batch_budget["deadline_utc"]
        return deadline is None or utc(self.clock()) < utc(deadline)

    def run_batch(self, projects, *, max_effects, invocation_id, deadline_utc=None):
        text(invocation_id, "invocation_id")
        if deadline_utc is not None:
            utc(deadline_utc)
        if type(max_effects) is not int or not 0 <= max_effects <= 2000:
            raise ValueError("batch effect budget must be an integer from 0 to 2000")
        if not isinstance(projects, list) or not 0 < len(projects) <= MAX_PROJECTS:
            raise ValueError("registry must contain 1 to 1000 projects")
        batch_leader=self._leader_binding(invocation_id) if max_effects>0 else None
        projects = copy.deepcopy(projects)
        for project in projects:
            validate_binding(project, incident=False)
            if portable_path_key(project["source_ref"]) == portable_path_key(self.store.ref):
                raise ValueError("coordination ref must be isolated from registered project refs")
        keys = [binding_key(project) for project in projects]
        if len(set(keys)) != len(keys):
            raise ValueError("registry has duplicate project bindings")
        if len({project["watchdog_id"] for project in projects}) != len(projects):
            raise ValueError("registry must bind each watchdog to exactly one project/ref")
        survivability = None
        survivability_effects = 0
        if self.survivability_runtime is not None:
            try:
                if max_effects>0 and self._leader_binding(invocation_id)!=batch_leader:
                    raise ValueError("Fleet head or leader changed before survivability effects")
                survivability = self.survivability_runtime.reconcile_registered(
                    max_effects=max_effects, invocation_id=invocation_id, leader_binding=batch_leader)
                if (not isinstance(survivability, dict)
                        or type(survivability.get("effects_attempted")) is not int
                        or not 0 <= survivability["effects_attempted"] <= max_effects
                        or type(survivability.get("continuation_required")) is not bool):
                    raise ValueError("watchdog survivability batch contract invalid")
                survivability_effects = survivability["effects_attempted"]
            except Exception as exc:
                survivability = {
                    "schema": "watchdog-survivability-batch/v1",
                    "effects_attempted": 0,
                    "continuation_required": True,
                    "outcome": "coordination_or_observation_unavailable",
                    "error_class": type(exc).__name__,
                }

        # Assess every registered project even when the side-effect budget is zero.
        assessments, observations = {}, {}
        for key, project in zip(keys, projects):
            try:
                value, result = self._observe(project)
                observations[key] = value
                assessments[key] = result
            except Exception:
                assessments[key] = {"schema": "watchdog-liveness-assessment/v1", "binding": project,
                                    "overall": "UNKNOWN", "recovery_eligible": False,
                                    "reasons": ["observation_unavailable"], "authorizes_scheduler_mutation": False}
        def checkpoint(state):
            wake_budget = {"max_effects": max_effects, "deadline_utc": deadline_utc}
            if invocation_id in state["wake_budgets"] and state["wake_budgets"][invocation_id] != wake_budget:
                raise ValueError("cannot change an invocation's durable wake budget")
            state["wake_budgets"][invocation_id] = wake_budget
            state["assessments"].update(assessments)
            pending = set(state["pending"])
            for key, project in zip(keys, projects):
                result = assessments[key]
                if self._needs_continuation(state, project, result):
                    pending.add(key)
                else:
                    pending.discard(key)
            state["pending"] = sorted(pending)
            state["last_batch"] = {"invocation_id": invocation_id, "max_effects": max_effects,
                                   "assessed_projects": keys, "checkpoint_at_utc": self.clock(),
                                   "leader": copy.deepcopy(batch_leader)}
            return True
        self._change(checkpoint)
        batch_budget, outcomes = {"attempted": survivability_effects, "deadline_utc": deadline_utc}, {}
        for key, project in zip(keys, projects):
            if key not in observations:
                outcomes[key] = "observation_unavailable"
                continue
            if batch_budget["attempted"] >= max_effects or not self._time_available(batch_budget):
                outcomes[key] = "batch_budget_exhausted"
                continue
            try:
                _, outcome = self._recover(project, observations[key], max_effects - batch_budget["attempted"], invocation_id, batch_budget, batch_leader)
                outcomes[key] = outcome
            except Exception:
                # A claim may already be durable. Preserve it and report uncertainty.
                outcomes[key] = "coordination_or_observation_unavailable"
            try:
                _, latest = self._observe(project)
                def settle(state):
                    if not self._needs_continuation(state, project, latest):
                        state["pending"] = [item for item in state["pending"] if item != key]
                    elif key not in state["pending"]:
                        state["pending"].append(key)
                    return True
                self._change(settle)
            except Exception:
                pass  # Existing checkpoint remains the durable continuation.
        _, state = self._read()
        return {"schema": "fleet-watchdog-batch/v1", "assessments": [assessments[key] for key in keys],
                "outcomes": outcomes, "effects_attempted": batch_budget["attempted"], "pending": state["pending"],
                "survivability": survivability,
                "continuation_required": bool(state["pending"])
                or bool(survivability and survivability.get("continuation_required"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Fleet config JSON with store, projects, invocation_id, max_effects")
    parser.add_argument("--backend", required=True, help="explicit installed Python module:factory supplying real capabilities")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.config).read_text(encoding="utf-8")
        if len(raw) > 1048576:
            raise ValueError("Fleet config exceeds 1 MiB")
        config = json.loads(raw)
        module, separator, factory = args.backend.partition(":")
        if not separator or not module or not factory:
            raise ValueError("backend must be an explicit module:factory")
        backend = getattr(importlib.import_module(module), factory)(config.get("backend_config", {}))
        store = GitDocumentStore(**config["store"])
        leader_guard=None
        if config["max_effects"]>0:
            leader_store=GitDocumentStore(**config["leader_store"])
            leader=copy.deepcopy(config["leader"])
            leader_guard=GitFleetLeaderGuard(leader_store,clock=now_utc,**leader)
        result = FleetRuntime(store, backend, leader_guard=leader_guard).run_batch(
            config["projects"], max_effects=config["max_effects"], invocation_id=config["invocation_id"],
            deadline_utc=config.get("deadline_utc"))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError, AttributeError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
