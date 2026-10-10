"""Observe the exact gated Windows sibling; never write the product checkout."""
import hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
host=Path(__file__).resolve().parent
out=Path(os.environ['CDC_PREFLIGHT_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
pinned=json.loads((host/'host-launch-intent.json').read_text())
def git(*args):return subprocess.check_output(['git',*args],text=True).strip()
def api(path):
 req=urllib.request.Request('https://api.github.com/repos/bajoicheg/g-switcher/'+path,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Cache-Control':'no-cache'})
 with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)
assert git('rev-parse','HEAD')==pinned['base'] and not git('status','--porcelain')
assert pinned['source_spec_verdict']==pinned['source_quality_verdict']=='PASS'
for path,digest in pinned['payload_sha256'].items():assert hashlib.sha256((host/path).read_bytes()).hexdigest()==digest,path
run=os.environ['GITHUB_RUN_ID'];assert os.environ['GITHUB_RUN_ATTEMPT']=='1'
deadline=time.monotonic()+570
while not (out/'controller-admitted.json').exists():
 assert time.monotonic()<deadline
 time.sleep(1)
required=['Checkout exact standalone diagnostic proposal','Await exact managed admission','Verify proposal and released CDC bindings','Windows PowerShell 5.1 parser and behavior checks','Package standalone probe and provenance','Upload tested diagnostic kit']
while True:
 assert time.monotonic()<deadline,'Windows sibling observation deadline'
 live=api('actions/runs/'+run)
 assert live['head_sha']==os.environ['GITHUB_SHA'] and live['run_attempt']==1
 jobs=api('actions/runs/'+run+'/attempts/1/jobs?per_page=100');assert jobs['total_count']<=100
 matches=[j for j in jobs['jobs'] if j['name']=='diagnostic'];assert len(matches)<=1
 if matches and matches[0]['status']=='completed':
  job=matches[0];(out/'windows-job.json').write_text(json.dumps(job,indent=2)+'\n')
  assert job['conclusion']=='success',job['conclusion']
  steps={s['name']:s for s in job['steps']}
  for name in required:assert name in steps and steps[name]['status']=='completed' and steps[name]['conclusion']=='success',name
  artifacts=api('actions/runs/'+run+'/artifacts?per_page=100');assert artifacts['total_count']<=100
  kits=[a for a in artifacts['artifacts'] if a['name']=='g-switcher-word-xml-probe' and not a['expired']];assert len(kits)==1
  break
 time.sleep(10)
assert git('rev-parse','HEAD')==pinned['base'] and not git('status','--porcelain')
result={'schema':'word-capture-Windows-evidence/v1','source_base':pinned['base'],'payload_sha256':pinned['proposal_hash'],'windows_job_conclusion':'success','run_id':int(run),'job_id':job['id'],'job_url':job['html_url'],'required_steps':required,'artifact_id':kits[0]['id'],'core_tests':18,'supervision_tests':2,'cleanup_tests':2,'product_integration':False,'actual_word_execution':'NOT_RUN'}
(out/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print('WORD_CAPTURE_WINDOWS_TESTS_PASS',flush=True)
