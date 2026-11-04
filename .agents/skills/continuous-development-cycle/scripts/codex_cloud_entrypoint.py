"""Pure startup preparation and thin delegation to the existing Cloud transports.
Supplied observations are not authenticated by this module. All authority stays
with the original fresh owner/intent/guard/budget/one-use launch callback.
"""
from __future__ import annotations
import copy,hashlib,json,re
from pathlib import Path
from datetime import datetime,timezone
import codex_cloud_profile as profile_api
import codex_cloud_cli as cli
import codex_cloud_development as development
import recovery_recipes as recipes
import resume_capsule
import cost_router
import capability_router

CONTEXT_FIELDS={'schema','repository','source_ref','exact_sha','task_id','task_mode','access_mode','intent','checks','development','restored','resume_capsule','resume_probe','live_recovery','recovery'}
RESTORED_FIELDS={'schema','mode','operation_key','journal_ref','journal_digest','journal_state','task_id','task_url','guard_ref','intent_ref','lookup','terminal_evidence_ref'}
PREPARED_FIELDS={'schema','action','access_mode','task_mode','request','request_digest','operation_key','task_id','journal_ref','profile_projection','profile_binding_digest','probe_projection','probe_binding_digest','context_projection','context_digest','restore_digest','checked_at_utc','max_age_seconds','recovery_decision','next_action','reasons','authorities'}
STATES={'NONE_VERIFIED','UNKNOWN','CORRUPT','prepared','submitting','unknown','submitted','running','waiting_report','waiting_result','succeeded','result_exported','failed','not_submitted'}
MODES={'COMPUTE_ONLY','DEVELOPMENT'}
AUTHORITIES={'takeover':False,'product_write':False,'external_start':False,'scheduler_mutation':False}

def _hash(v):return 'sha256:'+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def _fields(v,expected,name):
    if not isinstance(v,dict) or set(v)!=expected:raise ValueError(name+' fields mismatch')
def _text(v,nullable=False):
    if v is None and nullable:return
    cli._text(v)
