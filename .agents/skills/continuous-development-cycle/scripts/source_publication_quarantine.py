"""Sealed read-only source publication UNKNOWN quarantine, including claim-null.

A fresh descendant target is custody evidence, never confirmation of the old
conditional update. The original submitted journal and all lease facts survive.
"""
from __future__ import annotations
import copy
import operation_intent as op
import execution_lease_v2 as lease
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_remote_identity import remote_identity,isolated_remote_args
from managed_executor_runtime import VerifiedTerminalProof, _utc, _digest as native_digest
from project_lane_git import GitLaneIntegrationPublisher
from submission_recovery import _reference,_fresh,SHA
from unknown_recovery import _history,_identity

_SEAL=object()
SCHEMA='source-publication-quarantine/v1'


def _validate_proof(record,proof,at):
    fields={'schema','lease_revision','lease_digest','guard_digest','original_lease_revision','repository','source_ref','original_release','request_ref','handle_id','publication','observed_head','terminal','trusted_contract','observed_at_utc'}
    op._object(proof,fields,'source quarantine proof')
    guard=record.get('external_guard');release=record.get('last_release')
    if record.get('schema')!='execution-lease/v2' or record['owner_id'] is not None or record['invocation'] is not None or record['finalization'] is not None or guard is None or release is None or release['external_reconciliation']!='unknown_preserved':raise ValueError('exact released guarded UNKNOWN source lease required')
    if proof['schema']!='source-publication-quarantine-proof/v1' or proof['lease_digest']!=op._hash(record) or proof['guard_digest']!=op._hash(guard) or proof['repository']!=record['repository'] or proof['source_ref']!=record['source_ref'] or proof['original_release']!=release:raise ValueError('source quarantine must bind exact original guard/lease/release')
    for key in ('lease_revision','original_lease_revision','observed_head'):
        if not isinstance(proof[key],str) or not SHA.fullmatch(proof[key]):raise ValueError('immutable source quarantine revisions required')
    publication=proof['publication'];terminal=proof['terminal'];intent=guard['intent']
    if intent['binding']['backend']!='local_command' or intent['binding']['mode']!='writer':raise ValueError('native local writer source publication guard required')
    if (intent['state'] not in {'submitting','unknown'} or intent['task'] is not None or
        publication.get('status')!='submitted' or publication.get('shared_ref')!=record['source_ref'] or
        publication.get('result_commit')!=intent['binding']['candidate_sha'] or publication.get('intended_integrated_head')!=intent['binding']['candidate_sha'] or
        proof['observed_head']==publication.get('observed_shared_head') or terminal.get('status')!='succeeded' or terminal.get('request_ref')!=proof['request_ref']):raise ValueError('original submitted source journal/native integrated result required')
    ownership=terminal.get('ownership')
    if not isinstance(ownership,dict) or any(ownership.get(key)!=release[key] for key in ('owner_id','generation','invocation_id')):raise ValueError('exact original native release ownership required')
    claim=guard['submission_claim']
    if claim is not None and (claim['owner_id']!=release['owner_id'] or claim['generation']!=release['generation']):raise ValueError('original source claim/release mismatch')
    _fresh(proof['observed_at_utc'],at,op._timestamp(release['at_utc'],'release time'))


def quarantine_source_guard(record,proof,evidence_reference,at):
    """Pure canonical projection; native CAS additionally requires the sealed type."""
    lease.validate(record);_reference(evidence_reference);_validate_proof(record,proof,at)
    result=copy.deepcopy(record);result['external_guard']=None
    result.setdefault('submission_retirements',[]).append({'schema':SCHEMA,'outcome':'UNKNOWN','replay_forbidden':True,'guard':copy.deepcopy(record['external_guard']),'original_release':copy.deepcopy(record['last_release']),'proof':copy.deepcopy(proof),'evidence_reference':evidence_reference,'retired_at_utc':at})
    return lease.validate(result)


