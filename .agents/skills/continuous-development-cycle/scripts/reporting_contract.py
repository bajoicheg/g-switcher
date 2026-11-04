"""Fresh owner reports joined to an authoritative invocation RCA inventory.

Native Git history authenticates admission/verification records, not arbitrary
chat output or claims that a caller's unit tests ran in a provider. This module
submits no work, grants no capability and changes no lease/guard.
"""
from __future__ import annotations
import copy,hashlib,json,re
from datetime import datetime,timezone
import command_timestamp
import operation_report
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore

def _fields(data,fields,label):
 if not isinstance(data,dict) or set(data)!=set(fields):raise ValueError(label+' fields mismatch')
def _text(value,label):
 if not isinstance(value,str) or not value.strip() or value!=value.strip():raise ValueError(label+' must be text')
def _ids(values,label):
 if not isinstance(values,list) or len(set(values))!=len(values):raise ValueError(label+' must be distinct')
 for value in values:_text(value,label)
def _digest(value):
 return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def _time(value):
 try:at=datetime.fromisoformat(value.replace('Z','+00:00'))
 except (ValueError,AttributeError):raise ValueError('report timestamp invalid') from None
 if at.tzinfo is None:raise ValueError('report timestamp must be aware')
 return at.astimezone(timezone.utc)
def inventory_ref(invocation_id):
 _text(invocation_id,'invocation_id')
 return 'refs/heads/cdc/reporting-'+hashlib.sha256(invocation_id.encode()).hexdigest()

def _preserved_history(store,revision,doc):
 """An admitted material fact cannot disappear behind a fresh current label."""
 rows=store._git('rev-list','--first-parent',revision).splitlines()
 if len(rows)>1000:raise ValueError('RCA material history needs explicit bounded archival reconciliation')
 current={x['anomaly_id']:x for x in doc['material']}
 for prior_revision in rows[1:]:
  old=store.read_revision(prior_revision)
  for key in ('schema','invocation_id','owner_id','generation','owned_lease_revision'):
   if old.get(key)!=doc.get(key):raise ValueError('RCA material history original ownership substituted')
  for item in old.get('material',[]):
   actual=current.get(item['anomaly_id'])
   if actual is None or any(actual.get(k)!=item.get(k) for k in ('fix_key','backlog_ref','problem','cause')):
    raise ValueError('RCA material history removed/substituted')
   if actual['evidence_refs'][:len(item['evidence_refs'])]!=item['evidence_refs']:
    raise ValueError('RCA material history evidence overwritten')

def _verified_raw_terminal(store,receipt,item):
 if receipt.get('schema')!='rca-verification-receipt/v2' or not isinstance(receipt.get('raw_terminal'),dict):
  raise ValueError('resolved RCA requires pinned actual raw terminal, not a digest label')
 raw=receipt['raw_terminal']
 _fields(raw,('argv','stdout','stderr','return_code','started_at_utc','finished_at_utc','source_commit','root_tree'),'RCA raw terminal')
 if (not isinstance(raw['argv'],list) or not raw['argv'] or any(not isinstance(x,str) or not x for x in raw['argv']) or
     not isinstance(raw['stdout'],str) or not isinstance(raw['stderr'],str) or type(raw['return_code']) is not int or raw['return_code']!=0 or
     receipt['raw_terminal_digest']!=_digest(raw) or receipt['regression_exit_code']!=raw['return_code']):
  raise ValueError('RCA raw terminal bytes/returncode/digest mismatch')
 if _time(raw['finished_at_utc'])<_time(raw['started_at_utc']):raise ValueError('RCA raw terminal duration invalid')
 for key in ('source_commit','root_tree'):
  if not re.fullmatch('[0-9a-f]{40}',str(raw[key])):raise ValueError('RCA exact correction Git object missing')
 if ('git:'+raw['source_commit'] not in item['correction_refs'] or
     store._git('cat-file','-t',raw['source_commit'])!='commit' or
     store._git('rev-parse',raw['source_commit']+'^{tree}')!=raw['root_tree']):
  raise ValueError('RCA raw terminal does not bind exact correction commit/root')