def _digest(v,nullable=False):
    if v is None and nullable:return
    if not isinstance(v,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',v):raise ValueError('invalid wrapper digest')
def _time(v):return profile_api._utc(v,'observation time')
def _fresh(v,now,age=300):return 0<=(_time(now)-_time(v)).total_seconds()<=age

def _checks(checks):
    if not isinstance(checks,list) or not checks:raise ValueError('nonempty exact check plan required')
    seen=set()
    for check in checks:
        _fields(check,{'id','argv','minimum_test_count'},'check');_text(check['id'])
        if check['id'] in seen:raise ValueError('duplicate check identifier')
        seen.add(check['id'])
        if not isinstance(check['argv'],list) or not check['argv']:raise ValueError('nonempty argv required')
        for arg in check['argv']:_text(arg)  # Explicit rejection; never trim accepted strings.
        n=check['minimum_test_count']
        if n is not None and (type(n) is not int or n<1):raise ValueError('invalid minimum test count')

def validate_context(c):
    if not isinstance(c,dict) or set(c) not in (CONTEXT_FIELDS,CONTEXT_FIELDS|{'routing_request'}):raise ValueError('entry context fields mismatch')
    if c['schema']!='cloud-entry-context/v1':raise ValueError('unsupported entry context')
    profile_api._repository(c['repository']);profile_api._source_ref(c['source_ref']);_text(c['task_id'])
    if not isinstance(c['exact_sha'],str) or not re.fullmatch(r'[0-9a-f]{40}',c['exact_sha']):raise ValueError('invalid exact source SHA')
    if c['task_mode'] not in MODES or c['access_mode'] not in profile_api.MODES:raise ValueError('invalid entry mode')
    route=c.get('routing_request')
    if route is not None:
        capability_router.validate_request(route)
        if route['task_id']!=c['task_id'] or route['candidate_sha']!=c['exact_sha']:raise ValueError('routing request task/source mismatch')
    _checks(c['checks'])
    intent=c['intent']
    if intent is not None:
        _fields(intent,{'operation_key','attempt_id','intent_ref','intent_digest','request_binding_digest'},'entry intent')
        for k in ('operation_key','intent_digest','request_binding_digest'):_digest(intent[k])
        for k in ('attempt_id','intent_ref'):_text(intent[k])
    dev=c['development']
    if c['task_mode']=='COMPUTE_ONLY' and dev is not None:raise ValueError('compute context cannot carry development scope')
    if c['task_mode']=='DEVELOPMENT':
        _fields(dev,{'allowed_paths','acceptance_criteria','budget_ref'},'development scope');_text(dev['budget_ref'])
        if not isinstance(dev['allowed_paths'],list) or not dev['allowed_paths'] or not isinstance(dev['acceptance_criteria'],list) or not dev['acceptance_criteria']:raise ValueError('development scope/criteria required')
        keys=[]
        for p in dev['allowed_paths']:_text(p);keys.append(development.portable_path_key(p))
        if len(set(keys))!=len(keys):raise ValueError('duplicate portable write path')
        for value in dev['acceptance_criteria']:_text(value)
    restored=c['restored'];_fields(restored,RESTORED_FIELDS,'restored operation')
    if restored['schema']!='cloud-restored-operation/v1' or restored['mode'] not in MODES|{None} or restored['journal_state'] not in STATES:raise ValueError('invalid restored mode/state')
    for k in ('operation_key','journal_digest'):_digest(restored[k],True)
    for k in ('journal_ref','task_id','task_url','guard_ref','intent_ref','terminal_evidence_ref'):_text(restored[k],True)
    lookup=restored['lookup'];_fields(lookup,{'operation_key','observed_at_utc','complete','journal_absence_verified','evidence_ref'},'operation lookup');_digest(lookup['operation_key'],True);_time(lookup['observed_at_utc']);_text(lookup['evidence_ref'],True)
    for k in ('complete','journal_absence_verified'):
        if type(lookup[k]) is not bool:raise ValueError('lookup flags must be booleans')
    live=c['live_recovery'];_fields(live,{'schema','observed_at_utc','source','ownership','provider'},'live recovery')
    if live['schema']!='cloud-live-recovery/v1':raise ValueError('invalid live recovery schema')
    _time(live['observed_at_utc'])
    for k in ('source','ownership','provider'):
        d=live[k];_fields(d,{'complete','evidence_ref','binding_digest'},'live domain')
        if type(d['complete']) is not bool:raise ValueError('domain complete must be boolean')
        _text(d['evidence_ref'],True);_digest(d['binding_digest'],True)
    if c['resume_capsule'] is not None:
        resume_capsule.validate(c['resume_capsule'])
        if c['resume_probe'] is not None:resume_capsule.assess(c['resume_capsule'],c['resume_probe'])
    elif c['resume_probe'] is not None:raise ValueError('resume probe has no capsule')
    recovery=c['recovery'];_fields(recovery,{'schema','catalog_ref','catalog','diagnosis','history_ref','history','bindings','new_signal'},'entry recovery')
    if recovery['schema']!='cloud-entry-recovery/v1':raise ValueError('invalid entry recovery schema')
    for k in ('catalog_ref','history_ref'):_text(recovery[k],True)
    recipes.validate_bindings(recovery['bindings']);recipes._signal(recovery['new_signal'])
    for k,validator in [('catalog',recipes.validate_catalog),('diagnosis',recipes.validate_diagnosis),('history',recipes.validate_history)]:
        if recovery[k] is not None:validator(recovery[k])
    return c

def _domain_ready(c,now,domains):
    l=c['live_recovery']
    return _fresh(l['observed_at_utc'],now) and all(l[d]['complete'] and l[d]['evidence_ref'] is not None and l[d]['binding_digest'] is not None for d in domains)

def _request(p,c):
    i=c['intent'];env=p['environments'][c['access_mode']]
    common={'operation_key':i['operation_key'],'attempt_id':i['attempt_id'],'repository':c['repository'],'environment_id':env['id'],'environment_label':env['label'],'source_branch':c['source_ref'][len('refs/heads/'):],'checks':copy.deepcopy(c['checks'])}
    if c['task_mode']=='COMPUTE_ONLY':
        r=dict(common,schema='codex-cloud-cli-request/v1',candidate_sha=c['exact_sha']);cli.validate_request(r)
    else:
        r=dict(common,schema='codex-cloud-development-request/v1',base_sha=c['exact_sha'],**copy.deepcopy(c['development']));r=development.validate_development_request(r)
    return r

def _recovery(c,p,now):
    rec=c['recovery']
    if rec['diagnosis'] is None:return None
    if rec['catalog'] is None or rec['history'] is None or rec['catalog_ref'] is None or rec['history_ref'] is None:return {'status':'BLOCKED','reason':'recovery_documents_unconfigured','selection':None,'action_plan':None}
    b=rec['bindings'];env=p['environments'][c['access_mode']]
    if (b['repository']!=c['repository'] or b['environment_namespace']!=env['provider_namespace'] or b['environment_id']!=env['id'] or b['access_mode']!=c['access_mode'] or rec['history']['repository']!=c['repository']):return {'status':'BLOCKED','reason':'recovery_scope_mismatch','selection':None,'action_plan':None}
    if (b['policy_digest']!=p['policy_digest'] or b['input_digests'].get('cloud-profile:'+c['access_mode'])!=profile_api.profile_binding_digest(p,c['access_mode'])):return {'status':'BLOCKED','reason':'recovery_profile_binding_mismatch','selection':None,'action_plan':None}
    selected=recipes.select(rec['catalog'],rec['diagnosis'],bindings=b,now_utc=now,history=rec['history'],new_signal=rec['new_signal'])
    handler=selected['steps'][0]
    if handler=='inspect_exact_invocation':
        params={'invocation_ref':c['live_recovery']['ownership']['evidence_ref'] or c['task_id'],'error_evidence_ref':rec['diagnosis']['reference'],'approved_read_argv':copy.deepcopy(c['checks'][0]['argv']),'diagnostic_limit':1}
    elif handler=='reconcile_external':
        restore=c['restored'];params={'operation_key':restore['operation_key'],'journal_ref':restore['journal_ref'],'task_id':restore['task_id'],'task_mode':c['task_mode']}
    elif handler=='record_blocker':
        events=recipes._subject_events(rec['diagnosis'],b,rec['history']);params={'reason':selected['reason'],'evidence_ref':events[-1]['evidence_ref'] if events else rec['diagnosis']['reference']}
    elif handler=='resume_next_action':
        events=recipes._subject_events(rec['diagnosis'],b,rec['history'])
        proof_ref=events[-1]['evidence_ref'] if selected['reason']=='verified_evidence_reused' else selected['recipe']['provenance']['evidence_ref']
        check_ref='cloud-entry-check:'+_hash({'repository':c['repository'],'source_ref':c['source_ref'],'exact_sha':c['exact_sha'],'check':c['checks'][0]})
        params={'next_action_ref':check_ref,'evidence_ref':proof_ref}
    elif handler=='refresh_capability_registry':params={'executable':p['toolchain']['cli_executable'],'expected_version':p['toolchain']['cli_version'],'profile_binding':profile_api.profile_binding_digest(p,c['access_mode']),'evidence_ref':rec['diagnosis']['reference']}
    else:return {'status':'BLOCKED','reason':'handler_parameters_unavailable','selection':selected,'action_plan':None}
    try:plan=recipes.action_plan(selected,rec['diagnosis'],b,rec['history'],params)
    except ValueError as exc:return {'status':'BLOCKED','reason':str(exc),'selection':copy.deepcopy(selected),'action_plan':None}
    signal=selected.get('selected_signal')
    return {'status':'BLOCKED' if selected['action']=='blocked' else 'PLANNED','reason':selected['reason'],'selection':copy.deepcopy(selected),'action_plan':plan,'history_ref':rec['history_ref'],'history_digest':_hash(rec['history']),'new_signal_ref':None if signal is None else signal['reference'],'completed_correction_ref':None if signal is None else signal['completed_correction_ref']}

def prepare(profile,context,probe,registry,routing_policy,routing_context,now_utc):
    profile_api.validate_profile(profile);profile_api.validate_probe(probe);validate_context(context);_time(now_utc)
    p,c,q=copy.deepcopy((profile,context,probe));mode=c['access_mode'];restore=c['restored'];lookup=restore['lookup'];key=restore['operation_key']
    result={'schema':'cloud-entrypoint-preparation/v1','action':'BLOCKED','access_mode':mode,'task_mode':c['task_mode'],'request':None,'request_digest':None,'operation_key':key,'task_id':restore['task_id'],'journal_ref':restore['journal_ref'],'profile_projection':p,'profile_binding_digest':profile_api.profile_binding_digest(p,mode),'probe_projection':q,'probe_binding_digest':_hash(q),'context_projection':c,'context_digest':_hash(c),'restore_digest':_hash(restore),'checked_at_utc':now_utc,'max_age_seconds':300,'recovery_decision':None,'next_action':None,'reasons':[],'authorities':copy.deepcopy(AUTHORITIES)}
    def choose(action,reason,handler,params=None):
        result.update(action=action,reasons=[reason],next_action={'handler':handler,'parameters':copy.deepcopy(params or {}),'required_scope_ref':c['live_recovery']['ownership']['evidence_ref'],'verification':{'expected_operation_key':result['operation_key'],'exact_sha':c['exact_sha']}});return result
    capsule=c['resume_capsule'];external=None if capsule is None else capsule['external']
    if external is not None:
        capsule_key=external['operation_key'];_digest(capsule_key)
        if key is None:
            result.update(operation_key=capsule_key,task_id=external['id'])
            return choose('RECONCILE_EXISTING','capsule_effect_requires_exact_journal_recovery','reconcile_existing_operation',{'operation_key':capsule_key,'task_mode':c['task_mode'],'journal_ref':restore['journal_ref']})
        if (capsule_key!=key or external['id']!=restore['task_id'] or external['sha']!=c['exact_sha'] or capsule['repository']!=c['repository'] or capsule['source_ref']!=c['source_ref'] or capsule['head_sha']!=c['exact_sha']):
            return choose('RECONCILE_EXISTING','capsule_restored_identity_conflict','reconcile_existing_operation',{'operation_key':key,'task_mode':c['task_mode'],'journal_ref':restore['journal_ref']})
    known=(key is not None or restore['guard_ref'] is not None or restore['task_id'] is not None or restore['journal_ref'] is not None or restore['intent_ref'] is not None or restore['journal_state']!='NONE_VERIFIED')
    if known:
        if (key is None or restore['mode']!=c['task_mode'] or restore['journal_ref'] is None or restore['journal_digest'] is None or restore['journal_state'] in {'UNKNOWN','CORRUPT'} or lookup['operation_key']!=key or not lookup['complete'] or not _fresh(lookup['observed_at_utc'],now_utc)):
            return choose('RECONCILE_EXISTING','known_operation_binding_unresolved','reconcile_existing_operation',{'operation_key':key,'task_mode':restore['mode'],'journal_ref':restore['journal_ref']})
        state=restore['journal_state']
        if state in {'submitting','unknown','submitted','running'}:return choose('OBSERVE_EXISTING','same_operation_only','observe_existing_operation',{'operation_key':key,'task_mode':restore['mode'],'journal_ref':restore['journal_ref']})
        if state in {'waiting_report','waiting_result'}:return choose('INTAKE_EXISTING','same_operation_result_required','intake_existing_result',{'operation_key':key,'task_mode':restore['mode'],'journal_ref':restore['journal_ref']})
        return choose('RECONCILE_EXISTING','terminal_or_prepared_operation_requires_core_reconciliation','reconcile_existing_operation',{'operation_key':key,'task_mode':restore['mode'],'journal_ref':restore['journal_ref'],'terminal_evidence_ref':restore['terminal_evidence_ref']})
    if (lookup['operation_key'] is not None or not lookup['complete'] or not lookup['journal_absence_verified'] or lookup['evidence_ref'] is None or not _fresh(lookup['observed_at_utc'],now_utc)):
        return choose('BLOCKED','exact_prior_effect_boundary_unknown','record_blocker')
    if p['repository']!=c['repository'] or p['source_ref']!=c['source_ref'] or not _domain_ready(c,now_utc,('source','ownership')):return choose('BLOCKED','source_ownership_binding_not_fresh','record_blocker')
    qualification=profile_api.assess_profile(p,q,now_utc)
    if qualification['modes'][mode]['status']!='READY':return choose('BLOCKED','selected_mode_not_qualified','record_blocker')
    capability_router.validate_registry(registry);cost_router.validate_policy(routing_policy);cost_router.validate_context(routing_context)
    result['recovery_decision']=_recovery(c,p,now_utc)
    if result['recovery_decision'] is not None:
        decision=result['recovery_decision'];return choose('BLOCKED' if decision['status']=='BLOCKED' else 'CONTINUE_NATIVE' if mode=='native_runtime' else 'BLOCKED','bound_recovery_plan_requires_existing_caller','execute_existing_recovery_plan',{'decision':copy.deepcopy(decision)})
    if mode=='native_runtime':return choose('CONTINUE_NATIVE','native_qualified_inventory_remains_scoped_unknown','run_existing_native_check',{'check_id':c['checks'][0]['id'],'argv':c['checks'][0]['argv']})
    if mode=='official_ui':return choose('BLOCKED','official_ui_receipt_boundary_no_cli_delegation','use_existing_official_ui_boundary',{'task_mode':c['task_mode']})
    if c['intent'] is None or not _domain_ready(c,now_utc,('provider',)):return choose('BLOCKED','new_remote_intent_or_scoped_provider_boundary_missing','record_blocker')
    request=_request(p,c)
    if _hash(request)!=c['intent']['request_binding_digest']:return choose('BLOCKED','intent_request_binding_mismatch','record_blocker')
    route_request=c.get('routing_request')
    if route_request is None or not route_request['required_capabilities'] or route_request['required_backend_id'] is None:return choose('BLOCKED','explicit_cli_capability_request_missing','record_blocker')
    if routing_context.get('schema')!='compute-cost-context/v2':return choose('BLOCKED','qualified_cli_provider_binding_missing','record_blocker')
    provider_action=routing_context['provider_action'];env=p['environments'][mode]
    if (provider_action['backend_id']!=route_request['required_backend_id'] or provider_action['provider_kind']!='codex_cloud' or provider_action['provider_namespace']!=env['provider_namespace'] or provider_action['environment_id']!=env['id'] or provider_action['consumption']!='compute_backend' or provider_action['action']!='create' or provider_action['compute_backend_ref'] is None):return choose('BLOCKED','cli_provider_route_mismatch','record_blocker')
    assessed=cost_router.assess_provider_action(provider_action,routing_context,routing_policy,now_utc)
    if not assessed['allowed_for_callback']:return choose('BLOCKED',assessed['reason'],'record_blocker')
    routed=cost_router.route(registry,route_request,routing_policy,routing_context,now_utc)
    if routed['action']!='route' or routed['backend_id']!=route_request['required_backend_id']:return choose('BLOCKED',routed['reason'],'record_blocker')
    result.update(request=request,request_digest=_hash(request),operation_key=c['intent']['operation_key'])
    answer=choose('READY_FOR_SUBMIT','existing_intent_fresh_qualified_mode','submit_existing_transport',{'task_mode':c['task_mode'],'operation_key':c['intent']['operation_key']})
    answer['next_action']['verification'].update(routing_policy_digest=_hash(routing_policy),routing_context_digest=_hash(routing_context),registry_digest=_hash(registry))
    return answer

def submit(prepared,transport,*,read_preflight,launch_authorized,clock=None):
    _fields(prepared,PREPARED_FIELDS,'prepared entry')
    if prepared['schema']!='cloud-entrypoint-preparation/v1' or prepared['action']!='READY_FOR_SUBMIT' or prepared['access_mode']!='official_cli':raise ValueError('only qualified official CLI READY can submit')
    if prepared['authorities']!=AUTHORITIES or any(type(v) is not bool for v in prepared['authorities'].values()) or prepared['max_age_seconds']!=300 or type(prepared['max_age_seconds']) is not int or not callable(read_preflight) or not callable(launch_authorized):raise ValueError('fresh original callbacks required')
    if (profile_api.profile_binding_digest(prepared['profile_projection'],prepared['access_mode'])!=prepared['profile_binding_digest'] or _hash(prepared['probe_projection'])!=prepared['probe_binding_digest'] or _hash(prepared['context_projection'])!=prepared['context_digest'] or _hash(prepared['context_projection']['restored'])!=prepared['restore_digest'] or _hash(prepared['request'])!=prepared['request_digest']):raise ValueError('prepared projection mutated')
    now=clock() if clock else datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    if not _fresh(prepared['checked_at_utc'],now,prepared['max_age_seconds']):raise ValueError('prepared entry expired')
    fresh=read_preflight();_fields(fresh,{'schema','profile','context','probe','registry','routing_policy','routing_context'},'fresh preflight')
    if fresh['schema']!='cloud-entrypoint-preflight/v1':raise ValueError('invalid preflight schema')
    new=prepare(*(fresh[k] for k in ('profile','context','probe','registry','routing_policy','routing_context')),now)
    if any(new[k]!=prepared[k] for k in PREPARED_FIELDS-{'checked_at_utc'}):raise ValueError('fresh preflight changed prepared binding')
    is_dev=isinstance(transport,development.CodexCloudDevelopment)
    if not isinstance(transport,cli.CodexCloudCLI) or is_dev!=(prepared['task_mode']=='DEVELOPMENT'):raise ValueError('transport task mode mismatch')
    if transport.executable!=new['profile_projection']['toolchain']['cli_executable']:raise ValueError('transport executable differs from qualified CLI')
    return transport.submit(copy.deepcopy(new['request']),launch_authorized=launch_authorized)

def observe(operation_key,transport):
    if not cli.KEY.fullmatch(operation_key) or not isinstance(transport,cli.CodexCloudCLI):raise ValueError('exact existing transport/key required')
    return transport.observe(operation_key)

def intake(operation_key,payload,evidence_ref,transport,*,evidence_root=None):
    if not cli.KEY.fullmatch(operation_key):raise ValueError('exact operation key required')
    if isinstance(transport,development.CodexCloudDevelopment):
        if payload is not None or evidence_root is None:raise ValueError('development intake exports original bound result')
        return transport.export_diff(operation_key,evidence_root=evidence_root)
    if not isinstance(transport,cli.CodexCloudCLI) or evidence_root is not None:raise ValueError('compute intake mode mismatch')
    return transport.ingest_report(operation_key,payload,evidence_ref)

INPUT_NAMES=('context','probe','registry','routing_policy','routing_context')
HANDOFF_FIELDS={'schema','repository','source_ref','exact_sha','profile_ref','profile_digest','task','phase','journal_ref','guard_ref','budget_ref','recipe_ref','next_action','operation_key','task_mode','access_mode','restore_ref','restore_digest','recovery_history_ref'}
NEXT_HANDLERS={'run_existing_native_check','observe_existing_operation','reconcile_existing_operation','intake_existing_result','record_blocker','execute_existing_recovery_plan','use_existing_official_ui_boundary','submit_existing_transport'}

def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON field')
        result[key]=value
    return result

def _read_json(path):
    try:return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=_unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON value')))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:raise ValueError('materialized input unavailable or corrupt') from exc

def _project_path(root,path):
    root=Path(root).resolve();p=Path(path)
    if not p.is_absolute():p=root/p
    # Reject symlink components, including an in-root symlink to another input.
    if '..' in p.parts:raise ValueError('input traversal rejected')
    resolved=p.resolve()
    if resolved==root or root not in resolved.parents:raise ValueError('input outside project root')
    for part in [p,*p.parents]:
        if part==root:break
        if part.is_symlink():raise ValueError('symlink input rejected')
    if not p.is_file():raise ValueError('materialized input missing')
    return p

def load_inputs(inputs_path,*,project_root):
    """Load each exact hash-bound snapshot once; no discovery or freshening."""
    doc=_read_json(_project_path(project_root,inputs_path))
    _fields(doc,{'schema',*INPUT_NAMES},'entry input references')
    if doc['schema']!='cloud-entry-inputs/v1':raise ValueError('unsupported input references')
    result={}
    for name in INPUT_NAMES:
        ref=doc[name];_fields(ref,{'path','sha256'},'input reference');_text(ref['path'])
        if Path(ref['path']).is_absolute():raise ValueError('input reference must be project-relative')
        digest=ref['sha256']
        if not isinstance(digest,str) or not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}',digest):raise ValueError('invalid exact byte hash')
        p=_project_path(project_root,ref['path'])
        try:raw=p.read_bytes()
        except OSError as exc:raise ValueError('input read failed') from exc
        if hashlib.sha256(raw).hexdigest()!=digest.removeprefix('sha256:'):raise ValueError('input bytes hash mismatch')
        try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite input')))
        except (UnicodeError,json.JSONDecodeError) as exc:raise ValueError('input JSON corrupt') from exc
        result[name]=value
    return copy.deepcopy(result)

