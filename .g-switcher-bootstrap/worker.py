"""Owned isolated writer: observed regression RED, scoped payload, GREEN, exact bundle."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from constants import BASE

host = Path(__file__).resolve().parent
root = Path.cwd()
out = Path(os.environ['CDC_PREFLIGHT_OUTPUT'])
out.mkdir(parents=True, exist_ok=True)
checks = []

def write(name, value):
    temporary = out / (name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(out / name)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).rstrip('\n')

def check(label, argv, *, expected=0, required_text=None, timeout=600):
    start = time.monotonic()
    print('WORD_GUARD_CHECK_START ' + label, flush=True)
    with (out / (label + '.log')).open('w') as log:
        result = subprocess.run(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    text = (out / (label + '.log')).read_text(errors='replace')
    record = {'name':label, 'argv':argv, 'exit_code':result.returncode,
              'expected_exit_code':expected, 'elapsed_seconds':round(time.monotonic()-start,3)}
    checks.append(record)
    write('checks.json', checks)
    if result.returncode != expected or (required_text is not None and required_text not in text):
        print(text[-16000:], flush=True)
        raise RuntimeError('Owned validation failed: ' + label)
    print('WORD_GUARD_CHECK_PASS ' + label, flush=True)

assert git('rev-parse', 'HEAD') == BASE and not git('status', '--porcelain')
payload_bytes = (host / 'product-payload.json').read_bytes()
pinned = json.loads((host / 'host-launch-intent.json').read_text())
assert hashlib.sha256(payload_bytes).hexdigest() == pinned['product_payload_sha256']
payload = json.loads(payload_bytes)
assert payload['integration_complete'] is True and payload['source_base'] == BASE
assert set(payload['files']) == set(pinned['write_paths']) == set(payload['original_sha256'])
for relative, expected in payload['original_sha256'].items():
    path = root / relative
    if expected is None:
        assert not path.exists(), 'Unexpected product path'
    else:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Original source drift'

deadline = time.monotonic() + 120
while not (out / 'controller-admitted.json').exists():
    assert time.monotonic() < deadline
    time.sleep(1)

# Regression compilation succeeds; failure must be an actual named test assertion.
red = host / 'protocol-tests' / 'baseline.rs'
red_bin = out / 'baseline-tests'
check('red-compile', ['rustc','--edition','2021','--test',str(red),'-o',str(red_bin)])
check('red-restart-regression', [str(red_bin),'tests::restart_refuses_previous_pending_before_any_provider_call','--exact','--nocapture'],
      expected=101, required_text='FAILED')

for relative, content in payload['files'].items():
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == payload['payload_sha256'][relative]

green = root / payload['green_source']
green_bin = out / 'fixed-tests'
green_harness = out / 'production-guard-tests.rs'
green_harness.write_text('#[path = ' + json.dumps(str(green), ensure_ascii=False) + '] mod production_guard;\n')
check('green-compile', ['rustc','--edition','2021','--test',str(green_harness),'-o',str(green_bin)])
check('green-protocol-tests', [str(green_bin),'--test-threads=1','--nocapture'])
green_log = (out / 'green-protocol-tests.log').read_text(errors='replace')
for test_name in payload['required_green_tests']:
    assert '::' + test_name + ' ... ok' in green_log, 'Missing passed protocol regression: ' + test_name
check('format', ['rustfmt','--edition','2021','--config','skip_children=true',
                *[p for p in pinned['write_paths'] if p.endswith('.rs')]])
check('portable-library-tests', ['cargo','test','--locked','--lib'])
check('Windows-typed-compile', ['cargo','check','--locked','--target','x86_64-pc-windows-gnu','--all-targets'])
check('Windows-clippy', ['cargo','clippy','--locked','--target','x86_64-pc-windows-gnu','--all-targets','--','-D','warnings'])
check('whitespace', ['git','diff','--check'])
changed = {line[3:] for line in git('status','--porcelain','--untracked-files=all').splitlines()}
assert changed == set(pinned['write_paths']), 'Owned write scope drift'
git('config','user.name','G-switcher managed executor')
git('config','user.email','g-switcher@example.invalid')
git('add','--',*pinned['write_paths'])
git('diff','--cached','--check')
git('commit','-m','[skip ci] retain Word provider uncertainty across switcher restarts')
result = git('rev-parse','HEAD')
assert result != BASE and not git('status','--porcelain')
git('bundle','create',str(out / 'result.bundle'),'HEAD','^'+BASE)
digest = hashlib.sha256((out / 'result.bundle').read_bytes()).hexdigest()
write('preflight.json', {'source':BASE,'result':result,'owned_worker_checks_passed':True,
    'checks':checks,'write_paths':pinned['write_paths'],'bundle_sha256':digest,
    'installed_Word_acceptance':'pending','partial_replacement_fix':False})
write('bundle-ready.json', {'candidate':result,'waiting_for_terminal_validation':True})
deadline = time.monotonic() + 35*60
while time.monotonic() < deadline:
    if (out / 'abort-worker.json').exists():
        raise RuntimeError('Controller could not verify terminal validation')
    path = out / 'windows-terminal.json'
    if path.exists():
        result_observation = json.loads(path.read_text())
        assert result_observation['candidate'] == result and result_observation['external_guard_reconciled'] is True
        assert result_observation['conclusion'] == 'succeeded', 'Failed Windows candidate cannot publish'
        print('WORD_GUARD_CANDIDATE_VALIDATED ' + result, flush=True)
        break
    time.sleep(2)
else:
    raise RuntimeError('Owned Windows terminal evidence deadline')
