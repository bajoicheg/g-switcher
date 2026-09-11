#!/usr/bin/env python3
"""Classify scanner false positives and identify historical privacy coordinates.

No raw findings or source content are printed or exported. This job is read-only.
"""
from __future__ import annotations
import collections
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from publication_audit import ORG_PATTERN, digest, download, git, safe_label, scan_bytes

HOTKEYS = {'Ctrl+Shift+F10', 'Ctrl+Shift+F12'}
DOCS = {'docs/FUNCTIONAL_SPEC.md', 'docs/ACCEPTANCE_TESTS.md'}


def classify(finding: dict) -> dict:
    source = finding.get('File', '')
    known_doc = any(source == p or source.endswith('/' + p) for p in DOCS)
    benign = finding.get('RuleID') == 'generic-api-key' and known_doc and finding.get('Secret') in HOTKEYS
    return {'classification': 'documented-hotkey' if benign else 'requires-review',
            'rule': safe_label(finding.get('RuleID', '')), 'source': safe_label(source),
            'line': finding.get('StartLine', 0), 'commit': finding.get('Commit', '')}


def run_scan(args: list[str], report_path: Path, config: Path) -> list[dict]:
    # Capture all output; ephemeral JSON is read locally and deleted on return.
    command = ['gitleaks', *args, '--config', str(config), '--no-banner',
               '--ignore-gitleaks-allow', '--gitleaks-ignore-path', '/dev/null',
               '--report-format=json', '--report-path', str(report_path), '--exit-code=9']
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if result.returncode not in (0, 9) or not report_path.is_file():
        raise RuntimeError('Secret scanner execution failed; result cannot be accepted')
    return [classify(f) for f in json.loads(report_path.read_text())]


def main() -> None:
    out = Path(os.environ['AUDIT_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    report = {'head': git('rev-parse', 'HEAD').decode().strip(), 'classified': {}, 'corporate_metadata': [], 'email_identity_classes': [], 'current_corporate_files': {}, 'remaining_review_count': 0}
    with tempfile.TemporaryDirectory(prefix='triage-private-') as td:
        tmp = Path(td)
        default = tmp / 'defaults.toml'
        default.write_text('[extend]\nuseDefault = true\n')
        config = Path('.gitleaks.toml').resolve()
        blobroot = tmp / 'blobs'
        blobroot.mkdir()
        proc = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        blob_count = 0
        for record in git('rev-list', '--objects', '--all').decode(errors='replace').splitlines():
            oid, _, name = record.partition(' ')
            proc.stdin.write((oid + '\n').encode())
            proc.stdin.flush()
            header = proc.stdout.readline().decode().split()
            data = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)
            if header[1] != 'blob':
                continue
            blob_count += 1
            relative = Path(name) if name else Path('unnamed')
            if relative.is_absolute() or '..' in relative.parts:
                relative = Path('untrusted-name')
            dest = blobroot / oid / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        proc.stdin.close()
        proc.wait(timeout=10)
        report['blob_count'] = blob_count
        for label, args in [('history', ['git', '.', '--log-opts=--all', '--max-decode-depth=2']),
                            ('snapshots', ['dir', str(blobroot), '--max-decode-depth=2', '--max-archive-depth=3'])]:
            initial = run_scan(args, tmp / (label + '-baseline.json'), default)
            after = run_scan(args, tmp / (label + '-configured.json'), config)
            report['classified'][label] = {'baseline': initial, 'after_narrow_allowlist': after}
            report['remaining_review_count'] += sum(f['classification'] != 'documented-hotkey' for f in initial) + len(after)
        identities = {}
        for record in git('log', '--all', '-z', '--format=%H%x1f%ae%x1f%ce%x1f%B').decode(errors='replace').split('\0'):
            parts = record.strip('\n').split('\x1f', 3)
            if len(parts) != 4:
                continue
            sha, author, committer, message = parts
            for field, value in [('author_email', author), ('committer_email', committer), ('message', message)]:
                if ORG_PATTERN.search(value):
                    refs = git('for-each-ref', '--contains', sha, '--format=%(refname)').decode().splitlines()
                    report['corporate_metadata'].append({'commit': sha, 'field': field, 'affected_refs': refs})
            for address in (author, committer):
                if 'noreply' in address.lower():
                    category = 'github-noreply'
                elif ORG_PATTERN.search(address):
                    category = 'corporate-email'
                elif address.lower().endswith(('.test', '.invalid', '@example.com')):
                    category = 'example-email'
                else:
                    category = 'other-personal-or-service-email'
                identities[digest(address.encode())] = category
        report['email_identity_classes'] = [{'identity': k, 'class': v} for k, v in identities.items()]
        refs = git('for-each-ref', '--format=%(refname)', 'refs/remotes/origin').decode().splitlines()
        for ref in refs:
            if ref.endswith('/HEAD'):
                continue
            names = []
            for entry in git('ls-tree', '-rz', ref).split(b'\0'):
                if not entry:
                    continue
                meta, path = entry.split(b'\t', 1)
                if meta.split()[1] != b'blob':
                    continue
                raw = git('cat-file', 'blob', meta.split()[2].decode())
                if any(f['kind'] == 'corporate-reference' for f in scan_bytes(raw, path.decode(errors='replace'))):
                    names.append(safe_label(path.decode(errors='replace')))
            if names:
                report['current_corporate_files'][ref] = names
        # Retry the two non-permanent gaps from the initial audit snapshot.
        report['retried_surfaces'] = []
        for run in (33752618330, 34634432522):
            label = f'workflow-logs/{run}'
            try:
                raw = download(f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{run}/logs', os.environ.get('GH_TOKEN', ''))
                path = tmp / f'log-{run}.zip'
                path.write_bytes(raw)
                flags = scan_bytes(raw, label)
                secret_flags = run_scan(['dir', str(path), '--max-decode-depth=2', '--max-archive-depth=3'], tmp / f'log-{run}.json', default)
                report['retried_surfaces'].append({'source': label, 'status': 'scanned', 'flags': flags, 'secret_flags': secret_flags})
                report['remaining_review_count'] += len(secret_flags)
            except Exception as error:
                report['retried_surfaces'].append({'source': label, 'status': 'unavailable', 'error_type': type(error).__name__})
        (out / 'triage-redacted.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({'baseline_counts': {k: len(v['baseline']) for k, v in report['classified'].items()},
                          'remaining_review_count': report['remaining_review_count'],
                          'historical_corporate_metadata_records': len(report['corporate_metadata']),
                          'email_classes': dict(collections.Counter(identities.values()))}, indent=2))
        if report['remaining_review_count']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
