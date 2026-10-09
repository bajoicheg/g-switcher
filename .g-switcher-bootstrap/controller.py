"""Authorized host bootstrap; package-owned capability, guard, CI and release."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone

from constants import BASE, EXPECTED_GENERATION
from github_api import api, archive, member, REPO

PACKAGE = '9c45d98c3254e9658d452c505d8c97698e3fc9a7'
SOURCE = 'refs/heads/release/2.0.1'
LEASE = 'refs/heads/cdc/coordination'
OLD_PUBLICATION = 'refs/heads/cdc/managed-host-publish-eef54c384ecb5248873f80618b1d658c'
OLD_ARTIFACT_DIGEST = '627b2e11482720a22bd8b5812d969d55687b7e14df7e450509a176e0456ff109'


def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def prepare_validation_intent(operation, binding, attempt):
    return operation.prepare(binding, attempt, SOURCE, utc())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def git(repo, *args):
    process = subprocess.run(['git', '-C', str(repo), *args], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, timeout=30)
    if process.returncode:
        raise RuntimeError('Git host operation failed: ' + args[0])
    return process.stdout.strip()


def main():
    root = Path(__file__).resolve().parent
    RESULT = None
    repo = Path(os.environ['CDC_REPO_ROOT']).resolve()
    run = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    key = 'word-bootstrap-' + run + '-' + attempt
    work = Path(os.environ['RUNNER_TEMP']) / key
    protocol = work / 'protocol'
    output = work / 'recovered'
    handles = work / 'handles'
    journal = work / 'journal'
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repo / '.agents/skills/continuous-development-cycle/scripts'))
    import managed_host_bridge as bridge
    import managed_executor_pool as pool
    import execution_lease_v2 as leasev2
    import operation_intent as operation
    import budget
    from git_lease_store import GitLeaseStore
    from git_document_store import GitDocumentStore
    from git_remote_identity import remote_identity

    assert git(repo, 'rev-parse', 'HEAD') == BASE
    assert not git(repo, 'status', '--porcelain')
    assert git(repo, 'rev-parse', BASE + ':.agents/skills/continuous-development-cycle') == PACKAGE
    git(repo, 'config', 'core.logAllRefUpdates', 'true')
    source_id = remote_identity(repo, 'origin')
    lease_store = GitLeaseStore(repo, 'origin', LEASE)
    pinned = json.loads((root / 'host-launch-intent.json').read_text())
    # Exact canonical types are preserved. Only the supported acquisition argument is supplied by this host adapter.
    from runtime_factory import make_runtime_factory
    def authenticate(store, revision, repository, source_ref, owner_id, task_id, attempt_id, at):
        current_revision, current = store.read()
        assert current_revision == revision == pinned['prior_release_revision']
        leasev2.validate(current)
        assert current['generation'] == pinned['prior_generation'] == EXPECTED_GENERATION - 1
        assert current['owner_id'] is None and current['invocation'] is None
        assert current['external_guard'] == pinned['prior_external_guard'] and current['finalization'] is None
        assert current['last_release'] == pinned['prior_release']
        assert current['repository'] == REPO and current['source_ref'] == SOURCE
        assert bridge._remote_head(repo, 'origin', SOURCE) == BASE
        write(protocol / 'authenticated-prior-release.json',
              {'lease_revision': revision, 'last_release': current['last_release'], 'checked_at_utc': utc()})
        assert store.read() == (revision, current)
        return None  # Ordinary canonical acquisition from an already released lease.
    bridge.ManagedExecutorRuntime = make_runtime_factory(bridge.ManagedExecutorRuntime, authenticate, lease_ttl=45 * 60)

    for name in pinned['payload_sha256']:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == pinned['payload_sha256'][name]
    # A durable host-only one-use CAS binds the bootstrap to its actual Actions run.
    assert attempt == '1'
    bootstrap_store = GitDocumentStore(repo, 'origin', pinned['bootstrap_admission_ref'], source_id,
        protected_refs=[SOURCE, LEASE, pinned['windows_ref']])
    bootstrap_revision, bootstrap = bootstrap_store.read()
    assert bootstrap['state'] == 'prepared' and bootstrap.get('host_admission') is None
    assert bootstrap['host_head'] == os.environ['GITHUB_SHA']
    assert bootstrap['intent_sha256'] == hashlib.sha256((root / 'host-launch-intent.json').read_bytes()).hexdigest()
    assert bootstrap['budget_ledger'] == pinned['budget_ledger']
    assert bridge._remote_head(repo, 'origin', SOURCE) == BASE
    bootstrap.update(state='claimed', host_admission={'run_id': int(run), 'run_attempt': 1,
        'host_head': os.environ['GITHUB_SHA'], 'claimed_at_utc': utc()})
    bootstrap_revision = bootstrap_store.compare_and_swap(bootstrap_revision, bootstrap)
    assert bootstrap_store.read() == (bootstrap_revision, bootstrap)
    write(protocol / 'bootstrap-admission.json', bootstrap)
    plan = {'schema': 'managed-executor-pool-plan/v1', 'pool_id': key,
            'change_id': 'Word-restart-persistent-provider-admission',
            'parent_invocation_id': 'github-actions:' + run + ':' + attempt,
            'base_sha': BASE, 'integrator_id': 'canonical-managed-host-bridge',
            'coordination_ref': 'refs/heads/cdc/managed-word-bootstrap/' + key,
            'coordination_store_id': source_id, 'max_parallel': 1,
            'total_runtime_budget_seconds': 40 * 60, 'total_cost_budget_units': 1,
            'tasks': [{'id': 'word-broker-isolation', 'role': 'writer', 'required': True,
                       'dependencies': [], 'executor_id': 'managed-word-diagnostic-recovery',
                       'branch': 'cdc/word-restart-worker/' + key, 'worktree': 'word-restart-writer-' + run,
                       'write_paths': pinned['write_paths'],
                       'expected_outputs': ['out:word-broker-isolation-bundle'],
                       'expected_evidence': ['evidence:Word-broker-isolation-Windows'],
                       'backend_preferences': ['local_command'], 'max_runtime_seconds': 40 * 60,
                       'max_cost_units': 1}]}
    pool.validate_plan(plan)
    os.environ['CDC_PREFLIGHT_OUTPUT'] = str(output)
    request = {'schema': 'managed-host-start/v1', 'repo_root': str(repo), 'remote': 'origin',
               'plan': plan, 'journal_root': str(journal), 'handle_root': str(handles),
               'lease_coordination_ref': LEASE, 'lease_repository': REPO,
               'lease_source_ref': SOURCE, 'task_id': 'word-broker-isolation',
               'attempt_id': key + '-a1', 'reservation_token': 'reserve:' + key,
               'owner_id': str(uuid.uuid4()), 'argv': [sys.executable, '-B', str(root / 'worker.py')]}
    write(protocol / 'start.json', request)
    handle = None
    success = False
    conclusion = None
    try:
        handle = bridge.start(request)
        write(protocol / 'handle.json', handle)
        assert handle['generation'] == pinned['expected_generation'] == EXPECTED_GENERATION
        assert source_id == pinned['coordination_store_id']
        write(output / 'controller-admitted.json', {'owned_generation': handle['generation']})
        observe = {'schema': 'managed-host-observe/v1', 'handle_root': str(handles), 'handle_id': handle['handle_id']}
        deadline = time.monotonic() + 35 * 60
        while not (output / 'bundle-ready.json').exists():
            state = bridge.observe(observe)
            write(protocol / 'observed.json', state)
            if state.get('runtime_status') == 'awaiting_release':
                raise RuntimeError('Reconstruction worker exited before validated bundle readiness')
            assert time.monotonic() < deadline, 'Reconstruction deadline'
            time.sleep(3)
        recovery = json.loads((output / 'preflight.json').read_text())
        RESULT = recovery['result']
        assert re.fullmatch(r'[0-9a-f]{40}', RESULT) and RESULT != BASE
        assert recovery['source'] == BASE and recovery['owned_worker_checks_passed']
        assert recovery['write_paths'] == pinned['write_paths']
        bundle_digest = hashlib.sha256((output / 'result.bundle').read_bytes()).hexdigest()
        assert bundle_digest == recovery['bundle_sha256']
        write(output / 'upload-ready.json', {'candidate': RESULT, 'bundle_sha256': bundle_digest,
                                            'generation': handle['generation']})

        # Official upload-artifact is a host output-transport step while this controller and supervisor stay live.
        artifact_name = 'word-exact-diagnostic-bundle-' + run + '-' + attempt
        while True:
            listing = api('actions/runs/' + run + '/artifacts?per_page=100')
            assert listing['total_count'] <= 100
            matches = [a for a in listing['artifacts'] if a['name'] == artifact_name]
            if matches:
                assert len(matches) == 1
                artifact = matches[0]
                break
            assert time.monotonic() < deadline, 'Bundle upload deadline'
            time.sleep(5)
        uploaded = archive(artifact['id'])
        assert hashlib.sha256(uploaded).hexdigest() == artifact['digest'].removeprefix('sha256:')
        assert hashlib.sha256(member(uploaded, 'result.bundle')).hexdigest() == bundle_digest

        # Persist intent, budget, readbacks, then consume the canonical one-use guard claim.
        operation_store = GitDocumentStore(repo, 'origin', 'refs/heads/cdc/word-diagnostic-operation/' + key,
                                           source_id, protected_refs=[SOURCE, LEASE, plan['coordination_ref']])
        contract = pinned['windows_contract']
        binding = {'repository': REPO, 'candidate_sha': RESULT, 'backend': 'github_actions',
                   'mode': 'CI_ONLY', 'check_suite_fingerprint': operation._hash(contract['steps']),
                   'environment_fingerprint': operation._hash(contract['environment']),
                   'check_plan_digest': operation._hash(contract), 'environment_id': 'windows-latest/rust1.98.1'}
        intent = prepare_validation_intent(operation, binding, key + '-windows-a1')
        ledger = pinned['budget_ledger']
        reservation = {'type': 'reserve', 'event_id': key + '-windows-ci', 'task_id': ledger['task_id'],
                       'wake_id': ledger['wake_ids'][-1], 'at_utc': utc(), 'operation_key': intent['operation_key'],
                       'attempt_id': intent['attempt_id'], 'kind': 'ci_start',
                       'scope': 'github-actions/g-switcher/exact-word-diagnostic-windows',
                       'recovery_ref': pinned['windows_recovery_ref'], 'cost': {'tool_calls': 1, 'tokens': None, 'elapsed_seconds': None}}
        decision = budget.decide(ledger, reservation)
        assert decision['allow_reservation'], decision
        ledger = budget.apply_event(ledger, reservation)
        document = {'schema': 'word-diagnostic-validation-operation/v1', 'intent': intent,
                    'budget_ledger': ledger, 'bundle_artifact': artifact, 'bundle_sha256': bundle_digest,
                    'contract': contract, 'managed_handle': handle, 'windows_head': pinned['windows_head'], 'operation_store_ref': operation_store.ref, 'state': 'prepared'}
        revision = operation_store.compare_and_swap(None, document)
        read_revision, readback = operation_store.read()
        assert read_revision == revision and readback == document
        receipt = operation.verify_readback(intent, readback['intent'], 'git:' + revision + ':document.json', utc())
        intent = operation.transition(intent, 'submitting', utc(), receipt=receipt)
        document.update(intent=intent, state='submitting')
        revision = operation_store.compare_and_swap(revision, document)
        read_revision, readback = operation_store.read()
        assert read_revision == revision and readback == document
        lease_revision, live = lease_store.read()
        assert live['owner_id'] == handle['owner_id'] and live['generation'] == handle['generation']
        assert bridge._remote_head(repo, 'origin', SOURCE) == BASE
        live = leasev2.set_guard(live, handle['owner_id'], handle['generation'], handle['invocation_id'],
                                 utc(), intent, 'git:' + revision + ':document.json')
        lease_revision = lease_store.compare_and_swap(lease_revision, live)
        claim = leasev2.claim_submission(lease_store, lease_revision, REPO, SOURCE, handle['owner_id'],
                                       handle['generation'], handle['invocation_id'], utc(),
                                       intent_digest=operation._hash(intent))
        fresh_revision, fresh = lease_store.read()
        assert fresh_revision == claim['revision'] and fresh['external_guard']['submission_claim'] == claim['grant']
        assert bridge._remote_head(repo, 'origin', SOURCE) == BASE
        inputs = {'bundle_artifact_id': str(artifact['id']), 'bundle_artifact_digest': artifact['digest'],
                  'bundle_sha256': bundle_digest, 'operation_key': intent['operation_key'],
                  'attempt_id': intent['attempt_id'], 'grant_id': claim['grant']['grant_id'],
                  'owner_id': handle['owner_id'], 'generation': str(handle['generation']),
                  'invocation_id': handle['invocation_id'], 'candidate_sha': RESULT}
        # This is the fresh returned claim only, not a reconstructed saved grant.
        api('actions/workflows/windows-ci.yml/dispatches', method='POST',
            data={'ref': pinned['windows_ref'].removeprefix('refs/heads/'), 'inputs': inputs})
        document.update(state='submitted', submission_claim=claim['grant'])
        revision = operation_store.compare_and_swap(revision, document)
        write(protocol / 'windows-submitted.json', document)
        known_run = None
        previous_activity = None
        while time.monotonic() < deadline:
            runs = api('actions/workflows/windows-ci.yml/runs?event=workflow_dispatch&branch=' +
                       pinned['windows_ref'].removeprefix('refs/heads/') + '&per_page=100')
            assert runs['total_count'] <= 100
            selected = [r for r in runs['workflow_runs'] if r.get('display_title') == 'Word restart guard ' + intent['attempt_id']]
            if selected:
                assert len(selected) == 1
                child = selected[0]
                if known_run is None:
                    assert child['run_attempt'] == 1
                    child_jobs = api('actions/runs/' + str(child['id']) + '/attempts/1/jobs?per_page=100')
                    assert child_jobs['total_count'] <= 1
                    if child_jobs['total_count'] == 0:
                        write(protocol / 'windows-provisioning.json', child)
                        time.sleep(5)
                        continue
                    document['child_admission'] = {'run_id': child['id'], 'run_attempt': 1,
                        'job_id': child_jobs['jobs'][0]['id'], 'grant_id': claim['grant']['grant_id'],
                        'operation_key': intent['operation_key'], 'admitted_at_utc': utc()}
                    revision = operation_store.compare_and_swap(revision, document)
                    assert operation_store.read() == (revision, document)
                else:
                    assert child['id'] == known_run
                    child = api('actions/runs/' + str(known_run) + '/attempts/1')
                assert child['head_sha'] == pinned['windows_head']
                known_run = child['id']
                write(protocol / 'windows-run.json', child)
                activity = (child['status'], child['updated_at'])
                if activity != previous_activity:
                    lease_revision, live = lease_store.read()
                    live = leasev2.renew(live, handle['owner_id'], handle['generation'], handle['invocation_id'], utc(),
                                          activity_ref='github:' + str(known_run) + ':' + activity[0] + ':' + activity[1], ttl=45 * 60)
                    lease_store.compare_and_swap(lease_revision, live)
                    previous_activity = activity
                    print('WINDOWS_OBSERVED run=' + str(known_run) + ' status=' + child['status'], flush=True)
                if child['status'] == 'completed':
                    break
            time.sleep(15)
        else:
            raise RuntimeError('Windows provider outcome unresolved at recovery deadline')
        assert known_run is not None
        jobs = api('actions/runs/' + str(known_run) + '/attempts/1/jobs?per_page=100')
        assert jobs['total_count'] == 1
        child_job = jobs['jobs'][0]
        assert child_job['status'] == 'completed' and child_job['id'] == document['child_admission']['job_id']
        logs = api('actions/jobs/' + str(child_job['id']) + '/logs', binary=True).decode('utf-8-sig', errors='replace')
        # An authenticated actual gate log independently binds the provider to the leased request and loaded bundle.
        marker = 'WORD_BUNDLE_GATE_PASS candidate=' + RESULT + ' operation=' + intent['operation_key'] + ' grant=' + claim['grant']['grant_id'] + ' run=' + str(known_run) + ' attempt=1'
        candidate_admitted = marker in logs
        by_name = {s['name']: s for s in child_job['steps']}
        mandatory_steps_verified = all(by_name.get(s['name'], {}).get('conclusion') == 'success' for s in contract['steps'])
        missing_fixture_tests = [name for name in pinned['required_windows_tests'] if '::' + name + ' ... ok' not in logs]
        fixture_gates_verified = not missing_fixture_tests
        write(protocol / 'broker-windows-fixture-evidence.json', {'candidate':RESULT,'run_id':known_run,'job_id':child_job['id'],'mandatory_steps_verified':mandatory_steps_verified,'fixture_gates_verified':fixture_gates_verified,'missing_fixture_tests':missing_fixture_tests,'test_boundary':'actual applied fixtures; installed Word pending'})
        if not candidate_admitted:
            request_marker = marker.replace('WORD_BUNDLE_GATE_PASS', 'WORD_BUNDLE_GATE_REQUEST')
            by_name = {s['name']: s for s in child_job['steps']}
            assert request_marker in logs and child['conclusion'] == 'failure'
            assert by_name['Admit exact one-use child and load verified bundle']['conclusion'] == 'failure'
            assert all(by_name[s['name']]['conclusion'] == 'skipped' for s in contract['steps'])
            conclusion = 'setup_failed'  # Requested CI failed before candidate admission; no validation success.
        else:
            conclusion = 'succeeded' if child['conclusion'] == 'success' and mandatory_steps_verified and fixture_gates_verified else (
                'cancelled' if child['conclusion'] == 'cancelled' else 'failed')
        task = {'task_id': str(known_run) + ':1', 'task_url': child['html_url'], 'operation_key': intent['operation_key'],
                'attempt_id': intent['attempt_id'], 'binding': binding, 'state': 'terminal',
                'conclusion': conclusion, 'evidence_refs': [child['html_url'],
                    'https://github.com/' + REPO + '/actions/runs/' + str(known_run) + '/job/' + str(child_job['id'])]}
        observation = {'schema': 'operation-observation/v1', 'operation_key': intent['operation_key'],
                       'observed_at_utc': utc(), 'lookup_complete': True, 'tasks': [task]}
        ledger = budget.apply_event(ledger, {'type': 'outcome', 'event_id': key + '-windows-outcome',
            'task_id': ledger['task_id'], 'wake_id': ledger['wake_ids'][-1], 'at_utc': utc(),
            'reservation_id': reservation['event_id'], 'status': conclusion,
            'failure': None if conclusion in {'succeeded','cancelled'} else {'category':'code' if candidate_admitted else 'configuration',
            'signature':'Windows-required-broker-fixture-missing' if candidate_admitted and child['conclusion']=='success' and not fixture_gates_verified else ('Windows-candidate-check-failed' if candidate_admitted else 'Windows-admission-failed')},
            'usage': {'tokens':None, 'elapsed_seconds':None}})
        document.update(budget_ledger=ledger, state='terminal', terminal_observation=observation,
                        windows_run=child, windows_job=child_job, actual_gate_marker=marker if candidate_admitted else request_marker,
                        candidate_admitted=candidate_admitted, candidate_validation_succeeded=conclusion == 'succeeded',
                        mandatory_steps_verified=mandatory_steps_verified,fixture_gates_verified=fixture_gates_verified,missing_fixture_tests=missing_fixture_tests)
        revision = operation_store.compare_and_swap(revision, document)
        read_revision, readback = operation_store.read()
        assert read_revision == revision and readback == document
        lease_revision, live = lease_store.read()
        live = leasev2.clear_guard(live, handle['owner_id'], handle['generation'], handle['invocation_id'],
                                   utc(), observation, 'git:' + revision + ':document.json')
        lease_store.compare_and_swap(lease_revision, live)
        write(output / 'windows-terminal.json', {'candidate': RESULT, 'external_guard_reconciled': True,
                                                  'windows_run_id': known_run, 'conclusion': conclusion})
        while True:
            state = bridge.observe(observe)
            write(protocol / 'observed.json', state)
            if state.get('runtime_status') == 'awaiting_release':
                assert state['pending_terminal_status'] == 'succeeded'
                break
            assert time.monotonic() < deadline
            time.sleep(2)
        finished = bridge.finish({'schema': 'managed-host-finish/v1', 'handle_root': str(handles),
                                  'handle_id': handle['handle_id'], 'output_refs': ['out:word-broker-isolation-bundle'],
                                  'evidence_refs': ['evidence:Word-broker-isolation-Windows', child['html_url']],
                                  'checkpoint_ref': 'git:' + revision + ':document.json'})
        write(protocol / 'finished.json', finished)
        assert finished['final_response_allowed'] and finished['published_commit'] == RESULT
        success = True
        print('MANAGED_RECOVERY_RELEASED generation=' + str(handle['generation']) + ' windows_run=' + str(known_run), flush=True)
        return 0 if conclusion == 'succeeded' else 1
    finally:
        if not success and handle is not None:
            write(output / 'abort-worker.json', {'reason': 'Controller could not prove terminal validation'})
            observe = {'schema': 'managed-host-observe/v1', 'handle_root': str(handles), 'handle_id': handle['handle_id']}
            end = time.monotonic() + 50
            while time.monotonic() < end:
                state = bridge.observe(observe)
                if state.get('runtime_status') == 'awaiting_release':
                    status = state.get('pending_terminal_status')
                    if status in {'failed', 'cancelled', 'timed_out'}:
                        result = bridge.finish({'schema': 'managed-host-finish/v1', 'handle_root': str(handles),
                            'handle_id': handle['handle_id'], 'output_refs': ['failure:worker:' + status],
                            'evidence_refs': ['failure:managed-recovery-incomplete'], 'checkpoint_ref': None})
                        write(protocol / 'failure-finished.json', result)
                    break
                time.sleep(2)
        write(work / 'controller-result.json', {'controller_scope_complete': success, 'windows_conclusion': conclusion, 'completed_at_utc': utc()})


if __name__ == '__main__':
    raise SystemExit(main())
