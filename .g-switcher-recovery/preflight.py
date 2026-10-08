"""Read-only recovery: reconstruct exact lost candidate, preserve it, probe transport."""
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

BASE = '10b7e90dfa9521170c48d9f09e2c5a4d6d77c3c3'
RESULT = '3407a2d0570b88864fd265de61a8761999995380'
REPO = 'bajoicheg/g-switcher'
SOURCE = 'refs/heads/release/2.0.1'
WORKER_HASH = '04a9e38ec5ed9f4e3ccec1425a41303b06639b0280340c2bdef7eae987e70ee5'


def commit_bytes(tree, parent, author_time, committer_time):
    identity = 'G-switcher managed executor <g-switcher@example.invalid>'
    return (f'tree {tree}\nparent {parent}\nauthor {identity} {author_time} +0000\n'
            f'committer {identity} {committer_time} +0000\n\n'
            '[skip ci] diagnose Word mutation refusal and pending native calls\n').encode()


def object_sha(kind, data):
    return hashlib.sha1(f'{kind} {len(data)}\0'.encode() + data).hexdigest()


def rejection_class(stdout, stderr):
    # Never retain raw transport text: it may contain credentials or endpoints.
    value = (stdout + '\n' + stderr).casefold()
    for needle, label in [('stale info', 'stale_info'), ('non-fast-forward', 'non_fast_forward'),
                          ('shallow update', 'shallow_update'), ('workflow', 'workflow_permission'),
                          ('protected branch', 'protected_branch'), ('repository rule', 'repository_rule'),
                          ('permission', 'permission'), ('authentication', 'authentication')]:
        if needle in value:
            return label
    return 'unclassified_transport_rejection'


