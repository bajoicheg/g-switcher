"""Owned isolated writer: broker regression RED, scoped payload, GREEN, exact bundle; PREPARED ONLY."""
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
assert set(pinned['expected_changed_paths']).issubset(pinned['write_paths'])
expected_changed = {p for p in payload['files'] if payload['payload_sha256'][p] != payload['original_sha256'][p]}
assert expected_changed == set(pinned['expected_changed_paths'])
assert pinned['source_spec_verdict'] == pinned['source_quality_verdict'] == 'PASS'
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
check('red-restart-regression', [str(red_bin),payload['red_test'],'--exact','--test-threads=1','--nocapture'],
      expected=101, required_text='main dispatcher was blocked by the exact pending Word provider')

authority_red = host / 'protocol-tests' / 'authority-baseline.rs'
authority_red_bin = out / 'authority-baseline-tests'
check('authority-red-compile', ['rustc','--edition','2021','--test',str(authority_red),'-o',str(authority_red_bin)])
for name in payload['required_authority_tests']:
    check('authority-red-' + name, [str(authority_red_bin),'authority_tests::' + name,'--exact','--nocapture'],
          expected=101,required_text='assertion `left == right` failed')

cleanup_red = host / 'protocol-tests' / 'cleanup-baseline.rs'
cleanup_red_bin = out / 'cleanup-baseline-tests'
check('cleanup-red-compile', ['rustc','--edition','2021','--test',str(cleanup_red),'-o',str(cleanup_red_bin)])
check('cleanup-red', [str(cleanup_red_bin),payload['cleanup_red_test'],'--exact','--nocapture'],
      expected=101,required_text='assertion `left == right` failed')

for relative, content in payload['files'].items():
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == payload['payload_sha256'][relative]

def required_passes(label, names):
    log = (out / (label + '.log')).read_text(errors='replace')
    for name in names:
        assert '::' + name + ' ... ok' in log, 'Missing passed regression: ' + name

def harness(label, modules, required):
    source = out / (label + '.rs')
    source.write_text(''.join('#[path = ' + json.dumps(str(root / relative)) + '] mod ' + name + ';\n' for name, relative in modules))
    executable = out / (label + '-tests')
    check(label + '-compile', ['rustc','--edition','2021','--test',str(source),'-o',str(executable)])
    check(label, [str(executable),'--test-threads=1'])
    required_passes(label, required)

harness('green-dispatch', [('production_dispatch',payload['green_source'])], payload['required_green_tests'])
harness('green-cleanup', [('production_cleanup','src/windows_runtime/word_call_gate.rs')], payload['required_cleanup_tests'])
harness('green-guard-reader', [('production_guard','src/windows_runtime/guard_core.rs'),('production_reader','src/windows_runtime/read_worker.rs')], pinned['required_guard_reader_tests'] + payload['required_authority_tests'])
check('format', ['rustfmt','--edition','2021','--config','skip_children=true',
                *[p for p in pinned['write_paths'] if p.endswith('.rs')]])
check('portable-library-tests', ['cargo','test','--locked','--lib'])
required_passes('portable-library-tests', payload['required_candidate_tests'])
check('Windows-typed-compile', ['cargo','check','--locked','--target','x86_64-pc-windows-gnu','--all-targets'])
check('Windows-clippy', ['cargo','clippy','--locked','--target','x86_64-pc-windows-gnu','--all-targets','--','-D','warnings'])
check('whitespace', ['git','diff','--check'])
changed = {line[3:] for line in git('status','--porcelain','--untracked-files=all').splitlines()}
assert changed == set(pinned['expected_changed_paths']), 'Owned exact changed scope drift'
git('config','user.name','G-switcher managed executor')
git('config','user.email','g-switcher@example.invalid')
git('add','--',*pinned['write_paths'])
git('diff','--cached','--check')
git('commit','-m','[skip ci] isolate Word provider waiting from switcher input dispatch')
result = git('rev-parse','HEAD')
assert result != BASE and not git('status','--porcelain')
git('bundle','create',str(out / 'result.bundle'),'HEAD','^'+BASE)
digest = hashlib.sha256((out / 'result.bundle').read_bytes()).hexdigest()
write('preflight.json', {'source':BASE,'result':result,'owned_worker_checks_passed':True,
    'checks':checks,'write_paths':pinned['write_paths'],'bundle_sha256':digest,
    'installed_Word_acceptance':'pending','partial_replacement_fix':False,
    'required_windows_tests':payload['required_windows_tests'],'broker_isolation_runtime_acceptance':'Windows fixture gates required'})
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