def _handoff_recovery(decision,h):
    minimal={'status','reason','selection','action_plan'}
    full=minimal|{'history_ref','history_digest','new_signal_ref','completed_correction_ref'}
    if not isinstance(decision,dict) or set(decision) not in (minimal,full):raise ValueError('recovery decision fields mismatch')
    if not isinstance(decision['status'],str) or decision['status'] not in {'BLOCKED','PLANNED'}:raise ValueError('invalid recovery decision status')
    _text(decision['reason'])
    if set(decision)==full:
        _text(decision['history_ref']);_digest(decision['history_digest'])
        if decision['history_ref']!=h['recovery_history_ref']:raise ValueError('recovery history binding mismatch')
        for k in ('new_signal_ref','completed_correction_ref'):_text(decision[k],True)
    selection=decision['selection'];plan=decision['action_plan']
    if selection is None:
        if plan is not None or decision['status']!='BLOCKED':raise ValueError('unselected recovery cannot plan')
        return
    _fields(selection,recipes.SELECTION_FIELDS,'recovery selection')
    recipes._signal(selection['selected_signal']);_text(selection['reason'])
    if decision['reason']!=selection['reason']:raise ValueError('recovery selection reason mismatch')
    if set(decision)==full:
        signal=selection['selected_signal']
        if (decision['new_signal_ref']!=(None if signal is None else signal['reference']) or decision['completed_correction_ref']!=(None if signal is None else signal['completed_correction_ref'])):raise ValueError('recovery selected signal mismatch')
    if not isinstance(selection['action'],str) or selection['action'] not in {'apply_recipe','blocked','reconcile'} or not isinstance(selection['outcome'],str) or selection['outcome'] not in recipes.OUTCOMES:raise ValueError('invalid recovery selection')
    recipes._tokens(selection['steps'],'selection.steps')
    if not selection['steps'] or set(selection['steps'])-recipes.ACTIONS:raise ValueError('untyped recovery steps')
    if any(selection['authorizes_'+k] is not False for k in recipes.AUTHORITIES):raise ValueError('handoff cannot grant recovery authority')
    recipe=selection['recipe']
    if recipe is not None:
        recipes._recipe(recipe,True)
        if selection['recipe_id']!=recipe['id']:raise ValueError('selection recipe mismatch')
    elif selection['recipe_id'] is not None:raise ValueError('missing recipe projection')
    verification=recipes.selection_verification(selection)
    if selection['action']=='blocked' and (decision['status']!='BLOCKED' or selection['steps']!=['record_blocker']):raise ValueError('blocked selection cannot execute another handler')
    if plan is None:
        if decision['status']!='BLOCKED':raise ValueError('planned recovery requires plan')
        return
    if set(decision)!=full:raise ValueError('recovery plan requires history binding')
    _fields(plan,{'schema','handler','parameters','action_fingerprint','verification','next_on_success','next_on_failure','authorities'},'recovery action plan')
    if plan['schema']!='recovery-action-plan/v1' or plan['handler']!=selection['steps'][0]:raise ValueError('recovery handler mismatch')
    recipes._parameters(plan['handler'],plan['parameters']);_digest(plan['action_fingerprint']);recipes._verification(plan['verification'])
    if plan['verification']!=verification:raise ValueError('plan verification differs from selected recipe')
    if plan['authorities']!=recipes.AUTHORITIES or any(type(v) is not bool for v in plan['authorities'].values()):raise ValueError('recovery authority rejected')
    if (plan['next_on_success']!=plan['verification']['success_next_action'] or plan['next_on_failure']!=plan['verification']['failure_next_action']):raise ValueError('recovery branch mismatch')
    if plan['handler']=='reconcile_external':
        p=plan['parameters']
        if (p['operation_key']!=h['operation_key'] or p['task_mode']!=h['task_mode'] or p['journal_ref']!=h['journal_ref'] or p['task_id']!=h['task']['id']):raise ValueError('recovery operation binding mismatch')

