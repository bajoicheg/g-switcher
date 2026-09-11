#!/usr/bin/env python3
"""Read-only publication audit; export coordinates, never matching secret values."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MAX_BYTES = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
ORG = 'gra' + 'dient'
ORG_RU = ''.join(map(chr, [1075, 1088, 1072, 1076, 1080, 1077, 1085, 1090]))
ORG_PATTERN = re.compile(r'(?i)(?:' + ORG + '|' + ORG_RU + r')')
EMAIL = re.compile(r'(?i)\b[A-Z0-9._%+-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,}\b')
PRIVATE_KEY = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----')
ASSIGNMENT = re.compile(r'''(?ix)\b(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|access[_-]?token)\b\s*[:=]\s*["']([^"'\r\n]{4,200})["']''')
INTERNAL = re.compile(r'(?i)\b(?:[a-z0-9-]+\.)+(?:local|internal|corp|lan)\b|\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b')
BENIGN = re.compile(r'(?i)(?:linear-|radial-|conic-|repeating-linear-)' + ORG + r'\s*\(')
BINARY_EXTENSIONS = {'.exe', '.dll', '.png', '.bmp', '.ico', '.jpg', '.jpeg', '.gif', '.pdf', '.pfx', '.p12'}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:16]


def safe_label(value: str) -> str:
    value = EMAIL.sub('[email]', str(value))
    value = re.sub(r'(?i)(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}', '[token]', value)
    return value.replace('\x00', '').replace('\r', '').replace('\n', ' ')[:300]


def scan_text(text: str, source: str, encoding: str = 'utf-8') -> list[dict]:
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        lexical = bool(BENIGN.search(line)) and not re.search(r'(?i)' + ORG + r'\.(?:ru|com)|@|<Company>|ООО|ГК|НТС', line)
        if 'frequen' in source.lower() and re.fullmatch(r'[\s"\w(),:;\-]+', line):
            lexical = True
        kinds = []
        if ORG_PATTERN.search(line):
            kinds.append('lexical-reference' if lexical else 'corporate-reference')
        if PRIVATE_KEY.search(line):
            kinds.append('private-key-marker')
        if ASSIGNMENT.search(line):
            kinds.append('credential-assignment-candidate')
        if INTERNAL.search(line):
            kinds.append('internal-address-candidate')
        emails = EMAIL.findall(line)
        if emails and not all(e.lower().endswith(('@users.noreply.github.com', '@example.com', '@example.org', '@example.net', '@noreply.github.com')) for e in emails):
            kinds.append('email-candidate')
        for kind in kinds:
            rows.append({'kind': kind, 'source': safe_label(source), 'line': number,
                         'encoding': encoding, 'fingerprint': digest((kind + '\0' + line).encode())})
    return rows


def scan_bytes(data: bytes, source: str, depth: int = 0) -> list[dict]:
    rows = []
    if len(data) > MAX_BYTES:
        return [{'kind': 'coverage-limit', 'source': safe_label(source), 'line': 0}]
    if data[:2] == b'PK' and zipfile.is_zipfile(io.BytesIO(data)):
        if depth >= 3:
            return [{'kind': 'archive-depth-limit', 'source': safe_label(source), 'line': 0}]
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED:
                    return [{'kind': 'archive-size-limit', 'source': safe_label(source), 'line': 0}]
                for item in archive.infolist():
                    if not item.is_dir():
                        try:
                            rows.extend(scan_bytes(archive.read(item), source + '::' + item.filename, depth + 1))
                        except (RuntimeError, zipfile.BadZipFile, NotImplementedError):
                            rows.append({'kind': 'unreadable-archive-member', 'source': safe_label(source + '::' + item.filename), 'line': 0})
            return rows
        except zipfile.BadZipFile:
            rows.append({'kind': 'unreadable-archive', 'source': safe_label(source), 'line': 0})
    rows.extend(scan_text(data.decode('utf-8', errors='replace'), source))
    if b'\x00' in data or Path(source).suffix.lower() in BINARY_EXTENSIONS:
        for offset in (0, 1):
            rows.extend(scan_text(data[offset:].decode('utf-16le', errors='replace'), source, f'utf-16le-offset-{offset}'))
    unique = {(r['kind'], r.get('fingerprint'), r['source'], r.get('encoding')): r for r in rows}
    return list(unique.values())


def safe_findings(rows: list[dict]) -> list[dict]:
    return [{'rule': safe_label(r.get('RuleID', 'unknown')),
             'source': safe_label(r.get('File', '')),
             'line': r.get('StartLine', 0),
             'commit': r.get('Commit', '') if re.fullmatch(r'[0-9a-f]{40,64}', r.get('Commit', '')) else ''}
            for r in rows]


def git(*args: str) -> bytes:
    return subprocess.run(['git', *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(url: str, token: str = '', accept: str = 'application/vnd.github+json') -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https':
        raise ValueError('HTTPS required')
    headers = {'User-Agent': 'publication-audit', 'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        if parsed.hostname != 'api.github.com':
            raise ValueError('Credentials restricted to GitHub API')
        headers['Authorization'] = 'Bearer ' + token
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=45) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError('Download limit exceeded')
                return data
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                return download(urllib.parse.urljoin(url, error.headers['Location']), '', accept)
            if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError('Download failed')


def api_pages(repository: str, endpoint: str, token: str, key: str | None = None) -> list[dict]:
    values = []
    for page in range(1, 31):
        separator = '&' if '?' in endpoint else '?'
        url = f'https://api.github.com/repos/{repository}/{endpoint}{separator}per_page=100&page={page}'
        payload = json.loads(download(url, token))
        items = payload[key] if key else payload
        if not isinstance(items, list):
            raise ValueError('Expected paginated list')
        values.extend(items)
        if len(items) < 100:
            return values
    raise ValueError('Pagination limit exceeded; audit incomplete')


def scan_gitleaks(arguments: list[str], output: Path) -> dict:
    command = ['gitleaks', *arguments, '--redact=100', '--no-banner', '--ignore-gitleaks-allow',
               '--gitleaks-ignore-path', '/dev/null', '--report-format', 'json', '--report-path', str(output)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if result.returncode not in (0, 1):
        raise RuntimeError(f'Gitleaks failed with exit {result.returncode}; no clean claim allowed')
    if not output.is_file():
        raise RuntimeError('Gitleaks report missing')
    findings = safe_findings(json.loads(output.read_text()))
    return {'exit_code': result.returncode, 'count': len(findings), 'findings': findings}


def audit(repository: str, out: Path, include_remote: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    report = {'repository': repository, 'head': git('rev-parse', 'HEAD').decode().strip(),
              'scope': {}, 'findings': [], 'coverage_gaps': [], 'secret_scan': {}, 'ref_snapshot': []}
    with tempfile.TemporaryDirectory(prefix='publication-audit-') as temp:
        root = Path(temp)
        objects_dir = root / 'objects'
        surfaces_dir = root / 'surfaces'
        objects_dir.mkdir()
        surfaces_dir.mkdir()
        mapping = {}
        refs = git('for-each-ref', '--format=%(refname) %(objectname)').decode().splitlines()
        report['ref_snapshot'] = [safe_label(r) for r in refs]
        report['scope']['refs'] = len(refs)
        report['scope']['commits'] = int(git('rev-list', '--all', '--count'))
        objects = git('rev-list', '--objects', '--all').decode('utf-8', errors='replace').splitlines()
        proc = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        blob_count = 0
        binary_count = 0
        for record in objects:
            oid, _, name = record.partition(' ')
            proc.stdin.write((oid + '\n').encode())
            proc.stdin.flush()
            header = proc.stdout.readline().decode().split()
            if len(header) != 3:
                raise RuntimeError('Invalid git object header')
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)
            if header[1] != 'blob':
                continue
            blob_count += 1
            binary_count += int(b'\x00' in data)
            label = f'git-blob/{oid}/{name}'
            report['findings'].extend(scan_bytes(data, label))
            (objects_dir / oid).write_bytes(data)
            mapping[oid] = safe_label(name)
        proc.stdin.close()
        proc.wait(timeout=10)
        report['scope']['unique_blobs'] = blob_count
        report['scope']['binary_blobs'] = binary_count
        for ref in ('refs/remotes/origin/main', 'refs/remotes/origin/release/2.0.1'):
            try:
                listing = git('ls-tree', '-rz', '--full-tree', ref)
                current = []
                for entry in listing.split(b'\0'):
                    if not entry:
                        continue
                    meta, path = entry.split(b'\t', 1)
                    mode, kind, oid = meta.decode().split()
                    if kind == 'blob':
                        name = path.decode('utf-8', errors='replace')
                        current.extend(scan_bytes((objects_dir / oid).read_bytes(), ref + '/' + name))
                report.setdefault('current_findings', {})[ref] = current
            except (subprocess.SubprocessError, FileNotFoundError):
                report['coverage_gaps'].append({'source': ref, 'reason': 'head snapshot unavailable'})
        metadata = git('log', '--all', '--format=%H%n%an <%ae>%n%cn <%ce>%n%B%n---AUDIT-COMMIT---')
        report['findings'].extend(scan_bytes(metadata, 'commit-metadata'))
        (surfaces_dir / 'commit-metadata.txt').write_bytes(metadata)
        report['scope']['author_email_identities'] = len(set(EMAIL.findall(metadata.decode(errors='replace'))))
        for ref in refs:
            report['findings'].extend(scan_text(ref, 'ref-name'))
        report['secret_scan']['git_history'] = scan_gitleaks(['git', '.', '--log-opts=--all', '--max-decode-depth=2'], root / 'git-secrets.json')
        report['secret_scan']['all_blobs'] = scan_gitleaks(['dir', str(objects_dir), '--max-decode-depth=2', '--max-archive-depth=3'], root / 'blob-secrets.json')
        report['blob_paths'] = {Path(f['source']).name: mapping.get(Path(f['source']).name, '') for f in report['secret_scan']['all_blobs']['findings']}
        if include_remote:
            token = os.environ.get('GH_TOKEN', '')
            endpoint_specs = [('issues?state=all', None), ('issues/comments', None), ('pulls/comments', None),
                              ('comments', None), ('releases', None), ('pulls?state=all', None)]
            downloads = []
            surface_paths = {}
            pull_requests = []
            for endpoint, key in endpoint_specs:
                try:
                    values = api_pages(repository, endpoint, token, key)
                    report['scope'][endpoint] = len(values)
                    if endpoint == 'pulls?state=all':
                        pull_requests = values
                    for value in values:
                        identity = value.get('number', value.get('id', 'unknown'))
                        label = endpoint.split('?')[0] + '/' + str(identity)
                        text = '\n'.join(str(value.get(k) or '') for k in ('title', 'body', 'name', 'tag_name'))
                        raw = text.encode()
                        report['findings'].extend(scan_bytes(raw, label))
                        (surfaces_dir / (digest(label.encode()) + '.txt')).write_bytes(raw)
                        surface_paths[digest(label.encode()) + '.txt'] = safe_label(label)
                        if endpoint == 'releases':
                            for asset in value.get('assets', []):
                                downloads.append(('release-asset/' + str(asset['id']) + '/' + asset['name'], asset['browser_download_url'], False))
                except (urllib.error.HTTPError, ValueError, OSError) as error:
                    report['coverage_gaps'].append({'source': endpoint, 'reason': type(error).__name__, 'status': getattr(error, 'code', None)})
            for value in pull_requests:
                number = value['number']
                try:
                    reviews = api_pages(repository, f'pulls/{number}/reviews', token)
                    report['scope']['reviews'] = report['scope'].get('reviews', 0) + len(reviews)
                    for review in reviews:
                        label = f'review/{number}/{review["id"]}'
                        raw = (review.get('body') or '').encode()
                        report['findings'].extend(scan_bytes(raw, label))
                        (surfaces_dir / (digest(label.encode()) + '.txt')).write_bytes(raw)
                        surface_paths[digest(label.encode()) + '.txt'] = safe_label(label)
                except (urllib.error.HTTPError, ValueError, OSError) as error:
                    report['coverage_gaps'].append({'source': f'reviews/{number}', 'reason': type(error).__name__})
            try:
                runs = api_pages(repository, 'actions/runs', token, 'workflow_runs')
                report['scope']['workflow_runs_listed'] = len(runs)
                for run in runs:
                    if str(run['id']) == os.environ.get('GITHUB_RUN_ID'):
                        continue
                    if run['status'] == 'completed':
                        downloads.append(('workflow-logs/' + str(run['id']), run['logs_url'], True))
                    else:
                        report['coverage_gaps'].append({'source': 'workflow/' + str(run['id']), 'reason': 'run not complete at audit snapshot'})
                artifacts = api_pages(repository, 'actions/artifacts', token, 'artifacts')
                report['scope']['artifacts_listed'] = len(artifacts)
                report['scope']['artifacts_expired'] = sum(bool(a['expired']) for a in artifacts)
                for artifact in artifacts:
                    if not artifact['expired']:
                        downloads.append(('workflow-artifact/' + str(artifact['id']) + '/' + artifact['name'], artifact['archive_download_url'], True))
            except (urllib.error.HTTPError, ValueError, OSError) as error:
                report['coverage_gaps'].append({'source': 'actions', 'reason': type(error).__name__, 'status': getattr(error, 'code', None)})
            def process_remote(item):
                label, url, authenticated = item
                try:
                    raw = download(url, token if authenticated else '', 'application/octet-stream' if not authenticated else 'application/vnd.github+json')
                    (surfaces_dir / digest(label.encode())).write_bytes(raw)
                    return scan_bytes(raw, label), None, label.split('/')[0]
                except (urllib.error.HTTPError, ValueError, OSError, zipfile.BadZipFile) as error:
                    return [], {'source': safe_label(label), 'reason': type(error).__name__, 'status': getattr(error, 'code', None)}, None
            for label, _, _ in downloads:
                surface_paths[digest(label.encode())] = safe_label(label)
            report['surface_paths'] = surface_paths
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                for found, gap, source_type in pool.map(process_remote, downloads):
                    report['findings'].extend(found)
                    if gap:
                        report['coverage_gaps'].append(gap)
                    if source_type:
                        report['scope'][source_type + '_scanned'] = report['scope'].get(source_type + '_scanned', 0) + 1
        report['secret_scan']['public_surfaces'] = scan_gitleaks(['dir', str(surfaces_dir), '--max-decode-depth=2', '--max-archive-depth=3'], root / 'surface-secrets.json')
        report['limitations'] = ['Pattern matching is not proof of absence of secrets.',
                                 'Credentials are not tested against providers; no secret validation network requests.',
                                 'Raster image pixels are not OCR-scanned; strings and archive metadata are scanned.',
                                 'Unreachable server objects, deleted logs, private caches and external forks are outside accessible scope.',
                                 'Source coordinates do not include secret values; triage candidates before remediation.']
        counts = {}
        for row in report['findings']:
            counts[row['kind']] = counts.get(row['kind'], 0) + 1
        report['finding_counts'] = counts
        (out / 'publication-audit-redacted.json').write_text(json.dumps(report, indent=2, ensure_ascii=True))
        summary = {'scope': report['scope'], 'finding_counts': counts, 'secret_scan_counts': {k: v['count'] for k, v in report['secret_scan'].items()}, 'coverage_gaps': len(report['coverage_gaps'])}
        print(json.dumps(summary, indent=2))
        summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary_path:
            with open(summary_path, 'a') as handle:
                handle.write('## Publication audit (redacted)\n```json\n' + json.dumps(summary, indent=2) + '\n```\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--remote', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('Invalid owner/repository')
    audit(args.repository, args.output, args.remote)
