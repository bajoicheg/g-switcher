"""Native receiving-event admission; never dispatches, skips or waives checks."""
from __future__ import annotations
import copy,hashlib,json,re,subprocess
from datetime import datetime,timezone
from pathlib import PurePosixPath
import budget
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_remote_identity import remote_identity
from live_target import GitSource,verify_release_binding

PACKAGE='.agents/skills/continuous-development-cycle'
_SEAL=object()
def _digest(value):return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def _now():return datetime.now(timezone.utc)
def _stamp(at):return at.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def _glob(pattern,value):
 if not isinstance(pattern,str) or not pattern or any(c in pattern for c in ('[',']','+','?','\\')):raise ValueError('unsupported workflow filter pattern; reconcile explicitly')
 regex='';i=0
 while i<len(pattern):
  if pattern[i:i+3]=='**/':regex+='(?:.*/)?';i+=3
  elif pattern[i:i+2]=='**':regex+='.*';i+=2
  elif pattern[i]=='*':regex+='[^/]*';i+=1
  else:regex+=re.escape(pattern[i]);i+=1
 return re.fullmatch(regex,value) is not None
def _matches(patterns,value):
 if not isinstance(patterns,list) or not patterns:raise ValueError('workflow filter list required')
 match=False
 for pattern in patterns:
  if not isinstance(pattern,str):raise ValueError('workflow filter must be text')
  negative=pattern.startswith('!');pattern=pattern[1:] if negative else pattern
  if _glob(pattern,value):match=not negative
 return match
def _selected(config,branch,paths,*,workflow_run=False,conservative_paths=False):
 config={} if config is None or config=='' else config
 if not isinstance(config,dict):raise ValueError('event filter mapping required')
 allowed={'branches','branches-ignore','paths','paths-ignore','types'} | ({'workflows'} if workflow_run else set())
 if set(config)-allowed:raise ValueError('unknown event filter must not suppress required CI')
 for pair in (('branches','branches-ignore'),('paths','paths-ignore')):
  if all(k in config for k in pair):raise ValueError('conflicting event filters')
 if 'branches' in config and not _matches(config['branches'],branch):return False
 if 'branches-ignore' in config and _matches(config['branches-ignore'],branch):return False
 if not conservative_paths:
  if 'paths' in config and not any(_matches(config['paths'],path) for path in paths):return False
  if 'paths-ignore' in config and paths and all(_matches(config['paths-ignore'],path) for path in paths):return False
 return True
def _workflow(text):
 import yaml
 try:doc=yaml.load(text,Loader=yaml.BaseLoader)
 except yaml.YAMLError:raise ValueError('invalid receiving workflow YAML') from None
 if not isinstance(doc,dict) or 'on' not in doc or not isinstance(doc.get('jobs'),dict):raise ValueError('receiving workflow definition incomplete')
 on=doc['on']
 if isinstance(on,str):on={on:{}}
 elif isinstance(on,list):on={name:{} for name in on}
 if not isinstance(on,dict):raise ValueError('workflow events invalid')
 return doc,on
def _cycle(path,event,doc,definition,paths):
 jobs=[]
 for name,job in doc['jobs'].items():
  if not isinstance(job,dict):raise ValueError('job definition invalid')
  jobs.append({'id':name,'if':job.get('if'),'predicate':'possible_requires_provider_reconciliation','steps':[step.get('if') for step in job.get('steps',[]) if isinstance(step,dict)]})
 return {'path':path,'event':event,'name':doc.get('name',path),'definition':definition,'jobs':jobs,'selection_paths':list(paths),'definition_sha256':hashlib.sha256(definition.encode()).hexdigest()}
