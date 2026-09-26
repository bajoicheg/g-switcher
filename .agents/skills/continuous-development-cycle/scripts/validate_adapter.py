#!/usr/bin/env python3
"""Validate actual YAML values, compatibility and policy contradictions."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid
from contracts import (ContractError, check, digest, load_yaml, nonempty,
                       nullable_text, positive, semver, utc)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_SCHEMA = "continuous-development-cycle/v3"
TRUE, FALSE = (True,), (False,)
RUNTIME = {"subagents": ("enabled", "disabled"), "additional_subagent_approval_required": bool}
EXCEPTION_SETTINGS = {"execution.work.subagents", "execution.codex_orchestrator.subagents",
                      "execution.work.additional_subagent_approval_required",
                      "execution.codex_orchestrator.additional_subagent_approval_required",
                      "compute.preference"}
SCHEMA = {
    "schema": (ADAPTER_SCHEMA,),
    "policy": {
        "revision": nonempty, "skill_min_version": nonempty,
        "skill_max_version_exclusive": nonempty,
        "approved_exceptions": [{"setting": nonempty,
            "value": lambda v: type(v) in (str, bool), "source": nonempty,
            "reason": nonempty, "recorded_at_utc": utc}],
    },
    "repository": {"name": nonempty, "remote": nonempty, "identity_must_match_before_push": TRUE,
        "branch_policy": ("checkpoint_or_discover",), "pr_policy": ("active_or_discover",)},
    "planning": {"active_change_policy": ("exactly_one",), "specification_root": str,
                 "strict_validation_command": str},
    "checkpoint": {"path": nonempty, "schema": ("development-work-status/v3", "development-work-status/v4")},
    "validation": {"quick": str, "full": str, "release": str, "final_platform": nonempty,
        "final_remote_required": bool, "evidence_schema": ("command-evidence/v1",),
        "check_plan": str},
    "compute": {"preference": ("codex_first", "local_first"), "fallback_order": [nonempty],
        "codex_backend": {"enabled": bool, "configure_when_authorized": bool,
            "configuration_status": ("unconfigured", "ready", "setup_failed", "unavailable", "ineligible"),
            "environment_id": nullable_text, "environment_url": nullable_text,
            "linked_github_user": nullable_text, "channel": nonempty, "runbook": nonempty,
            "mode": ("COMPUTE_ONLY",), "exact_sha_required": TRUE,
            "clean_before_after_required": TRUE, "eligible": [nonempty], "ineligible": [nonempty]}},
    "operations": {"intent_schema": ("operation-intent/v1",), "store": nonempty,
        "persist_before_submit": TRUE, "reconcile_before_resubmit": TRUE,
        "unknown_outcome_blocks_resubmit": TRUE},
    "ci": {"provider": nonempty, "workflow": str, "required_final_green": bool,
        "actions_budget": ("normal", "conserve", "exhausted"),
        "actions_budget_restore_requires_explicit_confirmation": TRUE,
        "max_full_runs_per_task_when_conserve": positive,
        "exhausted_forbids_launch_rerun_retry_dispatch_probe": TRUE,
        "skip_ci_marker": nonempty, "skip_ci_allowed_for": [nonempty], "skip_ci_forbidden_for": [nonempty]},
    "execution": {"orchestrator_owns_task_closure": TRUE,
        "ordinary_chat": {"subagents": ("disabled",)}, "work": RUNTIME,
        "codex_orchestrator": RUNTIME, "unknown_runtime": {"subagents": ("disabled",)},
        "subagents": {"delegate_when_useful": bool, "effort_policy": ("adaptive",),
            "selection_rule": ("minimum_sufficient_for_task",), "maximum_effort_is_default": FALSE,
            "writer_isolation_required": TRUE, "parallel_read_only_allowed": bool},
        "lease": {"default_ttl_minutes": positive, "heartbeat_fresh_minutes": positive,
            "renew_requires_observable_owner_activity": TRUE, "external_wait_state": ("waiting_external",),
            "external_inflight_is_concurrency_guard": TRUE, "terminal_external_event_renews_owner": FALSE,
            "terminal_external_takeover_without_fresh_heartbeat": bool, "explicit_release_on_handoff": TRUE,
            "legacy_long_lease": ("normalize_at_next_safe_checkpoint",)}},
    "progress": {"interactive_updates": bool, "update_on_phase_change": bool,
        "update_on_evidence": bool, "update_on_blocker": bool, "update_on_backend_switch": bool,
        "anti_silence_minutes": positive, "do_not_stream_trivial_tool_calls": bool},
    "watchdog": {"enabled": bool, "cadence": nonempty, "idle_guard_minutes": positive,
        "explicit_kick_bypasses_idle_guard_only": TRUE, "inherits_runtime_subagent_policy": TRUE,
        "concurrency_guard_always": TRUE},
    "release": {"enabled": bool, "candidate_sha_required": TRUE, "version_consistency_required": TRUE,
        "artifact_sha_binding_required": TRUE, "package_smoke_required": bool, "checksum_required": bool,
        "tag_or_release_evidence_required": bool, "parallel_release_trains": bool},
    "migration": {name: TRUE for name in ("verify_repository_identity_on_resume", "verify_default_branch",
        "verify_pr_refs", "verify_workflow_runner_state", "verify_release_state", "update_checkpoint_remote_identity")},
    "safety": {"never_force_push": TRUE, "destructive_actions_require_explicit_confirmation": TRUE,
               "stop_on_unreconciled_external_branch_movement": TRUE},
}


def validate_orchestration(value, actions_budget):
    """Additive v2.3 controls; older v3 adapters remain readable unchanged."""
    check(value, {
        "execution_lease": {"backend": ("git", "single_writer"), "remote": nullable_text,
            "coordination_ref": nullable_text, "designated_executor_id": nullable_text,
            "assignment_ref": nullable_text},
        "wait": dict, "recovery": {"max_snapshot_age_seconds": positive}, "budget": dict,
    }, "adapter.orchestration")
    lease = value["execution_lease"]
    if lease["backend"] == "git":
        ref = lease["coordination_ref"]
        if not lease["remote"] or not ref or not ref.startswith("refs/heads/"):
            raise ContractError("git lease requires remote and full coordination branch ref")
        if lease["designated_executor_id"] is not None or lease["assignment_ref"] is not None:
            raise ContractError("git lease must not mix single-writer assignment fields")
        try:
            valid = subprocess.run(["git", "check-ref-format", ref], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContractError("cannot validate coordination Git ref") from exc
        if valid.returncode:
            raise ContractError("invalid coordination Git ref")
    else:
        if lease["remote"] is not None or lease["coordination_ref"] is not None:
            raise ContractError("single-writer mode must not mix Git lease configuration")
        owner, source = lease["designated_executor_id"], lease["assignment_ref"]
        if (owner is None) != (source is None):
            raise ContractError("single-writer assignment requires both executor UUID and source reference")
        if owner is not None:
            try:
                if str(uuid.UUID(owner)) != owner:
                    raise ValueError("non-canonical UUID")
            except ValueError as exc:
                raise ContractError("designated executor must be a canonical UUID") from exc
    from recovery import validate_wait_policy
    from budget import validate_policy
    try:
        validate_wait_policy(value["wait"])
        validate_policy(value["budget"])
    except ValueError as exc:
        raise ContractError(f"orchestration control policy: {exc}") from exc
    if value["budget"]["actions_budget"] != actions_budget:
        raise ContractError("orchestration budget must match ci.actions_budget; reconcile policy drift")


def validate_v25_controls(data, require_cost=False, require_visibility=False):
    routing_schema = {
        "capability_registry_ref": nonempty,
        "request_schema": ("capability-request/v1",),
        "backend_kind_preference": [nonempty],
        "require_fresh_registry": TRUE,
        "no_match_state": ("waiting_external",),
        "router_authority": ("recommendation_only",),
        "max_registry_age_seconds": positive,
    }
    cost_fields = {
        "cost_policy_ref": nonempty,
        "cost_router_authority": ("recommendation_only",),
        "github_actions_requires_reason": TRUE,
        "transient_primary_failure_policy": ("recover_or_wait",),
    }
    if require_cost or any(name in data["routing"] for name in cost_fields):
        routing_schema.update(cost_fields)
    if require_visibility or "repository_visibility" in data["routing"]:
        routing_schema["repository_visibility"] = ("public","private","internal")
    check(data["routing"], routing_schema, "adapter.routing")
    kinds = data["routing"]["backend_kind_preference"]
    allowed = {"codex_compute", "local", "other_compute", "github_actions"}
    if not kinds or len(set(kinds)) != len(kinds) or not set(kinds) <= allowed:
        raise ContractError("routing backend_kind_preference is invalid or duplicated")
    check(data["recovery_recipes"], {
        "catalog_ref": nonempty,
        "diagnosis_schema": ("recovery-diagnosis/v1",),
        "deterministic_selection": TRUE,
        "recipe_authority": ("recommendation_only",),
    }, "adapter.recovery_recipes")
    check(data["continuation"], {
        "queue_ref": nonempty,
        "event_schema": ("continuation-event/v1",),
        "event_wake_is_authority": FALSE,
        "scheduler_fallback_required": TRUE,
        "dedupe_required": TRUE,
        "claim_ttl_seconds": positive,
    }, "adapter.continuation")

def validate_v26_controls(data):
    check(data["fleet"], {
        "snapshot_ref": nonempty,
        "snapshot_schema": ("fleet-project-snapshot/v1",),
        "supervisor_authority": ("control_plane_only",),
        "product_write_authority": FALSE,
        "takeover_authority": FALSE,
        "external_start_authority": FALSE,
        "merge_authority": FALSE,
        "assessment_max_age_seconds": positive,
    }, "adapter.fleet")
    check(data["convergence"], {
        "target_version": nonempty,
        "target_package_fingerprint_ref": nonempty,
        "exact_package_fingerprint_required": TRUE,
        "safe_boundary_required": TRUE,
    }, "adapter.convergence")
    target = semver(data["convergence"]["target_version"])
    lower = semver(data["policy"]["skill_min_version"])
    upper = semver(data["policy"]["skill_max_version_exclusive"])
    if not lower <= target < upper:
        raise ContractError("convergence target_version must fit policy version range")
    check(data["progress_slo"], {
        "policy_ref": nonempty,
        "degraded_after_seconds": positive,
        "stalled_after_seconds": positive,
        "primitive_activity_is_progress": FALSE,
        "blocked_pauses_clock": TRUE,
        "waiting_external_pauses_clock": TRUE,
    }, "adapter.progress_slo")
    if data["progress_slo"]["stalled_after_seconds"] <= data["progress_slo"]["degraded_after_seconds"]:
        raise ContractError("progress SLO stalled threshold must exceed degraded threshold")
    check(data["audit"], {
        "log_ref": nonempty,
        "schema": ("control-plane-audit-log/v1",),
        "append_only": TRUE,
        "hash_chain_required": TRUE,
    }, "adapter.audit")

def validate_v28_controls(data):
    check(data["autonomy"], {
        "terminal_state_schema": ("terminal-state/v2",),
        "no_idle_invariant": TRUE,
        "execution_channel_supervisor": TRUE,
        "max_channel_failovers": positive,
        "concurrent_writer_reconciliation": TRUE,
        "force_push_on_reconcile": FALSE,
    }, "adapter.autonomy")
    check(data["publication"], {
        "inventory_schema": ("publication-inventory/v1",),
        "sensitive_context_policy_ref": nonempty,
        "scan_all_refs_required": TRUE,
        "scan_conversations_required": TRUE,
        "scan_artifacts_required": TRUE,
        "control_plane_externalized": TRUE,
        "direct_visibility_toggle_requires_guard_green": TRUE,
        "sanitized_export_on_findings": TRUE,
    }, "adapter.publication")

def validate_v281_controls(data):
    check(data["hardening"], {
        "watchdog_repair_schema": ("watchdog-repair-state/v1",),
        "watchdog_self_repair": TRUE,
        "ref_inventory_schema": ("ref-inventory/v1",),
        "ref_hygiene_authority": ("plan_only",),
        "coordination_retention_schema": ("coordination-retention/v1",),
        "coordination_retention_authority": ("plan_only",),
        "blocker_proof_schema": ("blocked-state-proof/v1",),
        "blocker_proof_required": TRUE,
        "decision_request_schema": ("decision-request/v1",),
        "decision_authority_must_preexist": TRUE,
        "evidence_stream_schema": ("evidence-stream/v1",),
        "canonical_evidence_schema": ("canonical-evidence/v1",),
        "compact_evidence_required": TRUE,
        "progress_enforcement_schema": ("progress-enforcement/v1",),
        "stalled_requires_recovery_action": TRUE,
    }, "adapter.hardening")

def validate_v282_controls(data):
    check(data["maturity"], {
        "fleet_control_schema": ("fleet-control-input/v1",),
        "project_independent_fleet_control": TRUE,
        "stuck_state_schema": ("stuck-state-input/v1",),
        "stuck_requires_strategy_change": TRUE,
        "counterfactual_recovery_schema": ("counterfactual-recovery/v1",),
        "repeat_failed_strategy_forbidden": TRUE,
        "public_export_schema": ("public-export-request/v1",),
        "new_public_history_required": TRUE,
        "dogfood_schema": ("cdc-dogfood-input/v1",),
        "dogfood_is_authority": FALSE,
    }, "adapter.maturity")

def validate_adapter(data, skill_version=None):
    if isinstance(data, dict) and data.get("schema") in (
            "continuous-development-cycle/v1", "continuous-development-cycle/v2"):
        raise ContractError("legacy adapter: migrate explicitly using references/policy-compatibility.md; "
                            "preserve restrictions and in-flight operations")
    schema = dict(SCHEMA)
    if isinstance(data, dict) and "orchestration" in data:
        schema["orchestration"] = dict
    for name in ("routing", "recovery_recipes", "continuation", "fleet", "convergence", "progress_slo", "audit", "autonomy", "publication", "hardening", "maturity"):
        if isinstance(data, dict) and name in data:
            schema[name] = dict
    check(data, schema)
    policy = data["policy"]
    version = semver(skill_version or (ROOT / "VERSION").read_text().strip())
    lower, upper = semver(policy["skill_min_version"]), semver(policy["skill_max_version_exclusive"])
    if not lower <= version < upper:
        raise ContractError("policy skill version range is incompatible with installed skill")
    if lower < (2, 2, 0):
        raise ContractError("adapter v3 requires skill_min_version >= 2.2.0")
    if data["checkpoint"]["schema"] == "development-work-status/v4" and lower < (2, 4, 0):
        raise ContractError("checkpoint v4 requires skill_min_version >= 2.4.0")
    if lower >= (2, 4, 0) and data["checkpoint"]["schema"] != "development-work-status/v4":
        raise ContractError("CDC 2.4+ policy must use checkpoint v4")
    v25_names = ("routing", "recovery_recipes", "continuation")
    v25_present = [name in data for name in v25_names]
    if any(v25_present) and lower < (2, 5, 0):
        raise ContractError("CDC 2.5 controls require skill_min_version >= 2.5.0")
    if lower >= (2, 5, 0) and not all(v25_present):
        raise ContractError("CDC 2.5+ policy requires routing, recovery_recipes and continuation")
    if all(v25_present):
        validate_v25_controls(data, require_cost=lower >= (2, 7, 2), require_visibility=lower >= (2, 7, 3))
    v26_names = ("fleet", "convergence", "progress_slo", "audit")
    v26_present = [name in data for name in v26_names]
    if any(v26_present) and lower < (2, 6, 0):
        raise ContractError("CDC 2.6 controls require skill_min_version >= 2.6.0")
    if lower >= (2, 6, 0) and not all(v26_present):
        raise ContractError("CDC 2.6+ policy requires fleet, convergence, progress_slo and audit")
    if all(v26_present):
        validate_v26_controls(data)
    v28_names = ("autonomy", "publication")
    v28_present = [name in data for name in v28_names]
    if any(v28_present) and lower < (2, 8, 0):
        raise ContractError("CDC 2.8 controls require skill_min_version >= 2.8.0")
    if lower >= (2, 8, 0) and not all(v28_present):
        raise ContractError("CDC 2.8+ policy requires autonomy and publication controls")
    if all(v28_present):
        validate_v28_controls(data)
    if "hardening" in data and lower < (2, 8, 1):
        raise ContractError("CDC 2.8.1 hardening controls require skill_min_version >= 2.8.1")
    if lower >= (2, 8, 1) and "hardening" not in data:
        raise ContractError("CDC 2.8.1+ policy requires hardening controls")
    if "hardening" in data:
        validate_v281_controls(data)
    if "maturity" in data and lower < (2, 8, 2):
        raise ContractError("CDC 2.8.2 maturity controls require skill_min_version >= 2.8.2")
    if lower >= (2, 8, 2) and "maturity" not in data:
        raise ContractError("CDC 2.8.2+ policy requires maturity controls")
    if "maturity" in data:
        validate_v282_controls(data)
    if "orchestration" in data:
        if lower < (2, 3, 0):
            raise ContractError("orchestration controls require skill_min_version >= 2.3.0")
        validate_orchestration(data["orchestration"], data["ci"]["actions_budget"])
        if data["execution"]["lease"]["terminal_external_takeover_without_fresh_heartbeat"]:
            raise ContractError("orchestration forbids timer-only takeover; require release or verified quiescence")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", data["repository"]["remote"]):
        raise ContractError("repository.remote must be canonical owner/repository")
    seen = set()
    for entry in policy["approved_exceptions"]:
        setting = entry["setting"]
        if setting not in EXCEPTION_SETTINGS or setting in seen:
            raise ContractError(f"unsupported or duplicate exception setting: {setting}")
        seen.add(setting)
        current = data
        for segment in setting.split("."):
            current = current[segment]
        if type(current) is not type(entry["value"]) or current != entry["value"]:
            raise ContractError(f"approved exception disagrees with effective setting: {setting}")
    if data["compute"]["preference"] != "codex_first" and "compute.preference" not in seen:
        raise ContractError("non-default compute preference requires a sourced approved exception")
    backend = data["compute"]["codex_backend"]
    if backend["enabled"] and (backend["configuration_status"] != "ready" or not all(
            backend[field] for field in ("environment_id", "environment_url", "linked_github_user"))):
        raise ContractError("enabled compute requires ready status and verified environment/user binding")
    if backend["configuration_status"] == "ready" and not backend["enabled"]:
        raise ContractError("ready compute must be enabled; use unavailable/ineligible for disabled setup")
    fallback = data["compute"]["fallback_order"]
    if not fallback or len(set(fallback)) != len(fallback) or not set(fallback) <= {
            "correct_local_runtime", "other_approved_compute", "hosted_platform_ci"}:
        raise ContractError("invalid/duplicate fallback_order entries")
    if set(backend["eligible"]) & set(backend["ineligible"]):
        raise ContractError("compute eligible/ineligible overlap")
    if set(data["ci"]["skip_ci_allowed_for"]) & set(data["ci"]["skip_ci_forbidden_for"]):
        raise ContractError("CI skip policy is contradictory")
    lease = data["execution"]["lease"]
    if lease["heartbeat_fresh_minutes"] > lease["default_ttl_minutes"]:
        raise ContractError("heartbeat freshness must not exceed lease TTL")
    return {"schema": ADAPTER_SCHEMA, "policy_revision": policy["revision"], "policy_digest": digest(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter")
    parser.add_argument("--json", action="store_true", help="print compatibility and semantic policy digest")
    args = parser.parse_args()
    try:
        result = validate_adapter(load_yaml(args.adapter))
    except (ContractError, OSError, UnicodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps(result, sort_keys=True) if args.json else "PASS: adapter v3 types, compatibility and policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