def validate_handoff(h):
    _fields(h,HANDOFF_FIELDS,'cloud handoff')
    if h['schema']!='cloud-entrypoint-handoff/v1':raise ValueError('unsupported handoff')
    profile_api._repository(h['repository']);profile_api._source_ref(h['source_ref'])
    if not isinstance(h['exact_sha'],str) or not re.fullmatch(r'[0-9a-f]{40}',h['exact_sha']):raise ValueError('invalid handoff exact SHA')
    _digest(h['profile_digest']);_digest(h['operation_key'],True);_digest(h['restore_digest'],True)
    if not isinstance(h['task_mode'],str) or h['task_mode'] not in MODES or not isinstance(h['access_mode'],str) or h['access_mode'] not in profile_api.MODES:raise ValueError('invalid handoff mode')
    for k in ('profile_ref','phase'):_text(h[k])
    for k in ('journal_ref','guard_ref','budget_ref','recipe_ref','restore_ref','recovery_history_ref'):_text(h[k],True)
    if (h['restore_ref'] is None)!=(h['restore_digest'] is None):raise ValueError('restore reference/digest must be paired')
    task=h['task'];_fields(task,{'id','url','mode'},'handoff task');_text(task['id'],True);_text(task['url'],True)
    if task['mode']!=h['task_mode']:raise ValueError('handoff task mode mismatch')
    action=h['next_action'];_fields(action,{'handler','parameters','required_scope_ref','verification'},'single next action')
    handler=action['handler'];p=action['parameters'];v=action['verification']
    if not isinstance(handler,str) or handler not in NEXT_HANDLERS:raise ValueError('invalid typed next action')
    _text(action['required_scope_ref'],True)
    vf={'expected_operation_key','exact_sha'}
    if handler=='submit_existing_transport':vf|={'routing_policy_digest','routing_context_digest','registry_digest'}
    _fields(v,vf,'handoff verification');_digest(v['expected_operation_key'],True)
    if v['expected_operation_key']!=h['operation_key'] or v['exact_sha']!=h['exact_sha']:raise ValueError('handoff verification identity mismatch')
    for k in vf-{'expected_operation_key','exact_sha'}:_digest(v[k])
    if handler=='run_existing_native_check':
        _fields(p,{'check_id','argv'},'native check parameters');_text(p['check_id']);recipes._argv(p['argv'],'approved native argv')
        if h['access_mode']!='native_runtime' or h['operation_key'] is not None:raise ValueError('native check mode/operation mismatch')
    elif handler in {'observe_existing_operation','intake_existing_result','reconcile_existing_operation'}:
        expected={'operation_key','task_mode','journal_ref'}
        if handler=='reconcile_existing_operation' and isinstance(p,dict) and 'terminal_evidence_ref' in p:expected.add('terminal_evidence_ref')
        _fields(p,expected,'existing operation parameters');_digest(p['operation_key'],True);_text(p['journal_ref'],True)
        if 'terminal_evidence_ref' in p:_text(p['terminal_evidence_ref'],True)
        if (p['operation_key']!=h['operation_key'] or p['task_mode']!=h['task_mode'] or p['journal_ref']!=h['journal_ref']):raise ValueError('handoff existing operation mismatch')
        if handler!='reconcile_existing_operation' and (p['operation_key'] is None or p['journal_ref'] is None):raise ValueError('known operation required')
    elif handler=='submit_existing_transport':
        _fields(p,{'operation_key','task_mode'},'submit parameters');_digest(p['operation_key'])
        if h['access_mode']!='official_cli' or p['operation_key']!=h['operation_key'] or p['task_mode']!=h['task_mode']:raise ValueError('submit mode/operation mismatch')
    elif handler=='use_existing_official_ui_boundary':
        _fields(p,{'task_mode'},'UI parameters')
        if h['access_mode']!='official_ui' or p['task_mode']!=h['task_mode']:raise ValueError('UI mode mismatch')
    elif handler=='record_blocker':_fields(p,set(),'blocker parameters')
    else:
        _fields(p,{'decision'},'recovery parameters');_handoff_recovery(p['decision'],h)
    # Shape/identity validation creates no capability and cannot execute any action.
    return copy.deepcopy(h)