def predict(*,branch,pr_base_branch,push_paths,cumulative_pr_paths,head_workflows,default_workflows,pr_base_workflows=None,push_commits=1):
 if cumulative_pr_paths is None and pr_base_branch is not None:raise ValueError('authentic cumulative PR paths required, not only last commit delta')
 for paths in (push_paths,cumulative_pr_paths or []):
  if not isinstance(paths,list) or any(not isinstance(x,str) or not x or '..' in PurePosixPath(x).parts or PurePosixPath(x).is_absolute() for x in paths):raise ValueError('receiving paths invalid')
 if type(push_commits) is not int or push_commits<1:raise ValueError('existing-branch push commit count required')
 push_uncertain=len(push_paths)>3000 or push_commits>1000
 pr_uncertain=len(cumulative_pr_paths or [])>3000
 cycles=[]
 for path,text in head_workflows.items():
  doc,on=_workflow(text)
  if 'push' in on and _selected(on['push'],branch,push_paths,conservative_paths=push_uncertain):cycles.append(_cycle(path,'push',doc,text,push_paths))
  for event in ('pull_request',):
   if pr_base_branch is not None and event in on and _selected(on[event],pr_base_branch,cumulative_pr_paths,conservative_paths=pr_uncertain):
    types=on[event].get('types') if isinstance(on[event],dict) else None
    if types is None or 'synchronize' in types:cycles.append(_cycle(path,event,doc,text,cumulative_pr_paths))
 if pr_base_branch is not None:
  if pr_base_workflows is None and any('pull_request_target' in _workflow(text)[1] for text in head_workflows.values()):
   raise ValueError('authentic PR base workflow definitions required')
  for path,text in (pr_base_workflows or {}).items():
   doc,on=_workflow(text)
   if 'pull_request_target' in on and _selected(on['pull_request_target'],pr_base_branch,cumulative_pr_paths,conservative_paths=pr_uncertain):
    config=on['pull_request_target'];types=config.get('types') if isinstance(config,dict) else None
    if types is None or 'synchronize' in types:cycles.append(_cycle(path,'pull_request_target',doc,text,cumulative_pr_paths))
 for cycle in cycles:
  uncertain=push_uncertain if cycle['event']=='push' else pr_uncertain
  cycle['coverage_reason']='provider_diff_limit_conservative_admission' if uncertain else 'native_complete_paths_provider_job_reconciliation'
 names={x['name'] for x in cycles}
 # workflow_run definitions come from the default branch, not the PR head.
 seen=set()
 for level in range(1,4):
  downstream=set()
  for path,text in default_workflows.items():
   doc,on=_workflow(text)
   if 'workflow_run' not in on or path in seen:continue
   config=on['workflow_run']
   if not isinstance(config,dict) or not isinstance(config.get('workflows'),list):raise ValueError('workflow_run upstream binding missing')
   if any(_matches(config['workflows'],name) for name in names) and _selected(config,branch,[],workflow_run=True):
    cycle=_cycle(path,'workflow_run',doc,text,[]);cycle['chain_level']=level
    cycle['coverage_reason']='default_branch_upstream_branch_any_conclusion_provider_job_reconciliation'
    cycles.append(cycle);seen.add(path);downstream.add(cycle['name'])
  names=downstream
 return {'schema':'receiving-ci-prediction/v1','required_cycles':cycles,'cumulative_pr_paths':cumulative_pr_paths,'job_predicates_are_not_provider_results':True,'authorizes_writer_start':False,'authorizes_dispatch':False,'authorizes_gate_waiver':False}

