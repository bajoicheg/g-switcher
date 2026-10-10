# Guidance-test consolidation for the 3.0 source baseline

The prior guidance tests primarily searched literal phrases in SKILL.md,
references or Python source. Those assertions do not prove runtime behavior
and forced every historical subsystem into the startup prompt. The compact
core retains its mandatory boundaries and routes phase references; the prior
complete instruction bytes are archived. No executable gate is removed.

Two actual fixture checks remain in test_guidance_contracts.py: configured
cost policy validation and pressure-fixture ID integrity. test_lean_package.py
executes the new fixtures and rejects weakened core/report inputs. Package
validation checks portable reference targets, required packaged files and
actual parsers. The independent behavioral suites remain unchanged:

| Risk previously named by prose assertions | Retained executable coverage |
|---|---|
| Budget, quota, infrastructure retry and cost | test_budget.py, test_cost_router.py, test_submission_recovery.py |
| Continuity, terminal response and recovery | test_execution_continuity.py, test_terminal_state_v2.py, test_execution_channel_supervisor.py, test_watchdog_liveness.py |
| Invocation ownership, finalization and writes | test_execution_lease_v2.py, test_concurrent_writer.py, test_managed_executor_runtime.py |
| Capability and continuation queue | test_capability_router.py, test_recovery_recipes.py, test_continuation_queue.py |
| Source release and exact package identity | independent bootstrap/tests, test_active_package.py, test_package_transport.py |
| Public/control-state isolation | test_publication_guard.py, test_public_export_planner.py |
| Review, spec, evidence and integration | test_review_pipeline.py, test_spec_plan_queue.py, test_verification_gate.py, test_integration_gate.py |
| Fleet and adoption boundaries | test_fleet_supervisor_control.py, test_consumer_adoption.py, test_final_response_gate.py |
| Reports and resume routing | test_command_timestamp.py, test_resume_capsule.py, test_cdc_entrypoint.py, test_operation_report.py |

These mappings identify retained suites, not a claim that word presence was
independent behavioral coverage. Full suite results bind the actual candidate.
Historical pressure examples stay available for behavioral evaluation; phrase
matches are not counted as GREEN behavior evidence.

Retired assertion identifiers (including two fixture checks replaced above):

- test_higher_compute_budget_is_capacity_not_retry_permission
- test_compute_environment_guidance_is_lean_and_missing_only
- test_failures_are_classified_before_another_start
- test_pressure_scenarios_cover_new_failure_modes
- test_announced_next_action_cannot_end_on_discovery
- test_final_handoff_matches_release_shape
- test_watchdog_distinguishes_visibility_from_progress
- test_pressure_suite_covers_new_rca_modes
- test_core_mentions_v24_controls
- test_watchdog_requires_hard_gate_and_release
- test_core_has_all_v25_subsystems
- test_watchdog_keeps_scheduler_fallback
- test_core_names_v26_controls
- test_watchdog_says_fleet_is_not_authority
- test_core_names_27_release_contracts
- test_reference_separates_evidence_classes
- test_watchdog_treats_version_equality_as_insufficient
- test_pressure_suite_covers_release_and_drift_fail_closed
- test_missing_connector_method_is_not_manual_approval
- test_cost_policy_is_codex_first_and_actions_expensive
- test_guidance_blocks_automatic_actions_on_transient_codex_failure
- test_watchdog_names_expensive_fallback_reasons
- test_pressure_suite_covers_cost_failure_modes
- test_continue_means_terminal_state
- test_watchdog_preserves_terminal_semantics
- test_public_actions_are_visibility_aware
- test_skill_enforces_no_idle_and_failover
- test_publication_contract_is_not_secret_scan_only
- test_control_plane_is_separated
- test_skill_names_operational_hardening
- test_reference_prevents_fake_blocked_state
- test_decision_classifier_never_creates_authority
- test_skill_names_p2_controls
- test_publication_reference_requires_new_history
- test_dogfood_has_no_release_authority
- test_skill_names_distribution_convergence_controls
- test_reference_is_fail_closed
- test_skill_names_transactional_controls
- test_timestamp_guidance
- test_behavioral_tdd_and_verification_guidance
- test_review_guidance
- test_package_validator_binds_gate_result_fixture
- test_parallel_guidance
- test_managed_executor_guidance_is_wired
- test_pressure_numbering_is_continuous_through_101
- test_guidance_preserves_authority_boundary
- test_failure_isolation_and_fallback_are_explicit
- test_skill_names_2113_controls
- test_reference_has_fail_closed_boundaries
