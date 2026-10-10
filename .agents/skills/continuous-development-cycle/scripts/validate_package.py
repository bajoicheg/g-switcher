#!/usr/bin/env python3
"""Check installed package integrity and validate templates with their actual parsers."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import re
import sys

sys.dont_write_bytecode = True
from contracts import ContractError, load_yaml, semver
from codex_cloud_development import validate_development_request
from validate_adapter import ADAPTER_SCHEMA, validate_adapter
from validate_checkpoint import validate_checkpoint
from validate_checkpoint_24 import validate_checkpoint_24
from run_checks import load_plan
from operation_intent import validate_intent
from execution_lease import validate as validate_lease
from execution_lease_v2 import validate as validate_lease_v2
from execution_continuity import evaluate as evaluate_continuity
from resume_capsule import validate as validate_resume_capsule
from budget import validate_ledger
from recovery import validate_wait_state, decide_recovery
from watchdog_health import assess as assess_watchdog_health
from watchdog_liveness import validate_probe as validate_liveness_probe
from capability_router import validate_registry, validate_request, route as route_backend
from cost_router import validate_policy as validate_cost_policy, validate_context as validate_cost_context, route as route_cost
from recovery_recipes import validate_catalog, validate_diagnosis, select as select_recovery_recipe
from continuation_queue import validate_event, validate_queue, ingest as ingest_continuation
from progress_slo import validate_policy as validate_slo_policy, validate_observation as validate_progress_observation, classify as classify_progress
from version_convergence import validate_target as validate_convergence_target, validate_snapshot as validate_convergence_snapshot, assess as assess_convergence
from control_plane_audit import validate as validate_audit_log, append as append_audit
from fleet_supervisor import validate_registry as validate_fleet_registry, validate_snapshot as validate_fleet_snapshot, assess_fleet
from consumer_lock import validate as validate_consumer_lock
from terminal_state_v2 import evaluate as evaluate_terminal_state
from execution_channel_supervisor import validate as validate_channel_supervision
from concurrent_writer import reconcile as reconcile_writer
from sensitive_context import validate_policy as validate_sensitive_context_policy
from publication_guard import assess as assess_publication
from watchdog_self_repair import plan as plan_watchdog_repair
from ref_hygiene import assess as assess_ref_hygiene
from coordination_retention import assess as assess_coordination_retention
from blocker_proof import assess as assess_blocker_proof
from decision_authority import classify as classify_decision
from evidence_compactor import compact as compact_evidence
from progress_enforcer import enforce as enforce_progress
from fleet_controller import plan as plan_fleet_control
from stuck_state import detect as detect_stuck
from counterfactual_recovery import choose as choose_counterfactual
from public_export_planner import plan as plan_public_export
from dogfood_metrics import measure as measure_dogfood
from package_transport import validate_manifest as validate_transport_manifest
from convergence_vector import normalize as normalize_convergence_vector
from ci_evidence_classifier import classify as classify_ci_evidence
from policy_migration import plan as plan_policy_migration
from checkpoint_builder import build as build_typed_checkpoint
from migration_transaction import plan as plan_migration_transaction
from provider_reconciliation import reconcile as reconcile_provider_terminal
from continuation_cycle import decide as decide_continuation_cycle
from command_timestamp import render as render_command_timestamp
from rca_feedback import disposition as disposition_rca_feedback
from fleet_improvement import harvest as harvest_fleet_improvement
from behavioral_eval import evaluate_suite as evaluate_behavioral_suite
from verification_gate import evaluate as evaluate_verification_gate
from systematic_rca import analyze as analyze_systematic_rca
from spec_plan_queue import evaluate as evaluate_spec_plan_queue
from review_pipeline import evaluate as evaluate_review_pipeline
from branch_finish import evaluate as evaluate_branch_finish
from parallel_task_planner import plan as plan_parallel_tasks
from worktree_worker_contract import (
    assess as assess_worker_contract, validate_prior_integration_record,
    validate_gate_evidence, validate_gate_result, validate_assembly_evidence,
)
from integration_gate import evaluate as evaluate_integration_gate
from parallel_benchmark import evaluate_from_files as evaluate_parallel_benchmark_files, load_observations as load_parallel_benchmark_observations

from managed_executor_attempt import validate_attempt as validate_managed_executor_attempt, validate_result as validate_managed_executor_result, acceptance as accept_managed_executor_result
from managed_executor_pool import validate_plan as validate_managed_pool_plan, validate_state as validate_managed_pool_state, dispatch as dispatch_managed_pool, assess as assess_managed_pool
from managed_executor_handoff import validate_handoff as validate_managed_handoff, publication_plan as plan_managed_handoff_publication
from execution_liveness import classify as classify_execution_liveness
from final_response_gate import evaluate as evaluate_final_response_gate
from fleet_supervisor_control import validate as validate_fleet_supervisor_control
from consumer_adoption import assess as assess_consumer_adoption

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    'scripts/release_delivery.py', 'tests/test_release_delivery.py',
    'tests/test_release_delivery_git.py', 'tests/test_release_delivery_cli.py',
    'references/release-delivery.md', 'templates/release-delivery.json',
    'scripts/adaptive_allocation.py', 'tests/test_adaptive_allocation.py',
    'references/adaptive-allocation.md', 'templates/adaptive-allocation.json',
    'scripts/project_setup.py', 'tests/test_project_setup.py',
    'references/project-setup.md',
    'scripts/quality_levels.py', 'scripts/evidence_reuse.py',
    'tests/test_quality_levels.py', 'tests/test_evidence_reuse.py',
    'tests/test_review_levels.py', 'tests/test_validation_cycles.py',
    'tests/test_quality_behavior.py', 'tests/test_branch_finish_levels.py', 'tests/test_quality_package.py',
    'references/quality-levels.md', 'templates/quality-assessment.json',
    'templates/review-pipeline-v2.json', 'templates/evidence-reuse.json',
    'templates/verification-gate-v2.json', 'templates/validation-cycle.json',
    'templates/branch-finish-v2.json', 'templates/behavioral-quality-suite.json',
    "scripts/codex_development_bridge.py",
    "tests/test_codex_development_bridge.py",
    "scripts/codex_cloud_development.py",
    "tests/test_codex_cloud_development.py",
    "templates/codex-cloud-development-request.json",
    'SKILL.md',
    'VERSION',
    'manifest.json',
    'agents/openai.yaml',
    'scripts/live_target.py',
    'tests/test_live_target.py',
    'references/live-target-resolution.md',
    'scripts/git_object_integrity.py',
    'tests/test_git_object_integrity.py',
    'scripts/watchdog_liveness.py',
    'scripts/fleet_watchdog_runtime.py',
    'scripts/git_document_store.py',
    'templates/watchdog-liveness-probe.json',
    'tests/test_coordination_transport.py',
    'tests/test_watchdog_liveness.py',
    'tests/test_fleet_watchdog_runtime.py',
    'references/watchdog-liveness-runtime.md',
    'scripts/managed_executor_runtime.py',
    'scripts/managed_terminal_capability.py',
    'tests/test_managed_executor_runtime.py',
    'references/managed-executor-runtime.md',
    'scripts/managed_host_bridge.py',
    'tests/test_managed_host_bridge.py',
    'references/managed-host-bridge.md',
    'references/runtime-routing-and-subagents.md',
    'references/task-lifecycle.md',
    'references/validation-compute-and-ci.md',
    'references/codex-compute.md',
    'references/progress-and-checkpoints.md',
    'references/watchdog-recovery-and-migration.md',
    'references/release-management.md',
    'references/adapter-schema.md',
    'references/policy-compatibility.md',
    'references/command-evidence.md',
    'references/external-operations.md',
    'scripts/requirements.txt',
    'scripts/contracts.py',
    'scripts/validate_adapter.py',
    'scripts/validate_checkpoint.py',
    'scripts/run_checks.py',
    'scripts/validate_evidence.py',
    'scripts/operation_intent.py',
    'templates/development-cycle.yaml',
    'templates/work-status.md',
    'templates/check-plan.json',
    'templates/operation-intent.json',
    'templates/watchdog-prompt.md',
    'templates/AGENTS.snippet.md',
    'tests/pressure-scenarios.md',
    'tests/test_adapter.py',
    'tests/test_checkpoint.py',
    'tests/test_evidence.py',
    'tests/test_operation_intent.py',
    'references/orchestration-controls.md',
    'references/execution-ownership.md',
    'references/bounded-recovery.md',
    'references/budget-ledger.md',
    'scripts/execution_lease.py',
    'scripts/git_lease_store.py',
    'scripts/recovery.py',
    'scripts/budget.py',
    'templates/execution-lease.json',
    'templates/external-wait.json',
    'templates/recovery-snapshot.json',
    'templates/budget-ledger.json',
    'tests/test_execution_lease.py',
    'tests/test_recovery.py',
    'tests/test_budget.py',
    'tests/test_orchestration_policy.py',
    'tests/test_package_metadata.py',
    'scripts/watchdog_health.py',
    'templates/watchdog-health.json',
    'tests/test_watchdog_health.py',
    'references/control-plane-v2.4.md',
    'scripts/execution_lease_v2.py',
    'scripts/execution_continuity.py',
    'scripts/resume_capsule.py',
    'scripts/validate_checkpoint_24.py',
    'templates/execution-lease-v2.json',
    'templates/execution-continuity.json',
    'templates/resume-capsule.json',
    'templates/work-status-v4.md',
    'tests/test_execution_lease_v2.py',
    'tests/test_execution_continuity.py',
    'tests/test_resume_capsule.py',
    'tests/test_checkpoint_v4.py',
    'references/capability-routing.md',
    'references/deterministic-recovery.md',
    'references/event-driven-continuation.md',
    'scripts/capability_router.py',
    'scripts/recovery_recipes.py',
    'scripts/continuation_queue.py',
    'templates/backend-registry.json',
    'templates/capability-request.json',
    'templates/recovery-recipes.json',
    'templates/recovery-diagnosis.json',
    'templates/continuation-event.json',
    'templates/continuation-queue.json',
    'tests/test_capability_router.py',
    'tests/test_recovery_recipes.py',
    'tests/test_continuation_queue.py',
    'references/fleet-supervision.md',
    'references/version-convergence.md',
    'references/progress-slo.md',
    'references/control-plane-audit.md',
    'scripts/fleet_supervisor.py',
    'scripts/version_convergence.py',
    'scripts/progress_slo.py',
    'scripts/control_plane_audit.py',
    'templates/fleet-registry.json',
    'templates/fleet-project-snapshot.json',
    'templates/version-convergence-target.json',
    'templates/version-convergence-snapshot.json',
    'templates/progress-slo-policy.json',
    'templates/progress-observation.json',
    'templates/control-plane-audit-log.json',
    'tests/test_fleet_supervisor.py',
    'tests/test_version_convergence.py',
    'tests/test_progress_slo.py',
    'tests/test_control_plane_audit.py',
    'references/canonical-source-and-release.md',
    'scripts/consumer_lock.py',
    'templates/consumer-lock.json',
    'tests/test_consumer_lock.py',
    'tests/test_git_lease_store_v2.py',
    'references/cost-aware-routing.md',
    'scripts/cost_router.py',
    'templates/cost-routing-policy.json',
    'templates/cost-routing-context.json',
    'tests/test_cost_router.py',
    'references/autonomous-continuity-and-isolation.md',
    'references/publication-safety.md',
    'scripts/terminal_state_v2.py',
    'scripts/execution_channel_supervisor.py',
    'scripts/concurrent_writer.py',
    'scripts/sensitive_context.py',
    'scripts/publication_guard.py',
    'templates/terminal-state-v2.json',
    'templates/channel-supervision.json',
    'templates/writer-reconciliation.json',
    'templates/sensitive-context-policy.json',
    'templates/publication-inventory.json',
    'tests/test_terminal_state_v2.py',
    'tests/test_execution_channel_supervisor.py',
    'tests/test_concurrent_writer.py',
    'tests/test_sensitive_context.py',
    'tests/test_publication_guard.py',
    'references/operational-hardening.md',
    'references/decision-authority.md',
    'scripts/watchdog_self_repair.py',
    'scripts/ref_hygiene.py',
    'scripts/coordination_retention.py',
    'scripts/blocker_proof.py',
    'scripts/decision_authority.py',
    'scripts/evidence_compactor.py',
    'scripts/progress_enforcer.py',
    'templates/watchdog-repair-state.json',
    'templates/ref-inventory.json',
    'templates/coordination-retention.json',
    'templates/blocked-state-proof.json',
    'templates/decision-request.json',
    'templates/evidence-stream.json',
    'templates/progress-enforcement.json',
    'tests/test_watchdog_self_repair.py',
    'tests/test_ref_hygiene.py',
    'tests/test_coordination_retention.py',
    'tests/test_blocker_proof.py',
    'tests/test_decision_authority.py',
    'tests/test_evidence_compactor.py',
    'tests/test_progress_enforcer.py',
    'references/fleet-and-publication-maturity.md',
    'scripts/fleet_controller.py',
    'scripts/stuck_state.py',
    'scripts/counterfactual_recovery.py',
    'scripts/public_export_planner.py',
    'scripts/dogfood_metrics.py',
    'templates/fleet-control-input.json',
    'templates/stuck-state-input.json',
    'templates/counterfactual-recovery.json',
    'templates/public-export-request.json',
    'templates/cdc-dogfood-input.json',
    'tests/test_fleet_controller.py',
    'tests/test_stuck_state.py',
    'tests/test_counterfactual_recovery.py',
    'tests/test_public_export_planner.py',
    'tests/test_dogfood_metrics.py',
    'references/deterministic-distribution-and-convergence.md',
    'scripts/package_transport.py',
    'scripts/convergence_vector.py',
    'scripts/ci_evidence_classifier.py',
    'templates/package-transport.json',
    'templates/convergence-observation.json',
    'templates/ci-execution-observation.json',
    'tests/test_package_transport.py',
    'tests/test_convergence_vector.py',
    'tests/test_ci_evidence_classifier.py',
    'references/transactional-migration-and-provider-reconciliation.md',
    'scripts/policy_migration.py',
    'scripts/checkpoint_builder.py',
    'scripts/migration_transaction.py',
    'scripts/provider_reconciliation.py',
    'templates/policy-migration-request.json',
    'templates/typed-checkpoint-build.json',
    'templates/migration-transaction.json',
    'templates/provider-terminal-observation.json',
    'tests/test_policy_migration.py',
    'tests/test_checkpoint_builder.py',
    'tests/test_migration_transaction.py',
    'tests/test_provider_reconciliation.py',
    'references/continuous-autonomy-and-learning.md',
    'scripts/continuation_cycle.py',
    'scripts/command_timestamp.py',
    'scripts/rca_feedback.py',
    'scripts/fleet_improvement.py',
    'templates/continuation-cycle.json',
    'templates/command-timestamp-request.json',
    'templates/rca-feedback.json',
    'templates/fleet-improvement-harvest.json',
    'tests/test_continuation_cycle.py',
    'tests/test_command_timestamp.py',
    'tests/test_rca_feedback.py',
    'tests/test_fleet_improvement.py',
    'references/behavioral-tdd-and-verification.md',
    'scripts/behavioral_eval.py',
    'scripts/verification_gate.py',
    'scripts/systematic_rca.py',
    'templates/behavioral-eval-suite.json',
    'templates/verification-gate.json',
    'templates/systematic-rca.json',
    'tests/test_behavioral_eval.py',
    'tests/test_verification_gate.py',
    'tests/test_systematic_rca.py',
    'references/specification-review-and-finishing.md',
    'scripts/spec_plan_queue.py',
    'scripts/review_pipeline.py',
    'scripts/branch_finish.py',
    'templates/spec-plan-queue.json',
    'templates/review-pipeline.json',
    'templates/branch-finish.json',
    'tests/test_spec_plan_queue.py',
    'tests/test_review_pipeline.py',
    'tests/test_branch_finish.py',
    'references/worktree-parallelism-and-integration.md',
    'scripts/parallel_task_planner.py',
    'scripts/worktree_worker_contract.py',
    'scripts/integration_gate.py',
    'scripts/parallel_benchmark.py',
    'templates/parallel-task-plan.json',
    'templates/worktree-worker-contract.json',
    'templates/integration-gate.json',
    'templates/parallel-benchmark.json',
    'templates/wave-integration-record.json',
    'templates/wave-integration-gate-evidence.json',
    'templates/wave-integration-gate-result.json',
    'templates/wave-assembly-evidence.json',
    'templates/parallel-benchmark-plan.json',
    'templates/parallel-benchmark-environment.json',
    'templates/parallel-benchmark-observation-sequential.json',
    'templates/parallel-benchmark-observation-parallel.json',
    'tests/test_parallel_task_planner.py',
    'tests/test_worktree_worker_contract.py',
    'tests/test_integration_gate.py',
    'tests/test_parallel_benchmark.py',
    'tests/test_continuity_recovery.py',
    'tests/continuity_fixtures.py',
    'references/managed-executor-pool.md',
    'scripts/managed_executor_attempt.py',
    'scripts/managed_executor_pool.py',
    'scripts/managed_executor_handoff.py',
    'scripts/managed_executor_store.py',
    'templates/managed-executor-attempt.json',
    'templates/managed-executor-result.json',
    'templates/managed-executor-pool-plan.json',
    'templates/managed-executor-pool-state.json',
    'templates/managed-executor-handoff.json',
    'templates/managed-executor-publication-proof.json',
    'templates/managed-executor-handoff-artifact.patch',
    'tests/test_managed_executor_attempt.py',
    'tests/test_managed_executor_pool.py',
    'tests/test_managed_executor_handoff.py',
    'tests/test_managed_executor_store.py',
    'scripts/git_remote_identity.py',
    'tests/test_git_remote_identity.py',
    'scripts/active_package.py',
    'tests/test_active_package.py',
    'scripts/project_lanes.py',
    'scripts/project_lane_runtime.py',
    'scripts/project_lane_git.py',
    'scripts/project_lane_executor.py',
    'scripts/watchdog_survivability.py',
    'scripts/watchdog_survivability_runtime.py',
    'scripts/watchdog_sentinel.py',
    'tests/test_project_lanes.py',
    'tests/test_project_lanes_extended.py',
    'tests/test_project_lane_registry_binding.py',
    'tests/test_project_lane_git.py',
    'tests/test_project_lane_executor.py',
    'tests/test_project_lane_concurrency_demo.py',
    'tests/test_watchdog_survivability.py',
    'tests/test_watchdog_survivability_runtime.py',
    'tests/test_watchdog_sentinel.py',
    'references/cooperative-project-lanes-and-watchdog-survivability.md',
    'scripts/execution_liveness.py',
    'scripts/final_response_gate.py',
    'scripts/fleet_supervisor_control.py',
    'scripts/consumer_adoption.py',
    'templates/runtime-observation.json',
    'templates/final-response-gate.json',
    'templates/fleet-supervisor-state.json',
    'templates/consumer-adoption-publication.json',
    'tests/test_execution_liveness.py',
    'tests/test_final_response_gate.py',
    'tests/test_fleet_supervisor_control.py',
    'tests/test_consumer_adoption.py',
    'references/multi-subscription-coordination-and-ownership.md',
    'tests/test_guidance_contracts.py',
    'tests/test_policy_controls.py',
    'scripts/cdc.py', 'scripts/development_contract.py',
    'scripts/operation_report.py', 'scripts/execution_strategy.py',
    'tests/test_cdc_entrypoint.py', 'tests/test_development_contract.py',
    'tests/test_operation_report.py', 'tests/test_execution_strategy.py',
    'tests/test_lean_package.py', 'references/phase-routing.md',
    'references/lean-execution-core.md', 'references/legacy-core-2.12.1.md',
    'templates/development-assessment.json', 'templates/operation-observation.json',
    'templates/execution-strategy.json',
]


def validate():
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    if missing:
        raise ContractError('missing package files: ' + ', '.join(missing))
    validate_liveness_probe(json.loads((ROOT / 'templates/watchdog-liveness-probe.json').read_text()))
    version = (ROOT / 'VERSION').read_text().strip()
    semver(version)
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    if manifest.get('version') != version or manifest.get('schema') != ADAPTER_SCHEMA or manifest.get('entrypoint') != 'SKILL.md':
        raise ContractError('manifest version/schema/entrypoint mismatch')
    metadata = load_yaml(ROOT / 'agents/openai.yaml')
    if str(metadata.get('version')) != version:
        raise ContractError('agent metadata version mismatch')
    skill = (ROOT / 'SKILL.md').read_text()
    frontmatter = load_yaml(ROOT / 'SKILL.md', frontmatter=True)
    if frontmatter.get('name') != 'continuous-development-cycle':
        raise ContractError('wrong skill name')
    description = frontmatter.get('description', '')
    if not description.startswith('Use when') or len(description) > 500:
        raise ContractError('description must start with Use when and fit 500 characters')
    if f'# Continuous Development Cycle v{".".join(version.split(".")[:2])}' not in skill:
        raise ContractError('skill heading version mismatch')
    for term in ('ordinary ChatGPT chat', 'ChatGPT Work', 'Codex used as the orchestration environment',
                 'minimum sufficient effort', 'COMPUTE_ONLY', 'concurrency guard',
                 'runtime/tool limit', 'release-candidate SHA', 'policy-compatibility.md',
                 'command-evidence.md', 'external-operations.md'):
        if term.lower() not in ' '.join(skill.lower().split()):
            raise ContractError('skill contract missing: ' + term)
    validate_lean_templates(ROOT)
    adapter = load_yaml(ROOT / 'templates/development-cycle.yaml')
    validate_adapter(adapter, version)
    validate_checkpoint(load_yaml(ROOT / 'templates/work-status.md', frontmatter=True), adapter)
    validate_checkpoint_24(load_yaml(ROOT / 'templates/work-status-v4.md', frontmatter=True), adapter)
    load_plan(ROOT / 'templates/check-plan.json')
    validate_intent(json.loads((ROOT / 'templates/operation-intent.json').read_text()))
    validate_lease(json.loads((ROOT / 'templates/execution-lease.json').read_text()))
    validate_lease_v2(json.loads((ROOT / 'templates/execution-lease-v2.json').read_text()))
    runtime_template = json.loads((ROOT / 'templates/runtime-observation.json').read_text())
    released_liveness = classify_execution_liveness(
        json.loads((ROOT / 'templates/execution-lease-v2.json').read_text()), runtime_template, '2026-01-01T00:00:05Z')
    if released_liveness['state'] != 'released' or released_liveness['authorizes_takeover']:
        raise ContractError('invalid CDC 2.11.3 execution liveness template')
    final_gate_template = json.loads((ROOT / 'templates/final-response-gate.json').read_text())
    final_gate = evaluate_final_response_gate(final_gate_template['invocation_id'], final_gate_template['lease'],
                                              final_gate_template['continuity'], final_gate_template['owned_lease'],
                                              final_gate_template['release_receipt'], None, '2026-01-01T00:00:00Z')
    if not final_gate['allowed'] or not final_gate['final_response_allowed']:
        raise ContractError('invalid CDC 2.11.3 final-response gate template')
    validate_fleet_supervisor_control(json.loads((ROOT / 'templates/fleet-supervisor-state.json').read_text()))
    adoption_plan = assess_consumer_adoption(json.loads((ROOT / 'templates/consumer-adoption-publication.json').read_text()))
    if adoption_plan['action'] != 'PREPARE_DETACHED' or adoption_plan['authorizes_ref_move']:
        raise ContractError('invalid CDC 2.11.3 atomic adoption template')
    validate_resume_capsule(json.loads((ROOT / 'templates/resume-capsule.json').read_text()))
    continuity_template = json.loads((ROOT / 'templates/execution-continuity.json').read_text())
    # Static example validation uses its own observation time, not live evidence.
    continuity = evaluate_continuity(continuity_template, now_utc=continuity_template['blocker_proof']['observed_at_utc'])
    if not continuity['allowed']:
        raise ContractError('invalid CDC 2.4 execution-continuity template: ' + continuity['reason'])
    validate_ledger(json.loads((ROOT / 'templates/budget-ledger.json').read_text()))
    validate_wait_state(json.loads((ROOT / 'templates/external-wait.json').read_text()))
    snapshot = json.loads((ROOT / 'templates/recovery-snapshot.json').read_text())
    probe = dict(snapshot, schema='recovery-probe/v1', complete=True, source_valid=True)
    recovery = decide_recovery(snapshot, probe, snapshot['observed_at_utc'])
    if not recovery['fast_path']:
        raise ContractError('invalid recovery template: ' + '; '.join(recovery['reasons']))
    registry = json.loads((ROOT / 'templates/backend-registry.json').read_text())
    request = json.loads((ROOT / 'templates/capability-request.json').read_text())
    validate_registry(registry); validate_request(request)
    routed = route_backend(registry, request, '2026-01-01T00:00:01Z')
    if routed['action'] != 'route' or routed['authorizes_external_start']:
        raise ContractError('invalid capability routing template')
    cost_policy = json.loads((ROOT / 'templates/cost-routing-policy.json').read_text())
    cost_context = json.loads((ROOT / 'templates/cost-routing-context.json').read_text())
    validate_cost_policy(cost_policy); validate_cost_context(cost_context)
    cost_route = route_cost(registry, request, cost_policy, cost_context, '2026-01-01T00:00:01Z')
    if cost_route['action'] != 'route' or cost_route['backend_kind'] != 'codex_compute' or any(
            cost_route[name] for name in ('authorizes_external_start','authorizes_product_write',
                                          'authorizes_takeover','authorizes_scheduler_mutation')):
        raise ContractError('invalid cost-aware routing templates')
    catalog = json.loads((ROOT / 'templates/recovery-recipes.json').read_text())
    diagnosis = json.loads((ROOT / 'templates/recovery-diagnosis.json').read_text())
    validate_catalog(catalog); validate_diagnosis(diagnosis)
    recipe = select_recovery_recipe(catalog, diagnosis)
    if recipe['action'] != 'apply_recipe' or any(recipe[name] for name in (
            'authorizes_takeover', 'authorizes_product_write', 'authorizes_external_start',
            'authorizes_scheduler_mutation')):
        raise ContractError('invalid deterministic recovery template')
    event = json.loads((ROOT / 'templates/continuation-event.json').read_text())
    queue = json.loads((ROOT / 'templates/continuation-queue.json').read_text())
    validate_event(event); validate_queue(queue)
    queued, delivery = ingest_continuation(queue, event)
    if not delivery['wake_required'] or delivery['authorizes_side_effects'] or queued['generation'] != 1:
        raise ContractError('invalid continuation event/queue templates')
    slo_policy = json.loads((ROOT / 'templates/progress-slo-policy.json').read_text())
    progress_observation = json.loads((ROOT / 'templates/progress-observation.json').read_text())
    validate_slo_policy(slo_policy); validate_progress_observation(progress_observation)
    if classify_progress(slo_policy, progress_observation)['state'] != 'HEALTHY':
        raise ContractError('invalid progress SLO template')
    convergence_target = json.loads((ROOT / 'templates/version-convergence-target.json').read_text())
    convergence_snapshot = json.loads((ROOT / 'templates/version-convergence-snapshot.json').read_text())
    validate_convergence_target(convergence_target); validate_convergence_snapshot(convergence_snapshot)
    if assess_convergence(convergence_target, convergence_snapshot)['state'] != 'CONVERGED':
        raise ContractError('invalid convergence templates')
    audit_log = json.loads((ROOT / 'templates/control-plane-audit-log.json').read_text())
    validate_audit_log(audit_log)
    audit_log, audit_event = append_audit(audit_log, occurred_at_utc='2026-01-01T00:00:00Z',
                                          actor_invocation_id='template-validation',
                                          event_type='fleet_assessment', object_ref='fleet:template',
                                          outcome='healthy', details_digest='sha256:' + '1' * 64)
    validate_audit_log(audit_log)
    fleet_registry = json.loads((ROOT / 'templates/fleet-registry.json').read_text())
    fleet_snapshot = json.loads((ROOT / 'templates/fleet-project-snapshot.json').read_text())
    validate_fleet_registry(fleet_registry); validate_fleet_snapshot(fleet_snapshot)
    fleet_assessment = assess_fleet(fleet_registry, [fleet_snapshot], '2026-01-01T00:11:00Z')
    if fleet_assessment['overall'] != 'HEALTHY' or any(fleet_assessment[name] for name in (
            'authorizes_product_write', 'authorizes_takeover', 'authorizes_merge', 'authorizes_external_start')):
        raise ContractError('invalid fleet supervision template/authority contract')
    validate_consumer_lock(json.loads((ROOT / 'templates/consumer-lock.json').read_text()))
    health = assess_watchdog_health(json.loads((ROOT / 'templates/watchdog-health.json').read_text()))
    if health['overall'] != 'HEALTHY' or any(health[name] for name in ('authorizes_takeover', 'authorizes_external_start', 'authorizes_product_write')):
        raise ContractError('invalid watchdog health template/authority contract')
    terminal = evaluate_terminal_state(json.loads((ROOT / 'templates/terminal-state-v2.json').read_text()))
    if not terminal['allowed'] or not terminal['final_response_allowed'] or terminal['reason'] != 'proven_resumable_blocker':
        raise ContractError('invalid CDC 2.8 terminal-state template')
    validate_channel_supervision(json.loads((ROOT / 'templates/channel-supervision.json').read_text()))
    writer = reconcile_writer(json.loads((ROOT / 'templates/writer-reconciliation.json').read_text()))
    if writer['action'] != 'PROCEED' or writer['force_push_allowed']:
        raise ContractError('invalid concurrent-writer reconciliation template')
    sensitive = json.loads((ROOT / 'templates/sensitive-context-policy.json').read_text())
    validate_sensitive_context_policy(sensitive)
    publication = assess_publication(json.loads((ROOT / 'templates/publication-inventory.json').read_text()), sensitive)
    if not publication['pass'] or publication['authorizes_visibility_change']:
        raise ContractError('invalid publication-safety template')
    watchdog_repair = plan_watchdog_repair(json.loads((ROOT / 'templates/watchdog-repair-state.json').read_text()))
    if watchdog_repair['action'] != 'HEALTHY' or watchdog_repair['authorizes_scheduler_mutation']:
        raise ContractError('invalid watchdog self-repair template')
    ref_plan = assess_ref_hygiene(json.loads((ROOT / 'templates/ref-inventory.json').read_text()))
    if ref_plan['delete_candidates'] or ref_plan['authorizes_delete']:
        raise ContractError('invalid ref hygiene template')
    retention = assess_coordination_retention(json.loads((ROOT / 'templates/coordination-retention.json').read_text()))
    if retention['delete_candidates'] or retention['archive_candidates'] or retention['authorizes_delete'] or retention['authorizes_archive']:
        raise ContractError('invalid coordination retention template')
    blocker = assess_blocker_proof(json.loads((ROOT / 'templates/blocked-state-proof.json').read_text()), '2026-01-01T00:05:00Z')
    if not blocker['terminal_boundary_valid'] or blocker['state'] != 'BLOCKED':
        raise ContractError('invalid blocker proof template')
    decision = classify_decision(json.loads((ROOT / 'templates/decision-request.json').read_text()))
    if decision['decision'] != 'AUTO_EXECUTE' or decision['creates_authority']:
        raise ContractError('invalid decision-authority template')
    compacted = compact_evidence(json.loads((ROOT / 'templates/evidence-stream.json').read_text()))
    if compacted['source_event_count'] != 1 or compacted['details_retained']:
        raise ContractError('invalid evidence compaction template')
    progress_plan = enforce_progress(json.loads((ROOT / 'templates/progress-enforcement.json').read_text()))
    if progress_plan['action'] != 'NOOP' or not progress_plan['final_response_allowed']:
        raise ContractError('invalid progress enforcement template')
    fleet_plan = plan_fleet_control(json.loads((ROOT / 'templates/fleet-control-input.json').read_text()))
    if fleet_plan['projects'][0]['action'] != 'NOOP' or fleet_plan['project_specific_code_required']:
        raise ContractError('invalid fleet control template')
    stuck = detect_stuck(json.loads((ROOT / 'templates/stuck-state-input.json').read_text()))
    if stuck['stuck']:
        raise ContractError('invalid stuck-state template')
    counterfactual = choose_counterfactual(json.loads((ROOT / 'templates/counterfactual-recovery.json').read_text()))
    if counterfactual['action'] != 'TRY_NEW_STRATEGY' or counterfactual['authorizes_external_start']:
        raise ContractError('invalid counterfactual recovery template')
    export = plan_public_export(json.loads((ROOT / 'templates/public-export-request.json').read_text()))
    if export['action'] != 'EXPORT_NEW_HISTORY' or export['authorizes_visibility_change'] or export['authorizes_push']:
        raise ContractError('invalid public export template')
    dogfood = measure_dogfood(json.loads((ROOT / 'templates/cdc-dogfood-input.json').read_text()))
    if dogfood['compliance_percent'] != 100.0 or dogfood['authorizes_release'] or dogfood['authorizes_policy_change']:
        raise ContractError('invalid dogfood metrics template')
    transport = validate_transport_manifest(json.loads((ROOT / 'templates/package-transport.json').read_text()))
    if transport['version'] != version:
        raise ContractError('invalid package transport template version')
    vector = normalize_convergence_vector(json.loads((ROOT / 'templates/convergence-observation.json').read_text()))
    if not vector['integrated'] or vector['adoption_state'] != 'integrated' or vector['blockers']:
        raise ContractError('invalid convergence vector template')
    ci_class = classify_ci_evidence(json.loads((ROOT / 'templates/ci-execution-observation.json').read_text()))
    if ci_class['class'] != 'terminal_success' or ci_class['source_change_allowed']:
        raise ContractError('invalid CI evidence classification template')
    policy_req = json.loads((ROOT / 'templates/policy-migration-request.json').read_text())
    policy_plan = plan_policy_migration(policy_req)
    if policy_plan['action'] != 'APPLY' or policy_plan['authorizes_product_write']:
        raise ContractError('invalid policy migration template')
    policy_req['current_policy_yaml'] = policy_plan['rendered_policy_yaml']
    if plan_policy_migration(policy_req)['action'] != 'NOOP':
        raise ContractError('policy migration template is not idempotent')
    built_checkpoint = build_typed_checkpoint(
        load_yaml(ROOT / 'templates/work-status-v4.md', frontmatter=True),
        json.loads((ROOT / 'templates/typed-checkpoint-build.json').read_text()), adapter)
    validate_checkpoint_24(built_checkpoint, adapter)
    migration_plan = plan_migration_transaction(json.loads((ROOT / 'templates/migration-transaction.json').read_text()))
    if migration_plan['action'] != 'APPLY_BATCH' or migration_plan['authorizes_ref_move']:
        raise ContractError('invalid migration transaction template')
    provider_plan = reconcile_provider_terminal(json.loads((ROOT / 'templates/provider-terminal-observation.json').read_text()))
    if provider_plan['action'] != 'REENTER_RECONCILIATION' or not provider_plan['wake_required'] or provider_plan['authorizes_takeover']:
        raise ContractError('invalid provider reconciliation template')
    continuation = decide_continuation_cycle(json.loads((ROOT / 'templates/continuation-cycle.json').read_text()))
    if continuation['action'] != 'CONTINUE_NOW' or continuation['final_response_allowed'] or continuation['progress_is_terminal']:
        raise ContractError('invalid continuation cycle template')
    timestamp_request = json.loads((ROOT / 'templates/command-timestamp-request.json').read_text())
    timestamp_fixture_clock = datetime.fromisoformat(timestamp_request['observed_at'].replace('Z','+00:00'))
    timestamp = render_command_timestamp(timestamp_request, now=timestamp_fixture_clock)
    if timestamp['action'] != 'EMIT_ONCE' or timestamp['display'] != '[19:31 26.09]' or timestamp['authorizes_anything']:
        raise ContractError('invalid command timestamp template')
    rca = disposition_rca_feedback(json.loads((ROOT / 'templates/rca-feedback.json').read_text()))
    if rca['action'] != 'REINFORCE_EXISTING' or rca['authorizes_roadmap_write']:
        raise ContractError('invalid RCA feedback template')
    improvement = harvest_fleet_improvement(json.loads((ROOT / 'templates/fleet-improvement-harvest.json').read_text()))
    if improvement['proposal_count'] != 1 or improvement['action'] != 'REINFORCE_EXISTING' or improvement['authorizes_roadmap_write']:
        raise ContractError('invalid fleet improvement template')
    validate_quality_templates(ROOT)
    behavioral = evaluate_behavioral_suite(json.loads((ROOT / 'templates/behavioral-eval-suite.json').read_text()))
    if (not behavioral['all_regressions_green'] or behavioral['case_count'] < 6 or
            any(behavioral[name] for name in ('authorizes_product_write','authorizes_takeover','authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10 behavioral eval template')
    verification = evaluate_verification_gate(json.loads((ROOT / 'templates/verification-gate.json').read_text()))
    if (not verification['allowed'] or not verification['final_claim_allowed'] or verification['blockers'] or
            any(verification[name] for name in ('authorizes_product_write','authorizes_takeover','authorizes_external_start',
                                                'authorizes_merge','authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10 verification template')
    systematic = analyze_systematic_rca(json.loads((ROOT / 'templates/systematic-rca.json').read_text()))
    if (not systematic['ready_for_feedback_disposition'] or
            any(systematic[name] for name in ('authorizes_product_write','authorizes_roadmap_write','authorizes_takeover'))):
        raise ContractError('invalid CDC 2.10 systematic RCA template')
    systematic_disposition = disposition_rca_feedback(systematic['feedback'])
    if systematic_disposition['action'] != 'REINFORCE_EXISTING' or systematic_disposition['authorizes_roadmap_write']:
        raise ContractError('systematic RCA did not preserve bounded feedback authority')
    spec_plan = evaluate_spec_plan_queue(json.loads((ROOT / 'templates/spec-plan-queue.json').read_text()))
    if (not spec_plan['ready'] or spec_plan['blockers'] or spec_plan['brainstorming_required'] or
            any(spec_plan[name] for name in ('authorizes_product_write','authorizes_external_start',
                                             'authorizes_scope_expansion','authorizes_merge','authorizes_release'))):
        raise ContractError('invalid CDC 2.10.1 spec-plan template')
    review = evaluate_review_pipeline(json.loads((ROOT / 'templates/review-pipeline.json').read_text()))
    if (not review['review_green'] or review['action'] != 'REVIEW_GREEN' or review['blockers'] or
            any(review[name] for name in ('authorizes_product_write','authorizes_merge',
                                          'authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10.1 review pipeline template')
    branch_finish = evaluate_branch_finish(json.loads((ROOT / 'templates/branch-finish.json').read_text()))
    if (not branch_finish['ready'] or branch_finish['action'] != 'READY_FOR_CDC_TERMINAL' or branch_finish['blockers'] or
            any(branch_finish[name] for name in ('authorizes_product_write','authorizes_merge',
                                                 'authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10.1 branch-finishing template')
    parallel_plan = plan_parallel_tasks(json.loads((ROOT / 'templates/parallel-task-plan.json').read_text()))
    if (not parallel_plan['parallel_safe'] or not parallel_plan['waves'] or len(parallel_plan['waves'][0]['task_ids']) < 2 or
            parallel_plan['parallel_estimate_seconds'] >= parallel_plan['sequential_estimate_seconds'] or
            any(parallel_plan[name] for name in ('authorizes_worker_launch','authorizes_product_write',
                                                 'authorizes_merge','authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10.2 parallel planner template')
    worker_contract = assess_worker_contract(json.loads((ROOT / 'templates/worktree-worker-contract.json').read_text()))
    if (not worker_contract['valid'] or
            any(worker_contract[name] for name in ('authorizes_worker_launch','authorizes_shared_branch_write',
                                                   'authorizes_merge','authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10.2 worker isolation template')
    prior_record = json.loads((ROOT / 'templates/wave-integration-record.json').read_text())
    validate_prior_integration_record(prior_record)
    gate = json.loads((ROOT / 'templates/wave-integration-gate-evidence.json').read_text())
    assembly = json.loads((ROOT / 'templates/wave-assembly-evidence.json').read_text())
    validate_gate_evidence(gate); validate_assembly_evidence(assembly)
    for ref_name in ('gate_artifact_ref','assembly_artifact_ref'):
        ref = prior_record[ref_name]
        payload = (ROOT / ref['path']).read_bytes()
        observed = 'sha256:' + hashlib.sha256(payload).hexdigest()
        if observed != ref['sha256']:
            raise ContractError('invalid CDC 2.10.2 prior-wave artifact digest: ' + ref_name)
    gate_result_ref = gate['result_artifact_ref']
    gate_result_payload = (ROOT / gate_result_ref['path']).read_bytes()
    gate_result_observed = 'sha256:' + hashlib.sha256(gate_result_payload).hexdigest()
    if gate_result_observed != gate_result_ref['sha256']:
        raise ContractError('invalid CDC 2.10.2 integration gate result artifact digest')
    gate_result = json.loads(gate_result_payload)
    validate_gate_result(gate_result)
    if (gate_result['change_id'] != prior_record['change_id'] or
            gate_result['plan_ref'] != prior_record['plan_ref'] or
            gate_result['wave'] != prior_record['wave'] or
            gate_result['shared_branch'] != prior_record['shared_branch'] or
            gate_result['expected_shared_head'] != prior_record['base_sha'] or
            gate_result['observed_shared_head'] != prior_record['base_sha'] or
            not gate_result['ready'] or gate_result['action'] != 'READY_FOR_INTEGRATOR' or gate_result['blockers']):
        raise ContractError('invalid CDC 2.10.2 integration gate result binding')
    if gate_result['writer_result_shas'] != prior_record['writer_result_shas']:
        raise ContractError('invalid CDC 2.10.2 gate/result writer binding')
    if assembly['writer_result_shas'] != prior_record['writer_result_shas']:
        raise ContractError('invalid CDC 2.10.2 assembly/result writer binding')
    if assembly['gate_sha256'] != prior_record['gate_artifact_ref']['sha256']:
        raise ContractError('invalid CDC 2.10.2 prior-wave gate/assembly binding')
    if prior_record['base_sha'] == prior_record['integrated_head']:
        raise ContractError('invalid CDC 2.10.2 prior-wave non-advancing integration record')
    integration = evaluate_integration_gate(json.loads((ROOT / 'templates/integration-gate.json').read_text()))
    if (not integration['ready'] or integration['action'] != 'READY_FOR_INTEGRATOR' or integration['blockers'] or
            integration['next_gate'] != 'cdc_2.10.1_review_branch_finish_then_2.10.0_verification' or
            any(integration[name] for name in ('authorizes_shared_branch_write','authorizes_force_push',
                                               'authorizes_merge','authorizes_release','authorizes_scope_expansion'))):
        raise ContractError('invalid CDC 2.10.2 integration gate template')
    benchmark_template = json.loads((ROOT / 'templates/parallel-benchmark.json').read_text())
    benchmark = evaluate_parallel_benchmark_files(benchmark_template, ROOT)
    if (not benchmark['passed'] or benchmark['blockers'] or benchmark['evidence_class'] != 'fixture'
            or benchmark['release_evidence_eligible']
            or any(benchmark[name] for name in ('authorizes_worker_launch','authorizes_product_write',
                                                 'authorizes_merge','authorizes_release'))):
        raise ContractError('invalid CDC 2.10.2 fixture-only benchmark template')
    managed_attempt = json.loads((ROOT / 'templates/managed-executor-attempt.json').read_text())
    managed_result = json.loads((ROOT / 'templates/managed-executor-result.json').read_text())
    validate_managed_executor_attempt(managed_attempt)
    validate_managed_executor_result(managed_result, managed_attempt)
    managed_acceptance = accept_managed_executor_result(managed_result, managed_attempt)
    if (not managed_acceptance['accepted'] or managed_acceptance['integrated'] or
            any(managed_acceptance[name] for name in ('authorizes_shared_branch_write','authorizes_merge',
                                                       'authorizes_release','authorizes_scope_expansion',
                                                       'authorizes_scheduler_mutation','authorizes_user_approval'))):
        raise ContractError('invalid CDC 2.11.0 managed executor attempt/result templates')
    managed_pool_plan = json.loads((ROOT / 'templates/managed-executor-pool-plan.json').read_text())
    managed_pool_state = json.loads((ROOT / 'templates/managed-executor-pool-state.json').read_text())
    validate_managed_pool_plan(managed_pool_plan)
    validate_managed_pool_state(managed_pool_plan, managed_pool_state)
    managed_dispatch = dispatch_managed_pool(managed_pool_plan, managed_pool_state)
    managed_assessment = assess_managed_pool(managed_pool_plan, managed_pool_state)
    if (managed_dispatch['task_ids'] != ['writer-a','writer-b'] or
            managed_dispatch['fallback_serialized'] or managed_assessment['complete'] or
            managed_assessment['terminal_allowed'] or
            any(managed_dispatch[name] for name in ('authorizes_worker_launch','authorizes_shared_branch_write',
                                                    'authorizes_merge','authorizes_release','authorizes_scope_expansion',
                                                    'authorizes_scheduler_mutation','authorizes_user_approval')) or
            any(managed_assessment[name] for name in ('authorizes_worker_launch','authorizes_shared_branch_write',
                                                      'authorizes_merge','authorizes_release','authorizes_scope_expansion',
                                                      'authorizes_scheduler_mutation','authorizes_user_approval'))):
        raise ContractError('invalid CDC 2.11.0 managed executor pool templates')
    managed_handoff = json.loads((ROOT / 'templates/managed-executor-handoff.json').read_text())
    validate_managed_handoff(managed_handoff)
    handoff_plan = plan_managed_handoff_publication(managed_handoff, ROOT)
    if (handoff_plan['action'] != 'IMPORT_CONTENT_ARTIFACT_TO_ASSIGNED_BRANCH' or
            handoff_plan['requires_reexecution'] or
            any(handoff_plan[name] for name in ('authorizes_product_write','authorizes_shared_branch_write',
                                                'authorizes_force_push','authorizes_merge','authorizes_release',
                                                'authorizes_scope_expansion','authorizes_scheduler_mutation'))):
        raise ContractError('invalid CDC 2.11.0 managed executor handoff template')
    validate_development_request(json.loads((ROOT / 'templates/codex-cloud-development-request.json').read_text()))
    for required in ('scripts/codex_cloud_development.py', 'tests/test_codex_cloud_development.py'):
        if not (ROOT / required).is_file():raise ContractError('missing development transport file: ' + required)
    for path in ROOT.rglob('*.md'):
        content = path.read_text()
        # Only portable package paths; repository paths in examples remain project-specific inputs.
        for relative in re.findall(r'`((?:references|templates|scripts)/[A-Za-z0-9_.-]+)`', content):
            if not (ROOT / relative).is_file():
                raise ContractError(f'broken package reference in {path.name}: {relative}')
    banned = ['bajo' + 'icheg', 'g-' + 'ad-control', 'Grad' + 'ient', 'Гра' + 'диент']
    for path in ROOT.rglob('*'):
        if path.is_file() and path.suffix in {'.md', '.py', '.yaml', '.json', '.txt'}:
            content = path.read_text()
            for literal in banned:
                if literal.lower() in content.lower():
                    raise ContractError(f'project-specific literal in {path.relative_to(ROOT)}')
    return version


def validate_quality_templates(root):
    from quality_levels import evaluate as assess, evaluate_cycle
    from evidence_reuse import evaluate as reuse
    def load(name):return json.loads((root/'templates'/name).read_text())
    checks=[(assess,'quality-assessment.json','effective_level','MEDIUM'),
            (evaluate_cycle,'validation-cycle.json','validation_recommended',True),
            (reuse,'evidence-reuse.json','reusable',True),
            (evaluate_review_pipeline,'review-pipeline-v2.json','review_green',True),
            (evaluate_verification_gate,'verification-gate-v2.json','allowed',True),
            (evaluate_branch_finish,'branch-finish-v2.json','ready',True),
            (evaluate_behavioral_suite,'behavioral-quality-suite.json','all_regressions_green',True)]
    for function,name,key,want in checks:
        result=function(load(name))
        if result[key]!=want or any(v for k,v in result.items() if k.startswith('authorizes_')):
            raise ContractError('invalid quality template: '+name)

def validate_lean_templates(root):
    """Execute source-development examples; missing core evidence stays missing."""
    from development_contract import evaluate as assess
    from execution_strategy import evaluate as strategy
    from operation_report import measure, render
    from adaptive_allocation import evaluate as allocate
    from release_delivery import plan as delivery
    def load(name):
        return json.loads((root / 'templates' / name).read_text())
    assessment = assess(load('development-assessment.json'))
    if (assessment['quality']['effective_level'] != 'FULL' or
            assessment['validation_recommended'] or
            not assessment['blockers'] or
            any(not blocker.startswith('mandatory_check_unsatisfied:')
                for blocker in assessment['blockers'])):
        raise ContractError('lean core template must retain missing mandatory FULL gates')
    observation = load('operation-observation.json')
    report = measure(observation)
    if report['tokens']['provenance'] != 'unknown' or render(observation) != '(4 мин)':
        raise ContractError('lean report template must omit unknown tokens')
    execution = strategy(load('execution-strategy.json'))
    if execution['action'] != 'SINGLE' or execution['batch_candidate']['effective_level'] != 'MEDIUM':
        raise ContractError('lean strategy template must preserve project floor and missing admissions')
    allocation = allocate(load('adaptive-allocation.json'))
    if allocation['selection'] != 'default' or allocation['action'] != 'SINGLE' or allocation['measurement'] is not None:
        raise ContractError('allocation template must preserve safe default without fabricated measurements')
    proposed = delivery(load('release-delivery.json'))
    if proposed['action'] != 'VERIFY_RELEASE_AND_OWNERSHIP' or proposed['publication_prerequisites_satisfied']:
        raise ContractError('delivery template must retain missing live authority')
    for result in (assessment, execution, allocation, proposed):
        if any(value for key, value in result.items() if key.startswith('authorizes_')):
            raise ContractError('lean template cannot grant effect authority')


def main():
    try:
        version = validate()
    except (ContractError, OSError, UnicodeError, ValueError) as exc:
        print(f'FAIL: {exc}')
        return 1
    print(f'PASS: continuous-development-cycle {version}, {len(REQUIRED)} files and parsed templates')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