class GitHubReadOnlyAPI:
 """Existing official gh read-only transport; capture raw rc before interpretation."""
 def __init__(self,repository,journal_root,*,clock=_now):
  if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('canonical repository required')
  from pathlib import Path
  self.repository=repository;self.journal=Path(journal_root);self.clock=clock;self.journal.mkdir(parents=True,exist_ok=True)
 def read(self,suffix):
  if suffix not in ('','/pulls?state=open&per_page=100'):raise ValueError('bounded receiving GET only')
  import uuid
  identifier=uuid.uuid4().hex
  result=subprocess.run(['gh','api','--method','GET','repos/'+self.repository+suffix],capture_output=True,timeout=30)
  (self.journal/(identifier+'.stdout')).write_bytes(result.stdout);(self.journal/(identifier+'.stderr')).write_bytes(result.stderr)
  record={'schema':'native-provider-read/v1','repository':self.repository,'path':'repos/'+self.repository+suffix,'return_code':result.returncode,'observed_at_utc':_stamp(self.clock()),'stdout_sha256':hashlib.sha256(result.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(result.stderr).hexdigest()}
  (self.journal/(identifier+'.json')).write_text(json.dumps(record)+'\n')
  if result.returncode:raise ValueError('existing receiving provider route failed rc'+str(result.returncode)+'; no retry, token creation or replacement route')
  try:data=json.loads(result.stdout)
  except (ValueError,UnicodeError):raise ValueError('invalid authentic provider response') from None
  return data,record

def _workflows(source,snapshot):
 rows=source._git('ls-tree','-r','--name-only',snapshot.revision,'--','.github/workflows')[1].splitlines()
 return {PurePosixPath(path).name:source.read_file(snapshot,path) for path in rows if path.endswith(('.yml','.yaml'))}

class CanonicalProviderReads:
 """Read original connector GET bytes from the configured native control store.

The host saves authentic raw tool responses before interpretation. This reader
requires canonical Git provenance, original lease binding and independent native
Git joins; a caller JSON/URL/boolean is not a provider-read capability.
"""
 def __init__(self,lease_store,source_ref,revision,*,clock=_now):
  if type(lease_store) is not GitLeaseStore:raise ValueError('canonical lease store required')
  _,record=lease_store.read();self.repository=record['repository'];self.clock=clock
  ref='refs/heads/cdc/receiving-api-'+hashlib.sha256((self.repository+'\n'+source_ref).encode()).hexdigest()
  self.store=GitDocumentStore(lease_store.repo,lease_store.remote,ref,lease_store.store_id,protected_refs=[lease_store.ref]);self.revision=revision
  self.lease_store=lease_store;self.source_ref=source_ref
 def read(self,suffix):
  if suffix not in ('','/pulls?state=open&per_page=100'):raise ValueError('bounded receiving GET only')
  current,doc=self.store.read()
  if current!=self.revision or doc!=self.store.read_revision(self.revision):raise ValueError('provider-read canonical snapshot moved')
  if not isinstance(doc,dict) or set(doc)!={'schema','repository','source_ref','lease_revision','reads'} or doc['schema']!='canonical-provider-reads/v1' or doc['repository']!=self.repository or doc['source_ref']!=self.source_ref:raise ValueError('provider-read original scope mismatch')
  original=self.lease_store.read_revision(doc['lease_revision'])
  if original['repository']!=self.repository or original['source_ref']!=self.source_ref:raise ValueError('provider-read original canonical lease mismatch')
  rows=[x for x in doc['reads'] if x.get('path')=='repos/'+self.repository+suffix]
  if len(rows)!=1:raise ValueError('complete exact original provider GET receipt required')
  read=rows[0]
  if set(read)!={'schema','transport','tool_name','path','observed_at_utc','raw_response','raw_sha256'} or read['schema']!='provider-get-receipt/v1' or read['transport']!='github_connector' or read['tool_name']!='github_fetch':raise ValueError('authentic supported provider GET provenance required')
  raw=read['raw_response']
  if not isinstance(raw,str) or hashlib.sha256(raw.encode()).hexdigest()!=read['raw_sha256']:raise ValueError('original provider bytes/digest mismatch')
  at=datetime.fromisoformat(read['observed_at_utc'].replace('Z','+00:00'))
  if at.tzinfo is None or not 0<=(self.clock()-at).total_seconds()<=90:raise ValueError('provider lookup stale/future')
  try:value=json.loads(raw)
  except ValueError:raise ValueError('original provider response invalid') from None
  return value,{k:v for k,v in read.items() if k!='raw_response'} | {'canonical_revision':self.revision,'canonical_ref':self.store.ref}

def _current_definitions(source,prediction,*,confirmed_source=None):
 default=source.pin(prediction['default_ref']).revision
 if default!=prediction['default_revision'] and (prediction['default_ref'],default)!=confirmed_source:
  raise ValueError('receiving default workflow definition moved; reconcile original admission')
 for pr in prediction['pull_requests']:
  if source.pin(pr['base_ref']).revision!=pr['base']:
   raise ValueError('receiving cumulative PR base moved; reconcile original admission')

def _budget_read(source,lease_store,revision,ledger_path,baseline,reservation):
 coordination=GitSource(source.repo,lease_store.remote,lease_store.store_id)
 control=coordination.pin(lease_store.ref)
 if control.revision!=revision:raise ValueError('receiving canonical budget/control moved')
 ledger=json.loads(coordination.read_file(control,ledger_path));budget.validate_ledger(ledger)
 if ledger['events'][:len(baseline['events'])]!=baseline['events']:
  raise ValueError('receiving budget history/charges changed')
 if [x for x in ledger['events'] if x['type']=='reserve' and x['event_id']==reservation['event_id']]!=[reservation]:
  raise ValueError('receiving exact original reservation substituted')
 if any(x['type']=='outcome' and x['reservation_id']==reservation['event_id'] for x in ledger['events']):
  raise ValueError('consumed receiving cycle cannot rearm')

class ReceivingPreflight:
 def __init__(self,seal,source,lease_store,snapshot,lease_revision,lease_record,descriptor,ledger_path,ledger,prediction,at,provider):
  if seal is not _SEAL:raise ValueError('package-owned native receiving preflight required')
  self.source,self.lease_store,self.snapshot=source,lease_store,snapshot
  self.lease_revision,self.lease_record=lease_revision,copy.deepcopy(lease_record)
  self.descriptor,self.ledger_path,self.ledger=copy.deepcopy(descriptor),ledger_path,copy.deepcopy(ledger)
  self.prediction,self.at=copy.deepcopy(prediction),at
  self.provider=provider
 def reservation_descriptor(self):
  return {'operation_key':_digest(self.descriptor),'descriptor':copy.deepcopy(self.descriptor),'authorizes_writer_start':False,'authorizes_ci_start':False}
 def admit(self,reservation_id):
  lr,record=self.lease_store.read()
  if record!=self.lease_record or any(record[key] is not None for key in ('owner_id','invocation','external_guard')):raise ValueError('receiving ownership boundary moved before reservation readback')
  coordination=GitSource(self.source.repo,self.lease_store.remote,self.lease_store.store_id)
  control=coordination.pin(self.lease_store.ref)
  if control.revision!=lr or not coordination.is_ancestor(self.lease_revision,lr):raise ValueError('receiving budget is not in original canonical control ancestry')
  ledger=json.loads(coordination.read_file(control,self.ledger_path));budget.validate_ledger(ledger)
  if ledger['events'][:len(self.ledger['events'])]!=self.ledger['events']:raise ValueError('receiving budget history/charges changed')
  reservations=[event for event in ledger['events'] if event['type']=='reserve' and event['event_id']==reservation_id]
  if len(reservations)!=1 or reservations[0]['kind']!='ci_start' or reservations[0]['operation_key']!=_digest(self.descriptor):raise ValueError('actual required receiving cycle budget reservation missing/mismatched')
  if any(event['type']=='outcome' and event['reservation_id']==reservation_id for event in ledger['events']):raise ValueError('consumed receiving cycle cannot rearm')
  self.source.assert_current(self.snapshot)
  _current_definitions(self.source,self.prediction)
  if self.lease_store.read()!=(lr,record):raise ValueError('receiving controls drifted during reservation readback')
  return ReceivingAdmission(_SEAL,self.source,self.lease_store,self.snapshot,lr,record,self.descriptor,reservations[0],self.ledger_path,self.prediction,self.at,ledger,self.provider)

class ReceivingAdmission:
 def __init__(self,seal,source,lease_store,snapshot,lease_revision,lease_record,descriptor,reservation,ledger_path,prediction,at,ledger,provider):
  if seal is not _SEAL:raise ValueError('package-owned native receiving admission required')
  self.source,self.lease_store,self.snapshot=source,lease_store,snapshot
  self.lease_revision,self.lease_record=lease_revision,copy.deepcopy(lease_record)
  self.descriptor,self.reservation,self.ledger_path=copy.deepcopy(descriptor),copy.deepcopy(reservation),ledger_path
  self.prediction,self.at=copy.deepcopy(prediction),at
  self.ledger=copy.deepcopy(ledger)
  self.provider=provider
  self._candidate=None
 def before_start(self,request):
  if request['repo_root']!=str(self.source.repo) or request['remote']!=self.source.remote or request['lease_source_ref']!=self.snapshot.ref or request['plan']['base_sha']!=self.snapshot.revision:raise ValueError('receiving admission does not bind exact writer source')
  self.source.assert_current(self.snapshot)
  _current_definitions(self.source,self.prediction)
  if self.lease_store.read()!=(self.lease_revision,self.lease_record):raise ValueError('receiving ownership boundary moved before writer admission')
  _budget_read(self.source,self.lease_store,self.lease_revision,self.ledger_path,self.ledger,self.reservation)
  if not 0<=(_now()-self.at).total_seconds()<=90:raise ValueError('receiving preflight stale before writer start')
 def bind_owner(self,ownership):
  import execution_lease_v2 as lease
  lease.check(self.lease_store,ownership['expected_revision'],ownership['repository'],ownership['source_ref'],ownership['owner_id'],ownership['generation'],ownership['invocation_id'],_stamp(_now()),action='product_write')
  original=self.lease_store.read_revision(ownership['expected_revision'])
  if (original['owner_id']!=ownership['owner_id'] or original['generation']!=self.lease_record['generation']+1 or original['generation']!=ownership['generation'] or not original['invocation'] or original['invocation']['invocation_id']!=ownership['invocation_id']):raise ValueError('receiving preflight must precede exact fresh owned generation')
  if datetime.fromisoformat(original['acquired_at_utc'].replace('Z','+00:00'))<self.at:raise ValueError('receiving preflight occurred after writer admission')
  _budget_read(self.source,self.lease_store,ownership['expected_revision'],self.ledger_path,self.ledger,self.reservation)
  head=self.source.pin(self.snapshot.ref).revision
  if head!=self.snapshot.revision:
   # The already bound original result permits readback reconciliation only;
   # a new head/candidate is never a replacement publication grant.
   if self._candidate is None or head!=self._candidate:raise ValueError('receiving source moved before stock prepare')
   store=self._cycle_store();_,record=store.read()
   if record is None or record.get('candidate_commit')!=head or record.get('descriptor')!=self.descriptor or record.get('reservation_id')!=self.reservation['event_id']:
    raise ValueError('receiving lost reply needs exact original canonical candidate binding')
  _current_definitions(self.source,self.prediction,confirmed_source=(self.snapshot.ref,head) if head==self._candidate else None)
  if head==self.snapshot.revision:self._provider_recheck()
 def refresh_provider(self,provider):
  if type(provider) not in (CanonicalProviderReads,GitHubReadOnlyAPI) or provider.repository!=self.lease_record['repository']:
   raise ValueError('same approved receiving provider route required')
  if type(provider) is CanonicalProviderReads and (provider.lease_store.store_id,provider.lease_store.ref,provider.source_ref)!=(self.lease_store.store_id,self.lease_store.ref,self.snapshot.ref):
   raise ValueError('receiving provider canonical control binding substituted')
  prior=self.provider;self.provider=provider
  try:self._provider_recheck()
  except Exception:self.provider=prior;raise
 def _provider_recheck(self):
  metadata,_=self.provider.read('');prs,_=self.provider.read('/pulls?state=open&per_page=100')
  if (metadata.get('full_name')!=self.lease_record['repository'] or 'refs/heads/'+metadata.get('default_branch','')!=self.prediction['default_ref'] or not isinstance(prs,list) or len(prs)>=100):
   raise ValueError('receiving current provider metadata moved/incomplete')
  current=[]
  for pr in prs:
   if pr.get('head',{}).get('ref')==self.snapshot.ref.removeprefix('refs/heads/') and pr.get('head',{}).get('repo',{}).get('full_name')==self.lease_record['repository']:
    current.append((pr['number'],'refs/heads/'+pr['base']['ref'],pr['base']['sha'],pr['head']['sha']))
  expected=[(pr['number'],pr['base_ref'],pr['base'],pr['head']) for pr in self.prediction['pull_requests']]
  if sorted(current)!=sorted(expected):raise ValueError('receiving current cumulative PR inventory moved; reconcile original admission')
 def _cycle_store(self,ownership=None):
  ref='refs/heads/cdc/receiving-cycle-'+self.reservation['operation_key'].split(':')[1]
  cls=GitDocumentStore
  if ownership is not None:
   # Repeat the genuine ownership/budget/definition check at the actual CAS
   # effect, including races between an earlier read and this Git push.
   guard=lambda:self.bind_owner(ownership)
   class CheckedCycleStore(GitDocumentStore):
    def _git(self,*args,**kwargs):
     if 'push' in args:guard()
     return super()._git(*args,**kwargs)
   cls=CheckedCycleStore
  return cls(self.source.repo,self.lease_store.remote,ref,self.lease_store.store_id,protected_refs=[self.lease_store.ref])
 def bind_prepared(self,prepared,ownership):
  self.bind_owner(ownership)
  state=prepared['state']
  if state['source_head']!=self.snapshot.revision or prepared['release']['release_commit']!=self.descriptor['release_commit'] or prepared['release']['package_tree']!=self.descriptor['package_tree'] or state['assembly_authority']['transaction_id']!=self.descriptor['transaction_id']:raise ValueError('receiving cycle does not bind immutable prepared identity')
  candidate=state['candidate_commit']
  if self._candidate is not None and self._candidate!=candidate:raise ValueError('prepared candidate/SHA rebinding forbidden')
  self._candidate=candidate
  store=self._cycle_store(ownership)
  record={'schema':'receiving-candidate-cycle-binding/v1','operation_key':self.reservation['operation_key'],'reservation_id':self.reservation['event_id'],'descriptor':self.descriptor,'candidate_commit':candidate,'root_tree':state['final_tree_sha'],'publication_claim':state['publication_claim'],'assembly_authority':state['assembly_authority'],'prediction':self.prediction}
  revision,current=store.read()
  if current is not None and current!=record:raise ValueError('existing receiving cycle binding cannot be rebound or replaced')
  if current is None:revision=store.compare_and_swap(None,record)
  if store.read_revision(revision)!=record:raise ValueError('receiving candidate binding authoritative readback failed')
  return {'revision':revision,'ref':store.ref,'record':record}

def prepare_admission(source,lease_store,*,release_commit,package_tree,canonical_source,release_binding,transaction_id,ledger_path,provider,journal_clock=_now):
 """Must run at the released/unowned boundary before genuine writer start.

Caller first reserves one prospective receiving cycle through its existing
canonical budget CAS. This reads the actual stored charge; it grants no launch.
The later stock prepare binds that same cycle to exactly one real candidate.
"""
 if type(source) is not GitSource or type(canonical_source) is not GitSource or type(lease_store) is not GitLeaseStore or type(provider) not in (GitHubReadOnlyAPI,CanonicalProviderReads):raise ValueError('native Git/provider/lease types required; caller data is not admission')
 if canonical_source.repo!=source.repo:raise ValueError('canonical release must share native receiving cache')
 proof=verify_release_binding(canonical_source,release_binding,canonical_repository=release_binding.get('canonical_repository'),clock=journal_clock)
 if proof['release']['release_commit']!=release_commit or proof['release']['package_tree']!=package_tree:raise ValueError('preflight immutable release binding mismatch')
 lr,record=lease_store.read()
 if any(record[key] is not None for key in ('owner_id','invocation','external_guard')):raise ValueError('fresh released/unowned receiving boundary required')
 if provider.repository!=record['repository']:raise ValueError('receiving API repository binding mismatch')
 snapshot=source.pin(record['source_ref']);metadata,meta_receipt=provider.read('');prs,pr_receipt=provider.read('/pulls?state=open&per_page=100')
 if metadata.get('full_name')!=record['repository'] or not isinstance(prs,list) or len(prs)>=100:raise ValueError('complete bounded authentic receiving metadata required')
 default=source.pin('refs/heads/'+metadata['default_branch'])
 _receiving_controls(source,snapshot,record,proof['release'])
 head_workflows=_workflows(source,snapshot);default_workflows=_workflows(source,default)
 package_rows=source._git('ls-tree','-r','--name-only',snapshot.revision,'--',PACKAGE)[1].splitlines()
 # Conservative prospective paths include all package files plus lock/audit.
 # Cumulative PR history is derived separately from exact authenticated bases.
 target_rows=source._git('ls-tree','-r','--name-only',release_commit,'--','src/continuous-development-cycle')[1].splitlines()
 target_paths=[PACKAGE+path.removeprefix('src/continuous-development-cycle') for path in target_rows]
 if source._git('rev-parse',release_commit+':src/continuous-development-cycle')[1]!=package_tree:raise ValueError('preflight exact target package object mismatch')
 push_paths=sorted(set(package_rows+target_paths+['docs/cdc-consumer-lock.json','docs/cdc-adoption-'+source._git('show',release_commit+':src/continuous-development-cycle/VERSION')[1].strip()+'.md']))
 matching=[pr for pr in prs if pr.get('head',{}).get('ref')==snapshot.ref.removeprefix('refs/heads/') and pr.get('head',{}).get('repo',{}).get('full_name')==record['repository']]
 predictions=[];pr_bindings=[]
 for pr in matching:
  if pr['head']['sha']!=snapshot.revision:raise ValueError('provider PR head and actual receiving source disagree')
  base=source.pin('refs/heads/'+pr['base']['ref'])
  if base.revision!=pr['base']['sha']:raise ValueError('provider PR base and actual native base disagree')
  paths=source._git('diff','--name-only',base.revision+'...'+snapshot.revision)[1].splitlines()
  cumulative=sorted(set(paths+push_paths))
  predictions.append(predict(branch=snapshot.ref.removeprefix('refs/heads/'),pr_base_branch=pr['base']['ref'],push_paths=push_paths,cumulative_pr_paths=cumulative,head_workflows=head_workflows,default_workflows=default_workflows,pr_base_workflows=_workflows(source,base)))
  pr_bindings.append({'number':pr['number'],'base':base.revision,'base_ref':base.ref,'head':snapshot.revision,'cumulative_paths':cumulative})
 if not matching:predictions.append(predict(branch=snapshot.ref.removeprefix('refs/heads/'),pr_base_branch=None,push_paths=push_paths,cumulative_pr_paths=[],head_workflows=head_workflows,default_workflows=default_workflows))
 cycles={_digest(x):x for prediction in predictions for x in prediction['required_cycles']}
 prediction={'schema':'native-receiving-preflight/v1','source_revision':snapshot.revision,'default_revision':default.revision,'default_ref':default.ref,'provider_reads':[meta_receipt,pr_receipt],'pull_requests':pr_bindings,'required_cycles':list(cycles.values()),'stock_commit_message_customization':False,'skip_ci_required':False,'no_gate_waiver':True,'event_coverage':'existing_branch_push_two_dot_and_authentic_pr_three_dot_conservative_prospective_paths','qualified_provider':'GitHub.com','provider_path_filter_cap':3000,'workflow_run_max_chain_levels':3}
 descriptor={'schema':'receiving-cycle-operation/v1','repository':record['repository'],'source_ref':record['source_ref'],'parent':snapshot.revision,'release_commit':release_commit,'package_tree':package_tree,'transaction_id':transaction_id,'prediction_digest':_digest(prediction)}
 coordination=GitSource(source.repo,lease_store.remote,lease_store.store_id)
 control=coordination.pin(lease_store.ref)
 if control.revision!=lr:raise ValueError('receiving budget/control boundary moved')
 ledger=json.loads(coordination.read_file(control,ledger_path));budget.validate_ledger(ledger)
 source.assert_current(snapshot)
 if lease_store.read()!=(lr,record):raise ValueError('receiving controls drifted during preflight')
 return ReceivingPreflight(_SEAL,source,lease_store,snapshot,lr,record,descriptor,ledger_path,ledger,prediction,journal_clock(),provider)

def _receiving_controls(source,snapshot,record,release):
 import project_setup
 from consumer_lock import validate as validate_lock
 from contracts import require_supported_runtime
 from validate_adapter import validate_adapter
 from validate_checkpoint_24 import validate_checkpoint_24
 lock=project_setup._unique  # duplicate JSON keys stay invalid
 try:current=json.loads(source.read_file(snapshot,'docs/cdc-consumer-lock.json'),object_pairs_hook=lock)
 except (ValueError,TypeError):raise ValueError('receiving control lock invalid') from None
 validate_lock(current);require_supported_runtime(current['version'])
 installed=source.read_file(snapshot,PACKAGE+'/VERSION').strip();require_supported_runtime(installed)
 if installed!=current['version'] or source.tree_oid(snapshot,PACKAGE)!=current['package_tree'] or current['canonical_repository']!=release['canonical_repository']:
  raise ValueError('receiving installed package/lock/provenance drift')
 adapter=project_setup._yaml(source.read_file(snapshot,'docs/development-cycle.yaml'))
 checkpoint,_=project_setup._checkpoint(source.read_file(snapshot,'docs/work-status/current.md'))
 for version in (installed,release['version']):
  validate_adapter(adapter,skill_version=version);validate_checkpoint_24(checkpoint,adapter,skill_version=version)
 if (adapter['repository']['remote']!=record['repository'] or checkpoint['repository']!=record['repository'] or
     checkpoint['branch']!=snapshot.ref.removeprefix('refs/heads/') or checkpoint['lease_state']!='released' or
     project_setup._existing_operation(checkpoint) is not None):raise ValueError('receiving control is not released/reconciled original product boundary')

def github_receiving_source(source):
 url=source._git('config','--get','remote.'+source.remote+'.url')[1]
 from urllib.parse import urlsplit
 host=urlsplit(url).hostname if '://' in url else ('github.com' if re.match(r'^[^@/]+@github\.com:',url) else None)
 return host=='github.com'

def require_for_writer(request,value):
 task=next(x for x in request['plan']['tasks'] if x['id']==request['task_id'])
 needs=task['role']=='writer' and any(path==PACKAGE or PACKAGE.startswith(path.rstrip('/')+'/') or path.startswith(PACKAGE+'/') for path in task['write_paths'])
 if needs:
  if type(value) is not ReceivingAdmission:raise ValueError('receiving CI/API/budget preflight required BEFORE delivery writer admission')
  value.before_start(request)
