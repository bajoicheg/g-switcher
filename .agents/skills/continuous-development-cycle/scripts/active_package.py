#!/usr/bin/env python3
"""Verify the files actually read from an installed CDC package against a pinned tree.

This is a file witness, not proof that a model obeyed the instructions. Behavioral
acceptance remains a separate gate. Canonical Git consumers use strict mode;
personal-skill storage may opt in to explicitly reported metadata normalization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat

from contracts import load_yaml
from package_transport import _blob_oid, _tree_oid


def _inventory(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('package must be a real directory')
    files, ignored = {}, []
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if rel.parts[0] == '.git':
            continue
        if path.is_symlink():
            raise ValueError('symlink in package: ' + rel.as_posix())
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('nonregular package file: ' + rel.as_posix())
        data = path.read_bytes()
        files[rel.as_posix()] = {
            'path': rel.as_posix(), 'mode': '100755' if path.stat().st_mode & 0o111 else '100644',
            'blob_sha1': _blob_oid(data), 'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        }
    return files, ignored


def _version_errors(root, expected):
    root = Path(root)
    versions = [
        (root / 'VERSION').read_text().strip(),
        json.loads((root / 'manifest.json').read_text()).get('version'),
        load_yaml(root / 'agents/openai.yaml').get('version'),
    ]
    match = re.search(r'^# Continuous Development Cycle v(\d+\.\d+\.\d+)\s*$',
                      (root / 'SKILL.md').read_text(), re.M)
    versions.append(match.group(1) if match else None)
    return [] if all(v == expected for v in versions) else ['version_labels_disagree']


def verify(canonical, installed, *, expected_version, expected_package_tree,
           host_normalization=False):
    if not re.fullmatch(r'\d+\.\d+\.\d+', expected_version):
        raise ValueError('expected stable version required')
    if not re.fullmatch(r'[0-9a-f]{40}', expected_package_tree):
        raise ValueError('expected canonical Git tree required')
    if type(host_normalization) is not bool:
        raise ValueError('host_normalization must be boolean')
    out = {'schema': 'active-package-verification/v1', 'version': expected_version,
           'expected_package_tree': expected_package_tree, 'canonical_tree': None,
           'installed_tree': None, 'matched': False, 'errors': [],
           'normalizations': [], 'ignored_generated_files': [], 'byte_identical_files': 0,
           'proves_agent_behavior': False}
    try:
        source, source_ignored = _inventory(canonical)
        saved, ignored = _inventory(installed)
        out['ignored_generated_files'] = ignored
        out['canonical_tree'] = _tree_oid(source.values())
        out['installed_tree'] = _tree_oid(saved.values())
        if out['canonical_tree'] != expected_package_tree:
            out['errors'].append('canonical_tree_not_pinned_release')
        for label, root in [('canonical', canonical), ('installed', installed)]:
            out['errors'].extend(label + ':' + e for e in _version_errors(root, expected_version))
        for rel in sorted(source.keys() - saved.keys()):
            out['errors'].append('missing:' + rel)
        for rel in sorted(saved.keys() - source.keys()):
            out['errors'].append('unexpected:' + rel)
        for rel in sorted(source.keys() & saved.keys()):
            a, b = source[rel], saved[rel]
            if a['blob_sha1'] == b['blob_sha1']:
                out['byte_identical_files'] += 1
            else:
                kind = None
                if host_normalization and rel == 'agents/openai.yaml':
                    if load_yaml(Path(canonical) / rel) == load_yaml(Path(installed) / rel):
                        kind = 'interface_yaml_format'
                elif host_normalization and rel == 'assets/icon.svg':
                    kind = 'host_icon'
                if kind:
                    out['normalizations'].append({'path': rel, 'kind': kind,
                        'canonical_sha256': a['sha256'], 'installed_sha256': b['sha256']})
                else:
                    out['errors'].append('content_mismatch:' + rel)
            if a['mode'] != b['mode']:
                if host_normalization and a['mode'] == '100755' and b['mode'] == '100644':
                    out['normalizations'].append({'path': rel, 'kind': 'executable_mode',
                                                   'from': a['mode'], 'to': b['mode']})
                else:
                    out['errors'].append('mode_mismatch:' + rel)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        out['errors'].append('package_read_or_parse_failed:' + str(exc))
    out['matched'] = not out['errors']
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('canonical')
    parser.add_argument('installed')
    parser.add_argument('--version', required=True)
    parser.add_argument('--package-tree', required=True)
    parser.add_argument('--host-normalization', action='store_true')
    args = parser.parse_args(argv)
    result = verify(args.canonical, args.installed, expected_version=args.version,
                    expected_package_tree=args.package_tree,
                    host_normalization=args.host_normalization)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['matched'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
