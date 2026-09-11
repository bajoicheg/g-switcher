import concurrent.futures as cf
import hashlib, json, os, pathlib, subprocess, tarfile
import urllib.error, urllib.parse, urllib.request

root = pathlib.Path('private-evidence').resolve()
root.mkdir(mode=0o700, exist_ok=True)
repo = os.environ['AUDIT_REPOSITORY']
assert repo == 'bajoicheg/g-switcher'
base = 'https://api.github.com/repos/' + repo
errors = []

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError('non-HTTPS redirect')
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            result.remove_header('Authorization')
        return result

def get(url, limit=64*1024*1024):
    headers = {'User-Agent': 'repository-hygiene-audit', 'Accept': 'application/vnd.github+json'}
    if url.startswith(base + '/') or url == base:
        headers['Authorization'] = 'Bearer ' + os.environ['AUDIT_TOKEN']
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(SafeRedirect()).open(req, timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('response size limit')
    return data

def paged(path, key=None):
    result = []
    for page in range(1, 101):
        url = base + path + ('&' if '?' in path else '?') + f'per_page=100&page={page}'
        payload = json.loads(get(url))
        batch = payload[key] if key else payload
        assert isinstance(batch, list)
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError('pagination limit')

def save(name, value):
    (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

def optional(name, path, key=None):
    try:
        value = paged(path, key)
        save(name + '.json', value)
        return value
    except Exception as exc:
        errors.append({'surface': name, 'error_type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)})
        return []

def run(args, name, allowed=(0,)):
    env = {k:v for k,v in os.environ.items() if k != 'AUDIT_TOKEN'}
    with (root / (name + '.log')).open('wb') as log:
        proc = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=240)
    if proc.returncode not in allowed:
        raise RuntimeError(name + ' failed')
    return proc.returncode

run(['git','-c','credential.helper=','clone','--mirror','https://github.com/'+repo+'.git',str(root/'repo.git')], 'clone')
run(['git','--git-dir='+str(root/'repo.git'),'fetch','origin','+refs/pull/*/head:refs/pull/*/head'], 'pull-refs')
run(['git','--git-dir='+str(root/'repo.git'),'bundle','create',str(root/'repository.bundle'),'--all'], 'bundle')
save('repository.json', json.loads(get(base)))
issues = optional('issues', '/issues?state=all')
optional('issue-comments', '/issues/comments')
optional('review-comments', '/pulls/comments')
optional('commit-comments', '/comments')
prs = optional('pulls', '/pulls?state=all')
for pr in prs:
    optional('reviews-'+str(pr['number']), '/pulls/'+str(pr['number'])+'/reviews')
releases = optional('releases', '/releases')
runs = optional('workflow-runs', '/actions/runs', 'workflow_runs')
artifacts = optional('artifacts', '/actions/artifacts', 'artifacts')
optional('forks', '/forks')

jobs = []
for item in runs:
    if item['status'] == 'completed':
        jobs.append(('logs-'+str(item['id'])+'.zip', base+'/actions/runs/'+str(item['id'])+'/logs'))
for release in releases:
    for asset in release.get('assets', []):
        if asset['size'] <= 32*1024*1024:
            jobs.append(('release-'+str(asset['id'])+'.bin', asset['browser_download_url']))
        else:
            errors.append({'surface':'release-asset','id':asset['id'],'error_type':'size-limit'})
# Inspect one latest retained artifact for each name; the inventory records all.
seen = set()
for artifact in artifacts:
    if artifact['expired'] or artifact['name'] in seen:
        continue
    seen.add(artifact['name'])
    if artifact['size_in_bytes'] <= 32*1024*1024:
        jobs.append(('artifact-'+str(artifact['id'])+'.zip', base+'/actions/artifacts/'+str(artifact['id'])+'/zip'))
    else:
        errors.append({'surface':'artifact','id':artifact['id'],'error_type':'size-limit'})

def download(job):
    name, url = job
    try:
        data = get(url)
        (root/name).write_bytes(data)
        return {'file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    except Exception as exc:
        return {'file':name,'error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)}
with cf.ThreadPoolExecutor(max_workers=4) as pool:
    downloads = list(pool.map(download, jobs))
save('downloads.json', downloads)

scanner_url = 'https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz'
scanner_bytes = get(scanner_url)
expected = '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb'
assert hashlib.sha256(scanner_bytes).hexdigest() == expected
(root/'gitleaks.tar.gz').write_bytes(scanner_bytes)
with tarfile.open(root/'gitleaks.tar.gz') as archive:
    binary = archive.extractfile('gitleaks').read()
(root/'gitleaks').write_bytes(binary)
(root/'gitleaks').chmod(0o700)
(root/'scanner.toml').write_text('[extend]\nuseDefault = true\n', encoding='utf-8')
(root/'empty.ignore').write_text('', encoding='utf-8')
exit_code = run([str(root/'gitleaks'),'git',str(root/'repo.git'),'--log-opts=--all --full-history','--config='+str(root/'scanner.toml'),'--gitleaks-ignore-path='+str(root/'empty.ignore'),'--redact=100','--no-banner','--report-format=json','--report-path='+str(root/'gitleaks-history.json')], 'gitleaks-history', (0,1))
save('manifest.json', {'repository':repo,'audit_commit':os.environ['AUDIT_COMMIT'],'run_id':os.environ['AUDIT_RUN_ID'],'issues':len(issues),'pulls':len(prs),'releases':len(releases),'workflow_runs':len(runs),'artifact_inventory':len(artifacts),'downloads_ok':sum('sha256' in d for d in downloads),'downloads_failed':sum('error_type' in d for d in downloads),'gitleaks_history_exit':exit_code,'errors':errors,'scope':'All advertised Git refs plus pull heads; all accessible metadata; retained completed-run logs; release assets <=32MiB; latest retained artifact per name <=32MiB.'})
# No repository payload, match text, or credentials are printed to Actions logs.
print('Evidence collected; encrypting for offline review.')
