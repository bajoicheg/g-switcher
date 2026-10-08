"""Load the exact frozen candidate only under its fresh managed submission claim."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from github_api import api, archive, member
from admission import BASE, RESULT


def validate_child(admission, inputs, run_id, run_attempt, job_id):
    assert admission['run_id'] == int(run_id)
    assert admission['run_attempt'] == int(run_attempt) == 1
    assert admission['job_id'] == job_id
    assert admission['grant_id'] == inputs['grant_id']
    assert admission['operation_key'] == inputs['operation_key']


def main():
    inputs = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['inputs']
    assert inputs['candidate_sha'] == RESULT
    repo = Path.cwd()

    def git(*args):
        result = subprocess.run(['git', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=40)
        if result.returncode:
            raise RuntimeError('Windows bundle Git operation failed: ' + args[0])
        return result.stdout.strip()

    assert git('rev-parse', 'HEAD') == BASE and not git('status', '--porcelain')
    assert git('rev-parse', BASE + ':.agents/skills/continuous-development-cycle') == '9c45d98c3254e9658d452c505d8c97698e3fc9a7'
    sys.path.insert(0, str(repo / '.agents/skills/continuous-development-cycle/scripts'))
    import execution_lease_v2 as leasev2

    def read_lease():
        ref = api('git/ref/heads/cdc/coordination')['object']['sha']
        payload = api('contents/lease.json?ref=' + ref)
        record = json.loads(base64.b64decode(payload['content']))
        assert api('git/ref/heads/cdc/coordination')['object']['sha'] == ref
        leasev2.validate(record)
        assert record['owner_id'] == inputs['owner_id']
        assert record['generation'] == int(inputs['generation']) == 32
        assert record['invocation']['invocation_id'] == inputs['invocation_id']
        assert record['repository'] == 'bajoicheg/g-switcher'
        assert record['source_ref'] == 'refs/heads/release/2.0.1'
        assert record['finalization']['state'] == 'active'
        assert datetime.now(timezone.utc) < datetime.fromisoformat(record['expires_at_utc'].replace('Z', '+00:00'))
        guard = record['external_guard']
        assert guard is not None and guard['operation_key'] == inputs['operation_key']
        assert guard['intent']['attempt_id'] == inputs['attempt_id']
        assert guard['intent']['binding']['candidate_sha'] == RESULT
        assert guard['intent']['binding']['mode'] == 'CI_ONLY'
        assert guard['submission_claim']['grant_id'] == inputs['grant_id']
        assert guard['submission_claim']['intent_digest'] == guard['intent_digest']
        assert guard['submission_claim']['owner_id'] == record['owner_id']
        assert guard['submission_claim']['generation'] == record['generation']
        assert api('git/ref/heads/release/2.0.1')['object']['sha'] == BASE
        return guard

    guard = read_lease()
    # Read the exact durable intent object, not the mutable current operation ref.
    intent_commit = guard['intent_reference'].split(':')[1]
    document = json.loads(base64.b64decode(api('contents/document.json?ref=' + intent_commit)['content']))
    assert document['intent'] == guard['intent']
    assert document['windows_head'] == os.environ['GITHUB_SHA']
    assert document['bundle_artifact']['id'] == int(inputs['bundle_artifact_id'])
    assert document['bundle_artifact']['digest'] == inputs['bundle_artifact_digest']
    assert document['bundle_sha256'] == inputs['bundle_sha256']
    operation_ref = document['operation_store_ref'].removeprefix('refs/')
    run_id = os.environ['GITHUB_RUN_ID']
    run_attempt = os.environ['GITHUB_RUN_ATTEMPT']
    assert int(run_attempt) == 1
    jobs = api('actions/runs/' + run_id + '/attempts/1/jobs?per_page=100')
    assert jobs['total_count'] == 1
    job_id = jobs['jobs'][0]['id']

    def admitted_child():
        revision = api('git/ref/' + operation_ref)['object']['sha']
        live = json.loads(base64.b64decode(api('contents/document.json?ref=' + revision)['content']))
        assert api('git/ref/' + operation_ref)['object']['sha'] == revision
        assert live['intent'] == document['intent']
        assert live['windows_head'] == os.environ['GITHUB_SHA']
        admission = live.get('child_admission')
        if admission is not None:
            validate_child(admission, inputs, run_id, run_attempt, job_id)
        return admission

    deadline = time.monotonic() + 180
    while admitted_child() is None:
        read_lease()
        assert time.monotonic() < deadline, 'Parent did not admit this exact child run'
        time.sleep(3)
    artifact = api('actions/artifacts/' + inputs['bundle_artifact_id'])
    assert artifact['digest'] == inputs['bundle_artifact_digest']
    data = archive(artifact['id'])
    assert hashlib.sha256(data).hexdigest() == artifact['digest'].removeprefix('sha256:')
    bundle = member(data, 'result.bundle')
    assert hashlib.sha256(bundle).hexdigest() == inputs['bundle_sha256']
    path = Path(os.environ['RUNNER_TEMP']) / ('word-exact-' + inputs['bundle_artifact_id'] + '.bundle')
    path.write_bytes(bundle)
    git('bundle', 'verify', str(path))
    git('fetch', '--no-tags', str(path), 'refs/heads/cdc/reconstructed-word-diagnostic')
    git('checkout', '--detach', RESULT)
    assert git('rev-parse', 'HEAD') == RESULT and not git('status', '--porcelain')
    assert admitted_child() is not None
    read_lease()  # Recheck source/owner/claim after download and directly before product checks.
    print('WORD_BUNDLE_GATE_PASS candidate=' + RESULT + ' operation=' + inputs['operation_key'] +
          ' grant=' + inputs['grant_id'] + ' run=' + run_id + ' attempt=' + run_attempt, flush=True)


if __name__ == '__main__':
    main()