def record_history(store,expected_revision,event,*,read_authorization):
    """Existing authorized caller's append CAS; no lease/claim is created here."""
    if not callable(read_authorization):raise ValueError('fresh owner/action callback required')
    revision,history=store.read()
    if revision!=expected_revision or history is None:raise ValueError('stale or missing history revision')
    updated=recipes.append_history(history,event)
    if read_authorization() is False:raise ValueError('history action rejected')
    published=store.compare_and_swap(revision,updated)
    actual_revision,actual_history=store.read()
    if actual_revision!=published or actual_history!=updated:raise ValueError('history CAS readback unconfirmed; reconcile, never replay')
    return {'revision':published,'history':copy.deepcopy(actual_history)}

def main(argv=None):
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare']);parser.add_argument('--profile',required=True);parser.add_argument('--inputs');parser.add_argument('--project-root',default='.')
    for key in INPUT_NAMES:
        flags=['--routing-policy','--policy'] if key=='routing_policy' else ['--'+key.replace('_','-')]
        parser.add_argument(*flags,dest=key)
    parser.add_argument('--now',help='Explicit test-fixture clock only, not production freshness evidence')
    args=parser.parse_args(argv);root=Path(args.project_root).resolve()
    try:
        expanded={name:getattr(args,name) for name in INPUT_NAMES}
        if args.inputs:
            if any(v is not None for v in expanded.values()):raise ValueError('inputs and expanded snapshots conflict')
            values=load_inputs(args.inputs,project_root=root)
        else:
            if any(v is None for v in expanded.values()):raise ValueError('all expanded snapshot paths required')
            values={k:_read_json(_project_path(root,v)) for k,v in expanded.items()}
        profile=_read_json(_project_path(root,args.profile))
        now=args.now or datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        if args.now is not None:print('FIXTURE CLOCK: synthetic freshness input, not live qualification evidence',file=sys.stderr)
        result=prepare(profile,*(values[name] for name in INPUT_NAMES),now)
        print(json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False))
        return 1 if result['action']=='BLOCKED' else 0
    except (ValueError,TypeError,KeyError) as exc:
        print('Cloud entrypoint input rejected: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
