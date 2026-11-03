"""Native administrative UNKNOWN custody; never a terminal or send capability.

Trust inputs are deployment-owned original channel/contract pins. All effects
are single native CAS writes to the original record; lost replies are read only.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import os
from datetime import datetime, timezone, timedelta
import stat
import subprocess
import uuid
import sys
from pathlib import Path
import operation_intent as op
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from managed_executor_runtime import _process, _boot, _digest as native_digest

_SEAL=object()
INTAKE_SCHEMA='cdc-vps-control/v1'
DISPOSITION_SCHEMA='prelaunch-intake-disposition/v1'


def _history_snapshot(store):
    """Fresh endpoint, current document and complete graph, shared by readers."""
    if type(store) not in (GitDocumentStore,GitLeaseStore):raise ValueError('actual native Git store required')
    from immutable_history_cache import _cache,_context,_linear_chain
    current,current_document=store.read()
    if current is None:raise ValueError('original native history missing')
    if store._git('rev-parse','--is-shallow-repository')!='false':raise ValueError('complete native history required')
    rows=store._git('rev-list','--parents',current).splitlines()
    if len(rows)>10000:raise ValueError('native history exceeds authentication bound')
    chain=_linear_chain(reversed(rows))
    if not chain or chain[-1][0]!=current:raise ValueError('complete native history required')
    context=_context(store,'document' if type(store) is GitDocumentStore else 'lease')
    prior=_cache.get(context)
    if prior is not None and chain[:len(prior['chain'])]!=prior['chain']:
        raise ValueError('native history rewound or rewritten')
    return current,current_document,chain,context,prior


def _history(store):
    """Compatibility API for callers requiring detached full document history."""
    from immutable_history_cache import _cache
    current,current_document,chain,context,prior=_history_snapshot(store)
    result=[] if prior is None else [(revision,document) for revision,document in prior['documents']]
    suffix = [parts[0] for parts in chain[len(result):]]
    if type(store) is GitDocumentStore:
        # Current document was already checked by the fresh read above.
        historical = [revision for revision in suffix if revision != current]
        decoded = iter(store._read_document_objects(historical)) if historical else iter(())
        for revision in suffix:
            result.append((revision, current_document if revision == current else next(decoded)))
    else:
        for revision in suffix:
            result.append((revision, current_document if revision == current else store._read_record(revision)))
    if current!=store.read()[0]:raise ValueError('native history moved during authentication')
    _cache.put(context,{'chain':chain,'documents':result})
    return result


def _identity(value,*,absent):
    op._object(value,{'pid','birth','boot_id'},'original process identity')
    if type(value['pid']) is not int or value['pid']<=0 or not isinstance(value['birth'],str) or not value['birth'].isdigit() or value['boot_id']!=_boot():raise ValueError('original native birth/boot identity required')
    current=_process(value['pid'])
    if absent:
        try:Path('/proc',str(value['pid'])).stat()
        except FileNotFoundError:pass
        except OSError:raise ValueError('original physical PID probe unavailable') from None
        else:raise ValueError('original PID present, including reused or zombie birth')
    if not absent and (current is None or current['birth']!=value['birth']):raise ValueError('start consumption requires exact current controller birth')


def _row(document,task_id):
    if document.get('schema')!=INTAKE_SCHEMA or not isinstance(document.get('tasks'),dict) or task_id not in document['tasks']:raise ValueError('registered native intake row required')
    row=document['tasks'][task_id]
    if row.get('task',{}).get('id')!=task_id:raise ValueError('immutable native intake task index mismatch')
    return row


def _consumed(row):
    operation=row.get('operation') or {}
    return 'controllers' in operation or operation.get('controller_identity') is not None or operation.get('checkpoint_ref') is not None or operation.get('finish_result') is not None or operation.get('start_consumption') is not None or operation.get('handle_id') is not None or row.get('result') is not None


def semantic_intake_contract(row):
    """Only task identity/dependency names are excluded from replay matching."""
    task=row.get('task')
    if not isinstance(task,dict):raise ValueError('immutable intake task contract required')
    return op._hash({key:value for key,value in task.items() if key not in {'id','dependencies'}})


def _contract(row):
    request=(row.get('operation') or {}).get('start_request')
    if not isinstance(request,dict) or row['operation'].get('start_request_digest')!=native_digest(request):raise ValueError('original unchanged native start contract required')
    return native_digest(request)


def _intake_channels(store,row,pins,source=None):
    """Join independent configured channels to the original immutable request."""
    request=row['operation']['start_request'];channels=pins.get('channels')
    if channels is None:
        if ('preconsume_exit' in pins or 'guardian_bootstrap_failure' in pins) or source is not None and source.store_id!=store.store_id:
            raise ValueError('independent original intake/project channel pins required')
        return
    op._object(channels,{'intake_store_id','intake_ref','lease_store_id','lease_ref','pool_store_id','pool_ref'},'original intake/project channels')
    expected={'intake_store_id':store.store_id,'intake_ref':store.ref,
        'lease_store_id':request['plan']['coordination_store_id'],'lease_ref':request['lease_coordination_ref'],
        'pool_store_id':request['plan']['coordination_store_id'],'pool_ref':request['plan']['coordination_ref']}
    if channels!=expected:raise ValueError('original intake/project channel binding mismatch')
    if source is not None:
        from git_remote_identity import repository_root
        if type(source) is not GitLeaseStore or source.store_id!=channels['lease_store_id'] or source.ref!=channels['lease_ref'] or source.repo!=repository_root(request['repo_root']) or source.remote!=request.get('coordination_remote',request['remote']):
            raise ValueError('original typed project lease channel substituted')
        source._assert_remote_identity()


def _preconsume_rejection_stderr(raw):
    """Recognize documentary legacy diagnostics; never derive authority from them."""
    marker=b'CDC_VPS_ORIGINAL_CONTROLLER_RECONCILIATION_REQUIRED\n'
    codes=('INTAKE_OBSERVATION_CHANGED','INTAKE_CONSUMPTION_UNRESOLVED','HOST_IO_REJECTED','CONTRACT_OR_SCOPE_REJECTED')
    accepted={marker}|{marker+('CDC_VPS_REJECTION_CODE='+code+'\n').encode() for code in codes}
    if raw in accepted:return True
    lines=raw.splitlines(keepends=True)
    prefix=b'CDC_VPS_REJECTION_SITE='
    if (len(lines)!=3 or b''.join(lines[:2]) not in accepted or lines[0]!=marker
            or not lines[1].startswith(b'CDC_VPS_REJECTION_CODE=')
            or not lines[2].startswith(prefix) or not lines[2].endswith(b'\n')):return False
    payload=lines[2][len(prefix):-1]
    if len(payload)>1024:return False
    try:site=json.loads(payload,object_pairs_hook=op._unique_object)
    except (ValueError,UnicodeError):return False
    if not isinstance(site,dict) or set(site)!={'module','function','line','type'}:return False
    identifier=lambda value,limit: (isinstance(value,str) and len(value)<=limit
        and value.isascii() and value.isidentifier())
    module=site['module'];function=site['function']
    return (isinstance(module,str) and len(module)<=256
        and all(identifier(part,256) for part in module.split('.'))
        and (function=='<module>' or identifier(function,96))
        and identifier(site['type'],96) and type(site['line']) is int
        and 0<=site['line']<2**31)


def _preconsume_artifacts(row,pins,controller,guardian_pin):
    """A protected infrastructure wait is documentary, never a terminal wait."""
    evidence=pins.get('preconsume_exit')
    if evidence is None:return {}
    op._object(evidence,{'schema','controller','receipt_sha256','stdout_sha256','stderr_sha256','guardian_stdout_sha256','guardian_stderr_sha256'},'original preconsume controller exit')
    if evidence['schema']!='native-preconsume-controller-exit/v1':raise ValueError('unsupported preconsume exit evidence')
    identity=evidence['controller'];_identity(identity,absent=True)
    recorded_pids={pins['guardian']['pid']}
    if pins.get('creator') is not None:recorded_pids.add(pins['creator']['pid'])
    if identity['pid'] in recorded_pids:raise ValueError('distinct original controller birth required')
    nonce=pins['guardian_nonce']
    if not isinstance(nonce,str) or re.fullmatch('[0-9a-f]{32}',nonce) is None:raise ValueError('original controller nonce must be canonical')
    names={'receipt':nonce+'.receipt.json','stdout':nonce+'.stdout','stderr':nonce+'.stderr',
        'guardian_stdout':nonce+'.guardian.stdout','guardian_stderr':nonce+'.guardian.stderr'}
    raw={}
    for label,name in names.items():
        digest=evidence[label+'_sha256']
        if not isinstance(digest,str) or re.fullmatch('sha256:[0-9a-f]{64}',digest) is None:raise ValueError('original preconsume artifact digest required')
        path=controller/name
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=pins['custody']['controller_uid'] or info.st_gid!=guardian_pin['gid'] or stat.S_IMODE(info.st_mode) not in (0o600,0o640):raise ValueError('protected original wait artifact custody required')
                raw[label]=stream.read(65537)
        except OSError:raise ValueError('original wait artifact unavailable') from None
        if len(raw[label])>65536 or 'sha256:'+hashlib.sha256(raw[label]).hexdigest()!=digest:raise ValueError('original wait artifact bytes changed')
    try:receipt=json.loads(raw['receipt'],object_pairs_hook=op._unique_object)
    except (ValueError,UnicodeError):raise ValueError('original controller wait is not authentic JSON') from None
    op._object(receipt,{'schema','task_id','identity','controller','exit_code','observed_at_utc','stdout_path','stdout_sha256','stderr_path','stderr_sha256'},'original controller wait')
    if receipt['schema']!='cdc-vps-controller-wait/v1' or receipt['task_id']!=row['task']['id'] or receipt['identity']!=pins['guardian'] or receipt['controller']!=identity or type(receipt['exit_code']) is not int or receipt['exit_code']!=2:raise ValueError('original nonce/task/birth preconsume wait mismatch')
    observed=op._timestamp(receipt['observed_at_utc'],'original controller wait time')
    if observed>datetime.now(timezone.utc)+timedelta(seconds=5):raise ValueError('original controller wait observation is in the future')
    for label in ('stdout','stderr'):
        if receipt[label+'_path']!=str(controller/names[label]) or receipt[label+'_sha256']!=evidence[label+'_sha256'].split(':',1)[1]:raise ValueError('original controller stream path/digest mismatch')
    if raw['stdout'] or raw['guardian_stdout'] or raw['guardian_stderr'] or not _preconsume_rejection_stderr(raw['stderr']):raise ValueError('only original preconsume controller rejection artifacts are admissible')
    _identity(identity,absent=True)
    documentary={str(controller/name):raw[label] for label,name in names.items()}
    creator_wait=controller/(nonce+'.guardian-wait.json')
    pin=pins.get('creator_guardian_wait')
    if creator_wait.exists() or creator_wait.is_symlink() or pin is not None:
        op._object(pin,{'schema','sha256'},'original creator guardian wait pin')
        if pin['schema']!='native-creator-guardian-wait/v1':raise ValueError('original creator wait schema required')
        op._digest(pin['sha256'],'original creator wait digest')
        try:
            fd=os.open(creator_wait,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                before=os.fstat(stream.fileno())
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1
                        or before.st_uid!=pins['custody']['controller_uid'] or before.st_gid!=guardian_pin['gid']
                        or stat.S_IMODE(before.st_mode) not in (0o600,0o640)):
                    raise ValueError('protected original creator wait custody required')
                payload=stream.read(65537);after=os.fstat(stream.fileno())
        except OSError:raise ValueError('original creator wait unavailable') from None
        stable=('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
        if (any(getattr(before,name)!=getattr(after,name) for name in stable) or len(payload)>65536
                or 'sha256:'+hashlib.sha256(payload).hexdigest()!=pin['sha256']):
            raise ValueError('original creator wait bytes changed')
        try:wait=json.loads(payload,object_pairs_hook=op._unique_object)
        except (ValueError,UnicodeError):raise ValueError('original creator wait JSON required') from None
        fields={'schema','task_id','identity','nonce','exit_code','observed_at_utc','authorizes_slot_release',
                'stdout_path','stdout_sha256','stderr_path','stderr_sha256'}
        op._object(wait,fields,'original creator guardian wait')
        if (wait['schema']!='cdc-vps-guardian-wait/v1' or wait['task_id']!=row['task']['id']
                or op._hash(wait['identity'])!=op._hash(pins['guardian']) or wait['nonce']!=nonce
                or type(wait['exit_code']) is not int or wait['exit_code']!=2
                or wait['authorizes_slot_release'] is not False):
            raise ValueError('original creator wait identity/status/authority changed')
        timestamp=op._timestamp(wait['observed_at_utc'],'original creator wait time')
        if timestamp<observed or timestamp>datetime.now(timezone.utc)+timedelta(seconds=5):
            raise ValueError('original creator wait time changed')
        for label in ('stdout','stderr'):
            if (wait[label+'_path']!=str(controller/names['guardian_'+label])
                    or wait[label+'_sha256']!=evidence['guardian_'+label+'_sha256'].split(':',1)[1]):
                raise ValueError('original creator wait stream binding changed')
        documentary[str(creator_wait)]=payload
    return documentary


def _bootstrap_artifacts(row,pins,controller,guardian_pin):
    evidence=pins['guardian_bootstrap_failure']
    if 'preconsume_exit' in pins:raise ValueError('bootstrap streams cannot substitute for a controller wait')
    op._object(evidence,{'schema','stdout_sha256','stderr_sha256'},'original guardian bootstrap streams')
    if evidence['schema']!='native-guardian-bootstrap-failure/v1':raise ValueError('unsupported guardian bootstrap evidence')
    nonce=pins['guardian_nonce']
    if not isinstance(nonce,str) or re.fullmatch('[0-9a-f]{32}',nonce) is None:raise ValueError('original guardian nonce must be canonical')
    documentary={}
    for label in ('stdout','stderr'):
        path=controller/(nonce+'.guardian.'+label);digest=evidence[label+'_sha256']
        op._digest(digest,'original guardian stream digest')
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=pins['custody']['controller_uid'] or info.st_gid!=guardian_pin['gid'] or stat.S_IMODE(info.st_mode) not in (0o600,0o640):raise ValueError('protected original bootstrap stream custody required')
                data=stream.read(65537)
        except OSError:raise ValueError('original guardian bootstrap stream unavailable') from None
        if len(data)>65536 or 'sha256:'+hashlib.sha256(data).hexdigest()!=digest:raise ValueError('original guardian bootstrap bytes changed')
        if label=='stdout' and data:raise ValueError('original bootstrap stdout must be empty')
        if label=='stderr':
            marker=b'ValueError: original guardian birth never persisted; no child launch\n'
            if b'\0' in data or not data.startswith(b'Traceback (most recent call last):\n') or not data.endswith(marker) or data.count(marker)!=1:raise ValueError('original no-child bootstrap traceback required')
            try:data.decode('utf-8')
            except UnicodeError:raise ValueError('original bootstrap traceback encoding invalid') from None
        documentary[str(path)]=data
    return documentary


def _preparation_receipt(store,row,pins,budget_store,first):
    """Observe an original event; this never reserves, closes or grants launch."""
    preparation=row['operation'].get('reservation_preparation')
    if preparation is None:
        if 'preparation_budget' in pins or budget_store is not None:raise ValueError('unexpected original preparation budget channel')
        return None
    op._object(preparation,{'schema','root_parent_revision','project_budget'},'original reservation preparation')
    if preparation['schema']!='cdc-vps-reservation-preparation/v1':raise ValueError('original reservation preparation schema required')
    proposal=preparation['project_budget']
    if proposal is None:
        if 'preparation_budget' in pins or budget_store is not None or 'project_budget' in row['operation']:raise ValueError('unexpected original project receipt')
        return None
    from project_budget_store import GitProjectBudgetStore
    trusted=pins.get('preparation_budget')
    op._object(trusted,{'binding','registration_digest'},'trusted original preparation budget')
    op._digest(trusted['registration_digest'],'original registration digest')
    request=row['operation']['start_request'];task=row['task'];intent=row['operation']['intent']
    if type(budget_store) is not GitProjectBudgetStore or budget_store.binding!=trusted['binding'] or budget_store.repo!=Path(request['repo_root']).resolve() or budget_store.remote!=request.get('coordination_remote',request['remote']):raise ValueError('actual original typed preparation budget required')
    binding=budget_store.binding
    if binding['repository']!=request['lease_repository'] or binding['source_ref']!=request['lease_source_ref'] or binding['coordination_store_id']!=request['plan']['coordination_store_id']:raise ValueError('original project budget/source channel mismatch')
    fields={'schema','project_id','project_task_id','root_task_id','attempt_id','operation_key','registration_digest','budget_binding_digest','start_request_digest','prepared_budget_revision','event','event_digest','authorizes_launch'}
    op._object(proposal,fields,'original project budget proposal')
    receipt=row['operation'].get('project_budget')
    op._object(receipt,fields-{'prepared_budget_revision'}|{'reservation_revision'},'original project budget receipt')
    if proposal['authorizes_launch'] is not False or receipt['authorizes_launch'] is not False:raise ValueError('original preparation never authorizes launch')
    prepared=budget_store.read_revision(proposal['prepared_budget_revision'])
    event=proposal['event']
    expected_event={'type':'reserve','event_id':'vps-'+task['id']+'-original-compute-start','task_id':binding['task_id'],
        'wake_id':prepared['wake_ids'][-1],'at_utc':event['at_utc'],'operation_key':intent['operation_key'],
        'attempt_id':request['attempt_id'],'kind':'compute_start','scope':'registered-vps-project-adoption:'+task['id'],
        'recovery_ref':None,'cost':{'tool_calls':task['budget']['tool_calls'],'tokens':None,'elapsed_seconds':task['max_runtime_seconds']}}
    expected={'schema':'cdc-vps-project-budget-preparation/v1','project_id':task['project_id'],
        'project_task_id':binding['task_id'],'root_task_id':task['id'],'attempt_id':request['attempt_id'],
        'operation_key':intent['operation_key'],'registration_digest':trusted['registration_digest'],
        'budget_binding_digest':native_digest(binding),'start_request_digest':_contract(row),
        'prepared_budget_revision':proposal['prepared_budget_revision'],'event':expected_event,
        'event_digest':native_digest(expected_event),'authorizes_launch':False}
    if proposal!=expected:raise ValueError('original prepared project event/receipt contract mismatch')
    expected_receipt=copy.deepcopy(expected);expected_receipt.update(schema='cdc-vps-original-project-budget/v1',reservation_revision=receipt['reservation_revision']);del expected_receipt['prepared_budget_revision']
    if receipt!=expected_receipt:raise ValueError('original project receipt is not the exact preparation progress')
    import budget
    if any(e.get('event_id')==event['event_id'] or (e.get('operation_key'),e.get('attempt_id'))==(event['operation_key'],event['attempt_id']) for e in prepared['events']) or not budget.decide(prepared,event)['allow_reservation']:raise ValueError('original event did not follow eligible project preparation')
    recorded=budget_store.read_revision(receipt['reservation_revision']);_,current=budget_store.read()
    for ledger in (recorded,current):
        if sum(e==event for e in ledger['events'])!=1 or any(e['type']=='outcome' and e['reservation_id']==event['event_id'] for e in ledger['events']):raise ValueError('exact original unresolved project reservation required')
    parent=preparation['root_parent_revision'];parent_row=_row(store.read_revision(parent),task['id'])
    if parent_row['state']!='queued' or parent_row['task']!=task or parent_row.get('operation') is not None or parent_row.get('result') is not None or parent_row['budget']['events']:raise ValueError('original queued preparation predecessor required')
    if first is None:raise ValueError('original prepared Root row absent')
    revision,initial=first;operation=initial['operation']
    if store._git('rev-parse',revision+'^')!=parent or initial['state']!='reserved' or operation['intent']['state']!='prepared' or operation.get('guardian') is not None or 'project_budget' in operation:raise ValueError('original project preparation boundary changed')
    return {'receipt':receipt,'prepared_revision':revision,'prepared_intent':operation['intent']}


def _physical_and_artifacts(store,row,pins,source_store=None):
    request=row['operation']['start_request']
    _identity(pins['creator'],absent=True);_identity(pins['guardian'],absent=True)
    guardian=row['operation'].get('guardian')
    if not isinstance(guardian,dict) or guardian.get('nonce')!=pins['guardian_nonce'] or guardian.get('identity')!=pins['guardian']:raise ValueError('original canonical guardian nonce/identity required')
    _intake_channels(store,row,pins,source_store)
    channel=source_store or store
    if pins['pool_ref']!=request['plan']['coordination_ref'] or request['plan']['coordination_store_id']!=channel.store_id:raise ValueError('original protected pool channel mismatch')
    channel._assert_remote_identity();channel._git('check-ref-format',pins['pool_ref'])
    if channel._git('ls-remote','--refs',channel.remote,pins['pool_ref']):raise ValueError('native original pool/runtime effect already exists')
    custody=pins.get('custody')
    op._object(custody,{'controller_root','worker_launch_root','controller_uid','worker_gid'},'complete original protected custody')
    if any(type(custody[k]) is not int or custody[k]<0 for k in ('controller_uid','worker_gid')):raise ValueError('configured custody UID/GID required')
    task_id=request['task_id'];executor=row['operation']['executor']
    for name in (task_id,executor):
        if not isinstance(name,str) or not name or name in {'.','..'} or '/' in name or '\\' in name:raise ValueError('exact original custody identity required')
    controller=Path(custody['controller_root'])/task_id
    launch=Path(custody['worker_launch_root'])/executor/task_id
    roots=pins['launch_roots'];allowed=pins.get('artifact_pins',{})
    expected={request['journal_root'],request['handle_root'],str(controller),str(launch)}
    if not isinstance(roots,list) or len(roots)!=len(set(roots)) or set(roots)!=expected or not isinstance(allowed,dict):raise ValueError('complete derived original controller/worker/native roots required')
    from managed_host_bridge import _canonical
    from git_remote_identity import repository_root
    identity={'repo_root':str(repository_root(request['repo_root'])),'store':request['plan']['coordination_store_id'],'coordination_ref':request['plan']['coordination_ref'],'pool_id':request['plan']['pool_id'],'task_id':task_id,'attempt_id':request['attempt_id']}
    handle=str(uuid.uuid5(uuid.NAMESPACE_URL,_canonical(identity)))
    native_paths=[Path(request['handle_root'])/(handle+'.json'),Path(request['handle_root'])/'gates'/handle,Path(request['handle_root'])/'locks'/(handle+'.lock'),Path(request['journal_root'])/native_digest({name:identity[name] for name in ('pool_id','task_id','attempt_id')}).split(':',1)[1]]
    publication_ref='refs/heads/cdc/managed-host-publish-'+handle.replace('-','')
    if channel._git('ls-remote','--refs',channel.remote,publication_ref):raise ValueError('original publication journal already exists')
    # Native effect scopes are absent unconditionally, including empty directories
    # and broken symlinks. Deployment pins can never turn effects into static data.
    for path in native_paths:
        if any(p.is_symlink() for p in [path,*path.parents]) or path.exists():raise ValueError('native session/gate/lock/journal effect blocks prelaunch disposition')
    for raw in [*roots,custody['controller_root'],custody['worker_launch_root']]:
        path=Path(raw)
        if not path.is_absolute() or str(path.resolve())!=raw or any(p.is_symlink() for p in [path,*path.parents]):raise ValueError('protected exact launch root required')
        if path.exists() and not path.is_dir():raise ValueError('launch root must be a directory')
    # Original output is an absence fact, never a hash whitelist. Native worker
    # preparation may create this empty directory before dispatch.
    output=launch/'output'
    if output.is_symlink() or output.exists() and (not output.is_dir() or any(output.iterdir())):raise ValueError('original worker output must be empty')
    static={str(controller/'guardian.lock'),str(launch/'record.json'),str(launch/'registered-record.json')}
    if not static<=set(allowed):raise ValueError('original controller/preparation/registered static records required')
    checkout=launch/'worktree'
    checkout_dirs={checkout}
    if checkout.exists():
        if checkout.is_symlink() or not checkout.is_dir():raise ValueError('original static checkout custody required')
        from git_object_integrity import git_object_environment
        def checkout_git(*args,check=True,binary=False):
            result=subprocess.run(['git','--no-optional-locks','-c','safe.directory='+str(checkout),'-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',str(checkout),*args],env=git_object_environment(GIT_TERMINAL_PROMPT='0',GIT_OPTIONAL_LOCKS='0'),text=not binary,capture_output=True,timeout=20)
            if check and result.returncode:raise ValueError('original prepared checkout unavailable')
            return (result.stdout if binary else result.stdout.strip()),result.returncode
        if checkout_git('rev-parse','--show-toplevel')[0]!=str(checkout) or checkout_git('rev-parse','HEAD')[0]!=row['task']['source_sha'] or checkout_git('symbolic-ref','-q','HEAD',check=False)[1]!=1 or checkout_git('status','--porcelain','--untracked-files=all')[0] or checkout_git('remote')[0]:raise ValueError('prepared static checkout changed or is not isolated')
        # Index flags or cached stat data cannot turn changed worker bytes into a
        # static source snapshot. Compare every committed blob independently.
        tree=checkout_git('ls-tree','-r','-z','HEAD',binary=True)[0]
        source_files=set()
        for entry in tree.split(b'\0'):
            if not entry:continue
            metadata,name=entry.split(b'\t',1);mode,kind,oid=metadata.split()
            path=checkout/name.decode('utf-8');source_files.add(path)
            if mode not in (b'100644',b'100755') or kind!=b'blob' or path.is_symlink() or not path.is_file() or path.read_bytes()!=checkout_git('cat-file','blob',oid.decode(),binary=True)[0]:raise ValueError('original prepared source bytes differ from exact source commit')
        git_root=checkout/'.git'
        metadata_names={'HEAD','config','description','index','packed-refs','info/exclude','logs/HEAD'}
        samples={'applypatch-msg','commit-msg','fsmonitor-watchman','post-update','pre-applypatch','pre-commit','pre-merge-commit','pre-push','pre-rebase','pre-receive','prepare-commit-msg','push-to-checkout','sendemail-validate','update'}
        metadata_names.update('hooks/'+name+'.sample' for name in samples)
        metadata=set()
        for path in git_root.rglob('*'):
            if not path.is_file():continue
            name=path.relative_to(git_root).as_posix()
            is_ref=re.fullmatch(r'(?:logs/)?refs/(?:heads|tags|remotes)/[^\x00-\x20~^:?*\[\\]+',name)
            is_object=re.fullmatch(r'objects/(?:[0-9a-f]{2}/(?:[0-9a-f]{38}|[0-9a-f]{62})|pack/pack-(?:[0-9a-f]{40}|[0-9a-f]{64})\.(?:pack|idx|rev|bitmap))',name)
            if name not in metadata_names and not is_ref and not is_object:raise ValueError('unknown file cannot be pinned as static Git metadata')
            metadata.add(path)
        files={p for p in checkout.rglob('*') if p.is_file()}
        if files!=source_files|metadata:raise ValueError('unregistered worker file in prepared source checkout')
        static.update(str(p) for p in files)
        checkout_dirs.update(git_root/name for name in ('','branches','hooks','info','logs','objects','objects/info','objects/pack','refs','refs/heads','refs/tags','refs/remotes','logs/refs','logs/refs/heads','logs/refs/tags','logs/refs/remotes'))
        for path in files:
            checkout_dirs.update(parent for parent in path.parents if parent==checkout or checkout in parent.parents)
    if not set(allowed)<=static:raise ValueError('pins may describe only original pre-effect static custody')
    guardian_pin=allowed[str(controller/'guardian.lock')]
    op._object(guardian_pin,{'sha256','uid','gid','mode'},'original guardian static custody')
    documentary=(_bootstrap_artifacts(row,pins,controller,guardian_pin) if 'guardian_bootstrap_failure' in pins else _preconsume_artifacts(row,pins,controller,guardian_pin))
    seen=set();seen_documentary=set()
    for root in (controller,launch):
        expected_gid=guardian_pin['gid'] if root==controller else custody['worker_gid']
        if not root.is_dir():raise ValueError('complete original protected controller/worker scope missing')
        for child in [root,*root.rglob('*')]:
            if child.is_symlink():raise ValueError('contradictory symlink in protected launch root')
            info=child.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):raise ValueError('special entry in protected custody')
            if info.st_uid!=custody['controller_uid'] or info.st_gid!=expected_gid or info.st_mode & 0o002:raise ValueError('protected scope ownership/mode drift')
            if child.is_dir():
                if child!=output and info.st_mode & 0o020:raise ValueError('static custody must not be worker writable')
                if root==controller and child!=root:raise ValueError('unregistered controller effect directory')
                if root==launch and child not in {launch,output}|checkout_dirs:raise ValueError('unregistered worker effect directory')
                continue
            key=str(child)
            if key in documentary:
                if child.read_bytes()!=documentary[key]:raise ValueError('original wait artifact changed during authentication')
                seen_documentary.add(key);continue
            seen.add(key);pin=allowed.get(key)
            op._object(pin,{'sha256','uid','gid','mode'},'protected static artifact pin')
            if info.st_nlink!=1 or (info.st_uid,info.st_gid,info.st_mode & 0o7777)!=(pin['uid'],pin['gid'],pin['mode']) or info.st_mode & 0o022:raise ValueError('protected static file custody/mode drift')
            if 'sha256:'+hashlib.sha256(child.read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('original static artifact bytes drift')
            if child==controller/'guardian.lock' and child.read_bytes()!=b'':raise ValueError('original guardian lock must be empty')
            if child.name in {'record.json','registered-record.json'} and child.parent==launch:
                try:record=json.loads(child.read_text())
                except (ValueError,OSError):raise ValueError('original protected preparation record unavailable') from None
                if child.name=='registered-record.json':
                    op._object(record,{'schema','task','registry','task_digest','executor'},'original registered launch record')
                    if record['schema']!='cdc-vps-launch/v1' or record['task']!=row['task'] or record['task_digest']!=native_digest(row['task']) or record['executor']!=executor or not isinstance(record['registry'],dict):raise ValueError('registered launch record/task/executor mismatch')
                else:
                    op._object(record,{'operation_id','profile_id','source_sha','source_ref','profile_digest'},'original preparation record')
                    if record['operation_id']!=task_id or record['source_sha']!=row['task']['source_sha'] or record['source_ref']!=request['lease_source_ref'] or not isinstance(record['profile_id'],str) or not re.fullmatch('[0-9a-f]{64}',record['profile_digest']):raise ValueError('original preparation record/source mismatch')
    if seen!=set(allowed) or seen_documentary!=set(documentary):raise ValueError('pinned original static/documentary launch artifact missing')
    _identity(pins['creator'],absent=True);_identity(pins['guardian'],absent=True)
    if 'preconsume_exit' in pins:_identity(pins['preconsume_exit']['controller'],absent=True)


def _authenticate_intake(store,task_id,source,pins,*,retired=False,project_budget_store=None):
    if type(store) is not GitDocumentStore or type(source) is not GitLeaseStore:raise ValueError('actual configured native stores required')
    required={'original_revision','row_digest','source_revision','source_digest','creator','guardian','guardian_nonce','pool_ref','launch_roots','custody'}
    if not isinstance(pins,dict) or not required<=set(pins) or set(pins)-required-{'artifact_pins','channels','preconsume_exit','guardian_bootstrap_failure','preparation_budget','creator_guardian_wait'}:raise ValueError('independent trusted original contract pins required')
    if 'creator_guardian_wait' in pins and 'preconsume_exit' not in pins:raise ValueError('creator wait requires the exact original preconsume controller wait')
    from immutable_history_cache import _cache
    head,head_document,chain,context,prior=_history_snapshot(store)
    del prior
    error=None
    try:
        if pins['original_revision'] not in {parts[0] for parts in chain}:
            raise ValueError('original intake anchor is outside current history')
        original=store.read_revision(pins['original_revision']);original_row=_row(original,task_id)
        if op._hash(original_row)!=pins['row_digest'] or _consumed(original_row):raise ValueError('pinned original unconsumed task row required')
        from managed_host_bridge import _validate_start
        _validate_start(original_row['operation']['start_request'])
        request=original_row['operation']['start_request']
        if source.ref!=request['lease_coordination_ref'] or original_row['operation']['attempt_id']!=request['attempt_id'] or request['task_id']!=task_id:raise ValueError('original native source/start/attempt channel mismatch')
        import budget
        budget.validate_ledger(original_row['budget'])
        original_intent=original_row['operation']['intent'];op.validate_intent(original_intent)
        if original_intent['binding']['repository']!=request['lease_repository'] or original_intent['binding']['candidate_sha']!=request['plan']['base_sha'] or original_intent['source_ref']!=request['lease_source_ref'] or original_intent['attempt_id']!=request['attempt_id']:raise ValueError('original native intake intent/start contract mismatch')
        digest=_contract(original_row);seen=False;admitted=False;intent_rank=-1;receipt_seen=False;submitted=None;progress=None
    except (ValueError,TypeError,KeyError,AttributeError) as rejected:
        error=rejected.with_traceback(None)
    def check(revision,doc):
        nonlocal seen,admitted,intent_rank,receipt_seen,submitted,progress
        rows=doc.get('tasks',{})
        row=rows.get(task_id)
        if row is None:
            if seen:raise ValueError('original native task row was deleted')
            return
        seen=True
        budget.validate_ledger(row['budget'])
        if {key:value for key,value in row['budget'].items() if key not in {'events','wake_ids'}}!={key:value for key,value in original_row['budget'].items() if key not in {'events','wake_ids'}} or original_row['budget']['wake_ids'][:len(row['budget']['wake_ids'])]!=row['budget']['wake_ids']:raise ValueError('original charged budget policy/identity history changed')
        if row.get('task')!=original_row['task']:raise ValueError('original task contract changed in history')
        if row.get('operation') is None:
            if admitted or row.get('state')!='queued' or row.get('result') is not None:raise ValueError('native admission/history erased')
            return
        if not admitted:
            progress=_preparation_receipt(store,original_row,pins,project_budget_store,(revision,row))
        admitted=True
        if _consumed(row) and not (retired and row['state']=='retired_unknown'):raise ValueError('original controller/start/output history consumed')
        historical=copy.deepcopy(row['operation']);canonical=copy.deepcopy(original_row['operation'])
        historical.pop('guardian',None);canonical.pop('guardian',None)
        if progress is not None:
            receipt=historical.pop('project_budget',None);canonical.pop('project_budget')
            if receipt is not None:
                if receipt!=progress['receipt']:raise ValueError('original preparation receipt history changed')
                receipt_seen=True
            elif receipt_seen:raise ValueError('original preparation receipt was removed')
            initial=progress['prepared_intent'];current_intent=historical['intent']
            if current_intent['state']=='prepared':
                if current_intent!=initial or receipt is not None or row['operation'].get('guardian') is not None:raise ValueError('original prepared progress changed')
            elif current_intent['state']=='submitting':
                at=current_intent['updated_at_utc']
                readback=op.verify_readback(initial,initial,store.ref+'@'+progress['prepared_revision']+':tasks/'+task_id+'/operation/intent',at)
                expected=op.transition(initial,'submitting',at,receipt=readback)
                if current_intent!=expected or receipt is None or submitted is not None and submitted!=current_intent:raise ValueError('original submitted preparation/readback changed')
                submitted=copy.deepcopy(current_intent)
            else:raise ValueError('original preparation intent is not monotonic')
        if historical.get('observation') is not None and historical['observation']!=canonical.get('observation'):raise ValueError('original observational history changed')
        historical.pop('observation',None);canonical.pop('observation',None)
        historical_intent=historical.get('intent');original_intent=canonical.get('intent')
        if isinstance(original_intent,dict) and original_intent.get('schema')==op.SCHEMA:
            op.validate_intent(historical_intent);op.validate_intent(original_intent)
            ranks={'prepared':0,'submitting':1,'unknown':2}
            rank=ranks.get(historical_intent['state'],-1)
            if rank<0 or rank<intent_rank or rank>ranks.get(original_intent['state'],-1) or historical_intent['task'] is not None:raise ValueError('prelaunch native intent ancestry must remain unconsumed and forward')
            intent_rank=rank
            for transient in ('state','updated_at_utc','durable_intent'):
                historical['intent'].pop(transient,None);canonical['intent'].pop(transient,None)
        if _contract(row)!=digest or historical!=canonical:raise ValueError('complete original start contract/controller history changed')
        if 'guardian' in row['operation'] and row['operation']['guardian']!=original_row['operation']['guardian']:raise ValueError('original guardian history changed')
        if row['budget']!=original_row['budget']:
            old_events=row['budget'].get('events');events=original_row['budget'].get('events')
            if not isinstance(old_events,list) or not isinstance(events,list) or events[:len(old_events)]!=old_events or revision==pins['original_revision']:raise ValueError('original budget event ancestry changed')
    # Decode every complete immutable tree/canonical JSON even after semantic
    # denial. Keep only fixed original/current and first-preparation state.
    revisions=[parts[0] for parts in chain[:-1]]
    decoded=iter(store._read_document_objects(revisions)) if revisions else iter(())
    for parts in chain:
        revision=parts[0]
        document=head_document if revision==head else next(decoded)
        if error is None:
            try:
                if revision==pins['original_revision'] and _row(document,task_id)!=original_row:
                    raise ValueError('authenticated original intake row changed')
                check(revision,document)
            except (ValueError,TypeError,KeyError,AttributeError) as rejected:
                error=rejected.with_traceback(None)
        document=None
    del decoded
    if head!=store.read()[0]:raise ValueError('native history moved during authentication')
    _cache.put(context,{'chain':chain,'documents':[]})
    if error is not None:raise error
    revision,document=store.read();current=_row(document,task_id)
    if revision!=head or document!=head_document:raise ValueError('native intake observation moved')
    if retired:validate_prelaunch_disposition(current)
    elif current!=original_row or current.get('state') not in (('unknown','starting','start_unknown','running') if 'guardian_bootstrap_failure' in pins else ('unknown','starting','start_unknown')):raise ValueError('exact original prelaunch UNKNOWN row required')
    srev,sdoc=source.read()
    if retired:
        sdoc=source.read_revision(pins['source_revision']);srev=pins['source_revision']
    if srev!=pins['source_revision'] or op._hash(sdoc)!=pins['source_digest'] or sdoc['owner_id'] is not None or sdoc['external_guard'] is not None or sdoc['repository']!=request['lease_repository'] or sdoc['source_ref']!=request['lease_source_ref']:raise ValueError('unchanged canonical absent-native source lease required')
    _intake_channels(store,original_row,pins,source)
    _physical_and_artifacts(store,original_row,pins,source)
    return revision,current


class PrelaunchIntakeDispositionProof(dict):
    """Ephemeral administrative slot custody, distinct from terminal proof."""
    def __init__(self,seal,store,task_id,source,pins,at,*,retired=False,project_budget_store=None):
        if seal is not _SEAL:raise ValueError('package issued prelaunch disposition required')
        revision,row=_authenticate_intake(store,task_id,source,pins,retired=retired,project_budget_store=project_budget_store)
        super().__init__(schema=DISPOSITION_SCHEMA,task_id=task_id,contract_digest=_contract(row),original_effect='UNKNOWN',actual_wait=None,original_revision=pins['original_revision'])
        self._evidence=copy.deepcopy(dict(self))
        self._budget=project_budget_store
        self._seal=seal;self._store=store;self._source=source;self._pins=copy.deepcopy(pins);self._at=at;self._revision=revision;self._retired=retired
    def revalidate_for(self,store,task_id):
        if dict(self)!=self._evidence:raise ValueError('native disposition evidence capability was mutated')
        if self._seal is not _SEAL or store is not self._store or task_id!=self['task_id']:raise ValueError('original native disposition endpoint/task substituted')
        return _authenticate_intake(store,task_id,self._source,self._pins,retired=self._retired,project_budget_store=self._budget)[1]


def authenticate_prelaunch_intake(store,task_id,*,source_store,trusted_contract,at,project_budget_store=None):
    op._timestamp(at,'administrative disposition time')
    return PrelaunchIntakeDispositionProof(_SEAL,store,task_id,source_store,trusted_contract,at,project_budget_store=project_budget_store)


def _validate_prelaunch_disposition_row(row):
    """Structural history validation only; serialized data supplies no authority."""
    entry=(row.get('result') or {}).get('administrative_disposition')
    if isinstance(entry,dict) and entry.get('schema')==POSTLAUNCH_SCHEMA:return _validate_postlaunch_disposition_row(row)
    if isinstance(entry,dict) and entry.get('schema') in {PREHANDLE_SCHEMA,LEGACY_PREHANDLE_SCHEMA}:return _validate_prehandle_disposition_row(row)
    fields={'schema','task_id','contract_digest','original_effect','actual_wait','replay_forbidden','original_revision','original_row','trusted_contract','retired_at_utc'}
    op._object(entry,fields,'native prelaunch disposition')
    if row.get('state')!='retired_unknown' or entry['schema']!=DISPOSITION_SCHEMA or entry['original_effect']!='UNKNOWN' or entry['actual_wait'] is not None or entry['replay_forbidden'] is not True or _contract(row)!=entry['contract_digest']:raise ValueError('prelaunch disposition must preserve UNKNOWN/no wait/no replay')
    if entry['task_id']!=row['task'].get('id'):raise ValueError('original task identity must match disposition')
    original=entry['original_row'];expected=copy.deepcopy(original);expected['state']='retired_unknown';expected['result']={'administrative_disposition':copy.deepcopy(entry)}
    if expected!=row or _consumed(original) or op._hash(original)!=entry['trusted_contract']['row_digest'] or entry['original_revision']!=entry['trusted_contract']['original_revision']:raise ValueError('administrative disposition cannot alter original liabilities/contract')
    op._timestamp(entry['retired_at_utc'],'disposition time')
    return entry


def validate_intake_transition(previous,document,*,store,expected_revision,recovery_capability=None):
    if (not previous or previous.get('schema')!=INTAKE_SCHEMA) and document.get('schema')!=INTAKE_SCHEMA:return
    if not previous or previous.get('schema')!=INTAKE_SCHEMA:
        if any(row.get('state')=='retired_unknown' or (row.get('result') or {}).get('unstarted_cancellation') is not None for row in document.get('tasks',{}).values()):raise ValueError('raw initialization cannot mint native disposition')
        return
    if document.get('schema')!=INTAKE_SCHEMA:raise ValueError('native intake schema cannot be replaced')
    if type(recovery_capability) is _ReleasedRegistryMigration:
        recovery_capability.revalidate(store,expected_revision,previous,document)
    old_rows=previous['tasks'];new_rows=document['tasks'];retired=[]
    for task_id,row in old_rows.items():
        proposed=new_rows.get(task_id)
        if (row.get('result') or {}).get('unstarted_cancellation') is not None:
            entry=validate_queued_cancellation(row)
            if proposed!=row:raise ValueError('unstarted cancellation cannot be removed or rearmed')
            if entry['schema']==RESERVED_SCHEMA:retired.append((_contract(row),semantic_intake_contract(row)))
        elif proposed is not None and (proposed.get('result') or {}).get('unstarted_cancellation') is not None:
            if type(recovery_capability) is PrehandleIntakeDispositionProof:
                recovery_capability.revalidate_cancellation(store,expected_revision,task_id,proposed)
            elif type(recovery_capability) is UnstartedQueuedCancellation:
                recovery_capability.revalidate(store,expected_revision,task_id,proposed)
            else:raise ValueError('native queued cancellation capability required')
            expected=copy.deepcopy(previous);expected['tasks'][task_id]=copy.deepcopy(proposed)
            if expected!=document:raise ValueError('queued cancellation cannot mutate unrelated state')
            if validate_queued_cancellation(proposed)['schema']==RESERVED_SCHEMA:retired.append((_contract(row),semantic_intake_contract(row)))
        elif row.get('state')=='queued' and proposed is not None and proposed.get('state')=='cancelled' and proposed.get('operation') is None:
            raise ValueError('typed native unstarted cancellation required')
    for task_id,row in new_rows.items():
        if task_id not in old_rows and (row.get('state')=='retired_unknown' or (row.get('result') or {}).get('unstarted_cancellation') is not None):
            raise ValueError('cannot initialize a native disposition')
    for task_id,row in old_rows.items():
        if row.get('state')=='retired_unknown':
            validate_prelaunch_disposition(row)
            if new_rows.get(task_id)!=row:raise ValueError('native tombstone/history cannot be changed or removed')
            retired.append((_contract(row),semantic_intake_contract(row)))
        elif (new_rows.get(task_id) or {}).get('state')=='retired_unknown':
            if type(recovery_capability) not in (PrelaunchIntakeDispositionProof,PostlaunchIntakeDispositionProof,PrehandleIntakeDispositionProof) or recovery_capability._retired or recovery_capability._revision!=expected_revision:raise ValueError('native tombstone CAS requires issued exact revision proof')
            recovery_capability.revalidate_for(store,task_id)
            entry=validate_prelaunch_disposition(new_rows[task_id])
            if (entry['schema']==POSTLAUNCH_SCHEMA)!=(type(recovery_capability) is PostlaunchIntakeDispositionProof):raise ValueError('native disposition capability type mismatch')
            if (entry['schema'] in {PREHANDLE_SCHEMA,LEGACY_PREHANDLE_SCHEMA})!=(type(recovery_capability) is PrehandleIntakeDispositionProof):raise ValueError('native prehandle capability type mismatch')
            if entry['original_row']!=row or entry['trusted_contract']!=recovery_capability._pins or entry['retired_at_utc']!=recovery_capability._at:raise ValueError('native disposition proposal substituted')
            expected=copy.deepcopy(previous);expected['tasks'][task_id]=copy.deepcopy(new_rows[task_id])
            if expected!=document:raise ValueError('tombstone CAS cannot mutate unrelated fields')
            retired.append((_contract(row),semantic_intake_contract(row)))
        new_consumption=((new_rows.get(task_id) or {}).get('operation') or {}).get('start_consumption')
        if new_consumption is not None and (row.get('operation') or {}).get('start_consumption') is None:
            if type(recovery_capability) is not _StartConsumption:raise ValueError('start CAS requires native one-use consumption capability')
            recovery_capability.revalidate(store,expected_revision,task_id,document)
        if (row.get('operation') or {}).get('start_consumption') is not None and ((new_rows.get(task_id) or {}).get('operation') or {}).get('start_consumption')!=row['operation']['start_consumption']:raise ValueError('native one-use start consumption is immutable')
    for task_id,row in new_rows.items():
        frozen=row.get('state')=='retired_unknown' or ((row.get('result') or {}).get('unstarted_cancellation') or {}).get('schema')==RESERVED_SCHEMA
        if not frozen and any((row.get('operation') is not None and _contract(row)==contract) or semantic_intake_contract(row)==semantic for contract,semantic in retired):raise ValueError('retired original start contract cannot replay under another task/attempt')


def retire_prelaunch_intake_cas(store,expected_revision,task_id,proof,*,at):
    if type(proof) is not PrelaunchIntakeDispositionProof or proof._retired or at!=proof._at:raise ValueError('native issued administrative proof required')
    row=proof.revalidate_for(store,task_id);revision,document=store.read()
    if revision!=expected_revision or revision!=proof._revision:raise ValueError('stale original intake revision; observe without replay')
    changed=copy.deepcopy(document);new=changed['tasks'][task_id];new['state']='retired_unknown'
    new['result']={'administrative_disposition':dict(schema=DISPOSITION_SCHEMA,task_id=task_id,contract_digest=_contract(row),original_effect='UNKNOWN',actual_wait=None,replay_forbidden=True,original_revision=proof._pins['original_revision'],original_row=copy.deepcopy(row),trusted_contract=copy.deepcopy(proof._pins),retired_at_utc=at)}
    revision=store.compare_and_swap(expected_revision,changed,recovery_capability=proof)
    actual,readback=store.read()
    if actual!=revision or readback!=changed:raise ValueError('native disposition readback moved; observe without replay')
    retired_proof=observe_prelaunch_intake_disposition(store,task_id,contract_digest=_contract(row),source_store=proof._source,project_budget_store=proof._budget)
    return {'revision':revision,'row':new,'proof':retired_proof}


def observe_prelaunch_intake_disposition(store,task_id,*,contract_digest,source_store=None,project_budget_store=None):
    if type(store) is not GitDocumentStore:raise ValueError('actual native intake store required')
    _,document=store.read();row=_row(document,task_id);entry=validate_prelaunch_disposition(row)
    if entry['contract_digest']!=contract_digest:raise ValueError('original disposition contract mismatch')
    if source_store is None:
        request=row['operation']['start_request']
        if entry['trusted_contract'].get('channels') is not None:
            source_store=GitLeaseStore(request['repo_root'],request.get('coordination_remote',request['remote']),request['lease_coordination_ref'])
        else:source_store=GitLeaseStore(store.repo,store.remote,request.get('lease_coordination_ref','refs/heads/cdc/source-lease'))
    if project_budget_store is None and entry['trusted_contract'].get('preparation_budget') is not None:
        from project_budget_store import GitProjectBudgetStore
        request=row['operation']['start_request']
        project_budget_store=GitProjectBudgetStore(request['repo_root'],request.get('coordination_remote',request['remote']),entry['trusted_contract']['preparation_budget']['binding'])
    return PrelaunchIntakeDispositionProof(_SEAL,store,task_id,source_store,entry['trusted_contract'],entry['retired_at_utc'],retired=True,project_budget_store=project_budget_store)


def assert_intake_start_allowed(store,task_id,start_request_digest):
    _,document=store.read();row=_row(document,task_id)
    if row.get('state') in {'retired_unknown','cancelled'} or _consumed(row) or _contract(row)!=start_request_digest:raise ValueError('native intake start blocked by tombstone/consumption/contract')
    for other in document['tasks'].values():
        if other.get('state')=='retired_unknown' and (validate_prelaunch_disposition(other)['contract_digest']==start_request_digest or semantic_intake_contract(other)==semantic_intake_contract(row)):raise ValueError('original contract replay prohibited')
        if ((other.get('result') or {}).get('unstarted_cancellation') or {}).get('schema')==RESERVED_SCHEMA:
            validate_queued_cancellation(other)
            if _contract(other)==start_request_digest or semantic_intake_contract(other)==semantic_intake_contract(row):raise ValueError('cancelled reserved original contract replay prohibited')
    return row


def consume_intake_start(store,expected_revision,task_id,*,start_request_digest,controller_identity):
    if type(store) is not GitDocumentStore:raise ValueError('actual native intake store required')
    try:
        row=assert_intake_start_allowed(store,task_id,start_request_digest);_identity(controller_identity,absent=False)
        revision,document=store.read()
        if revision!=expected_revision or _row(document,task_id)!=row:raise ValueError('stale start consumption revision')
    except ValueError as error:
        if str(error) not in {'coordination ref moved during read','native history moved during authentication','stale start consumption revision'}:raise
        raise IntakeStartConsumptionFailure(_SEAL,store,expected_revision,task_id,start_request_digest,
            controller_identity,'before_cas',None,None,error) from error
    changed=copy.deepcopy(document);changed['tasks'][task_id]['operation']['start_consumption']={'schema':'native-intake-start-consumption/v1','contract_digest':start_request_digest,'controller':copy.deepcopy(controller_identity)}
    capability=_StartConsumption(_SEAL,store,expected_revision,task_id,changed,controller_identity)
    try:return store.compare_and_swap(expected_revision,changed,recovery_capability=capability)
    except ValueError as error:
        raise IntakeStartConsumptionFailure(_SEAL,store,expected_revision,task_id,start_request_digest,
            controller_identity,'cas',capability.proposal,changed,error) from error


class _StartConsumption:
    def __init__(self,seal,store,revision,task_id,document,identity):
        if seal is not _SEAL:raise ValueError('native one-use start required')
        self.store=store;self.revision=revision;self.task_id=task_id;self.document=copy.deepcopy(document);self.identity=copy.deepcopy(identity);self.proposal=None
    def _bind_proposal(self,store,revision,commit):
        if store is not self.store or revision!=self.revision or self.proposal is not None:raise ValueError('original start proposal binding changed')
        self.proposal=commit
    def revalidate(self,store,revision,task_id,document):
        if store is not self.store or revision!=self.revision or task_id!=self.task_id or document!=self.document:raise ValueError('native start CAS binding changed')
        _identity(self.identity,absent=False)
        assert_intake_start_allowed(store,task_id,document['tasks'][task_id]['operation']['start_request_digest'])


class IntakeStartConsumptionFailure(ValueError):
    """Process-local original call evidence; serialized exceptions grant nothing."""
    native_reconciliation_kind='sdk-intake-consumption-failure/v1'
    def __init__(self,seal,store,revision,task_id,digest,identity,phase,proposal,document,error):
        if seal is not _SEAL:raise ValueError('SDK-issued original consumption failure required')
        super().__init__('original intake start consumption requires native reconciliation')
        self._seal=seal;self._store=store;self._revision=revision;self._task=task_id
        self._digest=digest;self._identity=copy.deepcopy(identity);self._phase=phase
        self._proposal=proposal;self._document=copy.deepcopy(document)
        self._evidence=self._values();self.original_error_type=type(error).__name__
    def _values(self):
        return op._hash({'revision':self._revision,'task':self._task,'digest':self._digest,
            'identity':self._identity,'phase':self._phase,'proposal':self._proposal,'document':self._document})


def _observe_original_consumption(failure):
    if type(failure) is not IntakeStartConsumptionFailure or failure._seal is not _SEAL or failure._values()!=failure._evidence:
        raise ValueError('unaltered SDK-issued original call evidence required')
    store=failure._store;identity=failure._identity
    if type(store) is not GitDocumentStore or identity.get('pid')!=os.getpid():raise ValueError('original live consumption caller required')
    _identity(identity,absent=False)
    from immutable_history_cache import _cache
    head,head_document,chain,context,prior=_history_snapshot(store)
    del prior
    indexes={parts[0]:index for index,parts in enumerate(chain)}
    proposal=failure._proposal;confirmed=proposal is not None and proposal in indexes
    row=after=None;registry=None;registry_present=False;consumed=False;error=None
    try:
        if failure._revision not in indexes:raise ValueError('original consumption anchor is outside current history')
    except ValueError as rejected:
        error=rejected.with_traceback(None)

    # Authenticate every immutable tree/JSON, including the prefix before the
    # original anchor. Only the selected row and the fresh full head survive
    # a generation; neither a document list nor row projections accumulate.
    revisions=[parts[0] for parts in chain[:-1]]
    decoded=iter(store._read_document_objects(revisions)) if revisions else iter(())
    for parts in chain:
        revision=parts[0]
        document=head_document if revision==head else next(decoded)
        if error is None and indexes[revision]>=indexes[failure._revision]:
            try:
                if revision==failure._revision:
                    row=copy.deepcopy(_row(document,failure._task))
                    if document.get('schema')!=INTAKE_SCHEMA:raise ValueError('original native intake schema required')
                    if _consumed(row) or _contract(row)!=failure._digest:raise ValueError('original unconsumed contract changed')
                    import budget
                    budget.validate_ledger(row['budget']);registry=document.get('registry_digest')
                    registry_present='registry_digest' in document
                    after=copy.deepcopy(row);after['operation']['start_consumption']={'schema':'native-intake-start-consumption/v1',
                        'contract_digest':failure._digest,'controller':copy.deepcopy(identity)}
                    if confirmed:
                        if failure._document is None:raise ValueError('original issued proposal document changed')
                        if chain[indexes[proposal]]!=[proposal,failure._revision]:
                            raise ValueError('original consumption proposal parent changed')
                if confirmed and revision==proposal:
                    if document!=failure._document:raise ValueError('original issued proposal document changed')
                    consumed=True
                if (document.get('registry_digest')!=registry or ('registry_digest' in document)!=registry_present
                        or document.get('schema')!=INTAKE_SCHEMA):raise ValueError('original registry changed during consumption')
                expected=after if consumed else row
                if _row(document,failure._task)!=expected:raise ValueError('original task, charged budget or consumption history changed')
            except (ValueError, TypeError, KeyError, AttributeError) as rejected:
                # Semantic rejection must not stop object authentication or
                # erase the complete observed lineage used for rewind checks.
                error=rejected.with_traceback(None)
        document=None
    del decoded
    # Do not remember a partial graph if immutable decoding or this fresh
    # endpoint/head check failed. The compatibility _history API can still
    # load detached full documents from a chain-only cache entry when needed.
    if head!=store.read()[0]:raise ValueError('native history moved during authentication')
    _cache.put(context,{'chain':chain,'documents':[]})
    if error is not None:raise error
    revision,current=store.read()
    if revision!=head or current!=head_document:raise ValueError('native consumption observation moved')
    _identity(identity,absent=False)
    if confirmed:state='confirmed_original';retry=False
    elif failure._phase=='before_cas' or proposal is None:state='unconsumed_before_effect';retry=True
    elif revision!=failure._revision:state='unconsumed_after_head_advance';retry=True
    else:state='unresolved_original';retry=False
    return {'schema':'native-intake-consumption-observation/v1','task_id':failure._task,
        'contract_digest':failure._digest,'controller':copy.deepcopy(identity),'revision':revision,
        'original_revision':failure._revision,'original_proposal':proposal,'state':state,
        'retry_original_consumption':retry,'new_attempts':0,'new_budget_reservations':0}


class IntakeStartConsumptionObservation(dict):
    def __init__(self,seal,failure):
        if seal is not _SEAL:raise ValueError('native original consumption observation required')
        super().__init__(_observe_original_consumption(failure));self._seal=seal;self._failure=failure
        self._evidence=copy.deepcopy(dict(self))
    def revalidate_for(self,store,task_id,digest,identity):
        f=self._failure
        if (self._seal is not _SEAL or dict(self)!=self._evidence or store is not f._store
                or task_id!=f._task or digest!=f._digest or identity!=f._identity):
            raise ValueError('original consumption observation substituted or mutated')
        current=_observe_original_consumption(f)
        if current!=self._evidence:raise ValueError('original consumption observation is no longer current')
        return current


def reconcile_intake_start_consumption(failure):
    return IntakeStartConsumptionObservation(_SEAL,failure)


def _released_success_registry_reconciliation(store,task_id,row,proof):
    """Same-boot original success only; storage migration grants no completion."""
    import managed_host_bridge as bridge
    operation=row.get('operation') or {};start=operation.get('start_request') or {}
    task=row.get('task') or {};finish=operation.get('finish_result') or {}
    if (row.get('state')!='terminal_pending' or row.get('result') is not None
            or task.get('id')!=task_id or task.get('schema')!='cdc-vps-task/v2'
            or task.get('role')!='writer' or type((task.get('budget') or {}).get('ci_starts')) is not int
            or task['budget']['ci_starts']!=0
            or proof.get('task_id')!=task_id or proof.get('attempt_id')!=operation.get('attempt_id')
            or proof.get('status')!='succeeded' or 'boot_reconciliation' in proof
            or proof._boot_transition_path is not None
            or operation.get('start_request_digest')!=op._hash(start)
            or finish.get('worker_status')!='succeeded' or finish.get('scope_complete') is not True
            or finish.get('managed_finish_allowed') is not True):
        raise ValueError('exact original same-boot released success required for registry migration')
    try:
        session=bridge._load_session(start['handle_root'],operation['handle_id'])
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('original successful released native handle unavailable') from None
    binding=proof.get('ownership') or {}
    if (session.get('state')!='released' or session.get('worker_status')!='succeeded'
            or session.get('plan')!=proof._runtime.plan
            or start.get('schema')!='managed-host-start/v1'
            or set(start) not in (bridge._START_FIELDS,bridge._START_FIELDS|{'coordination_remote','source_remote_id'})
            or any(session.get(key)!=start.get(key) for key in bridge._START_FIELDS-{'schema','argv'})
            or any(session.get(key)!=start.get(key) for key in ('coordination_remote','source_remote_id'))
            or session.get('argv_digest')!=bridge._digest(start.get('argv'))
            or task.get('source_sha')!=session['plan']['base_sha']
            or bridge._task(session['plan'],task_id)['role']!='writer'
            or proof._runtime.store.store_id!=store.store_id
            or proof._store.ref!=start.get('lease_coordination_ref') or proof._store.store_id!=store.store_id
            or finish.get('release_receipt')!=session.get('release_receipt')
            or session.get('invocation_id')!=binding.get('invocation_id')
            or any(session.get(key)!=binding.get(key) for key in ('owner_id','generation'))
            or finish.get('published_commit')!=session.get('result_commit')
            or not isinstance(session.get('publication'),dict)):
        raise ValueError('original successful runtime migration Source/handle/release custody mismatch')
    # Authenticate the recorded successful conditional publication without
    # sending, recovering or touching the original source/lease/pool history.
    control,source_id=bridge._routes(session)
    publication_store=GitDocumentStore(session['repo_root'],control,session['publication_ref'],
        store.store_id,protected_refs=[session['lease_source_ref'],session['lease_coordination_ref'],
                                      session['plan']['coordination_ref']])
    publisher=bridge.GitLaneIntegrationPublisher(session['repo_root'],session['remote'],
        session['lease_source_ref'],source_id,attempt_store=publication_store,attempt_store_id=store.store_id)
    result=session['result_commit'];base=session['plan']['base_sha']
    item={'lane_id':task_id,'result_commit':result}
    intent={'operation_id':bridge._digest({'handle_id':session['handle_id'],'result_commit':result,
                'observed_shared_head':base,'shared_ref':session['lease_source_ref']}),
            'lane_id':task_id,'result_commit':result,'observed_shared_head':base,'intended_integrated_head':result}
    attempt=publisher._get_attempt(item,intent)
    if (attempt is None or attempt['status']!='confirmed'
            or session['publication']!=publisher._evidence(item,intent,attempt=attempt,conditional=True)):
        raise ValueError('original confirmed conditional publication evidence required')
    checked=proof.revalidate_for(proof._store,binding['invocation_id'],
        {'owner_id':binding['owner_id'],'generation':binding['generation']},session['release_receipt'])
    if (checked.get('status')!='succeeded' or 'boot_reconciliation' in checked
            or any(proof.get(key)!=checked.get(key) for key in
                ('schema','task_id','attempt_id','request_ref','status','boot_id',
                 'original_claim_revision','ownership','processes','fresh_physical_absence'))):
        raise ValueError('fresh unchanged original same-boot success proof required')


def _released_registry_reconciliations(store,document,proofs):
    """Authenticate stopped originals without assigning them terminal metadata."""
    from managed_executor_runtime import VerifiedTerminalProof
    import managed_host_bridge as bridge
    blocked={key:row for key,row in document['tasks'].items()
        if row.get('state') not in {'queued','succeeded','failed','cancelled','timed_out','retired_unknown'}}
    if not isinstance(proofs,dict) or set(proofs)!=set(blocked):
        raise ValueError('every active attempt needs its exact released original reconciliation')
    for task_id,row in blocked.items():
        proof=proofs[task_id]
        if type(proof) is not VerifiedTerminalProof:
            raise ValueError('live package-owned original terminal reconciliation required')
        if proof.get('status')=='succeeded' and 'boot_reconciliation' not in proof:
            _released_success_registry_reconciliation(store,task_id,row,proof)
            continue
        operation=row.get('operation') or {};start=operation.get('start_request') or {}
        task=row.get('task') or {};finish=operation.get('finish_result') or {}
        if (row.get('state')!='terminal_pending' or row.get('result') is not None
                or task.get('id')!=task_id or task.get('schema')!='cdc-vps-task/v2'
                or task.get('role')!='writer' or (task.get('budget') or {}).get('ci_starts')!=0
                or proof.get('task_id')!=task_id or proof.get('attempt_id')!=operation.get('attempt_id')
                or proof.get('status')!='failed' or not proof.get('boot_reconciliation')
                or operation.get('start_request_digest')!=op._hash(start)
                or finish.get('worker_status')!='failed' or finish.get('managed_finish_allowed') is not True):
            raise ValueError('only exact original released FAILED metadata may accompany runtime migration')
        try:
            session=bridge._load_session(start['handle_root'],operation['handle_id'])
        except (OSError,ValueError,KeyError,TypeError):
            raise ValueError('original released native handle unavailable') from None
        if (session.get('state')!='released' or session.get('worker_status')!='failed'
                or session.get('publication') is not None or session.get('plan')!=proof._runtime.plan
                or any(session.get(key)!=start.get(key) for key in
                    ('plan','owner_id','attempt_id','reservation_token','task_id','lease_source_ref','handle_root','repo_root','remote'))
                or task.get('source_sha')!=session['plan']['base_sha']
                or proof._runtime.store.store_id!=store.store_id
                or proof._store.ref!=start.get('lease_coordination_ref')
                or finish.get('release_receipt')!=session.get('release_receipt')):
            raise ValueError('original runtime migration Source/handle/release custody mismatch')
        binding=proof.get('ownership') or {}
        if session.get('invocation_id')!=binding.get('invocation_id'):
            raise ValueError('original runtime migration invocation mismatch')
        checked=proof.revalidate_for(proof._store,binding['invocation_id'],
            {'owner_id':binding['owner_id'],'generation':binding['generation']},session['release_receipt'])
        if checked.get('status')!='failed' or not checked.get('boot_reconciliation'):
            raise ValueError('fresh failed original boot reconciliation required')


class _ReleasedRegistryMigration:
    def __init__(self,seal,store,revision,previous,proposed,proofs):
        if seal is not _SEAL:raise ValueError('native runtime migration capability required')
        self._seal=seal;self._store=store;self._revision=revision
        self._previous=copy.deepcopy(previous);self._proposed=copy.deepcopy(proposed);self._proofs=dict(proofs)
    def revalidate(self,store,revision,previous,proposed):
        if (type(self) is not _ReleasedRegistryMigration or self._seal is not _SEAL
                or store is not self._store or revision!=self._revision
                or previous!=self._previous or proposed!=self._proposed):
            raise ValueError('original released runtime migration proposal substituted')
        expected=copy.deepcopy(previous);expected['registry_digest']=proposed['registry_digest']
        if expected!=proposed:raise ValueError('runtime migration may change only registry digest')
        _released_registry_reconciliations(store,previous,self._proofs)


def migrate_intake_registry_cas(store,expected_revision,old_digest,new_digest,*,terminal_reconciliations=None):
    """Root configured registry pin migration; no row, charge or queue edits."""
    if type(store) is not GitDocumentStore:raise ValueError('actual native store required')
    op._digest(old_digest,'old trusted registry digest');op._digest(new_digest,'new trusted registry digest')
    revision,document=store.read()
    if revision!=expected_revision or document.get('schema')!=INTAKE_SCHEMA or document.get('registry_digest')!=old_digest or old_digest==new_digest:raise ValueError('stale registry migration binding')
    pending=any(row.get('state') not in {'queued','succeeded','failed','cancelled','timed_out','retired_unknown'} for row in document['tasks'].values())
    if pending and terminal_reconciliations is None:raise ValueError('registry migration requires all active attempts reconciled')
    if terminal_reconciliations is not None:_released_registry_reconciliations(store,document,terminal_reconciliations)
    for row in document['tasks'].values():
        if row.get('state')=='retired_unknown':validate_prelaunch_disposition(row)
    changed=copy.deepcopy(document);changed['registry_digest']=new_digest
    capability=None if terminal_reconciliations is None else _ReleasedRegistryMigration(
        _SEAL,store,expected_revision,document,changed,terminal_reconciliations)
    revision=(store.compare_and_swap(expected_revision,changed) if capability is None
        else store.compare_and_swap(expected_revision,changed,recovery_capability=capability))
    actual,value=store.read()
    if actual!=revision or value!=changed:raise ValueError('registry migration reply changed; observe authoritative store')
    return {'revision':revision,'document':changed}


def _disposition_from_history(store, task_id, current, history, documents):
    entry=_validate_prelaunch_disposition_row(current)
    if entry['original_revision'] not in documents:raise ValueError('disposition original ancestry/task mismatch')
    original=_row(documents[entry['original_revision']],task_id)
    _intake_channels(store,original,entry['trusted_contract'])
    if original!=entry['original_row'] or entry['task_id']!=task_id:raise ValueError('disposition original ancestry/task mismatch')
    found=False
    for _,historical in history:
        historic=historical.get('tasks',{}).get(task_id)
        if historic is None:
            if found:raise ValueError('native tombstone/history deleted')
            continue
        if historic.get('state')=='retired_unknown':
            if historic!=current:raise ValueError('native tombstone history rewritten')
            found=True
        elif found:raise ValueError('native tombstone was rearmed')
        elif entry['schema']==DISPOSITION_SCHEMA and _consumed(historic):raise ValueError('prelaunch disposition has consumed controller/effect ancestry')
    if not found:raise ValueError('native disposition not authoritative')
    return copy.deepcopy(entry)


def _prelaunch_dispositions_fold(store, expected_revision, rows, revision, document):
    selected={};entries={};found=set();anchored=set();failure=None
    try:
        if revision!=expected_revision:raise ValueError('serialized disposition snapshot differs from authoritative head')
        for task_id,row in rows.items():
            current=_row(document,task_id)
            if current!=row:raise ValueError('serialized disposition differs from authoritative original row')
            selected[task_id]=current
            entries[task_id]=_validate_prelaunch_disposition_row(current)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        # Complete object authentication still precedes any semantic rejection,
        # as in _history. Remember its lineage even if selected rows are bad.
        failure=error.with_traceback(None)
    document=None

    while True:
        item = yield
        if item is None:break
        sha,historical = item
        if failure is None:
            try:
                for task_id,current in selected.items():
                    entry=entries[task_id]
                    if sha==entry['original_revision']:
                        original=_row(historical,task_id)
                        _intake_channels(store,original,entry['trusted_contract'])
                        if original!=entry['original_row'] or entry['task_id']!=task_id:
                            raise ValueError('disposition original ancestry/task mismatch')
                        anchored.add(task_id)
                    historic=historical.get('tasks',{}).get(task_id)
                    if historic is None:
                        if task_id in found:raise ValueError('native tombstone/history deleted')
                        continue
                    if historic.get('state')=='retired_unknown':
                        if historic!=current:raise ValueError('native tombstone history rewritten')
                        found.add(task_id)
                    elif task_id in found:raise ValueError('native tombstone was rearmed')
                    elif entry['schema']==DISPOSITION_SCHEMA and _consumed(historic):raise ValueError('prelaunch disposition has consumed controller/effect ancestry')
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                failure=error.with_traceback(None)
        historical=original=historic=item=None
    if failure is not None:raise failure
    if anchored!=selected.keys():raise ValueError('disposition original ancestry/task mismatch')
    if found!=selected.keys():raise ValueError('native disposition not authoritative')
    return {task_id:copy.deepcopy(entry) for task_id,entry in entries.items()}


_DISPOSITION_ROWS_MAX = 64
_DISPOSITION_ROWS_BYTES = 8 * 1024 * 1024


class _DispositionRowValidation:
    """One-call structural reuse only, followed by fresh original validation.

    Exact canonical bytes distinguish every JSON type/value. Cache entries are
    detached and bounded in both count and combined serialized key/row bytes.
    No verdict survives the intake walk or grants a recovery capability.
    """
    def __init__(self):
        self._rows = {}
        self._bytes = 0

    def check(self, row):
        key = op._canonical(row)
        if key in self._rows:
            return
        _validate_prehandle_disposition_row(row)
        size = 2 * len(key)
        if len(self._rows) < _DISPOSITION_ROWS_MAX and self._bytes + size <= _DISPOSITION_ROWS_BYTES:
            self._rows[key] = copy.deepcopy(row)
            self._bytes += size

    def revalidate(self):
        # The original validator includes current start routes, repository and
        # path custody. Never return a successful walk using only a prior check.
        for row in self._rows.values():
            _validate_prehandle_disposition_row(row)


_PREPARATION_PROJECTION_MAX_BYTES = 128 * 1024 * 1024


def validate_intake_dispositions(store, expected_revision, retired_rows, cancelled_rows):
    """Existing API and disposition result remain unchanged."""
    return _validate_intake_dispositions(store, expected_revision, retired_rows, cancelled_rows)[0]


def validate_intake_dispositions_projecting(store, expected_revision, retired_rows, cancelled_rows, task_id):
    """Authenticate as usual and return bounded selected-row DATA for custody replay.

    A projection is returned only after all original object/semantic/final-head
    checks pass. None means the existing consumer must perform its usual walk.
    It never represents start, disposition, lease or terminal authority.
    """
    op._text(task_id, 'preparation projection task')
    return _validate_intake_dispositions(store, expected_revision, retired_rows, cancelled_rows,
                                         project_task_id=task_id)


def _validate_intake_dispositions(store, expected_revision, retired_rows, cancelled_rows, *, project_task_id=None):
    """Authenticate all selected dispositions in one pass over immutable objects.

    Consumers retain only selected rows, anchors and semantic state. A semantic
    denial is delayed until every object and the final head are authenticated;
    the existing cache remembers only complete lineage, never authority.
    Returned retired entries are detached; cancellations grant no capability.
    """
    if (type(store) is not GitDocumentStore or not isinstance(retired_rows, dict)
            or not isinstance(cancelled_rows, dict)):
        raise ValueError('actual original native intake channel and rows required')
    from immutable_history_cache import _cache, _HistoryCache
    revision, document, chain, context, prior = _history_snapshot(store)
    del prior
    folds = []; failures = []; results = {}
    structural_rows = _DispositionRowValidation()
    projected = [] if project_task_id is not None else None
    projection_bytes = len(_HistoryCache._encode({'chain':chain, 'documents':[]}))
    if projection_bytes > _PREPARATION_PROJECTION_MAX_BYTES:projected = None

    def add(key, fold):
        try:
            next(fold)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            failures.append(error.with_traceback(None))
            fold.close()
        else:
            folds.append((key, fold))

    add('retired', _prelaunch_dispositions_fold(
        store, expected_revision, retired_rows, revision, document))
    # The selected entry's original row is joined to its authenticated anchor
    # by the prelaunch consumer; no separate original-document read is needed.
    for task_id, row in retired_rows.items():
        try:
            entry = _validate_prelaunch_disposition_row(row)
            if entry['schema'] == POSTLAUNCH_SCHEMA:
                add(('postlaunch', task_id), _postlaunch_history_fold(
                    task_id, entry['trusted_contract'], entry['original_row'], retired=True))
            elif entry['schema'] in {PREHANDLE_SCHEMA, LEGACY_PREHANDLE_SCHEMA}:
                add(('prehandle', task_id), _prehandle_history_fold(
                    task_id, entry['trusted_contract'], entry['original_row'], retired=True,
                    row_validator=structural_rows.check))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            failures.append(error.with_traceback(None))
    for task_id, row in cancelled_rows.items():
        try:
            if _row(document, task_id) != row:
                raise ValueError('queued cancellation row substituted')
            entry = validate_queued_cancellation(row)
            if entry['schema'] == RESERVED_SCHEMA:
                add(('reserved', task_id), _prehandle_history_fold(
                    task_id, entry['trusted_contract'], entry['original_row'], retired=True,
                    row_validator=structural_rows.check))
            else:
                add(('queued', task_id), _queued_history_fold(
                    task_id, entry['original_revision'], entry['original_row'], cancelled=True))
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            failures.append(error.with_traceback(None))

    # Selected dictionaries do not retain their parent document. Release the
    # fresh full head before decoding history; read it afresh at its generation.
    document = None
    try:
        revisions = [parts[0] for parts in chain[:-1]]
        decoded = iter(store._read_document_objects(revisions)) if revisions else iter(())
        for parts in chain:
            if parts[0] == revision:
                actual, historical = store.read()
                if actual != revision:raise ValueError('native history moved during authentication')
            else:historical = next(decoded)
            try:_assert_intake_disposition_replay_absent(historical, structural_rows.check)
            except (ValueError,TypeError,KeyError,AttributeError) as error:failures.append(error.with_traceback(None))
            for key, fold in folds:
                if fold.gi_frame is None:continue
                try:fold.send((parts[0], historical))
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    # Malformed selected semantic data cannot truncate object
                    # authentication, even if it fails outside a fold's guard.
                    if key == 'retired':failures.insert(0, error.with_traceback(None))
                    else:failures.append(error.with_traceback(None))
                    fold.close()
            if projected is not None:
                rows = historical.get('tasks', {})
                if not isinstance(rows, dict):
                    projected = None
                else:
                    selected = {'tasks':{project_task_id:rows[project_task_id]} if project_task_id in rows else {}}
                    item = (parts[0], selected)
                    projection_bytes += len(_HistoryCache._encode(item)) + 1
                    if projection_bytes > _PREPARATION_PROJECTION_MAX_BYTES:
                        projected = None  # Data-only optimization; original consumer can walk afresh.
                    else:
                        projected.append(copy.deepcopy(item))
            rows = selected = item = None
            historical = None
        del decoded
        if store.read()[0] != revision:
            raise ValueError('native history moved during authentication')
        _cache.put(context, {'chain': chain, 'documents': []})
        for key, fold in folds:
            if fold.gi_frame is None:continue
            try:
                fold.send(None)
            except StopIteration as done:
                results[key] = done.value
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                if key == 'retired':failures.insert(0, error.with_traceback(None))
                else:failures.append(error.with_traceback(None))
        try:structural_rows.revalidate()
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            failures.append(error.with_traceback(None))
        final_revision, final_document = store.read()
        if final_revision != revision or final_revision != expected_revision:
            raise ValueError('native disposition head moved during validation')
        for task_id, row in cancelled_rows.items():
            if _row(final_document, task_id) != row:
                raise ValueError('queued cancellation row substituted')
        if failures:raise failures[0]
        projection = None if projected is None else {
            'task_id':project_task_id, 'revision':revision, 'chain':chain, 'documents':projected}
        return results['retired'], projection
    finally:
        for _, fold in folds:fold.close()


def validate_prelaunch_dispositions(store, expected_revision, rows):
    """Return detached selected entries after complete native authentication."""
    return validate_intake_dispositions(store, expected_revision, rows, {})


def validate_prelaunch_disposition(store_or_row,task_id=None,row=None):
    """Original single-row API; structural form never grants native authority."""
    if task_id is None:return _validate_prelaunch_disposition_row(store_or_row)
    store=store_or_row
    if type(store) is not GitDocumentStore:raise ValueError('actual original native intake channel required')
    revision,document=store.read()
    if revision is None:raise ValueError('original native history missing')
    try:current=_row(document,task_id)
    except (ValueError,TypeError,KeyError,AttributeError):current=None
    # Let the shared walk retain authenticated lineage before semantic denial.
    return validate_prelaunch_dispositions(store,revision,{task_id:current if row is None else row})[task_id]


def assert_new_intake_allowed(store,task):
    if type(store) is not GitDocumentStore:raise ValueError('native intake admission store required')
    revision,document=store.read()
    retired={task_id:row for task_id,row in document['tasks'].items() if row.get('state')=='retired_unknown'}
    cancelled={task_id:row for task_id,row in document['tasks'].items() if ((row.get('result') or {}).get('unstarted_cancellation') or {}).get('schema')==RESERVED_SCHEMA}
    if retired or cancelled:validate_intake_dispositions(store,revision,retired,cancelled)
    for task_id,row in document['tasks'].items():
        if row.get('state')=='retired_unknown' or task_id in cancelled:
            if semantic_intake_contract({'task':task})==semantic_intake_contract(row):raise ValueError('retired original task contract replay prohibited')
    return True


POSTLAUNCH_SCHEMA = 'postlaunch-intake-disposition/v1'
QUEUED_SCHEMA = 'unstarted-intake-cancellation/v1'


def _protected_json(path, digest, *, uid, gid, mode):
    """Read pinned bytes without following links; custody is part of evidence."""
    path = Path(path)
    op._digest(digest, 'protected evidence digest')
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('absolute protected evidence without symlinks required')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)) != (uid, gid, mode)):
                raise ValueError('protected evidence ownership/mode/link mismatch')
            data = stream.read(4 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        def stable(info):
            return tuple(getattr(info, name) for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
        if stable(before) != stable(after) or stable(path.stat()) != stable(after) or len(data) > 4 * 1024 * 1024:
            raise ValueError('protected evidence changed during read')
        if 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('protected evidence bytes substituted')
        from git_document_store import unique_object
        return json.loads(data, object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('protected evidence unavailable') from error


def _recorded_births(value):
    found = []
    def walk(item):
        if isinstance(item, dict):
            if {'pid', 'birth', 'boot_id'} <= item.keys():
                identity = {k: item[k] for k in ('pid', 'birth', 'boot_id')}
                if identity not in found: found.append(identity)
            for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
    walk(value)
    return found


def _postlaunch_physical(row, pins, session, request, receipt, lease_revision, lease, historical_births):
    physical = pins['physical']
    op._object(physical, {'path', 'sha256', 'controller_root', 'controller_uid', 'controller_gid', 'worker_uid'}, 'protected physical pin')
    for name in ('controller_uid', 'controller_gid', 'worker_uid'):
        if type(physical[name]) is not int or physical[name] <= 0:
            raise ValueError('configured physical custody IDs required')
    path = Path(physical['path'])
    if path.parent != Path(physical['controller_root']) / row['task']['id']:
        raise ValueError('physical evidence must be in original task controller directory')
    evidence = _protected_json(path, physical['sha256'], uid=0, gid=physical['controller_gid'], mode=0o640)
    fields = {'schema', 'task_id', 'attempt_id', 'handle_id', 'start_request_digest',
              'runtime_request_digest', 'boot_id', 'observed_at_utc', 'owner_decision_reference',
              'lease_revision', 'lease_digest', 'owner_id', 'generation', 'invocation_id',
              'known_births', 'producer_scope', 'pending_shared_commands', 'service_stopped', 'projects_paused'}
    op._object(evidence, fields, 'current root physical evidence')
    expected = {'schema': 'native-postlaunch-physical/v1', 'task_id': row['task']['id'],
        'attempt_id': row['operation']['attempt_id'], 'handle_id': session['handle_id'],
        'start_request_digest': _contract(row), 'runtime_request_digest': native_digest(request),
        'boot_id': _boot(), 'owner_decision_reference': pins['owner_decision_reference'],
        'lease_revision': lease_revision, 'lease_digest': op._hash(lease),
        'owner_id': lease['owner_id'], 'generation': lease['generation'],
        'invocation_id': lease['invocation']['invocation_id'],
        'pending_shared_commands': False, 'service_stopped': True, 'projects_paused': True}
    if any(evidence[k] != v for k, v in expected.items()):
        raise ValueError('physical original task/handle/request/lease/closure mismatch')
    age = (datetime.now(timezone.utc) - op._timestamp(evidence['observed_at_utc'], 'physical observation')).total_seconds()
    if not 0 <= age <= 1800: raise ValueError('stale or future physical evidence')
    # Include every immutable recorded controller/guardian and native worker birth.
    known = copy.deepcopy(historical_births)
    for process in receipt['process_births']:
        identity = {'pid': process['pid'], 'birth': process['birth'], 'boot_id': receipt['boot_id']}
        if identity not in known: known.append(identity)
    supervisor = {'pid': receipt['supervisor_proc_pid'], 'birth': receipt['supervisor_birth'], 'boot_id': receipt['boot_id']}
    if supervisor not in known: known.append(supervisor)
    if not known or sorted(evidence['known_births'], key=op._hash) != sorted(known, key=op._hash):
        raise ValueError('complete original known births required')
    scope = evidence['producer_scope']
    op._object(scope, {'worker_uid', 'cwd', 'pid_namespace', 'cgroups', 'all_worker_uid_processes_checked',
                      'cwd_namespace_processes_checked', 'cgroups_checked', 'matching_producers'}, 'root producer exclusion scope')
    if (scope['worker_uid'] != physical['worker_uid'] or scope['cwd'] != request['cwd']
            or not isinstance(scope['pid_namespace'], str) or not scope['pid_namespace']
            or not isinstance(scope['cgroups'], list) or not scope['cgroups']
            or any(not isinstance(c, str) or not c.startswith('/') for c in scope['cgroups'])
            or any(scope[k] is not True for k in ('all_worker_uid_processes_checked', 'cwd_namespace_processes_checked', 'cgroups_checked'))
            or scope['matching_producers'] != []):
        raise ValueError('living or unexcluded detached producer')
    for identity in known: _identity(identity, absent=True)
    return evidence


def _authenticated_walk(store):
    """Authenticate full immutable documents with one generation in memory."""
    from immutable_history_cache import _cache
    head, current, chain, context, prior = _history_snapshot(store)
    del prior
    revisions = [parts[0] for parts in chain[:-1]]
    decoded = iter(store._read_document_objects(revisions)) if revisions else iter(())
    for parts in chain:
        document = current if parts[0] == head else next(decoded)
        yield parts[0], document
        document = None
    if store.read()[0] != head: raise ValueError('native history moved during authentication')
    _cache.put(context, {'chain': chain, 'documents': []})


def _postlaunch_history(store, task_id, pins, *, retired=False):
    original = _row(store.read_revision(pins['original_revision']), task_id)
    return _run_history_fold(store, _postlaunch_history_fold(task_id, pins, original, retired=retired))


def _postlaunch_history_fold(task_id, pins, original, *, retired=False):
    if (original['state'] not in {'running', 'unknown'} or not _consumed(original)
            or not original['operation'].get('handle_id') or op._hash(original) != pins['row_digest']):
        raise ValueError('exact consumed original postlaunch row required')
    import budget
    budget.validate_ledger(original['budget'])
    anchored = False; failure = None; current = None; head = None; prior_row = None; births = []; tombstone_revision = None
    while True:
        document = item = None
        item = yield
        if item is None:break
        revision, document = item
        head = revision; current = document.get('tasks', {}).get(task_id)
        if current is not None and not anchored and failure is None:
            try:
                if current['task'] != original['task']: raise ValueError('original immutable task contract changed')
                budget.validate_ledger(current['budget'])
                if prior_row is not None:
                    if current['budget']['events'][:len(prior_row['budget']['events'])] != prior_row['budget']['events']:
                        raise ValueError('original consumed budget ancestry erased')
                    for key in set(prior_row['budget']) - {'events', 'wake_ids'}:
                        if current['budget'].get(key) != prior_row['budget'][key]:
                            raise ValueError('original budget policy or identity ancestry changed')
                    previous_wakes = prior_row['budget']['wake_ids']
                    if current['budget']['wake_ids'][:len(previous_wakes)] != previous_wakes:
                        raise ValueError('original budget wake ancestry erased')
                    prior_op = prior_row.get('operation') or {}; current_op = current.get('operation') or {}
                    for key in ('start_request', 'start_request_digest', 'attempt_id', 'executor', 'start_consumption', 'handle_id'):
                        if prior_op.get(key) is not None and prior_op[key] != current_op.get(key):
                            raise ValueError('original immutable admission/handle/consumption ancestry changed')
                    prior_controllers = prior_op.get('controllers', [])
                    if current_op.get('controllers', [])[:len(prior_controllers)] != prior_controllers:
                        raise ValueError('original recorded controller ancestry erased')
                for birth in _recorded_births(current.get('operation')):
                    if birth not in births: births.append(birth)
                prior_row = copy.deepcopy(current)
            except (ValueError, KeyError, TypeError) as error: failure = error.with_traceback(None)
        elif current is None and prior_row is not None and failure is None:
            failure = ValueError('original intake ancestry deleted')
        if revision == pins['original_revision']: anchored = True
        if anchored and failure is None:
            try:
                if current == original and tombstone_revision is None: continue
                if retired and current is not None and current.get('state') == 'retired_unknown':
                    entry = _validate_postlaunch_disposition_row(current)
                    if entry['original_row'] == original and entry['trusted_contract'] == pins:
                        if tombstone_revision is None: tombstone_revision = revision
                        continue
                raise ValueError('original consumed row or budget changed after anchor')
            except (ValueError, KeyError, TypeError) as error: failure = error.with_traceback(None)
    if failure is not None: raise failure
    if not anchored: raise ValueError('original row outside native ancestry')
    if retired and current.get('state') != 'retired_unknown': raise ValueError('durable original tombstone required')
    return head, original, births, tombstone_revision


def _verify_postlaunch_runtime_argv(start, session, request, pins):
    """Join the genuine managed-host gate to its sealed original worker argv."""
    if request['argv'] == start['argv']:
        if 'worker_gate' in pins: raise ValueError('direct original argv cannot carry unrelated gate pins')
        return
    gate = pins.get('worker_gate')
    op._object(gate, {'module_path', 'module_sha256', 'payload_sha256', 'payload_custody'}, 'original worker gate pins')
    payload = Path(session['gate_directory']) / 'worker-payload.json'
    module = Path(gate['module_path'])
    expected = [sys.executable, '-B', str(module), '--worker-gate', str(payload)]
    if request['argv'] != expected or not module.is_absolute() or module.name != 'managed_host_bridge.py' or module.parent.name != 'scripts':
        raise ValueError('original managed-host gate argv substituted')
    for path in (module, *module.parents):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('original worker gate source custody changed')
    descriptor = os.open(module, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1: raise ValueError('original worker gate source file required')
        raw = os.read(descriptor, 1024*1024+1); after = os.fstat(descriptor)
        if len(raw)>1024*1024 or (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('original worker gate source changed')
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=gate['module_sha256']: raise ValueError('original worker gate source pin changed')
    finally: os.close(descriptor)
    custody=gate['payload_custody']
    op._object(custody, {'uid','gid','mode'}, 'original worker gate payload custody')
    if custody != {'uid':pins['physical']['controller_uid'],'gid':pins['physical']['controller_gid'],'mode':0o600}:
        raise ValueError('original worker gate payload principal changed')
    actual=_protected_json(payload,gate['payload_sha256'],**custody)
    expected_payload={'schema':'managed-host-worker-gate/v1','handle_id':session['handle_id'],
        'argv':start['argv'],'go_path':str(Path(session['gate_directory'])/'go.json'),
        'abort_path':str(Path(session['gate_directory'])/'abort.json')}
    if actual!=expected_payload: raise ValueError('original worker gate payload substituted')


def _authenticate_postlaunch(store, task_id, source, pins, *, retired=False):
    if type(store) is not GitDocumentStore or type(source) is not GitLeaseStore:
        raise ValueError('actual original typed native channels required')
    op._object(pins, {'original_revision', 'row_digest', 'source_revision', 'source_digest', 'channels',
                     'session_sha256', 'request_sha256', 'receipt_sha256', 'artifact_custody', 'physical', 'owner_decision_reference'} | ({'worker_gate'} if 'worker_gate' in pins else set()), 'postlaunch trusted contract')
    op._text(pins['owner_decision_reference'], 'owner decision reference')
    revision, row, historical_births, tombstone_revision = _postlaunch_history(store, task_id, pins, retired=retired)
    _intake_channels(store, row, pins, source)
    start = row['operation']['start_request']; handle = row['operation']['handle_id']
    from managed_host_bridge import _validate_session, _session_context, _canonical, _validate_start
    from git_remote_identity import repository_root
    _validate_start(start)
    intent = row['operation']['intent']
    op.validate_intent(intent)
    if (intent['attempt_id'] != start['attempt_id'] or intent['source_ref'] != start['lease_source_ref']
            or intent['binding']['candidate_sha'] != start['plan']['base_sha']
            or row['task']['source_sha'] != start['plan']['base_sha']):
        raise ValueError('original native intent/source/attempt binding changed')
    reserves = [event for event in row['budget']['events'] if event['type'] == 'reserve' and event['kind'] == 'compute_start']
    if (len(reserves) != 1 or reserves[0]['attempt_id'] != start['attempt_id']
            or reserves[0]['operation_key'] != intent['operation_key']):
        raise ValueError('original one-shot consumed compute reservation missing')
    physical = pins['physical']
    op._object(pins['artifact_custody'], {'session', 'request', 'receipt'}, 'original artifact custody')
    for label, custody in pins['artifact_custody'].items():
        op._object(custody, {'uid', 'gid', 'mode'}, 'original native file custody')
        if (type(custody['uid']) is not int or type(custody['gid']) is not int
                or custody['uid'] not in {physical['controller_uid'], physical['worker_uid']}
                or custody['gid'] < 0 or custody['mode'] not in {0o600, 0o640, 0o644}
                or label == 'session' and custody['uid'] != physical['controller_uid']):
            raise ValueError('original native artifact custody substituted')
    session_path = Path(start['handle_root']) / (handle + '.json')
    session = _validate_session(_protected_json(session_path, pins['session_sha256'], **pins['artifact_custody']['session']))
    identity = {'repo_root': str(repository_root(start['repo_root'])), 'store': start['plan']['coordination_store_id'],
                'coordination_ref': start['plan']['coordination_ref'], 'pool_id': start['plan']['pool_id'],
                'task_id': task_id, 'attempt_id': start['attempt_id']}
    if handle != str(uuid.uuid5(uuid.NAMESPACE_URL, _canonical(identity))): raise ValueError('original derived handle mismatch')
    context = {k: start[k] for k in ('repo_root', 'remote', 'plan', 'journal_root', 'handle_root',
        'lease_coordination_ref', 'lease_repository', 'lease_source_ref', 'task_id', 'attempt_id', 'reservation_token', 'owner_id')}
    context.update(handle_id=handle, argv_digest=native_digest(start['argv']),
        publication_ref='refs/heads/cdc/managed-host-publish-' + handle.replace('-', ''),
        gate_directory=str(Path(start['handle_root']) / 'gates' / handle))
    if 'coordination_remote' in start:
        context.update(coordination_remote=start['coordination_remote'], source_remote_id=start['source_remote_id'])
    if _session_context(session) != context: raise ValueError('original session/start immutable context substituted')
    directory = Path(start['journal_root']) / native_digest({k: identity[k] for k in ('pool_id', 'task_id', 'attempt_id')}).split(':')[1]
    request = _protected_json(directory / 'request.json', pins['request_sha256'], **pins['artifact_custody']['request'])
    receipt = _protected_json(directory / 'receipt.json', pins['receipt_sha256'], **pins['artifact_custody']['receipt'])
    from managed_executor_store import GitManagedExecutorStore
    import managed_executor_pool as pool
    from managed_executor_runtime import ManagedExecutorRuntime
    pool_store = GitManagedExecutorStore(start['repo_root'], start.get('coordination_remote', start['remote']),
        start['plan']['coordination_ref'], start['plan'])
    # Construct no backend or journal: authentication cannot create directories or observe/send effects.
    runtime = object.__new__(ManagedExecutorRuntime); runtime.plan = start['plan']
    expected_identity = runtime._identity(task_id, start['attempt_id'])
    if (request.get('schema') != 'managed-executor-start/v1' or request['identity'] != expected_identity
            or request['repo_root'] != str(repository_root(start['repo_root']))
            or request['journal_directory'] != str(directory)):
        raise ValueError('original runtime request substituted')
    _verify_postlaunch_runtime_argv(start, session, request, pins)
    task = next(t for t in start['plan']['tasks'] if t['id'] == task_id)
    if (row['operation']['executor'] != task['executor_id'] or row['operation']['attempt_id'] != start['attempt_id']
            or task['id'] != row['task']['id']): raise ValueError('original intake/pool executor/attempt binding changed')
    cwd = str((Path(start['repo_root']).parent / task['worktree']).resolve()) if task['role'] == 'writer' else str(directory / 'worktree')
    if request['cwd'] != cwd: raise ValueError('original runtime cwd substituted')
    claim = request['claim']; claim_revision = claim['store_revision']
    pool_head, state = pool_store.read()
    if pool_store._git('rev-parse', '--is-shallow-repository') != 'false': raise ValueError('complete pool history required')
    from immutable_history_cache import _linear_chain
    chain = _linear_chain(reversed(pool_store._git('rev-list', '--parents', pool_head).splitlines()))
    if len(chain) > 10000: raise ValueError('pool history exceeds authentication bound')
    states = {parts[0]: pool_store.read_revision(parts[0]) for parts in chain}
    claimed = states.get(claim_revision)
    parts = next((parts for parts in chain if parts[0] == claim_revision), [])
    if len(parts) != 2 or claimed is None: raise ValueError('original launch claim ancestry missing')
    before = states[parts[1]]
    expected_state = pool.mark_running(start['plan'], before, task_id, start['attempt_id'],
        expected_revision=before['revision'], reservation_token=start['reservation_token'])
    expected_claim = dict(schema='managed-executor-launch-claim/v1', store_revision=claim_revision,
        state_revision=claimed['revision'], state_ref=pool.canonical_state_ref(claimed), task_id=task_id,
        attempt_id=start['attempt_id'], reservation_token=start['reservation_token'], launch_allowed=True,
        **{name: False for name in pool.AUTHORITY_FIELDS})
    if claimed != expected_state or claim != expected_claim: raise ValueError('original consumed pool allocation/claim substituted')
    allocation = next(t for t in claimed['tasks'] if t['id'] == task_id)
    op._object(request, {'schema','identity','claim','argv','repo_root','cwd','timeout_seconds','journal_directory'}, 'original native runtime request')
    if request['timeout_seconds'] != task['max_runtime_seconds'] - allocation['runtime_seconds']:
        raise ValueError('original consumed runtime budget changed')
    seen = False
    for parts in chain:
        if parts[0] == claim_revision: seen = True
        if seen and next(t for t in states[parts[0]]['tasks'] if t['id'] == task_id) != allocation:
            raise ValueError('original pool allocation changed or rearmed')
    if pool_store.read() != (pool_head, state): raise ValueError('pool history moved')
    if (session.get('runtime_launch_id') != native_digest(request) or receipt.get('request_ref') != native_digest(request)
            or receipt.get('launch_id') != native_digest(request) or receipt.get('identity') != expected_identity
            or receipt.get('claim') != claim or receipt.get('quiescent') is not False):
        raise ValueError('original nonterminal runtime/session receipt mismatch')
    lease_revision, lease = source.read()
    if (lease_revision != pins['source_revision'] or op._hash(lease) != pins['source_digest']
            or source.read_revision(lease_revision) != lease or lease['schema'] != 'execution-lease/v2'
            or lease['owner_id'] != session['owner_id'] or lease['owner_id'] != start['owner_id']
            or lease['generation'] != session['generation'] or lease['invocation']['invocation_id'] != session['invocation_id']
            or session['lease_revision'] != lease_revision or lease['external_guard'] is not None
            or lease['finalization']['pending_shared_writes'] is not False
            or (lease['repository'], lease['source_ref']) != (start['lease_repository'], start['lease_source_ref'])):
        raise ValueError('original held lease/guard binding changed')
    _postlaunch_physical(row, pins, session, request, receipt, lease_revision, lease, historical_births)
    if source.read() != (lease_revision, lease) or store.read()[0] != revision:
        raise ValueError('postlaunch volatile head changed')
    return revision, row, lease, tombstone_revision


class PostlaunchIntakeDispositionProof:
    def __init__(self, seal, store, task_id, source, pins, at, *, retired=False):
        if seal is not _SEAL: raise ValueError('native issued postlaunch proof required')
        self._seal = seal; self._store = store; self._task = task_id; self._source = source
        self._pins = copy.deepcopy(pins); self._at = at; self._retired = retired
        self._revision, self._row, self._lease, self._tombstone_revision = _authenticate_postlaunch(store, task_id, source, pins, retired=retired)
        self._binding = op._hash([self._pins, at, retired, self._revision, self._row, self._lease, self._tombstone_revision])
    def revalidate_for(self, store, task_id):
        if (self._seal is not _SEAL or store is not self._store or task_id != self._task
                or self._binding != op._hash([self._pins, self._at, self._retired, self._revision, self._row, self._lease, self._tombstone_revision])):
            raise ValueError('postlaunch native capability substituted or mutated')
        revision, row, lease, tombstone_revision = _authenticate_postlaunch(store, task_id, self._source, self._pins, retired=self._retired)
        if revision != self._revision or row != self._row or lease != self._lease or tombstone_revision != self._tombstone_revision:
            raise ValueError('postlaunch capability head changed; observe without replay')
        return row


def authenticate_postlaunch_intake(store, task_id, *, source_store, trusted_contract, at):
    op._timestamp(at, 'postlaunch disposition time')
    return PostlaunchIntakeDispositionProof(_SEAL, store, task_id, source_store, trusted_contract, at)


def _validate_postlaunch_disposition_row(row):
    entry = (row.get('result') or {}).get('administrative_disposition')
    op._object(entry, {'schema', 'task_id', 'contract_digest', 'original_effect', 'actual_wait', 'replay_forbidden',
        'original_revision', 'original_row', 'trusted_contract', 'retired_at_utc'}, 'postlaunch disposition')
    original = entry['original_row']
    expected = copy.deepcopy(original); expected.update(state='retired_unknown', result={'administrative_disposition': entry})
    if (row != expected or entry['schema'] != POSTLAUNCH_SCHEMA or entry['task_id'] != row['task']['id']
            or entry['original_effect'] != 'UNKNOWN' or entry['actual_wait'] is not None or entry['replay_forbidden'] is not True
            or original['state'] not in {'running', 'unknown'} or not original['operation'].get('handle_id')
            or entry['contract_digest'] != _contract(original) or entry['original_revision'] != entry['trusted_contract']['original_revision']
            or op._hash(original) != entry['trusted_contract']['row_digest']):
        raise ValueError('postlaunch tombstone must preserve exact original consumed UNKNOWN liabilities')
    op._timestamp(entry['retired_at_utc'], 'postlaunch disposition time')
    return entry


def retire_postlaunch_intake_cas(store, expected_revision, task_id, proof, *, at):
    if type(proof) is not PostlaunchIntakeDispositionProof or proof._retired or at != proof._at:
        raise ValueError('native issued original postlaunch capability required')
    row = proof.revalidate_for(store, task_id)
    revision, document = store.read()
    if revision != expected_revision or revision != proof._revision: raise ValueError('stale postlaunch intake head')
    changed = copy.deepcopy(document)
    entry = dict(schema=POSTLAUNCH_SCHEMA, task_id=task_id, contract_digest=_contract(row), original_effect='UNKNOWN',
        actual_wait=None, replay_forbidden=True, original_revision=proof._pins['original_revision'],
        original_row=copy.deepcopy(row), trusted_contract=copy.deepcopy(proof._pins), retired_at_utc=at)
    changed['tasks'][task_id].update(state='retired_unknown', result={'administrative_disposition': entry})
    new_revision = store.compare_and_swap(expected_revision, changed, recovery_capability=proof)
    if store.read() != (new_revision, changed): raise ValueError('postlaunch reply moved; observe without replay')
    return {'revision': new_revision, 'row': changed['tasks'][task_id]}


def observe_postlaunch_intake_disposition(store, task_id, *, source_store, trusted_contract, at):
    """Read-only lost-reply/crash observation; grants only the remaining lease phase."""
    op._timestamp(at, 'administrative release time')
    return PostlaunchIntakeDispositionProof(_SEAL, store, task_id, source_store, trusted_contract, at, retired=True)


def _administrative_release(record, entry, reference, at):
    import execution_lease_v2 as lease_api
    lease_api.validate(record)
    if (record['owner_id'] is None or record['external_guard'] is not None
            or record['finalization']['pending_shared_writes'] is not False):
        raise ValueError('administrative release requires exact unguarded held owner')
    result = copy.deepcopy(record)
    result['last_release'] = dict(owner_id=record['owner_id'], generation=record['generation'],
        invocation_id=record['invocation']['invocation_id'], at_utc=at, checkpoint_ref=record['finalization']['checkpoint_ref'],
        external_reconciliation='unknown_preserved', completion_reason='administrative_unknown_retired',
        administrative_disposition={'schema': POSTLAUNCH_SCHEMA, 'reference': reference, 'digest': op._hash(entry),
                                    'original_effect': 'UNKNOWN', 'actual_wait': None, 'replay_forbidden': True})
    result.update(owner_id=None, acquired_at_utc=None, heartbeat_at_utc=None, expires_at_utc=None, invocation=None, finalization=None)
    return lease_api.validate(result)


class AdministrativeUnknownLeaseRelease:
    def __init__(self, seal, proof):
        if seal is not _SEAL or type(proof) is not PostlaunchIntakeDispositionProof or not proof._retired:
            raise ValueError('native durable postlaunch disposition required')
        self._seal = seal; self._proof = proof
    def revalidate(self, store, revision, previous, proposed):
        proof = self._proof
        if self._seal is not _SEAL or store is not proof._source or revision != proof._pins['source_revision']:
            raise ValueError('administrative lease endpoint/revision substituted')
        proof.revalidate_for(proof._store, proof._task)
        if previous != proof._lease: raise ValueError('administrative lease original changed')
        _, document = proof._store.read()
        entry = _validate_postlaunch_disposition_row(_row(document, proof._task))
        reference = proof._store.store_id + ':' + proof._store.ref + '@' + proof._tombstone_revision + '#' + proof._task
        if proposed != _administrative_release(previous, entry, reference, proof._at):
            raise ValueError('administrative lease release contains unrelated mutation')


def release_postlaunch_unknown_lease_cas(source_store, expected_revision, proof):
    if type(proof) is not PostlaunchIntakeDispositionProof or not proof._retired:
        raise ValueError('observed durable native postlaunch tombstone required')
    proof.revalidate_for(proof._store, proof._task)
    revision, record = source_store.read()
    if source_store is not proof._source or revision != expected_revision or revision != proof._pins['source_revision']:
        raise ValueError('stale original administrative lease release')
    _, document = proof._store.read()
    entry = _validate_postlaunch_disposition_row(_row(document, proof._task))
    reference = proof._store.store_id + ':' + proof._store.ref + '@' + proof._tombstone_revision + '#' + proof._task
    changed = _administrative_release(record, entry, reference, proof._at)
    new_revision = source_store.compare_and_swap(expected_revision, changed,
        retirement_capability=AdministrativeUnknownLeaseRelease(_SEAL, proof))
    if source_store.read() != (new_revision, changed): raise ValueError('administrative lease reply moved; observe without replay')
    return {'revision': new_revision, 'record': changed}


def _queued_original(row):
    import budget
    budget.validate_ledger(row['budget'])
    if row['state'] != 'queued' or row['operation'] is not None or row['result'] is not None or row['budget']['events']:
        raise ValueError('only original unstarted zero-charge queued row may be cancelled')


def validate_queued_cancellation(row):
    entry = (row.get('result') or {}).get('unstarted_cancellation')
    if isinstance(entry,dict) and entry.get('schema')==RESERVED_SCHEMA:return _validate_prehandle_disposition_row(row)
    op._object(entry, {'schema', 'task_id', 'original_revision', 'original_row', 'original_row_digest',
                      'reason', 'owner_decision_reference', 'at_utc', 'no_send'}, 'unstarted cancellation')
    original = entry['original_row']; _queued_original(original)
    expected = copy.deepcopy(original); expected.update(state='cancelled', result={'unstarted_cancellation': entry})
    if (row != expected or entry['schema'] != QUEUED_SCHEMA or entry['task_id'] != row['task']['id']
            or entry['original_row_digest'] != op._hash(original) or entry['no_send'] is not True
            or entry['reason'] not in {'cancelled', 'superseded'}):
        raise ValueError('typed cancellation cannot change original row/budget or invent operation')
    op._text(entry['owner_decision_reference'], 'queued owner decision'); op._timestamp(entry['at_utc'], 'queued cancellation time')
    return entry


def _run_history_fold(store, fold):
    next(fold)
    try:
        for item in _authenticated_walk(store):
            fold.send(item)
        try:fold.send(None)
        except StopIteration as done:return done.value
    finally:fold.close()


def _authenticate_queued(store, task_id, revision, original, *, cancelled=False):
    if type(store) is not GitDocumentStore: raise ValueError('actual native intake store required')
    return _run_history_fold(store, _queued_history_fold(task_id, revision, original, cancelled=cancelled))


def _queued_history_fold(task_id, revision, original, *, cancelled=False):
    _queued_original(original)
    anchored = False; seen = False; failure = None; head = None; tombstone = None
    while True:
        document = item = row = None
        item = yield
        if item is None:break
        sha, document = item
        head = sha
        if failure is not None: continue
        try:
            row = document.get('tasks', {}).get(task_id)
            if sha == revision:
                if row != original: raise ValueError('queued original ancestry substituted')
                anchored = True
            if row is None:
                if seen: raise ValueError('queued original history deleted')
                continue
            seen = True
            if row == original and tombstone is None: continue
            if cancelled and anchored and row.get('state') == 'cancelled':
                entry = validate_queued_cancellation(row)
                if (entry['original_row'] == original and entry['original_revision'] == revision
                        and (tombstone is None or tombstone == row)):
                    tombstone = copy.deepcopy(row); continue
            raise ValueError('queued history consumed, changed or rearmed')
        except (ValueError, KeyError, TypeError) as error: failure = error.with_traceback(None)
    if failure is not None: raise failure
    if not anchored: raise ValueError('queued original ancestry missing')
    if cancelled and tombstone is None: raise ValueError('durable queued cancellation missing')
    return head


class UnstartedQueuedCancellation:
    def __init__(self, seal, store, revision, task_id, row, entry):
        if seal is not _SEAL: raise ValueError('native queued cancellation required')
        self._seal = seal; self._store = store; self._revision = revision; self._task = task_id
        self._row = copy.deepcopy(row); self._entry = copy.deepcopy(entry)
        self._binding = op._hash([revision, task_id, row, entry])
    def revalidate(self, store, revision, task_id, proposed):
        if (self._seal is not _SEAL or store is not self._store or revision != self._revision or task_id != self._task
                or self._binding != op._hash([self._revision, self._task, self._row, self._entry])
                or validate_queued_cancellation(proposed) != self._entry
                or _authenticate_queued(store, task_id, revision, self._row) != revision):
            raise ValueError('native queued cancellation binding changed')


def cancel_unstarted_queued_cas(store, expected_revision, task_id, *, original_row_digest, reason, owner_decision_reference, at):
    revision, document = store.read(); row = _row(document, task_id)
    if revision != expected_revision or op._hash(row) != original_row_digest: raise ValueError('stale queued cancellation binding')
    _authenticate_queued(store, task_id, revision, row)
    entry = dict(schema=QUEUED_SCHEMA, task_id=task_id, original_revision=revision, original_row=copy.deepcopy(row),
        original_row_digest=original_row_digest, reason=reason, owner_decision_reference=owner_decision_reference, at_utc=at, no_send=True)
    changed = copy.deepcopy(document); changed['tasks'][task_id].update(state='cancelled', result={'unstarted_cancellation': entry})
    validate_queued_cancellation(changed['tasks'][task_id])
    proof = UnstartedQueuedCancellation(_SEAL, store, revision, task_id, row, entry)
    new_revision = store.compare_and_swap(revision, changed, recovery_capability=proof)
    if store.read() != (new_revision, changed): raise ValueError('queued cancellation reply moved; observe without replay')
    return {'revision': new_revision, 'row': changed['tasks'][task_id]}


def validate_queued_cancellations(store, expected_revision, rows):
    if any(((row.get('result') or {}).get('unstarted_cancellation') or {}).get('schema')==RESERVED_SCHEMA for row in rows.values()):
        validate_intake_dispositions(store,expected_revision,{},rows)
        return True
    for task_id, row in rows.items():
        entry = validate_queued_cancellation(row)
        if _authenticate_queued(store, task_id, entry['original_revision'], entry['original_row'], cancelled=True) != expected_revision:
            raise ValueError('queued cancellation head moved')
        if _row(store.read()[1], task_id) != row: raise ValueError('queued cancellation row substituted')
    if store.read()[0] != expected_revision: raise ValueError('queued cancellation head moved')
    return True


def observe_postlaunch_unknown_lease_release(store, task_id, *, source_store, trusted_contract):
    """Observe the exact completed lease phase after an uncertain reply; never CAS."""
    if type(store) is not GitDocumentStore or type(source_store) is not GitLeaseStore:
        raise ValueError('actual native observation channels required')
    head, original, _, tombstone = _postlaunch_history(store, task_id, trusted_contract, retired=True)
    _intake_channels(store, original, trusted_contract, source_store)
    entry = validate_prelaunch_disposition(_row(store.read()[1], task_id))
    original_lease = source_store.read_revision(trusted_contract['source_revision'])
    if op._hash(original_lease) != trusted_contract['source_digest']: raise ValueError('original lease observation substituted')
    reference = store.store_id + ':' + store.ref + '@' + tombstone + '#' + task_id
    found = None
    for revision, record in _history(source_store):
        release = record.get('last_release')
        if isinstance(release, dict) and release.get('administrative_disposition', {}).get('reference') == reference:
            expected = _administrative_release(original_lease, entry, reference, release['at_utc'])
            if release != expected['last_release']: raise ValueError('administrative lease receipt substituted')
            if found is None:
                if record != expected or source_store._git('rev-parse', revision + '^') != trusted_contract['source_revision']:
                    raise ValueError('administrative release ancestry or unrelated state changed')
                found = {'schema': 'postlaunch-unknown-lease-release-observation/v1', 'state': 'confirmed_original',
                    'release_revision': revision, 'release': copy.deepcopy(release), 'replay_forbidden': True}
    if store.read()[0] != head: raise ValueError('original tombstone observation head moved')
    if found is None: raise ValueError('original administrative release not confirmed; do not replay')
    return found


PREHANDLE_SCHEMA = 'consumed-prehandle-intake-disposition/v1'
LEGACY_PREHANDLE_SCHEMA = 'legacy-guardian-prehandle-intake-disposition/v1'
RESERVED_SCHEMA = 'unconsumed-reserved-intake-cancellation/v1'


def _prehandle_original(row):
    """Only the original charged reservation before any native handle exists."""
    import budget
    budget.validate_ledger(row['budget'])
    operation = row.get('operation')
    if not isinstance(operation, dict) or row.get('result') is not None:
        raise ValueError('original nonterminal reserved/consumed row required')
    from managed_host_bridge import _validate_start
    start = operation['start_request']; _validate_start(start)
    digest = _contract(row)
    intent = operation['intent']; op.validate_intent(intent)
    if (operation['attempt_id'] != start['attempt_id'] or row['task']['id'] != start['task_id']
            or row['task']['source_sha'] != start['plan']['base_sha']
            or intent['attempt_id'] != start['attempt_id'] or intent['source_ref'] != start['lease_source_ref']
            or intent['binding']['repository'] != start['lease_repository']
            or intent['binding']['candidate_sha'] != start['plan']['base_sha']
            or any(operation.get(k) is not None for k in ('handle_id','checkpoint_ref','finish_result'))):
        raise ValueError('original prehandle immutable contract required')
    task = next((t for t in start['plan']['tasks'] if t['id'] == start['task_id']), None)
    if task is None or task['executor_id'] != operation['executor']:
        raise ValueError('original prehandle pool/executor binding required')
    reserves = [e for e in row['budget']['events'] if e['type']=='reserve' and e['kind']=='compute_start']
    if (len(reserves)!=1 or reserves[0]['attempt_id']!=start['attempt_id']
            or reserves[0]['operation_key']!=intent['operation_key']):
        raise ValueError('exact original compute reservation required')
    consumption = operation.get('start_consumption')
    if consumption is not None:
        op._object(consumption, {'schema','contract_digest','controller'}, 'original start consumption')
        if (consumption['schema']!='native-intake-start-consumption/v1' or consumption['contract_digest']!=digest
                or row['state'] not in {'unknown','running','starting','start_unknown'}):
            raise ValueError('original consumed prehandle UNKNOWN required')
        return 'retired_unknown'
    if (row['state']=='unknown' and operation.get('guardian') is not None
            and operation.get('controller_identity') is None and 'controllers' not in operation):
        guardian=operation['guardian']
        op._object(guardian,{'identity','nonce'},'original legacy guardian')
        identity=guardian['identity']
        op._object(identity,{'pid','birth','boot_id'},'original legacy guardian identity')
        if (type(identity['pid']) is not int or identity['pid']<=0
                or not isinstance(identity['birth'],str) or not identity['birth'].isdigit()
                or not isinstance(identity['boot_id'],str) or not identity['boot_id']):
            raise ValueError('original legacy guardian birth identity required')
        if not isinstance(guardian['nonce'],str) or re.fullmatch('[0-9a-f]{32}',guardian['nonce']) is None:
            raise ValueError('original legacy guardian nonce required')
        return 'retired_unknown'
    if row['state']!='reserved' or _consumed(row) or operation.get('guardian') is not None:
        raise ValueError('unconsumed reserved row without guardian required')
    return 'cancelled'


def _prehandle_receipt_kind(row):
    disposition=_prehandle_original(row)
    if disposition=='cancelled':return RESERVED_SCHEMA,'owner_cancelled_unconsumed_reservation'
    if row['operation'].get('start_consumption') is None:
        return LEGACY_PREHANDLE_SCHEMA,'legacy_guardian_prehandle_unknown'
    return PREHANDLE_SCHEMA,'consumed_prehandle_start_failure'


def _legacy_prehandle_artifacts(row,physical,controller,artifacts):
    # Full ancestry and root quiescence supply the missing creator exclusion.
    # The actual protected rejection wait supplies controller birth; neither is
    # a native consumption, terminal wait, or proof that no effect was sent.
    guardian=row['operation']['guardian'];nonce=guardian['nonce']
    names={'receipt':'.receipt.json','stdout':'.stdout','stderr':'.stderr',
           'guardian_stdout':'.guardian.stdout','guardian_stderr':'.guardian.stderr'}
    paths={key:controller/(nonce+suffix) for key,suffix in names.items()}
    if any(str(path) not in artifacts for path in paths.values()):
        raise ValueError('complete original legacy rejection wait required')
    try:
        payload=paths['receipt'].read_bytes()
        if len(payload)>65536:raise ValueError('bounded original legacy wait required')
        receipt=json.loads(payload,object_pairs_hook=op._unique_object)
        identity=receipt['controller']
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('original legacy rejection wait required') from None
    pins={'guardian':guardian['identity'],'guardian_nonce':nonce,
        'custody':{'controller_uid':physical['controller_uid']},
        'preconsume_exit':dict(schema='native-preconsume-controller-exit/v1',controller=identity,
            **{key+'_sha256':artifacts[str(path)]['sha256'] for key,path in paths.items()})}
    wait=controller/(nonce+'.guardian-wait.json')
    if str(wait) in artifacts:
        pins['creator_guardian_wait']={'schema':'native-creator-guardian-wait/v1','sha256':artifacts[str(wait)]['sha256']}
    _preconsume_artifacts(row,pins,controller,{'gid':physical['controller_gid']})


def _prehandle_history_fold(task_id, pins, original, *, retired=False, row_validator=None):
    disposition = _prehandle_original(original)
    if op._hash(original)!=pins['row_digest']:
        raise ValueError('original prehandle row digest changed')
    anchored=False; seen=False; prior=None; births=[]; failure=None; head=None; tombstone=None
    import budget
    while True:
        item = yield
        if item is None: break
        revision, document = item; head=revision
        if failure is not None: continue
        try:
            row=document.get('tasks',{}).get(task_id)
            if row is None:
                if seen: raise ValueError('original prehandle row deleted')
                continue
            seen=True
            if revision==pins['original_revision']:
                if row!=original: raise ValueError('original prehandle anchor substituted')
            if anchored:
                if row==original and tombstone is None: continue
                if retired:
                    if row_validator is None:
                        entry=_validate_prehandle_disposition_row(row)
                    else:
                        row_validator(row)
                        key='administrative_disposition' if row.get('state')=='retired_unknown' else 'unstarted_cancellation'
                        entry=row['result'][key]
                    if entry['original_row']==original and entry['trusted_contract']==pins:
                        if tombstone is not None and row!=tombstone: raise ValueError('prehandle disposition changed')
                        tombstone=copy.deepcopy(row); continue
                raise ValueError('original prehandle row or budget changed after anchor')
            if row['task']!=original['task'] or row.get('result') is not None:
                raise ValueError('original prehandle task/result history changed')
            budget.validate_ledger(row['budget'])
            operation=row.get('operation')
            if operation is None:
                if row['state']!='queued' or row['budget']['events'] or prior is not None and prior.get('operation') is not None:
                    raise ValueError('original prehandle admission erased')
            else:
                if _contract(row)!=_contract(original) or any(operation.get(k) is not None for k in ('handle_id','finish_result','checkpoint_ref')):
                    raise ValueError('native session/effect ancestry blocks prehandle disposition')
                intent=operation['intent'];op.validate_intent(intent)
                canonical=original['operation']['intent']
                for key in set(canonical)-{'state','updated_at_utc','durable_intent'}:
                    if intent.get(key)!=canonical[key]:raise ValueError('original prehandle intent contract changed')
                if intent['state'] not in {'prepared','submitting','unknown'} or intent.get('task') is not None:
                    raise ValueError('original prehandle intent consumed')
                for key in ('start_request','start_request_digest','attempt_id','executor','reservation_preparation'):
                    if operation.get(key)!=original['operation'].get(key):raise ValueError('original prehandle admission contract changed')
                if disposition=='cancelled' and (_consumed(row) or operation.get('guardian') is not None):
                    raise ValueError('reserved cancellation has consumed ancestry')
                for identity in _recorded_births(operation):
                    if identity not in births:births.append(identity)
            if prior is not None:
                previous=prior['budget'];current=row['budget']
                if ({k:v for k,v in previous.items() if k not in {'events','wake_ids'}}!={k:v for k,v in current.items() if k not in {'events','wake_ids'}}
                        or current['events'][:len(previous['events'])]!=previous['events']
                        or current['wake_ids'][:len(previous['wake_ids'])]!=previous['wake_ids']):
                    raise ValueError('original prehandle budget ancestry erased')
                before=prior.get('operation') or {};after=operation or {}
                for key in ('guardian','start_consumption','controller_identity','project_budget'):
                    if before.get(key) is not None and before[key]!=after.get(key):raise ValueError('original prehandle custody ancestry erased')
                if 'controllers' in before and ('controllers' not in after or after['controllers'][:len(before['controllers'])]!=before['controllers']):
                    raise ValueError('original prehandle controller ancestry erased')
                if before.get('intent') and after.get('intent'):
                    rank={'prepared':0,'submitting':1,'unknown':2}
                    if rank[after['intent']['state']]<rank[before['intent']['state']]:raise ValueError('original prehandle intent rewound')
            prior=copy.deepcopy(row)
            if revision==pins['original_revision']:anchored=True
        except (ValueError, KeyError, TypeError, StopIteration) as error:failure=error.with_traceback(None)
    if failure is not None:raise failure
    if not anchored:raise ValueError('original prehandle anchor outside native ancestry')
    if retired and tombstone is None:raise ValueError('durable prehandle disposition missing')
    for identity in _recorded_births(original['operation']):
        if identity not in births:births.append(identity)
    return head, births


def _prehandle_native_paths(start):
    from managed_host_bridge import _canonical
    from git_remote_identity import repository_root
    identity={'repo_root':str(repository_root(start['repo_root'])),'store':start['plan']['coordination_store_id'],
        'coordination_ref':start['plan']['coordination_ref'],'pool_id':start['plan']['pool_id'],
        'task_id':start['task_id'],'attempt_id':start['attempt_id']}
    handle=str(uuid.uuid5(uuid.NAMESPACE_URL,_canonical(identity)))
    return handle, [Path(start['handle_root'])/(handle+'.json'),Path(start['handle_root'])/'gates'/handle,
        Path(start['handle_root'])/'locks'/(handle+'.lock'),Path(start['journal_root'])/native_digest(
            {k:identity[k] for k in ('pool_id','task_id','attempt_id')}).split(':',1)[1]]


def _prehandle_physical(store,row,source,pins,births):
    physical=pins['physical']
    op._object(physical, {'path','sha256','controller_root','worker_launch_root','controller_uid','controller_gid','worker_uid','worker_gid'}, 'prehandle physical custody')
    for key in ('controller_uid','controller_gid','worker_uid','worker_gid'):
        if type(physical[key]) is not int or physical[key]<=0:raise ValueError('configured original prehandle principals required')
    start=row['operation']['start_request'];task_id=row['task']['id'];executor=row['operation']['executor']
    for name in (task_id,executor):
        if not isinstance(name,str) or not name or name in {'.','..'} or '/' in name or '\\' in name:raise ValueError('exact prehandle custody identity required')
    controller=Path(physical['controller_root'])/task_id
    launch=Path(physical['worker_launch_root'])/executor/task_id
    certificate=Path(physical['path'])
    for root in (controller,launch,certificate,Path(start['handle_root']),Path(start['journal_root'])):
        if not root.is_absolute() or str(root.resolve())!=str(root) or any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('exact protected prehandle roots without symlinks required')
    if certificate==controller or controller in certificate.parents or certificate==launch or launch in certificate.parents:
        raise ValueError('physical certificate must be outside original launch artifacts')
    evidence=_protected_json(certificate,physical['sha256'],uid=0,gid=physical['controller_gid'],mode=0o640)
    expected={'schema':'native-prehandle-physical/v1','task_id':task_id,'attempt_id':start['attempt_id'],
        'start_request_digest':_contract(row),'original_revision':pins['original_revision'],'original_row_digest':pins['row_digest'],
        'intake_store_id':store.store_id,'intake_ref':store.ref,'source_store_id':source.store_id,'source_ref':source.ref,
        'source_revision':pins['source_revision'],'source_digest':pins['source_digest'],'boot_id':_boot(),
        'owner_decision_reference':pins['owner_decision_reference'],'disposition':_prehandle_original(row),
        'controller_root':str(controller),'worker_launch_root':str(launch),'native_session_absent':True,
        'worker_output_empty':True,'pending_shared_commands':False,'service_stopped':True,'socket_stopped':True,'projects_paused':True}
    op._object(evidence,set(expected)|{'observed_at_utc','known_births','producer_scope','artifact_pins'},'root prehandle physical certificate')
    if any(evidence[k]!=v for k,v in expected.items()):raise ValueError('physical prehandle task/source/closure binding changed')
    age=(datetime.now(timezone.utc)-op._timestamp(evidence['observed_at_utc'],'prehandle physical observation')).total_seconds()
    if not 0<=age<=1800:raise ValueError('stale or future prehandle physical evidence')
    if sorted(evidence['known_births'],key=op._hash)!=sorted(births,key=op._hash):raise ValueError('complete original prehandle births required')
    scope=evidence['producer_scope']
    op._object(scope,{'worker_uid','launch_root','cwd','pid_namespace','cgroups','all_worker_uid_processes_checked','cwd_namespace_processes_checked','cgroups_checked','matching_producers'},'root prehandle producer exclusion')
    if (scope['worker_uid']!=physical['worker_uid'] or scope['launch_root']!=str(launch) or scope['cwd']!=str(launch/'worktree')
            or not isinstance(scope['pid_namespace'],str) or not scope['pid_namespace'] or not isinstance(scope['cgroups'],list) or not scope['cgroups']
            or any(not isinstance(c,str) or not c.startswith('/') for c in scope['cgroups'])
            or any(scope[k] is not True for k in ('all_worker_uid_processes_checked','cwd_namespace_processes_checked','cgroups_checked'))
            or scope['matching_producers']!=[]):raise ValueError('living or unexcluded original prehandle producer')
    for identity in births:_identity(identity,absent=True)
    handle,paths=_prehandle_native_paths(start)
    for path in paths:
        if any(p.is_symlink() for p in (path,*path.parents)) or path.exists():raise ValueError('native session/gate/lock/journal blocks prehandle disposition')
    for ref in (start['plan']['coordination_ref'],'refs/heads/cdc/managed-host-publish-'+handle.replace('-','')):
        source._git('check-ref-format',ref)
        if source._git('ls-remote','--refs',source.remote,ref):raise ValueError('native original pool/publication exists')
    output=launch/'output'
    if output.is_symlink() or output.exists() and (not output.is_dir() or any(output.iterdir())):raise ValueError('original prehandle worker output must be empty')
    artifacts=evidence['artifact_pins']
    if not isinstance(artifacts,dict):raise ValueError('complete root artifact manifest required')
    seen=set()
    for root in (controller,launch):
        if root.exists() and not root.is_dir():raise ValueError('original custody directory required')
        for path in ([root,*root.rglob('*')] if root.exists() else []):
            info=path.lstat()
            if path.is_symlink() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or info.st_mode & 0o002:
                raise ValueError('special, linked or unprotected original prehandle artifact')
            if path.is_dir():
                if info.st_uid not in {0,physical['controller_uid']} or path!=output and info.st_mode & 0o020:
                    raise ValueError('worker writable original custody directory')
                continue
            key=str(path);pin=artifacts.get(key)
            op._object(pin,{'sha256','uid','gid','mode'},'root original artifact pin')
            if (info.st_uid not in {0,physical['controller_uid']} or info.st_nlink!=1 or info.st_mode & 0o022
                    or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(pin['uid'],pin['gid'],pin['mode'])
                    or 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()!=pin['sha256']):raise ValueError('protected original prehandle artifact changed')
            seen.add(key)
    if seen!=set(artifacts):raise ValueError('root original artifact manifest incomplete or substituted')
    if _prehandle_receipt_kind(row)[0]==LEGACY_PREHANDLE_SCHEMA:
        _legacy_prehandle_artifacts(row,physical,controller,artifacts)
    for identity in births:_identity(identity,absent=True)


def _authenticate_prehandle(store,task_id,source,pins,*,authenticated_births=None):
    if type(store) is not GitDocumentStore or type(source) is not GitLeaseStore:raise ValueError('actual original native prehandle channels required')
    op._object(pins,{'original_revision','row_digest','source_revision','source_digest','channels','owner_decision_reference','physical'},'trusted original prehandle contract')
    op._text(pins['owner_decision_reference'],'prehandle owner decision')
    revision,document=store.read();row=_row(document,task_id)
    if revision!=pins['original_revision'] or op._hash(row)!=pins['row_digest']:raise ValueError('stale exact original prehandle head/row')
    _prehandle_original(row);_intake_channels(store,row,pins,source)
    if authenticated_births is None:
        head,births=_run_history_fold(store,_prehandle_history_fold(task_id,pins,row))
        if head!=revision:raise ValueError('prehandle native history moved')
    else:births=copy.deepcopy(authenticated_births)
    srev,lease=source.read();start=row['operation']['start_request']
    if (srev!=pins['source_revision'] or op._hash(lease)!=pins['source_digest'] or lease['schema']!='execution-lease/v2'
            or lease['owner_id'] is not None or lease['external_guard'] is not None
            or (lease.get('finalization') or {}).get('pending_shared_writes',False) is not False
            or (lease['repository'],lease['source_ref'])!=(start['lease_repository'],start['lease_source_ref'])):
        raise ValueError('exact unowned unguarded original prehandle source lease required')
    _prehandle_physical(store,row,source,pins,births)
    if store.read()!=(revision,document) or source.read()!=(srev,lease):raise ValueError('prehandle volatile head changed')
    return revision,row,births


class PrehandleIntakeDispositionProof:
    """Ephemeral administrative custody; never a terminal, wait or send proof."""
    def __init__(self,seal,store,task_id,source,pins,at):
        if seal is not _SEAL:raise ValueError('package issued prehandle disposition required')
        self._seal=seal;self._store=store;self._task=task_id;self._source=source;self._pins=copy.deepcopy(pins);self._at=at;self._retired=False
        self._revision,self._row,self._births=_authenticate_prehandle(store,task_id,source,pins)
        self._binding=op._hash([self._pins,self._at,self._revision,self._row,self._births])
    def revalidate_for(self,store,task_id):
        if (self._seal is not _SEAL or store is not self._store or task_id!=self._task
                or self._binding!=op._hash([self._pins,self._at,self._revision,self._row,self._births])):raise ValueError('prehandle capability substituted or mutated')
        # Only this package-issued process-local capability can reuse its exact
        # immutable head verdict. Fresh head/source/physical checks still run.
        revision,row,_=_authenticate_prehandle(store,task_id,self._source,self._pins,authenticated_births=self._births)
        if revision!=self._revision or row!=self._row:raise ValueError('prehandle capability head changed')
        return row
    def revalidate_cancellation(self,store,revision,task_id,proposed):
        row=self.revalidate_for(store,task_id);entry=_validate_prehandle_disposition_row(proposed)
        if (revision!=self._revision or _prehandle_original(row)!='cancelled' or entry['original_row']!=row
                or entry['trusted_contract']!=self._pins or entry['retired_at_utc']!=self._at):raise ValueError('reserved cancellation capability binding changed')


def authenticate_prehandle_intake(store,task_id,*,source_store,trusted_contract,at):
    op._timestamp(at,'prehandle disposition time')
    return PrehandleIntakeDispositionProof(_SEAL,store,task_id,source_store,trusted_contract,at)


def _validate_prehandle_disposition_row(row):
    disposition=row.get('state');key='administrative_disposition' if disposition=='retired_unknown' else 'unstarted_cancellation'
    entry=(row.get('result') or {}).get(key)
    op._object(entry,{'schema','task_id','contract_digest','original_effect','actual_wait','replay_forbidden','original_revision','original_row','trusted_contract','retired_at_utc','reason','no_send'},'native prehandle disposition')
    original=entry['original_row'];expected=copy.deepcopy(original);expected.update(state=disposition,result={key:entry})
    required=_prehandle_original(original);schema,reason=_prehandle_receipt_kind(original)
    if (row!=expected or disposition!=required or entry['schema']!=schema or entry['task_id']!=row['task']['id']
            or entry['contract_digest']!=_contract(original) or entry['original_revision']!=entry['trusted_contract']['original_revision']
            or op._hash(original)!=entry['trusted_contract']['row_digest'] or entry['actual_wait'] is not None
            or entry['replay_forbidden'] is not True or entry['original_effect']!=('UNKNOWN' if required=='retired_unknown' else 'NOT_SENT')
            or entry['reason']!=reason
            or entry['no_send'] is not (required=='cancelled')):raise ValueError('prehandle disposition cannot alter original liability or claim terminal success')
    op._timestamp(entry['retired_at_utc'],'prehandle disposition time')
    op._text(entry['trusted_contract']['owner_decision_reference'],'prehandle owner decision')
    return entry


def dispose_prehandle_intake_cas(store,expected_revision,task_id,proof,*,at):
    if type(proof) is not PrehandleIntakeDispositionProof or proof._retired or at!=proof._at:raise ValueError('issued original prehandle proof required')
    row=proof.revalidate_for(store,task_id);revision,document=store.read()
    if revision!=expected_revision or revision!=proof._revision:raise ValueError('stale original prehandle CAS')
    disposition=_prehandle_original(row);consumed=disposition=='retired_unknown'
    key='administrative_disposition' if consumed else 'unstarted_cancellation'
    schema,reason=_prehandle_receipt_kind(row)
    entry=dict(schema=schema,task_id=task_id,contract_digest=_contract(row),
        original_effect='UNKNOWN' if consumed else 'NOT_SENT',actual_wait=None,replay_forbidden=True,
        original_revision=proof._pins['original_revision'],original_row=copy.deepcopy(row),trusted_contract=copy.deepcopy(proof._pins),
        retired_at_utc=at,reason=reason,no_send=not consumed)
    changed=copy.deepcopy(document);changed['tasks'][task_id].update(state=disposition,result={key:entry})
    _validate_prehandle_disposition_row(changed['tasks'][task_id])
    new_revision=store.compare_and_swap(expected_revision,changed,recovery_capability=proof)
    if store.read()!=(new_revision,changed):raise ValueError('prehandle disposition reply moved; observe without replay')
    return {'revision':new_revision,'row':copy.deepcopy(changed['tasks'][task_id])}


def assert_intake_disposition_replay_absent(document):
    """Structural current/history consumer guard; supplies no recovery authority."""
    return _assert_intake_disposition_replay_absent(document)


def _assert_intake_disposition_replay_absent(document, row_validator=None):
    rows=document.get('tasks',{})
    for task_id,row in rows.items():
        if row.get('state')=='retired_unknown' and ((row.get('result') or {}).get('administrative_disposition') or {}).get('schema') in {PREHANDLE_SCHEMA,LEGACY_PREHANDLE_SCHEMA}:
            (row_validator or _validate_prehandle_disposition_row)(row)
        elif ((row.get('result') or {}).get('unstarted_cancellation') or {}).get('schema')==RESERVED_SCHEMA:
            (row_validator or validate_queued_cancellation)(row)
        else:continue
        for other_id,other in rows.items():
            if other_id==task_id:continue
            if (semantic_intake_contract(other)==semantic_intake_contract(row)
                    or other.get('operation') is not None and _contract(other)==_contract(row)):
                raise ValueError('original disposed intake contract cannot replay under another task/attempt')
    return True
