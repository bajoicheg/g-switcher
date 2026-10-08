import re

BASE = '10b7e90dfa9521170c48d9f09e2c5a4d6d77c3c3'
RESULT = '3407a2d0570b88864fd265de61a8761999995380'
OWNER = '3c7f5381-2337-43bc-8f63-b641919be891'
INVOCATION = 'managed-terminal:1357602ce612f10f0b63b51ae19c7445687c092a4c5e5306e5f5a46c2a2a95db'
OPERATION = 'sha256:7709e357e72fc251281692f140ab79b8bff206d1898928f3c7a8f7115613ed80'


def authorize_previous(lease, publication, receipt, job, logs, source):
    """Validate freshly authenticated observations; never infer stopped from TTL."""
    def require(value):
        if not value:
            raise ValueError('Exact stopped generation31 admission failed')
    require(source == BASE)
    require(lease['repository'] == 'bajoicheg/g-switcher')
    require(lease['source_ref'] == 'refs/heads/release/2.0.1')
    require(lease['generation'] == 31 and lease['owner_id'] == OWNER)
    require(lease['invocation']['invocation_id'] == INVOCATION)
    require(lease['external_guard'] is None)
    require(lease['finalization']['state'] == 'active')
    require(lease['finalization']['pending_shared_writes'] is False)
    resolved = {x['grant_id'] for x in lease.get('submission_resolutions', [])}
    require(not any(x['generation'] == 31 and x['owner_id'] == OWNER and x['grant_id'] not in resolved
                    for x in lease['submission_claims']))
    require(job['id'] == 113331980853 and job['run_id'] == 37783419838)
    require(job['status'] == 'completed' and job['conclusion'] == 'failure' and job['completed_at'])
    require(receipt['supervisor_pid'] == 2943 and receipt['supervisor_proc_pid'] == 2943)
    require(receipt['supervisor_birth'] == '12670')
    require(receipt['boot_id'] == 'f743bd11-fb6d-40b9-bdfa-5329bf88e30b')
    require(receipt['worker_pid'] == 2976 and receipt['exit_code'] == 0)
    require(receipt['status'] == 'awaiting_release' and receipt['pending_terminal_status'] == 'succeeded')
    require(receipt['quiescent'] is False)
    require(receipt['identity']['parent_invocation_id'] == 'github-actions:37783419838:1')
    require(receipt['identity']['task_id'] == 'word-refusal-diagnostics')
    require(receipt['identity']['attempt_id'] == 'word-native-37783419838-1-a1')
    require(receipt['identity']['base_sha'] == BASE)
    require(receipt['launch_id'] == 'sha256:29421754e0e3a0b656759478a349498575bfd1afc0512bc8e4a5fbcbf52c4c53')
    # Canonical awaiting_release is emitted only after waitpid(ECHILD), so all worker descendants were drained.
    # The authenticated parent-job cleanup then stops that remaining exact supervisor.
    require(re.search(r'Terminate orphan process: pid \(2943\) \(python\)', logs) is not None)
    require(publication['schema'] == 'project-lane-publication-attempts/v1')
    require(publication['shared_ref'] == lease['source_ref'])
    require(set(publication['attempts']) == {OPERATION})
    attempt = publication['attempts'][OPERATION]
    require(attempt['status'] == 'rejected' and attempt['resolved_at_utc'])
    require(attempt['observed_shared_head'] == BASE and attempt['result_commit'] == RESULT)
    return {'owner_id': OWNER, 'generation': 31, 'repository': lease['repository'],
            'source_ref': lease['source_ref'], 'invocation_id': INVOCATION,
            'kind': 'executor_stopped',
            'reference': 'https://github.com/bajoicheg/g-switcher/actions/runs/37783419838/job/113331980853#exact-cleanup2943-and-authenticated-artifact11552529665',
            'pending_shared_writes': False, 'external_effects_state': 'reconciled'}
