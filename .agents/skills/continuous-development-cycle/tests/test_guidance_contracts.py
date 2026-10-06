"""Current guidance contracts grouped by capability."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cost_router as m


class ComputeBudgetGuidanceTests(unittest.TestCase):

    def test_higher_compute_budget_is_capacity_not_retry_permission(self):
        core = (ROOT / 'SKILL.md').read_text().lower()
        budget = (ROOT / 'references' / 'budget-ledger.md').read_text().lower()
        self.assertIn('higher compute capacity', core)
        self.assertIn('information gain', core)
        self.assertIn('not a retry instruction', core)
        self.assertIn('higher compute budget', budget)
        self.assertIn('distinct information', budget)
        self.assertIn('concrete correction', budget)

    def test_compute_environment_guidance_is_lean_and_missing_only(self):
        compute = (ROOT / 'references' / 'codex-compute.md').read_text().lower()
        for phrase in ('reuse the provider runtime', 'missing-only', 'allow-list', 'do not reinstall', 'third-party package sources'):
            self.assertIn(phrase, compute)

    def test_failures_are_classified_before_another_start(self):
        compute = (ROOT / 'references' / 'codex-compute.md').read_text().lower()
        self.assertIn('classify the failure', compute)
        for category in ('setup', 'network', 'runtime', 'product'):
            self.assertIn(category, compute)
        self.assertIn('before another compute start', compute)

    def test_pressure_scenarios_cover_new_failure_modes(self):
        scenarios = (ROOT / 'tests' / 'pressure-scenarios.md').read_text().lower()
        self.assertIn('larger compute budget tempts retries', scenarios)
        self.assertIn('heavy bootstrap repeats provider tools', scenarios)

class CommitmentClosureGuidanceTests(unittest.TestCase):

    def test_announced_next_action_cannot_end_on_discovery(self):
        core = (ROOT / 'SKILL.md').read_text().lower()
        self.assertIn('close every accepted execution commitment', core)
        self.assertIn('not a continuation boundary', core)
        self.assertIn('next policy-authorized fallback', core)
        self.assertIn('explicit durable handoff/blocker', core)

    def test_final_handoff_matches_release_shape(self):
        progress = (ROOT / 'references' / 'progress-and-checkpoints.md').read_text().lower()
        self.assertIn('commitment closure and visible continuity', progress)
        self.assertIn('release-consistent handoff', progress)
        self.assertIn('active_executor: none', progress)
        self.assertIn('lease_state: released', progress)

    def test_watchdog_distinguishes_visibility_from_progress(self):
        watchdog = (ROOT / 'references' / 'watchdog-recovery-and-migration.md').read_text().lower()
        self.assertIn('silent-dead-end recovery', watchdog)
        self.assertIn('execution visibility', watchdog)
        self.assertIn('meaningful development progress', watchdog)
        self.assertIn('ownership state', watchdog)

    def test_pressure_suite_covers_new_rca_modes(self):
        scenarios = (ROOT / 'tests' / 'pressure-scenarios.md').read_text().lower()
        self.assertIn('discovery dead-end after promised fallback', scenarios)
        self.assertIn('released lease but active checkpoint', scenarios)
        self.assertIn('partial multi-write success looks like external movement', scenarios)

class ControlPlaneGuidanceTests(unittest.TestCase):

    def test_core_mentions_v24_controls(self):
        text = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('invocation-bound', 'resume capsule', 'execution-continuity', 'transactional'):
            self.assertIn(term, text)

    def test_watchdog_requires_hard_gate_and_release(self):
        text = (ROOT / 'templates/watchdog-prompt.md').read_text().lower()
        for term in ('execution-continuity', 'transactionally', 'release'):
            self.assertIn(term, text)

class CapabilityRoutingGuidanceTests(unittest.TestCase):

    def test_core_has_all_v25_subsystems(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('capability router', 'deterministic recovery', 'continuation queue'):
            self.assertIn(term, t)

    def test_watchdog_keeps_scheduler_fallback(self):
        t = (ROOT / 'templates/watchdog-prompt.md').read_text().lower()
        for term in ('continuation', 'scheduler fallback', 'capability'):
            self.assertIn(term, t)

class FleetGuidanceTests(unittest.TestCase):

    def test_core_names_v26_controls(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('fleet supervisor', 'version convergence', 'progress slo', 'control-plane audit'):
            self.assertIn(term, t)

    def test_watchdog_says_fleet_is_not_authority(self):
        t = (ROOT / 'templates/watchdog-prompt.md').read_text().lower()
        self.assertIn('fleet', t)
        self.assertIn('never grants', t)

class CanonicalReleaseGuidanceTests(unittest.TestCase):

    def test_core_names_27_release_contracts(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('canonical source', 'independent release', 'consumer locks', 'candidate runtime', 'package git tree', 'self-hosting'):
            self.assertIn(term, t)

    def test_reference_separates_evidence_classes(self):
        t = (ROOT / 'references' / 'canonical-source-and-release.md').read_text().lower()
        for term in ('bootstrap', 'package', 'compatibility', 'fault-injection', 'three distinct consumers'):
            self.assertIn(term, t)

    def test_watchdog_treats_version_equality_as_insufficient(self):
        t = (ROOT / 'templates' / 'watchdog-prompt.md').read_text().lower()
        self.assertIn('version equality alone is not convergence', t)
        self.assertIn('vendored core', t)

    def test_pressure_suite_covers_release_and_drift_fail_closed(self):
        t = (ROOT / 'tests' / 'pressure-scenarios.md').read_text().lower()
        for term in ('candidate validates itself', 'consumer version matches but package tree differs', 'migration crosses active owner'):
            self.assertIn(term, t)

    def test_missing_connector_method_is_not_manual_approval(self):
        skill = (ROOT / 'SKILL.md').read_text().lower()
        watchdog = (ROOT / 'templates' / 'watchdog-prompt.md').read_text().lower()
        for text in (skill, watchdog):
            self.assertIn('human interaction is not an execution backend', text)
            self.assertIn('workflow_dispatch', text)
            self.assertIn('capability gap', text)

class CostRoutingGuidanceTests(unittest.TestCase):

    def test_cost_policy_is_codex_first_and_actions_expensive(self):
        p = json.loads((ROOT / 'templates' / 'cost-routing-policy.json').read_text())
        m.validate_policy(p)
        self.assertEqual(p['primary_kind'], 'codex_compute')
        self.assertIn('github_actions', p['expensive_kinds'])
        self.assertGreater(p['kind_cost_weights']['github_actions'], p['kind_cost_weights']['codex_compute'])
        self.assertTrue(p['github_actions_requires_reason'])

    def test_guidance_blocks_automatic_actions_on_transient_codex_failure(self):
        t = (ROOT / 'references' / 'cost-aware-routing.md').read_text().lower()
        for term in ('transient', 'waiting_compute', 'confirmed provider outage', 'product/test failure', 'explicit machine-readable reason'):
            self.assertIn(term, t)

    def test_watchdog_names_expensive_fallback_reasons(self):
        t = (ROOT / 'templates' / 'watchdog-prompt.md').read_text().lower()
        for term in ('final-platform', 'artifact production', 'release attestation', 'confirmed provider outage'):
            self.assertIn(term, t)

    def test_pressure_suite_covers_cost_failure_modes(self):
        t = (ROOT / 'tests' / 'pressure-scenarios.md').read_text().lower()
        for term in ('transient codex failure with expensive actions available', 'product failure on codex while actions is ready', 'expensive platform gate is genuinely required'):
            self.assertIn(term, t)

class TerminalContinuationGuidanceTests(unittest.TestCase):

    def test_continue_means_terminal_state(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('продолжай', 'continue', 'terminal state', 'real durable terminal blocker'):
            self.assertIn(term, t)

    def test_watchdog_preserves_terminal_semantics(self):
        t = (ROOT / 'templates' / 'watchdog-prompt.md').read_text().lower()
        self.assertIn('bare user continuation command', t)
        self.assertIn('terminal state', t)

    def test_public_actions_are_visibility_aware(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('repository visibility', 'public repositories', 'unmetered', 'private/internal'):
            self.assertIn(term, t)

class AutonomyPublicationGuidanceTests(unittest.TestCase):

    def test_skill_enforces_no_idle_and_failover(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('terminal-state v2', 'no-idle', 'execution-channel supervisor', 'concurrent-writer reconciliation'):
            self.assertIn(term, t)

    def test_publication_contract_is_not_secret_scan_only(self):
        t = (ROOT / 'references' / 'publication-safety.md').read_text().lower()
        for term in ('secret scanning is necessary but not sufficient', 'every ref', 'conversation text', 'sanitized export'):
            self.assertIn(term, t)

    def test_control_plane_is_separated(self):
        t = (ROOT / 'references' / 'autonomous-continuity-and-isolation.md').read_text().lower()
        for term in ('control-plane isolation', 'leases', 'ledgers', 'public export'):
            self.assertIn(term, t)

class OperationalHardeningGuidanceTests(unittest.TestCase):

    def test_skill_names_operational_hardening(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('watchdog self-repair', 'ref hygiene', 'blocker proof', 'decision authority', 'evidence compaction', 'progress enforcement'):
            self.assertIn(term, t)

    def test_reference_prevents_fake_blocked_state(self):
        t = (ROOT / 'references' / 'operational-hardening.md').read_text().lower()
        for term in ('fresh observation', 'same-invocation useful work', 'recheck trigger'):
            self.assertIn(term, t)

    def test_decision_classifier_never_creates_authority(self):
        t = (ROOT / 'references' / 'decision-authority.md').read_text().lower()
        self.assertIn('never creates authority', t)

class MaturityPublicationGuidanceTests(unittest.TestCase):

    def test_skill_names_p2_controls(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('project-independent fleet', 'stuck-state', 'counterfactual recovery', 'sanitized public export', 'dogfooding'):
            self.assertIn(term, t)

    def test_publication_reference_requires_new_history(self):
        t = (ROOT / 'references' / 'fleet-and-publication-maturity.md').read_text().lower()
        for term in ('sanitized export', 'new public history', 'preserve private history'):
            self.assertIn(term, t)

    def test_dogfood_has_no_release_authority(self):
        t = (ROOT / 'references' / 'fleet-and-publication-maturity.md').read_text().lower()
        self.assertIn('never release authority', t)

class DistributionConvergenceGuidanceTests(unittest.TestCase):

    def test_skill_names_distribution_convergence_controls(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('carrier-neutral', 'convergence vector', 'pre_run_infrastructure', 'version string alone'):
            self.assertIn(term, t)

    def test_reference_is_fail_closed(self):
        t = (ROOT / 'references' / 'deterministic-distribution-and-convergence.md').read_text().lower()
        for term in ('least-privilege', 'exact package git tree', 'fails closed', 'no source change'):
            self.assertIn(term, t)

class TransactionalPublicationGuidanceTests(unittest.TestCase):

    def test_skill_names_transactional_controls(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('fresh head', 'schema-typed', 'detached tree', 'terminal-provider reconciliation'):
            self.assertIn(term, t)

class TimestampGuidanceTests(unittest.TestCase):

    def test_timestamp_guidance(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('progress-is-not-terminal', '[hh:mm dd.mm]', 'actual current moscow time', 'rca-to-roadmap', 'exactly one improvement'):
            self.assertIn(term, t)

class BehavioralVerificationGuidanceTests(unittest.TestCase):

    def test_behavioral_tdd_and_verification_guidance(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('behavioral skill tdd', 'pressure scenario', 'verification-before-terminal', 'systematic debugging', 'baseline red', 'corrected green'):
            self.assertIn(term, t)
        ref = (ROOT / 'references' / 'behavioral-tdd-and-verification.md').read_text().lower()
        for term in ('superpowers', 'behavioral eval', 'verification gate', 'evidence-only', 'no authority'):
            self.assertIn(term, ref)

class SpecificationReviewGuidanceTests(unittest.TestCase):

    def test_review_guidance(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('spec-compliance review', 'code-quality review', 'selective brainstorming', 'spec → plan', 'branch finishing', 'independent reviewers'):
            self.assertIn(term, t)
        r = (ROOT / 'references' / 'specification-review-and-finishing.md').read_text().lower()
        for term in ('superpowers', 'spec compliance', 'code quality', 'continuation queue', 'no merge authority'):
            self.assertIn(term, r)

class ParallelIntegrationGuidanceTests(unittest.TestCase):

    def test_package_validator_binds_gate_result_fixture(self):
        s = (ROOT / 'scripts' / 'validate_package.py').read_text()
        self.assertIn("'templates/wave-integration-gate-result.json'", s)
        self.assertIn("'templates/parallel-benchmark-plan.json'", s)
        self.assertIn('validate_gate_result(gate_result)', s)
        self.assertIn('integration gate result artifact digest', s)

    def test_parallel_guidance(self):
        t = (ROOT / 'SKILL.md').read_text().lower()
        for term in ('worktree-isolated parallel development', 'ordinary chatgpt chat remains sequential', 'write-set', 'single integrator', 'ready_for_integrator', 'observed parallel benchmark', 'content-addressed prior integration', 'actual plan artifact'):
            self.assertIn(term, t)
        r = (ROOT / 'references' / 'worktree-parallelism-and-integration.md').read_text().lower()
        for term in ('worktree', 'single integrator', 'shared branch', 'observed parallel benchmark', 'no shared-branch write'):
            self.assertIn(term, r)

class ManagedExecutorGuidanceTests(unittest.TestCase):

    def test_managed_executor_guidance_is_wired(self):
        skill = (ROOT / 'SKILL.md').read_text().lower()
        ref = (ROOT / 'references' / 'managed-executor-pool.md').read_text().lower()
        readme = (ROOT / 'README.md').read_text().lower()
        for term in ('managed executor pool', 'capability-gated', 'deterministic sequential fallback', 'must not fabricate subagents', 'single integrator', 'attempt lineage', 'unintegrated successful result', 'content-addressed result handoff', 'progress is not terminal', 'durable-cas gated', 'never launch from an in-memory `queue_task()` result alone'):
            self.assertIn(term, skill)
        for term in ('parent authority', 'capability-gated', 'sequential fallback', 'isolated branch/worktree', 'duplicate-launch', 'unintegrated', 'terminal-state'):
            self.assertIn(term, ref)
        self.assertIn('managed executor pool', readme)
        self.assertIn('never fabricate subagents', readme)


    def test_pressure_numbering_is_continuous_through_101(self):
        text = (ROOT / 'tests' / 'pressure-scenarios.md').read_text()
        numbers = [int(x) for x in re.findall('(?m)^## (\\d+)\\.', text)]
        self.assertEqual(numbers, list(range(1, 107)))

    def test_guidance_preserves_authority_boundary(self):
        ref = (ROOT / 'references' / 'managed-executor-pool.md').read_text().lower()
        for term in ('shared-branch write', 'merge', 'release', 'scope-expansion', 'scheduler-mutation', 'user-approval'):
            self.assertIn(term, ref)

    def test_failure_isolation_and_fallback_are_explicit(self):
        ref = (ROOT / 'references' / 'managed-executor-pool.md').read_text().lower()
        self.assertIn('failure of one worker does not cancel unrelated independent work', ref)
        self.assertIn('same managed pool plan', ref)
        self.assertIn('never fabricate subagents', ref)
        self.assertIn('requires_reexecution=false', ref)