def emit(request,*,now=None):
 """Validate and format the actual substantive emission, including its body."""
 _fields(request,('schema','invocation_id','report_id','kind','observed_at_utc','body','completed_operation'),'owner report')
 if request['schema']!='owner-report/v1' or request['kind'] not in ('progress','blocker','continuation','final'):raise ValueError('owner report schema/kind invalid')
 for key in ('invocation_id','report_id','body'):_text(request[key],key)
 body=request['body']
 if not re.search('[А-Яа-яЁё]',body) or body.startswith('['):raise ValueError('Russian body without caller timestamp required')
 stamp=command_timestamp.render(dict(schema=command_timestamp.SCHEMA,command_id=request['invocation_id'],observed_at=request['observed_at_utc'],time_source='runtime_clock',already_timestamped_command_ids=[]),now=now)
 suffix=''
 if request['completed_operation'] is not None:
  completed=request['completed_operation']
  _fields(completed,('started_at_utc','finished_at_utc','observation'),'completed operation')
  start,end=_time(completed['started_at_utc']),_time(completed['finished_at_utc'])
  if end<start or end>_time(request['observed_at_utc']):raise ValueError('operation not completed before report')
  measured=operation_report.measure(completed['observation'])
  if abs(measured['elapsed_seconds']-(end-start).total_seconds())>0.001:raise ValueError('completed interval/duration mismatch')
  suffix=' '+operation_report.render(completed['observation'])
 return {'schema':'owner-report-evidence/v1','invocation_id':request['invocation_id'],'report_id':request['report_id'],'kind':request['kind'],'observed_at_utc':stamp['observed_at_utc'],'input_observation':request['observed_at_utc'],'text':stamp['display']+' '+body+suffix,'source':'runtime_clock','authorizes_anything':False}

def capture(invocation_id,kind,body,*,completed_operation=None,clock=None):
 """Read the runtime clock at the reporting boundary; caller cannot supply a stamp."""
 import uuid
 at=(clock or (lambda:datetime.now(timezone.utc)))()
 command_timestamp._aware(at,'runtime clock')
 return dict(schema='owner-report/v1',invocation_id=invocation_id,report_id=str(uuid.uuid4()),kind=kind,observed_at_utc=at.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),body=body,completed_operation=completed_operation)

