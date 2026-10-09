"""Actions host transport: keep the managed controller live during artifact upload."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(os.environ['RUNNER_TEMP']) / ('word-bootstrap-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'])
root.mkdir(parents=True, exist_ok=True)
if sys.argv[1] == 'start':
    log = (root / 'controller.log').open('ab')
    child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).with_name('controller.py'))],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (root / 'controller-pid.json').write_text(json.dumps({'pid': child.pid}))
    deadline = time.monotonic() + 12 * 60
    while time.monotonic() < deadline:
        if (root / 'recovered/upload-ready.json').exists():
            print('MANAGED_BUNDLE_UPLOAD_READY', flush=True)
            break
        if (root / 'controller-result.json').exists() or child.poll() is not None:
            print((root / 'controller.log').read_text(errors='replace')[-16000:], flush=True)
            raise RuntimeError('Managed bootstrap exited before upload readiness')
        time.sleep(3)
    else:
        raise RuntimeError('Managed bundle upload readiness deadline')
elif sys.argv[1] == 'wait':
    deadline = time.monotonic() + 40 * 60
    previous = 0
    while time.monotonic() < deadline:
        text = (root / 'controller.log').read_text(errors='replace')
        if len(text) > previous:
            print(text[previous:], end='', flush=True)
            previous = len(text)
        if (root / 'controller-result.json').exists():
            result = json.loads((root / 'controller-result.json').read_text())
            if result['controller_scope_complete'] and result.get('windows_conclusion') == 'succeeded':
                break
            raise RuntimeError('Managed recovery did not produce successful Windows evidence; inspect preserved protocol')
        time.sleep(5)
    else:
        raise RuntimeError('Managed controller supervision deadline')
else:
    raise ValueError('Unknown host step')