def validate_source_quarantine(entry,record):
    op._object(entry,{'schema','outcome','replay_forbidden','guard','original_release','proof','evidence_reference','retired_at_utc'},'source publication quarantine history')
    if entry['schema']!=SCHEMA or entry['outcome']!='UNKNOWN' or entry['replay_forbidden'] is not True:raise ValueError('source quarantine must retain UNKNOWN and no replay')
    _reference(entry['evidence_reference'])
    original=copy.deepcopy(record);original['external_guard']=copy.deepcopy(entry['guard']);original['last_release']=copy.deepcopy(entry['original_release']);original['owner_id']=None;original['invocation']=None;original['finalization']=None
    # Current lease may have acquired newer generations. Digest is checked against
    # the original proof snapshot through the archive, not today's unrelated state.
    proof=entry['proof'];original['generation']=proof['original_release']['generation']
    original['submission_retirements']=[e for e in record.get('submission_retirements',[]) if e is not entry and e!=entry]
    # Structural archive validation uses bound immutable release/guard and proof;
    # fresh original full bytes are authenticated again by the sealed CAS issuer.
    original_digest=proof['lease_digest'];projected=copy.deepcopy(proof);projected['lease_digest']=op._hash(original)
    _validate_proof(original,projected,entry['retired_at_utc']);op._digest(original_digest,'original source lease digest')
    return entry