def main():
    root = Path(__file__).resolve().parent
    repo = Path(os.environ['CDC_REPO_ROOT']).resolve()
    output = Path(os.environ['CDC_PREFLIGHT_OUTPUT']).resolve()
    output.mkdir(parents=True, exist_ok=True)

    def git(cwd, *args, data=None):
        result = subprocess.run(['git', '-C', str(cwd), *args], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if result.returncode:
            raise RuntimeError('Local Git operation failed: ' + args[0])
        return result.stdout.decode().strip()

    assert git(repo, 'rev-parse', 'HEAD') == BASE
    assert not git(repo, 'status', '--porcelain')
    assert git(repo, 'rev-parse', BASE + ':.agents/skills/continuous-development-cycle') == '9c45d98c3254e9658d452c505d8c97698e3fc9a7'
    # Authenticate the original job's terminal host cleanup, without exposing token/log.
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/actions/jobs/113331980853',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        job = json.load(response)
    assert job['run_id'] == 37783419838 and job['status'] == 'completed' and job['conclusion'] == 'failure'
    assert job['completed_at'] is not None
    artifact_request = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/actions/artifacts/11552529665',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(artifact_request, timeout=30) as response:
        artifact = json.load(response)
    assert artifact['id'] == 11552529665
    assert artifact['digest'] == 'sha256:627b2e11482720a22bd8b5812d969d55687b7e14df7e450509a176e0456ff109'
    assert artifact['workflow_run']['id'] == 37783419838
    assert artifact['workflow_run']['head_sha'] == '8f548515ec2cd57a2ed99160978ba975c9e52fd7'

    worker = (root / 'original-worker.py').read_bytes()
    assert hashlib.sha256(worker).hexdigest() == WORKER_HASH
    statements = ast.parse(worker).body[:3]
    values = {n.targets[0].id: ast.literal_eval(n.value) for n in statements}
    manifest, files = values['MANIFEST'], values['FILES']
    evidence_hashes = {'checks.json': 'ac2e93b0bd2d87265713dc92d071673f04f04fdc68de0aace2700ccbfb7549b9', 'result.json': '17511970d1c9e3ad68e656e88c08884112b95dbdf0f36467d031735f38205950'}
    for name, expected in evidence_hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, 'Original evidence drift'
    checks = json.loads((root / 'checks.json').read_text())
    result = json.loads((root / 'result.json').read_text())
    assert result['result_commit'] == RESULT and result['source_base'] == BASE
    assert checks == result['checks'] and len(checks) == 5 and all(x['exit_code'] == 0 for x in checks)
    cwd = Path(tempfile.mkdtemp(prefix='word-result-reconstruction-', dir=os.environ['RUNNER_TEMP'])) / 'worktree'
    git(repo, 'worktree', 'add', '--detach', str(cwd), BASE)
    for relative, content in files.items():
        original = manifest['original_sha256'][relative]
        path = cwd / relative
        assert (not path.exists()) if original is None else hashlib.sha256(path.read_bytes()).hexdigest() == original
        assert hashlib.sha256(content.encode()).hexdigest() == manifest['payload_sha256'][relative]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(['rustfmt', '+1.98.1', '--edition', '2021', '--config', 'skip_children=true',
                    'src/windows_runtime/word_native.rs'], cwd=cwd, check=True)
    status_path = cwd / 'docs/work-status/word-refusal-diagnostics-2026-10-08.json'
    record = json.loads(status_path.read_text())
    record.update(managed_validation=checks, installed_word_latency_measured=False)
    status_path.write_text(json.dumps(record, indent=2) + '\n')
    git(cwd, 'add', '--', *manifest['paths'])
    assert set(git(cwd, 'diff', '--cached', '--name-only').splitlines()) == set(manifest['paths'])
    git(cwd, 'diff', '--cached', '--check')
    tree = git(cwd, 'write-tree')
    # Hash matching authenticates every Git byte; timestamps are bounded by original worker lifetime.
    low = int(datetime.datetime.fromisoformat('2026-10-08T13:19:49+00:00').timestamp())
    high = int(datetime.datetime.fromisoformat('2026-10-08T13:21:32+00:00').timestamp())
    recovered = None
    for author in range(low, high + 1):
        for committer in range(author, high + 1):
            data = commit_bytes(tree, BASE, author, committer)
            if object_sha('commit', data) == RESULT:
                recovered = data
                break
        if recovered is not None:
            break
    assert recovered is not None, 'Exact validated Git result could not be reconstructed; do not acquire ownership'
    assert git(repo, 'hash-object', '-t', 'commit', '-w', '--stdin', data=recovered) == RESULT
    local_ref = 'refs/heads/cdc/reconstructed-word-diagnostic'
    git(repo, 'update-ref', local_ref, RESULT)
    bundle = output / 'result.bundle'
    git(repo, 'bundle', 'create', str(bundle), local_ref, '^' + BASE)
    git(repo, 'bundle', 'verify', str(bundle))
    for relative in manifest['paths']:
        target = output / 'formatted' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((cwd / relative).read_bytes())

    sys.path.insert(0, str(repo / '.agents/skills/continuous-development-cycle/scripts'))
    from git_remote_identity import isolated_remote_args, remote_identity
    from git_object_integrity import git_object_environment
    config, alias = isolated_remote_args(repo, 'origin', remote_identity(repo, 'origin'))
    assert git(repo, 'ls-remote', '--refs', 'origin', SOURCE) == BASE + '\t' + SOURCE
    dry_run = subprocess.run(['git', '-C', str(repo), *config, '-c', 'push.followTags=false',
                              'push', '--dry-run', '--porcelain', '--force-with-lease=' + SOURCE + ':' + BASE,
                              alias, RESULT + ':' + SOURCE], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, timeout=30, env=git_object_environment(GIT_TERMINAL_PROMPT='0'))
    report = {'schema': 'word-publication-recovery-preflight/v1', 'source': BASE, 'result': RESULT,
              'result_tree': tree, 'original_job_completed_at': job['completed_at'],
              'exact_result_reconstructed': True, 'source_writes': 0, 'lease_mutations': 0,
              'bundle_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(),
              'dry_run_exit': dry_run.returncode,
              'dry_run_reason': 'accepted' if dry_run.returncode == 0 else rejection_class(dry_run.stdout, dry_run.stderr),
              'full_windows_ci': 'not run', 'new_exe': False}
    (output / 'preflight.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    assert git(repo, 'ls-remote', '--refs', 'origin', SOURCE) == BASE + '\t' + SOURCE
    assert dry_run.returncode == 0, 'Read-only publication preflight rejected; preserve sanitized reason and bundle'


if __name__ == '__main__':
    main()
