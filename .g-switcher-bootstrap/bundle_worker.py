"""Reuse the authenticated exact validated result; no compile/reconstruction replay."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from admission import BASE, RESULT
from github_api import api, archive, member


def main():
    root = Path(__file__).resolve().parent
    pinned = json.loads((root / 'host-launch-intent.json').read_text())['reused_bundle']
    info = api('actions/artifacts/' + str(pinned['artifact_id']))
    assert info['workflow_run']['id'] == pinned['run_id']
    assert info['workflow_run']['head_sha'] == pinned['host_head']
    assert info['digest'] == pinned['archive_digest']
    data = archive(info['id'])
    assert 'sha256:' + hashlib.sha256(data).hexdigest() == pinned['archive_digest']
    bundle = member(data, 'result.bundle')
    assert hashlib.sha256(bundle).hexdigest() == pinned['bundle_sha256']
    report = json.loads(member(data, 'preflight.json'))
    assert report['source'] == BASE and report['result'] == RESULT
    assert report['exact_result_reconstructed'] is True and report['bundle_sha256'] == pinned['bundle_sha256']
    output = Path(os.environ['CDC_PREFLIGHT_OUTPUT'])
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'result.bundle'
    path.write_bytes(bundle)
    check = subprocess.run(['git', '-C', os.environ['CDC_REPO_ROOT'], 'bundle', 'verify', str(path)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert check.returncode == 0, 'Authenticated bundle prerequisites unavailable'
    for relative in ['src/windows_runtime/word_native.rs', 'docs/work-status/word-refusal-diagnostics-2026-10-08.json']:
        target = output / 'formatted' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(member(data, 'formatted/' + relative))
    report.update(reused_bundle_authenticated=True, prior_bundle_artifact=pinned['artifact_id'],
                  validation_repeated=False, reconstruction_repeated=False)
    (output / 'preflight.json').write_text(json.dumps(report, indent=2) + '\n')
    print('EXACT_VALIDATED_BUNDLE_REUSED candidate=' + RESULT, flush=True)