def _authenticate(store,terminal,publication_store,source_remote,pins,at):
    if type(store) is not GitLeaseStore or type(publication_store) is not GitDocumentStore or type(terminal) is not VerifiedTerminalProof:raise ValueError('genuine native lease/publication/terminal capabilities required')
    required={'lease_revision','lease_digest','original_lease_revision','handle_root','handle_id','request_ref','publication_revision','publication_digest','operation_id','source_remote_id','control_store_id','owner_decision','publication_processes'}
    op._object(pins,required,'independent configured source quarantine pins')
    op._timestamp(at,'source quarantine request time')
    revision,record=store.read()
    if revision!=pins['lease_revision'] or op._hash(record)!=pins['lease_digest'] or store.store_id!=pins['control_store_id'] or publication_store.store_id!=store.store_id:raise ValueError('source quarantine endpoint/current lease drift')
    original=store.read_revision(pins['original_lease_revision'])
    if original!=record:raise ValueError('exact immutable original released source lease required')
    histories=_history(store);started=False
    for rev,row in histories:
        if rev==pins['original_lease_revision']:started=True
        if started and row!=original:raise ValueError('original source lease history changed')
    release=record['last_release'];owned={'owner_id':release['owner_id'],'generation':release['generation']}
    verified=terminal.revalidate_for(store,release['invocation_id'],owned,terminal._receipt)
    if verified.get('request_ref')!=pins['request_ref']:raise ValueError('original native request substituted')
    from managed_host_bridge import _load_session,_runtime
    session=_load_session(pins['handle_root'],pins['handle_id'])
    if (session['handle_id']!=pins['handle_id'] or session['invocation_id']!=release['invocation_id'] or session['publication_ref']!=publication_store.ref or session['plan']['coordination_store_id']!=store.store_id or session['release_receipt']!=terminal._receipt or session['lease_coordination_ref']!=store.ref):raise ValueError('original handle/pool/release/source channel mismatch')
    runtime=_runtime(session);request=runtime._request(session['task_id'],session['attempt_id'])
    if request is None or native_digest(request)!=pins['request_ref']:raise ValueError('original bridge request/handle mismatch')
    if remote_identity(store.repo,source_remote)!=pins['source_remote_id']:raise ValueError('source publication endpoint drift')
    publisher=GitLaneIntegrationPublisher(store.repo,source_remote,record['source_ref'],pins['source_remote_id'],attempt_store=publication_store,attempt_store_id=store.store_id)
    p_revision,p_state=publisher._read_attempt_state();historical=publication_store.read_revision(pins['publication_revision'])
    publication=historical.get('attempts',{}).get(pins['operation_id'])
    if not isinstance(publication,dict) or op._hash(publication)!=pins['publication_digest'] or publication.get('status')!='submitted' or p_state['attempts'].get(pins['operation_id'])!=publication:raise ValueError('exact immutable original SUBMITTED journal required')
    from managed_host_bridge import _read
    result=_read(__import__('pathlib').Path(request['journal_directory'])/'result.json')
    if (runtime.store.store_id,runtime.store.ref,runtime.plan['pool_id'])!=(terminal._runtime.store.store_id,terminal._runtime.store.ref,terminal._runtime.plan['pool_id']):raise ValueError('original native result pool channel substituted')
    pool_revision,pool_state=runtime.store.read()
    accepted=next((row for row in pool_state['tasks'] if row['id']==session['task_id']),None)
    if (not isinstance(result,dict) or accepted is None or accepted['status']!='succeeded' or not accepted['integrated'] or
        accepted['accepted_result_ref']!=native_digest(result) or result.get('task_id')!=session['task_id'] or result.get('attempt_id')!=session['attempt_id']):raise ValueError('original source publication requires exact native accepted/integrated result')
    # An interrupted publisher can leave this informational cache empty after
    # genuine runtime release/acceptance. Never fill it from journal claims; the
    # fresh sealed proof and original pool/result digest remain mandatory.
    if publication['lane_id']!=session['task_id'] or publication['observed_shared_head']!=session['plan']['base_sha'] or session['result_commit'] not in (None,publication['result_commit']) or result.get('result_commit')!=publication['result_commit'] or verified['task_id']!=session['task_id'] or verified['attempt_id']!=session['attempt_id'] or next(t for t in session['plan']['tasks'] if t['id']==session['task_id'])['role']!='writer':raise ValueError('original source publication must join actual integrated writer result and handle')
    seen=False;previous=None
    for _,document in _history(publication_store):
        entry=document.get('attempts',{}).get(pins['operation_id'])
        if entry is None:
            if seen:raise ValueError('original publication journal history erased')
            continue
        seen=True
        if entry['status'] not in {'prepared','submitted'}:raise ValueError('original submitted publication history resolved/changed')
        immutable={key:value for key,value in entry.items() if key not in {'status','submitted_at_utc'}}
        expected={key:value for key,value in publication.items() if key not in {'status','submitted_at_utc'}}
        if immutable!=expected or previous=='submitted' and entry!=publication:raise ValueError('original publication journal ancestry tampered')
        previous=entry['status']
    decision=pins['owner_decision']
    op._object(decision,{'action','guard_digest','reference'},'configured administrative owner decision')
    if decision['action']!='quarantine_source_unknown_without_replay' or decision['guard_digest']!=op._hash(record['external_guard']):raise ValueError('exact owner source UNKNOWN quarantine decision required')
    _reference(decision['reference'])
    processes=pins['publication_processes']
    if not isinstance(processes,list) or not processes or len({p['pid'] for p in processes})!=len(processes):raise ValueError('complete original publication sender births required')
    for process in processes:_identity(process,absent=True)
    head=publisher._remote_head();config,remote=isolated_remote_args(store.repo,source_remote,pins['source_remote_id'])
    store._git(*config,'fetch','--no-tags','--no-write-fetch-head','--refmap=',remote,record['source_ref'])
    if head==publication['observed_shared_head'] or store._git('merge-base',publication['observed_shared_head'],head)!=publication['observed_shared_head'] or store._git('merge-base',publication['intended_integrated_head'],head)!=publication['intended_integrated_head']:raise ValueError('fresh target must advance original expected HEAD and retain candidate')
    if head!=publisher._remote_head() or p_revision!=publication_store.read()[0] or revision!=store.read()[0] or pool_revision!=runtime.store.read()[0]:raise ValueError('native source observations moved during authentication')
    # Finish physical observations after all network/history reads; archive the
    # actual completion clock, never the timestamp supplied before those reads.
    for process in verified['processes']:_identity({'pid':process['pid'],'birth':process['birth'],'boot_id':verified['boot_id']},absent=True)
    for process in processes:_identity(process,absent=True)
    observed_at=_utc()
    proof={'schema':'source-publication-quarantine-proof/v1','lease_revision':revision,'lease_digest':op._hash(record),'guard_digest':op._hash(record['external_guard']),'original_lease_revision':pins['original_lease_revision'],'repository':record['repository'],'source_ref':record['source_ref'],'original_release':copy.deepcopy(release),'request_ref':pins['request_ref'],'handle_id':pins['handle_id'],'publication':copy.deepcopy(publication),'observed_head':head,'terminal':verified,'trusted_contract':copy.deepcopy(pins),'observed_at_utc':observed_at}
    _validate_proof(record,proof,observed_at)
    return proof


