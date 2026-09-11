#!/usr/bin/env python3
"""Explicitly scoped prepare/publish/verify stages for the approved maintenance."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
import rewrite_history as m

REPO = 'bajoicheg/g-switcher'
REMOTE = 'https://github.com/' + REPO + '.git'
BRANCH = 'refs/heads/security/history-privacy-maintenance'
RUN_TO_DELETE = 33607554617
ROOT = Path(os.environ['RUNNER_TEMP']) / 'history-private'
EVIDENCE = ROOT / 'evidence'
SOURCE = Path(__file__).resolve().parent


def checked(args, cwd=None, env=None):
    p = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        # Store diagnostic output locally, but do not print raw payloads in public logs.
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / 'operation-error.log').write_bytes(p.stdout + p.stderr)
        raise RuntimeError('Maintenance command failed; private diagnostics retained')
    return p.stdout


def api(method, path, data=None, allow_missing=False):
    req = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + path,
        data=json.dumps(data).encode() if data is not None else None, method=method,
        headers={'Authorization': 'Bearer '+os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type':'application/json',
                 'X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw=response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if allow_missing and exc.code == 404:
            return 404, None
        raise RuntimeError('Scoped GitHub API operation failed, HTTP '+str(exc.code)) from None


def writable(refs):
    return {k:v for k,v in refs.items() if k.startswith(('refs/heads/','refs/tags/'))}


def live_refs():
    raw=checked(['git','ls-remote','--refs','--heads','--tags',REMOTE])
    return {ref:sha for sha,ref in (line.split() for line in raw.decode().splitlines())}


def confirm_prior_removal():
    status, _ = api('GET', f'actions/runs/{RUN_TO_DELETE}', allow_missing=True)
    if status != 404:
        raise RuntimeError('Previously deleted run is present; refusing an unreviewed deletion')
    return status


def confirm_window():
    status, rules = api('GET', 'rulesets/22084348')
    if status != 200 or rules.get('id') != 22084348 or rules.get('enforcement') != 'disabled':
        raise RuntimeError('Owner-controlled maintenance window is not open')


def prepare():
    confirm_window()
    confirm_prior_removal()
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    original=ROOT/'original.git'
    checked(['git','clone','--mirror',REMOTE,str(original)])
    actual=writable(m.refs(original))
    expected=json.loads((SOURCE/'expected-refs.json').read_text())
    expected[BRANCH]=os.environ['GITHUB_SHA']
    m.require_same_refs(expected,actual)
    (EVIDENCE/'old-run-absence.json').write_text(json.dumps({'run_id':RUN_TO_DELETE,'http_status':404}))
    checked(['git','-C',str(original),'bundle','create',str(EVIDENCE/'original.bundle'),'--all'])
    checked(['git','-C',str(original),'bundle','verify',str(EVIDENCE/'original.bundle')])
    report=m.run(original,ROOT/'rewritten.git',ROOT/'git-filter-repo',EVIDENCE)
    approved=json.loads((SOURCE/'expected-new-refs.json').read_text())
    actual_new=writable(report['refs_after']);actual_new.pop(BRANCH)
    m.require_same_refs(approved,actual_new)
    (EVIDENCE/'approved-push.json').write_text(json.dumps({'old':actual,'new':writable(report['refs_after'])},indent=2))
    # Source configuration is already reviewed; no broad scanner suppression.
    config=m.git(original,'show','refs/heads/main:.gitleaks.toml')
    (ROOT/'gitleaks.toml').write_bytes(config)
    checked([str(ROOT/'gitleaks'),'git',str(ROOT/'rewritten.git'),'--config',str(ROOT/'gitleaks.toml'),
        '--log-opts=--all','--max-decode-depth=2','--redact=100','--no-banner',
        '--ignore-gitleaks-allow','--gitleaks-ignore-path','/dev/null'])
    checked(['git','-C',str(ROOT/'rewritten.git'),'bundle','create',str(EVIDENCE/'rewritten.bundle'),'--all'])
    print('Exact ref preflight, every-commit verification, and secret scan passed. No remote changes yet.')


def publish():
    confirm_window()
    plan=json.loads((EVIDENCE/'approved-push.json').read_text())
    m.require_same_refs(plan['old'],live_refs())
    env=os.environ.copy()
    auth=base64.b64encode(('x-access-token:'+env['GH_TOKEN']).encode()).decode()
    env.update({'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'http.https://github.com/.extraheader',
                'GIT_CONFIG_VALUE_0':'AUTHORIZATION: basic '+auth})
    env.pop('GIT_TRACE',None);env.pop('GIT_CURL_VERBOSE',None)
    args=['git','-C',str(ROOT/'rewritten.git'),'push','--atomic','--porcelain']
    args += [f'--force-with-lease={ref}:{old}' for ref,old in sorted(plan['old'].items())]
    args += [REMOTE]+[ref+':'+ref for ref in sorted(plan['old'])]
    # One atomic transaction; no --mirror, no ref deletions, no protection bypass.
    checked(args,env=env)
    m.require_same_refs(plan['new'],live_refs())
    (EVIDENCE/'push-completed.json').write_text(json.dumps({'verified':True,'refs':len(plan['new'])}))
    print('Atomic leased update of all approved branches and tags completed and verified.')


def verify():
    plan=json.loads((EVIDENCE/'approved-push.json').read_text())
    m.require_same_refs(plan['new'],live_refs())
    after=ROOT/'remote-after.git'
    checked(['git','clone','--mirror',REMOTE,str(after)])
    m.require_same_refs(plan['new'],writable(m.refs(after)))
    checked(['git','-C',str(after),'fsck','--full'])
    approved_map = dict(line.split() for line in (EVIDENCE/'commit-map.txt').read_text().splitlines()[1:])
    owned_commits = set(m.git(after,'rev-list','--branches','--tags').decode().splitlines())
    if not owned_commits.issubset(set(approved_map.values())):
        raise RuntimeError('Remote owned history contains an unverified commit')
    original_email = m.git(ROOT/'original.git','show','-s','--format=%ae',m.SEED).strip()
    for oid in owned_commits:
        if original_email in m.git(after,'cat-file','commit',oid):
            raise RuntimeError('Original private identity remains in branch/tag history')
    owned_objects = {line.split()[0] for line in m.git(after,'rev-list','--objects','--branches','--tags').decode().splitlines()}
    if owned_objects.intersection(m.AUDITED_BLOBS):
        raise RuntimeError('Original audited test content remains in branch/tag history')
    residual=[]
    for ref,sha in m.refs(after).items():
        if ref.startswith('refs/pull/'):
            p=subprocess.run(['git','-C',str(after),'merge-base','--is-ancestor',m.SEED,sha],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if p.returncode == 0: residual.append(ref)
    status=confirm_prior_removal()
    report=json.loads((EVIDENCE/'verification.json').read_text())
    report.update({'atomic_push_verified':True,'owned_history_commits_verified':len(owned_commits),
        'owned_history_private_identity_occurrences':0,'owned_history_old_test_blobs':0,
        'deleted_run_id':RUN_TO_DELETE,
        'deleted_run_verified_http_status':status,'remaining_github_owned_pr_refs':residual})
    (ROOT/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    for ref in ('main','release/2.0.1'):
        for workflow in ('windows-ci.yml','secret-scan.yml'):
            status,_=api('POST',f'actions/workflows/{workflow}/dispatches',{'ref':ref})
            if status!=204: raise RuntimeError('Workflow dispatch not accepted')
    print('Fresh remote mirror verified; previous old-run deletion reconfirmed; main/release verification dispatched.')
    print('GitHub-owned historical PR references requiring separate follow-up:',len(residual))

if __name__=='__main__':
    if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_REF')!=BRANCH:
        raise SystemExit('Refusing to operate outside the authorized repository and maintenance branch')
    if len(sys.argv)!=2 or sys.argv[1] not in ('prepare','publish','verify'):
        raise SystemExit('Expected prepare, publish, or verify')
    globals()[sys.argv[1]]()
