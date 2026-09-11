#!/usr/bin/env python3
"""Prove a narrow documentation exception does not suppress credential detection."""
from pathlib import Path
import secrets
import tempfile
from triage_publication import run_scan


def main() -> None:
    config = Path('.gitleaks.toml').resolve()
    with tempfile.TemporaryDirectory(prefix='secret-rules-test-') as td:
        root = Path(td)
        defaults = root / 'defaults.toml'
        defaults.write_text('[extend]\nuseDefault = true\n')
        source = root / 'input'
        docs = source / 'docs'
        docs.mkdir(parents=True)
        path = docs / 'FUNCTIONAL_SPEC.md'
        path.write_text('- current-token manual conversion: `Ctrl+Shift+F12`;\n- previous-token manual conversion: `Ctrl+Shift+F10`;\n')
        args = ['dir', str(source)]
        baseline = run_scan(args, root / 'baseline.json', defaults)
        assert len(baseline) == 2, 'Fixture must reproduce both original default-rule false positives'
        assert not run_scan(args, root / 'allowed.json', config), 'Exact documented shortcuts should pass'
        # Synthetic random values only: these have never been issued by a service.
        value = secrets.token_hex(24)
        path.write_text('api_key = "' + value + '"\n')
        assert run_scan(args, root / 'blocked-doc.json', config), 'Credential-shaped text in documentation must remain detectable'
        path.unlink()
        src = source / 'src'
        src.mkdir()
        (src / 'config.txt').write_text('api_key = "' + value + '"\n')
        assert run_scan(args, root / 'blocked-src.json', config), 'Credential-shaped text in source must remain detectable'
        (src / 'config.txt').write_text('token = "' + 'ghp' + '_' + secrets.token_hex(18) + '"\n')
        assert run_scan(args, root / 'blocked-provider.json', config), 'Provider-specific token rule must remain enabled'
    print('Secret rule conformance: original false positives reproduced; exact exceptions pass; 3 negative checks block.')


if __name__ == '__main__':
    main()
