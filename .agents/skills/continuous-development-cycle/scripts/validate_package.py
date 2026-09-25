#!/usr/bin/env python3
"""Check installed package integrity and validate templates with their actual parsers."""
from pathlib import Path
import json
import re
import sys

sys.dont_write_bytecode = True
from contracts import ContractError, load_yaml, semver
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
from capability_router import validate_registry, validate_request, route as route_backend
from cost_router import validate_policy as validate_cost_policy, validate_context as validate_cost_context, route as route_cost
from recovery_recipes import validate_catalog, validate_diagnosis, select as select_recovery_recipe
from continuation_queue import validate_event, validate_queue, ingest as ingest_continuation
from progress_slo import validate_policy as validate_slo_policy, validate_observation as validate_progress_observation, classify as classify_progress
from version_convergence import validate_target as validate_convergence_target, validate_snapshot as validate_convergence_snapshot, assess as assess_convergence
from control_plane_audit import validate as validate_audit_log, append as append_audit
from fleet_supervisor import validate_registry as validate_fleet_registry, validate_snapshot as validate_fleet_snapshot, assess_fleet
from consumer_lock import validate as validate_consumer_lock

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    'SKILL.md', 'VERSION', 'manifest.json', 'agents/openai.yaml',
    'references/runtime-routing-and-subagents.md', 'references/task-lifecycle.md',
    'references/validation-compute-and-ci.md', 'references/codex-compute.md',
    'references/progress-and-checkpoints.md', 'references/watchdog-recovery-and-migration.md',
    'references/release-management.md', 'references/adapter-schema.md',
    'references/policy-compatibility.md', 'references/command-evidence.md',
    'references/external-operations.md', 'scripts/requirements.txt',
    'scripts/contracts.py', 'scripts/validate_adapter.py', 'scripts/validate_checkpoint.py',
    'scripts/run_checks.py', 'scripts/validate_evidence.py', 'scripts/operation_intent.py',
    'templates/development-cycle.yaml', 'templates/work-status.md',
    'templates/check-plan.json', 'templates/operation-intent.json',
    'templates/watchdog-prompt.md', 'templates/AGENTS.snippet.md',
    'tests/pressure-scenarios.md', 'tests/test_adapter.py', 'tests/test_checkpoint.py',
    'tests/test_evidence.py', 'tests/test_operation_intent.py',
    'references/orchestration-controls.md', 'references/execution-ownership.md',
    'references/bounded-recovery.md', 'references/budget-ledger.md',
    'scripts/execution_lease.py', 'scripts/git_lease_store.py',
    'scripts/recovery.py', 'scripts/budget.py',
    'templates/execution-lease.json', 'templates/external-wait.json',
    'templates/recovery-snapshot.json', 'templates/budget-ledger.json',
    'tests/test_execution_lease.py', 'tests/test_recovery.py',
    'tests/test_budget.py', 'tests/test_orchestration_policy.py',
    'tests/test_v233_guidance.py',
    'scripts/watchdog_health.py', 'templates/watchdog-health.json',
    'tests/test_watchdog_health.py',
    'tests/test_v238_guidance.py',
    'references/control-plane-v2.4.md',
    'scripts/execution_lease_v2.py', 'scripts/execution_continuity.py',
    'scripts/resume_capsule.py', 'scripts/validate_checkpoint_24.py',
    'templates/execution-lease-v2.json', 'templates/execution-continuity.json',
    'templates/resume-capsule.json', 'templates/work-status-v4.md',
    'tests/test_execution_lease_v2.py', 'tests/test_execution_continuity.py',
    'tests/test_resume_capsule.py', 'tests/test_checkpoint_v4.py',
    'tests/test_v240_guidance.py',
    'references/capability-routing.md', 'references/deterministic-recovery.md',
    'references/event-driven-continuation.md',
    'scripts/capability_router.py', 'scripts/recovery_recipes.py', 'scripts/continuation_queue.py',
    'templates/backend-registry.json', 'templates/capability-request.json',
    'templates/recovery-recipes.json', 'templates/recovery-diagnosis.json',
    'templates/continuation-event.json', 'templates/continuation-queue.json',
    'tests/test_capability_router.py', 'tests/test_recovery_recipes.py',
    'tests/test_continuation_queue.py', 'tests/test_v250_guidance.py',
    'references/fleet-supervision.md', 'references/version-convergence.md',
    'references/progress-slo.md', 'references/control-plane-audit.md',
    'scripts/fleet_supervisor.py', 'scripts/version_convergence.py',
    'scripts/progress_slo.py', 'scripts/control_plane_audit.py',
    'templates/fleet-registry.json', 'templates/fleet-project-snapshot.json',
    'templates/version-convergence-target.json', 'templates/version-convergence-snapshot.json',
    'templates/progress-slo-policy.json', 'templates/progress-observation.json',
    'templates/control-plane-audit-log.json',
    'tests/test_fleet_supervisor.py', 'tests/test_version_convergence.py',
    'tests/test_progress_slo.py', 'tests/test_control_plane_audit.py',
    'tests/test_v260_guidance.py', 'tests/test_v26_policy.py',
    'references/canonical-source-and-release.md', 'scripts/consumer_lock.py',
    'templates/consumer-lock.json', 'tests/test_consumer_lock.py',
    'tests/test_v270_guidance.py', 'tests/test_git_lease_store_v2.py',
    'references/cost-aware-routing.md', 'scripts/cost_router.py',
    'templates/cost-routing-policy.json', 'templates/cost-routing-context.json',
    'tests/test_cost_router.py', 'tests/test_v272_guidance.py',
]


def validate():
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    if missing:
        raise ContractError('missing package files: ' + ', '.join(missing))
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
        if term.lower() not in skill.lower():
            raise ContractError('skill contract missing: ' + term)
    adapter = load_yaml(ROOT / 'templates/development-cycle.yaml')
    validate_adapter(adapter, version)
    validate_checkpoint(load_yaml(ROOT / 'templates/work-status.md', frontmatter=True), adapter)
    validate_checkpoint_24(load_yaml(ROOT / 'templates/work-status-v4.md', frontmatter=True), adapter)
    load_plan(ROOT / 'templates/check-plan.json')
    validate_intent(json.loads((ROOT / 'templates/operation-intent.json').read_text()))
    validate_lease(json.loads((ROOT / 'templates/execution-lease.json').read_text()))
    validate_lease_v2(json.loads((ROOT / 'templates/execution-lease-v2.json').read_text()))
    validate_resume_capsule(json.loads((ROOT / 'templates/resume-capsule.json').read_text()))
    continuity = evaluate_continuity(json.loads((ROOT / 'templates/execution-continuity.json').read_text()))
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