_SEAL=object()
class ReportingAuthority:
 def __init__(self,seal,store,lease_store,binding,invocation_id,checkpoint_ref):
  if seal is not _SEAL:raise ValueError('native reporting authority required')
  self.store,self.lease_store=store,lease_store
  self.binding=copy.deepcopy(binding);self.invocation_id=invocation_id;self.checkpoint_ref=checkpoint_ref
 def check(self,binding,*,now=None):
  if binding!=self.binding:raise ValueError('reporting binding substituted')
  revision,doc=self.store.read()
  if revision!=binding['inventory_revision']:raise ValueError('stale RCA inventory; reconcile current admission')
  pinned=self.store.read_revision(revision)
  if pinned!=doc:raise ValueError('RCA inventory exact readback mismatch')
  _fields(doc,('schema','invocation_id','owner_id','generation','owned_lease_revision','checkpoint_ref','material'),'RCA inventory')
  if doc['schema']!='execution-rca-inventory/v1' or doc['invocation_id']!=self.invocation_id or doc['checkpoint_ref']!=self.checkpoint_ref:raise ValueError('RCA inventory invocation/checkpoint mismatch')
  original=self.lease_store.read_revision(doc['owned_lease_revision'])
  if (original['owner_id']!=doc['owner_id'] or original['generation']!=doc['generation'] or not original['invocation'] or original['invocation']['invocation_id']!=self.invocation_id):raise ValueError('RCA inventory original owned lease mismatch')
  if not isinstance(doc['material'],list):raise ValueError('material RCA inventory invalid')
  _preserved_history(self.store,revision,doc)
  seen=set();keys={};opened=[];verified=[]
  for item in doc['material']:
   _fields(item,('anomaly_id','fix_key','status','backlog_ref','problem','cause','evidence_refs','correction_refs','verification_revision','deferral'),'material RCA')
   for key in ('anomaly_id','fix_key','problem','cause'):_text(item[key],key)
   if item['anomaly_id'] in seen:raise ValueError('duplicate material anomaly')
   seen.add(item['anomaly_id'])
   _ids(item['evidence_refs'],'RCA evidence');_ids(item['correction_refs'],'correction evidence')
   if not item['evidence_refs']:raise ValueError('material RCA requires actual evidence')
   if item['status'] not in ('admitted_open','implementing','verified_resolved','deferred'):raise ValueError('proposal/diagnosis is not durable backlog admission')
   _text(item['backlog_ref'],'durable backlog reference')
   if item['fix_key'] in keys and keys[item['fix_key']]!=item['backlog_ref']:raise ValueError('fix key must reinforce same durable backlog')
   keys[item['fix_key']]=item['backlog_ref']
   if item['status']=='deferred':
    _fields(item['deferral'],('reason','next_action','recheck_trigger'),'RCA deferral')
    for value in item['deferral'].values():_text(value,'deferral')
   elif item['deferral'] is not None:raise ValueError('unexpected deferral')
   if item['status']=='verified_resolved':
    if not item['correction_refs'] or item['verification_revision'] is None:raise ValueError('resolved RCA requires correction and verification receipt')
    ref=self.store.ref+'-verification-'+hashlib.sha256(item['fix_key'].encode()).hexdigest()[:24]
    verification=GitDocumentStore(self.store.repo,self.store.remote,ref,self.store.store_id)
    receipt=verification.read_revision(item['verification_revision'])
    _verified_raw_terminal(self.store,receipt,item)
    _fields(receipt,('schema','invocation_id','anomaly_id','fix_key','correction_refs','regression_exit_code','evidence_refs','raw_terminal_digest','raw_terminal'),'RCA verification receipt')
    if (receipt['invocation_id']!=self.invocation_id or receipt['anomaly_id']!=item['anomaly_id'] or receipt['fix_key']!=item['fix_key'] or receipt['correction_refs']!=item['correction_refs'] or type(receipt['regression_exit_code']) is not int or receipt['regression_exit_code']!=0 or receipt['evidence_refs']!=item['evidence_refs']):raise ValueError('RCA verification does not bind exact correction/regression evidence')
    verified.append(item['anomaly_id'])
   else:
    if item['verification_revision'] is not None:raise ValueError('unverified RCA cannot claim verification')
    opened.append({'anomaly_id':item['anomaly_id'],'fix_key':item['fix_key'],'status':item['status'],'backlog_ref':item['backlog_ref']})
  if set(binding['material_ids'])!=seen:raise ValueError('material RCA inventory omitted/substituted')
  if not set(binding['claimed_resolved_ids'])<=set(verified):raise ValueError('false resolved/handled RCA closeout')
  report=emit(binding['report'],now=now)
  if report['invocation_id']!=self.invocation_id:raise ValueError('owner report invocation mismatch')
  if opened:report['text']+=' Открыто: '+', '.join(x['fix_key']+' ('+x['status']+')' for x in opened)+'.'
  return {'report':report,'inventory_revision':revision,'open_rca':opened,'verified_resolved_ids':verified,'historical_owned_revision':doc['owned_lease_revision']}

def authenticate(lease_store,binding,invocation_id,checkpoint_ref):
 if type(lease_store) is not GitLeaseStore:raise ValueError('authentic native canonical lease store required for reporting')
 _fields(binding,('schema','inventory_revision','report','material_ids','claimed_resolved_ids'),'reporting binding')
 if binding['schema']!='execution-reporting-binding/v1':raise ValueError('reporting binding schema invalid')
 _ids(binding['material_ids'],'material IDs');_ids(binding['claimed_resolved_ids'],'resolved IDs')
 store=GitDocumentStore(lease_store.repo,lease_store.remote,inventory_ref(invocation_id),lease_store.store_id,protected_refs=[lease_store.ref])
 return ReportingAuthority(_SEAL,store,lease_store,binding,invocation_id,checkpoint_ref)

def check(state,authority,*,now_utc=None):
 if state.get('schema')!='execution-continuity/v2' or state.get('reporting_binding') is None:raise ValueError('current authentic reporting binding required')
 if type(authority) is not ReportingAuthority:raise ValueError('native reporting authority required, not caller boolean')
 if authority.invocation_id!=state['invocation_id'] or authority.checkpoint_ref!=state['checkpoint_ref']:raise ValueError('reporting scope substituted')
 return authority.check(state['reporting_binding'],now=_time(now_utc) if now_utc else None)
