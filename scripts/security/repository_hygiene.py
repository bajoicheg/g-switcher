#!/usr/bin/env python3
"""Fail on tracked private material or company-specific text in the current tree."""
from pathlib import Path
import json
import re
from publication_audit import git, scan_bytes, safe_label

PRIVATE_NAMES = re.compile(r'(?i)(?:^|/)(?:\.env(?:\..+)?|credentials\.json|secrets\.(?:json|toml|ya?ml)|id_rsa|id_ed25519)$|\.(?:pfx|p12|key|jks|keystore|snk|kdbx|dmp|pcapng?)$')


def check_paths(root: Path, names: list[str]) -> list[dict]:
    findings = []
    for name in names:
        path = root / name
        if path.is_symlink():
            findings.append({'kind': 'unreviewed-symlink', 'source': safe_label(name)})
            continue
        if PRIVATE_NAMES.search(name) and path.name not in {'.env.example', '.env.sample'}:
            findings.append({'kind': 'private-material-filename', 'source': safe_label(name)})
        if not path.is_file():
            continue
        for f in scan_bytes(path.read_bytes(), name):
            if f['kind'] in {'corporate-reference', 'private-key-marker', 'coverage-limit', 'archive-depth-limit', 'archive-size-limit', 'unreadable-archive-member', 'unreadable-archive'}:
                findings.append(f)
    return findings


if __name__ == '__main__':
    names = [n.decode('utf-8') for n in git('ls-files', '-z').split(b'\0') if n]
    findings = check_paths(Path.cwd(), names)
    print(json.dumps({'tracked_files': len(names), 'blocking_findings': findings}, indent=2))
    raise SystemExit(bool(findings))
