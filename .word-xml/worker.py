"""Exact standalone proposal verification; product checkout remains read-only."""
import hashlib, json, os, subprocess, time
from pathlib import Path
host=Path(__file__).resolve().parent
root=Path.cwd()
out=Path(os.environ['CDC_PREFLIGHT_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
pinned=json.loads((host/'host-launch-intent.json').read_text())
manifest=json.loads((host/'proposal/manifest.json').read_text())
checks=[]
def git(*args):
 return subprocess.check_output(['git',*args],text=True).strip()
def check(label,argv,expected=0,required=()):
 start=time.monotonic()
 result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
 (out/(label+'.log')).write_text(result.stdout)
 checks.append(dict(name=label,argv=argv,exit_code=result.returncode,expected_exit_code=expected,elapsed_seconds=time.monotonic()-start))
 (out/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
 print('XML_CHECK '+label+' exit='+str(result.returncode),flush=True)
 assert result.returncode==expected,label
 for text in required: assert text in result.stdout,(label,text)
 return result.stdout
assert git('rev-parse','HEAD')==pinned['base'] and not git('status','--porcelain')
assert pinned['source_spec_verdict']==pinned['source_quality_verdict']=='PASS'
for path,digest in pinned['payload_sha256'].items():
 assert hashlib.sha256((host/path).read_bytes()).hexdigest()==digest,path
deadline=time.monotonic()+120
while not (out/'controller-admitted.json').exists():
 assert time.monotonic()<deadline
 time.sleep(1)
check('rust-version',['rustc','--version'],required=('rustc 1.98.1',))
red=out/'baseline-tests'
check('red-compile',['rustc','--edition=2021','--test',str(host/'proposal/baseline.rs'),'-o',str(red)])
check('red-model-contract',[str(red),manifest['required_red_test'],'--exact','--nocapture'],101,
 ('running 1 test','per-character baseline makes several submissions and leaves prefix','left: 3','right: 1','1 failed'))
check('baseline-prefix',[str(red),manifest['required_baseline_prefix_test'],'--exact','--nocapture'],required=('running 1 test','1 passed; 0 failed'))
green=out/'proposal-tests'
check('green-compile',['rustc','--edition=2021','--test',str(host/'proposal/green_harness.rs'),'-o',str(green)])
log=check('green',[str(green),'--test-threads=1','--nocapture'],required=('18 passed; 0 failed',))
for name in manifest['required_green_tests']: assert 'test '+name+' ... ok' in log,name
assert len(manifest['required_green_tests'])==18
assert git('rev-parse','HEAD')==pinned['base'] and not git('status','--porcelain')
result=dict(schema='word-xml-prototype-compiled-evidence/v1',source_base=pinned['base'],payload_sha256=pinned['proposal_hash'],
 red_observed=True,red_kind='per-character interface model, not old native runtime',green_required_tests=manifest['required_green_tests'],
 checks=checks,product_integration=False,actual_word_calls=False,formatting_fidelity_proved=False,native_undo_proved=False)
(out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print('XML_STANDALONE_RED_GREEN_PASS',flush=True)
