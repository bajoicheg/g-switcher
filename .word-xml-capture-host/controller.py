"""Own the canonical read-only host lifecycle for standalone proposal tests."""
import hashlib, json, os, sys, time, uuid
from pathlib import Path
from datetime import datetime, timezone
import subprocess, urllib.request

def utc(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def write(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def git(repo,*args): return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
def main():
 host=Path(__file__).resolve().parent;repo=Path(os.environ['CDC_REPO_ROOT']).resolve()
 pinned=json.loads((host/'host-launch-intent.json').read_text());base=pinned['base']
 source='refs/heads/release/2.0.1';lease_ref='refs/heads/cdc/coordination'
 run=os.environ['GITHUB_RUN_ID'];attempt=os.environ['GITHUB_RUN_ATTEMPT'];assert attempt=='1'
 work=Path(os.environ['RUNNER_TEMP'])/('word-capture-'+run+'-'+attempt)
 out=work/'evidence';out.mkdir(parents=True,exist_ok=True)
 sys.path.insert(0,str(repo/'.agents/skills/continuous-development-cycle/scripts'))
 import managed_host_bridge as bridge, managed_executor_pool as pool, execution_lease_v2 as leasev2, budget, operation_intent as op
 from git_lease_store import GitLeaseStore
 from git_document_store import GitDocumentStore
 from git_remote_identity import remote_identity
 from runtime_factory import make_runtime_factory
 assert git(repo,'rev-parse','HEAD')==base and not git(repo,'status','--porcelain')
 assert git(repo,'rev-parse',base+':.agents/skills/continuous-development-cycle')==pinned['cdc_package_tree']
 git(repo,'config','core.logAllRefUpdates','true')
 source_id=remote_identity(repo,'origin')
 store=GitDocumentStore(repo,'origin',pinned['admission_ref'],source_id,protected_refs=[source,lease_ref])
 revision,document=store.read()
 assert document['state']=='prepared' and document['host_admission'] is None
 assert document['host_head']==os.environ['GITHUB_SHA']
 assert document['intent_sha256']==hashlib.sha256((host/'host-launch-intent.json').read_bytes()).hexdigest()
 assert document['budget_ledger']==pinned['budget_ledger']
 for path,digest in pinned['payload_sha256'].items(): assert hashlib.sha256((host/path).read_bytes()).hexdigest()==digest,path
 def authenticate(lease_store,lease_revision,repository,source_ref,owner_id,task_id,attempt_id,at):
  actual_revision,actual=lease_store.read();leasev2.validate(actual)
  assert actual_revision==lease_revision==pinned['prior_release_revision']
  assert actual==pinned['prior_lease']
  assert actual['generation']==48 and all(actual[k] is None for k in ['owner_id','invocation','external_guard','finalization'])
  assert repository==actual['repository']=='bajoicheg/g-switcher' and source_ref==actual['source_ref']==source
  assert bridge._remote_head(repo,'origin',source)==base
  assert lease_store.read()==(actual_revision,actual)
  return None
 bridge.ManagedExecutorRuntime=make_runtime_factory(bridge.ManagedExecutorRuntime,authenticate,lease_ttl=900)
 document.update(state='claimed',host_admission=dict(run_id=int(run),run_attempt=1,host_head=os.environ['GITHUB_SHA'],claimed_at_utc=utc()))
 revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
 key='word-capture-'+run+'-'+attempt
 plan=dict(schema='managed-executor-pool-plan/v1',pool_id=key,change_id='Word-XML-capture-Windows-validation',parent_invocation_id='github-actions:'+run+':'+attempt,
  base_sha=base,integrator_id='canonical-managed-host-bridge',coordination_ref='refs/heads/cdc/managed-word-xml/'+key,coordination_store_id=source_id,
  max_parallel=1,total_runtime_budget_seconds=600,total_cost_budget_units=1,tasks=[dict(id='capture-validation',role='read_only',required=True,dependencies=[],
   executor_id='managed-word-capture-tests',branch=None,worktree=None,write_paths=[],expected_outputs=['out:windows-tool-tests'],expected_evidence=['evidence:windows-tool-validation'],
   backend_preferences=['local_command'],max_runtime_seconds=600,max_cost_units=1)])
 pool.validate_plan(plan)
 os.environ['CDC_PREFLIGHT_OUTPUT']=str(out)
 request=dict(schema='managed-host-start/v1',repo_root=str(repo),remote='origin',plan=plan,journal_root=str(work/'journal'),handle_root=str(work/'handles'),
  lease_coordination_ref=lease_ref,lease_repository='bajoicheg/g-switcher',lease_source_ref=source,task_id='capture-validation',attempt_id=key+'-a1',reservation_token='reserve:'+key,
  owner_id=str(uuid.uuid4()),argv=[sys.executable,'-B',str(host/'worker.py')])
 write(work/'start.json',request)
 handle=None;finalized=False
 try:
  handle=bridge.start(request);write(work/'handle.json',handle)
  assert handle['generation']==pinned['prior_lease']['generation']+1
  admitted_revision,admitted_lease=GitLeaseStore(repo,'origin',lease_ref).read()
  assert admitted_lease['owner_id']==request['owner_id'] and admitted_lease['generation']==handle['generation']
  inv=admitted_lease['invocation']['invocation_id']
  binding=dict(repository='bajoicheg/g-switcher',candidate_sha=os.environ['GITHUB_SHA'],backend='github_actions',mode='CI_ONLY',environment_id='windows-latest/powershell5.1',check_suite_fingerprint='sha256:'+pinned['proposal_hash'],environment_fingerprint=op._hash({'runner':'windows-latest','powershell':'5.1','native_word':'NOT_RUN'}),check_plan_digest=op._hash(pinned['windows_required_steps']))
  external_intent=op.prepare(binding,key+'-windows-a1',source,utc())
  document.update(state='windows-intent-prepared',windows_intent=external_intent)
  revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
  receipt=op.verify_readback(external_intent,store.read()[1]['windows_intent'],'git:'+revision+':document.json',utc())
  external_intent=op.transition(external_intent,'submitting',utc(),receipt=receipt)
  document.update(state='windows-submitting',windows_intent=external_intent)
  revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
  ls=GitLeaseStore(repo,'origin',lease_ref);lr,lv=ls.read()
  lv=leasev2.set_guard(lv,request['owner_id'],handle['generation'],inv,utc(),external_intent,'git:'+revision+':document.json')
  lr=ls.compare_and_swap(lr,lv);assert ls.read()==(lr,lv)
  claim=leasev2.claim_submission(ls,lr,'bajoicheg/g-switcher',source,request['owner_id'],handle['generation'],inv,utc(),intent_digest=op._hash(external_intent))
  document.update(state='managed-admitted',windows_claim=claim['grant'],managed_lease={'revision':claim['revision'],'owner_id':request['owner_id'],'generation':handle['generation'],'invocation_id':inv})
  revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
  write(out/'controller-admitted.json',{'generation':handle['generation']})
  observe=dict(schema='managed-host-observe/v1',handle_root=str(work/'handles'),handle_id=handle['handle_id'])
  deadline=time.monotonic()+600
  while True:
   state=bridge.observe(observe);write(work/'observed.json',state)
   if state.get('runtime_status')=='awaiting_release': break
   assert time.monotonic()<deadline
   time.sleep(2)
  status=state['pending_terminal_status'];assert status in ['succeeded','failed','cancelled','timed_out']
  def reconcile_windows():
   req=urllib.request.Request('https://api.github.com/repos/bajoicheg/g-switcher/actions/runs/'+run+'/attempts/1/jobs?per_page=100',headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Cache-Control':'no-cache'})
   with urllib.request.urlopen(req,timeout=20) as response: jobs=json.load(response)
   assert jobs['total_count']<=100
   matches=[j for j in jobs['jobs'] if j['name']=='diagnostic'];assert len(matches)<=1
   if not matches or matches[0]['status']!='completed':return False
   job=matches[0];conclusions={'success':'succeeded','failure':'failed','cancelled':'cancelled','timed_out':'timed_out','skipped':'setup_failed'}
   assert job['conclusion'] in conclusions
   ls=GitLeaseStore(repo,'origin',lease_ref);lr,lv=ls.read()
   if lv['external_guard'] is None:return True
   guarded=lv['external_guard']['intent']
   assert guarded['binding']['candidate_sha']==os.environ['GITHUB_SHA'] and guarded['attempt_id']==key+'-windows-a1'
   task=dict(task_id=run+':1:diagnostic',task_url=job['html_url'],operation_key=guarded['operation_key'],attempt_id=guarded['attempt_id'],binding=guarded['binding'],state='terminal',conclusion=conclusions[job['conclusion']],evidence_refs=[job['html_url']])
   observation=dict(schema='operation-observation/v1',operation_key=guarded['operation_key'],lookup_complete=True,observed_at_utc=utc(),tasks=[task])
   document.update(windows_terminal_observation=observation)
   nonlocal_revision=store.compare_and_swap(revision,document)
   assert store.read()==(nonlocal_revision,document)
   lv=leasev2.clear_guard(lv,request['owner_id'],handle['generation'],lv['invocation']['invocation_id'],utc(),observation,'git:'+nonlocal_revision+':document.json')
   lr=ls.compare_and_swap(lr,lv);assert ls.read()==(lr,lv)
   return True
  windows_reconciled=reconcile_windows()
  revision,document=store.read()
  if status=='succeeded':assert windows_reconciled

  result=json.loads((out/'result.json').read_text()) if status=='succeeded' else None
  if status=='succeeded': assert result['payload_sha256']==pinned['proposal_hash'] and result['windows_job_conclusion']=='success'
  ledger=pinned['budget_ledger'];reservation=pinned['host_reservation']
  elapsed=(datetime.fromisoformat(utc().replace('Z','+00:00'))-datetime.fromisoformat(reservation['at_utc'].replace('Z','+00:00'))).total_seconds()
  ledger=budget.apply_event(ledger,dict(type='outcome',event_id='word-capture-host-a1-outcome',task_id=ledger['task_id'],wake_id=ledger['wake_ids'][-1],at_utc=utc(),
   reservation_id=reservation['event_id'],status=status,failure=None if status in ['succeeded','cancelled'] else {'category':'code','signature':'Standalone-XML-tests-failed'},usage={'tokens':None,'elapsed_seconds':elapsed}))
  document.update(state='worker-terminal',worker_status=status,result=result,budget_ledger=ledger)
  revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
  finished=bridge.finish(dict(schema='managed-host-finish/v1',handle_root=str(work/'handles'),handle_id=handle['handle_id'],
   output_refs=['out:windows-tool-tests'],evidence_refs=['evidence:windows-tool-validation'],checkpoint_ref='git:'+revision+':document.json'))
  finalized=True
  write(work/'finished.json',finished)
  assert finished['final_response_allowed'] and finished['published_commit'] is None
  lease_revision,lease=GitLeaseStore(repo,'origin',lease_ref).read()
  assert lease['generation']==handle['generation'] and all(lease[k] is None for k in ['owner_id','invocation','external_guard','finalization'])
  assert bridge._remote_head(repo,'origin',source)==base
  document.update(state='terminal',finished=finished,lease_revision=lease_revision,lease=lease,completed_at_utc=utc())
  revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
  write(work/'terminal.json',document)
  print('WORD_CAPTURE_MANAGED_RELEASED status='+status+' checkpoint='+revision,flush=True)
  return 0 if status=='succeeded' else 1
 finally:
  if handle is None and not finalized:
   # Recover only an actually persisted opaque session for this exact request.
   # observe resumes its consumed attempt; no second start or lease fabrication.
   sessions=[]
   for path in (work/'handles').glob('*.json'):
    session=json.loads(path.read_text())
    if session.get('owner_id')==request['owner_id'] and session.get('attempt_id')==request['attempt_id'] and session.get('plan')==plan:
     sessions.append(session)
   assert len(sessions)<=1
   if sessions: handle={'handle_id':sessions[0]['handle_id']}
  if handle is not None and not finalized:
   # Failure finalization uses the canonical exact handle only. A successful
   # worker with missing result proof remains recoverable, never re-labelled.
   observe=dict(schema='managed-host-observe/v1',handle_root=str(work/'handles'),handle_id=handle['handle_id'])
   state=bridge.observe(observe)
   if state.get('runtime_status')!='awaiting_release':
    write(work/'cancel.json',bridge.cancel(dict(schema='managed-host-cancel/v1',handle_root=str(work/'handles'),handle_id=handle['handle_id'])))
   recovery_deadline=time.monotonic()+50
   while time.monotonic()<recovery_deadline:
    state=bridge.observe(observe);write(work/'failure-observed.json',state)
    if state.get('runtime_status')=='awaiting_release':
     status=state.get('pending_terminal_status')
     if status in ['failed','cancelled','timed_out']:
      if 'reconcile_windows' in locals(): reconcile_windows()
      revision,document=store.read()
      assert document['host_admission']['run_id']==int(run) and document['host_head']==os.environ['GITHUB_SHA']
      ledger=document['budget_ledger'];reservation=pinned['host_reservation']
      if not any(e['event_id']=='word-capture-host-a1-outcome' for e in ledger['events']):
       elapsed=(datetime.fromisoformat(utc().replace('Z','+00:00'))-datetime.fromisoformat(reservation['at_utc'].replace('Z','+00:00'))).total_seconds()
       ledger=budget.apply_event(ledger,dict(type='outcome',event_id='word-capture-host-a1-outcome',task_id=ledger['task_id'],wake_id=ledger['wake_ids'][-1],at_utc=utc(),reservation_id=reservation['event_id'],status=status,failure=None if status=='cancelled' else {'category':'configuration','signature':'Standalone-host-controller-incomplete'},usage={'tokens':None,'elapsed_seconds':elapsed}))
      document.update(state='failure-checkpoint',worker_status=status,budget_ledger=ledger,handle_id=handle['handle_id'],failure_observation=state)
      revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
      released=bridge.finish(dict(schema='managed-host-finish/v1',handle_root=str(work/'handles'),handle_id=handle['handle_id'],output_refs=['failure:xml-worker:'+status],evidence_refs=['failure:xml-controller-incomplete'],checkpoint_ref='git:'+revision+':document.json'))
      write(work/'failure-finished.json',released)
      document.update(state='failure-terminal',finished=released,completed_at_utc=utc())
      revision=store.compare_and_swap(revision,document);assert store.read()==(revision,document)
      write(work/'terminal.json',document)
     break
    time.sleep(2)
if __name__=='__main__': raise SystemExit(main())