class SourcePublicationQuarantine:
    def __init__(self,seal,store,terminal,publication_store,source_remote,pins,at):
        if seal is not _SEAL:raise ValueError('native source quarantine issuer required')
        self._seal=seal;self._store=store;self._terminal=terminal;self._publication_store=publication_store;self._source_remote=source_remote;self._pins=copy.deepcopy(pins);self._at=at
        self._proof=_authenticate(store,terminal,publication_store,source_remote,pins,at)
    @property
    def proof(self):
        return copy.deepcopy(self._proof)
    def revalidate(self,store,expected_revision,previous,entry):
        if self._seal is not _SEAL or store is not self._store or expected_revision!=self.proof['lease_revision'] or entry['proof']!=self.proof:raise ValueError('source quarantine CAS capability substituted')
        current=_authenticate(store,self._terminal,self._publication_store,self._source_remote,self._pins,self._at)
        # Fresh terminal observation timestamps may vary; all immutable bindings
        # and fresh absence checks are revalidated without rewriting archived proof.
        _fresh(self.proof['observed_at_utc'],_utc(),op._timestamp(entry['original_release']['at_utc'],'original release'))
        _fresh(entry['retired_at_utc'],_utc(),op._timestamp(self.proof['observed_at_utc'],'original observation'))
        current['terminal']['observed_at_utc']=self._proof['terminal']['observed_at_utc']
        current['observed_at_utc']=self.proof['observed_at_utc']
        if current!=self.proof or previous['external_guard']!=entry['guard'] or previous['last_release']!=entry['original_release']:raise ValueError('source quarantine original facts changed before CAS')


def authenticate_source_publication_quarantine(store,*,terminal_proof,publication_store,source_remote,trusted_contract,at):
    return SourcePublicationQuarantine(_SEAL,store,terminal_proof,publication_store,source_remote,trusted_contract,at)


def quarantine_source_publication_cas(store,expected_revision,proof,evidence_reference,at):
    if type(proof) is not SourcePublicationQuarantine:raise ValueError('native issued source quarantine required')
    revision,record=store.read()
    if revision!=expected_revision or revision!=proof.proof['lease_revision']:raise ValueError('stale source quarantine revision; observe without replay')
    changed=quarantine_source_guard(record,proof.proof,evidence_reference,at)
    revision=store.compare_and_swap(expected_revision,changed,retirement_capability=proof)
    actual,current=store.read()
    if actual!=revision or current!=changed:raise ValueError('source quarantine reply moved; observe without replay')
    return {'revision':revision,'record':changed,'outcome':'UNKNOWN','authorizes_submission':False,'conditional_update':False}


def observe_source_publication_quarantine(store,*,operation_key,evidence_reference):
    if type(store) is not GitLeaseStore:raise ValueError('native source lease required')
    revision,record=store.read()
    entries=[entry for entry in record.get('submission_retirements',[]) if entry['schema']==SCHEMA and entry['guard']['operation_key']==operation_key and entry['evidence_reference']==evidence_reference]
    if len(entries)!=1:raise ValueError('exact original source quarantine not observed')
    return {'revision':revision,'record':record,'outcome':'UNKNOWN','authorizes_submission':False,'conditional_update':False}


def assert_source_publication_not_quarantined(store,*,operation_id,result_commit,intended_commit):
    if type(store) is not GitLeaseStore:raise ValueError('native quarantine admission store required')
    _,record=store.read()
    if record is None:raise ValueError('canonical source quarantine custody missing')
    for entry in record.get('submission_retirements',[]):
        if entry['schema']==SCHEMA:
            old=entry['proof']['publication'];candidate=entry['guard']['intent']['binding']['candidate_sha']
            if operation_id in {old['operation_id'],entry['guard']['operation_key']} or candidate in {result_commit,intended_commit}:raise ValueError('quarantined original source operation/candidate cannot replay under new keys/refs')
