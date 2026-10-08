"""Managed read-only task: reconstruct frozen result, wait for governed validation."""
import json
import os
from pathlib import Path
import time
import bundle_worker

root = Path(os.environ['CDC_PREFLIGHT_OUTPUT'])
reconciliation_deadline = time.monotonic() + 5 * 60
while not (root / 'controller-reconciled.json').exists():
    if (root / 'abort-worker.json').exists():
        raise RuntimeError('Inherited validation was not reconciled')
    assert time.monotonic() < reconciliation_deadline, 'Prior validation reconciliation deadline'
    time.sleep(1)
proof = json.loads((root / 'controller-reconciled.json').read_text())
assert proof['candidate'] == bundle_worker.RESULT and proof['prior_external_guard_reconciled'] is True
bundle_worker.main()
(root / 'bundle-ready.json').write_text(json.dumps({'candidate': bundle_worker.RESULT, 'waiting_for_terminal_validation': True}))
deadline = time.monotonic() + 38 * 60
while time.monotonic() < deadline:
    if (root / 'abort-worker.json').exists():
        raise RuntimeError('Managed recovery did not reach terminal Windows evidence')
    terminal = root / 'windows-terminal.json'
    if terminal.exists():
        result = json.loads(terminal.read_text())
        assert result['candidate'] == bundle_worker.RESULT and result['external_guard_reconciled'] is True
        print('RECOVERY_TASK_COMPLETE exact_candidate=' + bundle_worker.RESULT, flush=True)
        break
    time.sleep(2)
else:
    raise RuntimeError('Managed recovery terminal evidence deadline exceeded')
