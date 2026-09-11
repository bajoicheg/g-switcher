#!/usr/bin/env python3
"""One-shot, narrowly scoped owner-authorized history maintenance.

No network access or push. Input and output must be separate bare repositories.
Raw output is retained only in the private working directory.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SEED = 'dda79270bd3998fae633269067514c7c639f3ef3'
NOREPLY = b'323938722+bajoicheg@users.noreply.github.com'
FILTER_SHA256 = '67447413e273fc76809289111748870b6f6072f08b17efe94863a92d810b7d94'
AUDITED_BLOBS = {
 '13ab1a73c6fbb6903a6307d0ad18e9da6154d8b0',
 '18c0349e6f3ab6f810fccd5280f96a42e53f2a09',
 'f8a175ed8854997edadfb670d888c0c52ff5335d',
 'ee737f07b08b50ba2cda1b7d49ba6601d6b46c45',
 '9e7511a205bf856ca169cf93657ae4ab51fe92e8',
 '7c7964202764459ebd1102f74a7f4c25eb2737bb',
 'a6d44492506e90215d14c90aa7d2dac2be61a870',
}
TARGET = 'src/windows_runtime/settings.rs'


def git(repo, *args, input=None):
    p = subprocess.run(['git', '-C', str(repo), *args], input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if p.returncode:
        raise RuntimeError('Git operation failed; no private payload printed: ' + args[0])
    return p.stdout


def refs(repo):
    return dict(line.split(' ', 1) for line in git(
        repo, 'for-each-ref', '--format=%(refname) %(objectname)').decode().splitlines())


def require_same_refs(expected, actual):
    if expected != actual:
        raise ValueError('Reference inventory changed; refusing to overwrite concurrent work')


def sanitize_test(data):
    marker = b'fn parses_user_dictionary_without_recording_history() {'
    start = data.find(marker)
    if start < 0:
        raise ValueError('Audited test marker missing')
    end = data.find(b'\n    }', start)
    if end < 0:
        raise ValueError('Audited test terminator missing')
    end += len(b'\n    }')
    block = data[start:end]
    m = re.search(rb'"([^"\\\n]+)\\n([^"\\\n]+)\\n\1"', block)
    if not m:
        raise ValueError('Audited test literal shape changed')
    ru, en = m.group(1), m.group(2)
    if ru == en or data.count(ru) != 3 or data.count(en) != 2:
        raise ValueError('Replacement occurrence count changed')
    if block.count(ru) != 3 or block.count(en) != 2:
        raise ValueError('Replacement would alter content outside the audited test')
    updated = block.replace(ru, 'Пример'.encode()).replace(en, b'Example')
    return data[:start] + updated + data[end:]


def tree(repo, commit):
    result = {}
    for line in git(repo, 'ls-tree', '-rz', commit).split(b'\0'):
        if line:
            meta, path = line.split(b'\t', 1)
            result[path] = meta
    return result


def commit_info(repo, oid):
    raw = git(repo, 'cat-file', 'commit', oid)
    header, message = raw.split(b'\n\n', 1)
    fields = []
    for line in header.split(b'\n'):
        if line.startswith(b' '):
            fields[-1] += b'\n' + line
        else:
            fields.append(line)
    return fields, message


def strip_signature(fields):
    return [f for f in fields if not f.startswith((b'gpgsig ', b'gpgsig-sha256 '))]


def run(original, output, tool, report_dir):
    original, output, tool, report_dir = map(lambda p: Path(p).resolve(),
                                           (original, output, tool, report_dir))
    if output.exists() or original == output:
        raise ValueError('Output must be a new isolated directory')
    if hashlib.sha256(tool.read_bytes()).hexdigest() != FILTER_SHA256:
        raise ValueError('Pinned git-filter-repo checksum mismatch')
    report_dir.mkdir(parents=True, exist_ok=True)
    old_refs = refs(original)
    commits = git(original, 'rev-list', '--all').decode().splitlines()
    email = git(original, 'show', '-s', '--format=%ae', SEED).strip()
    if not email or email != git(original, 'show', '-s', '--format=%ce', SEED).strip():
        raise ValueError('Audited identity is not the expected author/committer pair')
    if email == NOREPLY or b'@' not in email:
        raise ValueError('Audited identity is not eligible')
    replacements, blob_map = {}, {}
    for oid in sorted(AUDITED_BLOBS):
        content = git(original, 'cat-file', 'blob', oid)
        updated = sanitize_test(content)
        new_oid = hashlib.sha1(b'blob ' + str(len(updated)).encode() + b'\0' + updated).hexdigest()
        replacements[oid] = base64.b64encode(updated).decode()
        blob_map[oid] = new_oid
    mapping_file = report_dir / 'replacement-content.json'
    mapping_file.write_text(json.dumps(replacements), encoding='utf-8')
    env = os.environ.copy()
    env['REWRITE_EMAIL'] = email.decode('utf-8')
    env['REWRITE_BLOBS'] = str(mapping_file)
    subprocess.run(['git', 'clone', '--mirror', '--no-hardlinks', str(original), str(output)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    callback = ('import os, json, base64\n'
                'replacements = json.load(open(os.environ["REWRITE_BLOBS"]))\n'
                'key = blob.original_id.decode()\n'
                'if key in replacements:\n'
                '    blob.data = base64.b64decode(replacements[key])\n')
    email_callback = ('import os\nreturn ' + repr(NOREPLY) +
                      ' if email == os.environ["REWRITE_EMAIL"].encode() else email')
    args = [sys.executable, str(tool), '--force', '--sensitive-data-removal', '--no-fetch',
            '--preserve-commit-hashes', '--preserve-commit-encoding',
            '--prune-empty', 'never', '--prune-degenerate', 'never',
            '--blob-callback', callback, '--email-callback', email_callback]
    with (report_dir / 'filter.log').open('wb') as log:
        subprocess.run(args, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    commit_map_path = output / 'filter-repo' / 'commit-map'
    mapping = dict(line.split() for line in commit_map_path.read_text().splitlines()[1:])
    if len(mapping) != len(commits) or set(mapping) != set(commits):
        raise ValueError('Commit-map coverage mismatch')
    if len(set(mapping.values())) != len(mapping) or any(v == '0'*40 for v in mapping.values()):
        raise ValueError('History lost or collapsed commits')
    new_refs = refs(output)
    if set(new_refs) != set(old_refs):
        raise ValueError('Ref names changed')
    changed_files = set()
    signatures_removed = 0
    identities_changed = 0
    for old, new in mapping.items():
        old_fields, old_message = commit_info(original, old)
        new_fields, new_message = commit_info(output, new)
        if old_message != new_message:
            raise ValueError('Commit message changed')
        expected_fields = []
        for f in strip_signature(old_fields):
            if f.startswith(b'tree '):
                continue
            if f.startswith(b'parent '):
                f = b'parent ' + mapping[f[7:].decode()].encode()
            if f.startswith((b'author ', b'committer ')):
                m = re.search(rb'<([^<>]+)> ', f)
                if m and m[1] == email:
                    f = f[:m.start(1)] + NOREPLY + f[m.end(1):]
                    identities_changed += 1
            expected_fields.append(f)
        if expected_fields != [f for f in new_fields if not f.startswith(b'tree ')]:
            raise ValueError('Unexpected commit metadata or topology change')
        signatures_removed += len(old_fields) - len(strip_signature(old_fields))
        before, after = tree(original, old), tree(output, new)
        if set(before) != set(after):
            raise ValueError('File inventory changed')
        for p in before:
            expected_meta = before[p]
            old_blob = expected_meta.split()[-1].decode()
            if old_blob in blob_map:
                if p.decode() != TARGET:
                    raise ValueError('Audited blob appears at an unexpected path')
                expected_meta = expected_meta.rsplit(b' ', 1)[0] + b' ' + blob_map[old_blob].encode()
                changed_files.add(p.decode())
            if after[p] != expected_meta:
                raise ValueError('Unexpected file bytes or mode changed')
    if identities_changed != 2:
        raise ValueError('Unexpected number of corporate identity fields')
    annotated_tags = 0
    for ref, old in old_refs.items():
        if git(original, 'cat-file', '-t', old).strip() == b'commit':
            if new_refs[ref] != mapping[old]:
                raise ValueError('Ref target not mapped to its original commit')
        elif ref.startswith('refs/tags/'):
            annotated_tags += 1
            before = git(original, 'cat-file', 'tag', old)
            after = git(output, 'cat-file', 'tag', new_refs[ref])
            # This repository's annotated tags have no signatures and point at commits.
            lines = before.split(b'\n', 1)
            target = lines[0].split()[1].decode()
            expected = b'object ' + mapping[target].encode() + b'\n' + lines[1]
            if after != expected:
                raise ValueError('Unexpected annotated tag change')
        else:
            raise ValueError('Unexpected reference object type')
    git(output, 'fsck', '--full')
    for oid in git(output, 'rev-list', '--all').decode().splitlines():
        if email in git(output, 'cat-file', 'commit', oid):
            raise ValueError('Corporate email remains in reachable commit metadata')
    report = {
        'commits_verified': len(mapping),
        'commits_rewritten': sum(k != v for k, v in mapping.items()),
        'branches': sum(r.startswith('refs/heads/') for r in old_refs),
        'tags': sum(r.startswith('refs/tags/') for r in old_refs),
        'annotated_tags': annotated_tags,
        'pr_refs_local': sum(r.startswith('refs/pull/') for r in old_refs),
        'blob_versions_sanitized': len(blob_map),
        'changed_paths': sorted(changed_files),
        'identity_fields_replaced': identities_changed,
        'commit_signatures_removed': signatures_removed,
        'main_tree_unchanged': tree(original, old_refs['refs/heads/main']) == tree(output, new_refs['refs/heads/main']),
        'release_tree_unchanged': tree(original, old_refs['refs/heads/release/2.0.1']) == tree(output, new_refs['refs/heads/release/2.0.1']),
        'refs_before': old_refs, 'refs_after': new_refs, 'blob_map': blob_map,
    }
    (report_dir/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    (report_dir/'commit-map.txt').write_bytes(commit_map_path.read_bytes())
    print(json.dumps({k:v for k,v in report.items() if k not in ('refs_before','refs_after','blob_map')}))
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('original', 'output', 'tool', 'report_dir'): p.add_argument(name)
    a = p.parse_args()
    run(a.original, a.output, a.tool, a.report_dir)
