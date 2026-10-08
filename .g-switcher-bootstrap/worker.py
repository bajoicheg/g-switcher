"""Managed read-only task: reconstruct frozen result, wait for governed validation."""
import json
import os
from pathlib import Path
import time
import bundle_worker

bundle_worker.main()
root = Path(os.environ['CDC_PREFLIGHT_OUTPUT'])
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
