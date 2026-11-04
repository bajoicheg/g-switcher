"""New delayed-finish risks using real native reporting/lease gates and fake I/O.

No native task, child process, provider, Git transport or live state is used.
"""
import copy
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, '/opt/cdc-tools/cdc-3.6.8-prehandle-20261022/scripts')
sys.path.insert(0, str(ROOT/'scripts'))
import managed_host_bridge as bridge
import reporting_contract as reporting
import execution_lease_v2 as leasev2
from git_lease_store import GitLeaseStore


class FinishFixture:
    """In-memory transports around unchanged real native authority and gates."""
    def __init__(self, status='succeeded', publication_delay=0, finalization_delay=0, pool_delay=0):
        self.at = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
        self.status=status;self.publication_delay=publication_delay
        self.finalization_delay=finalization_delay;self.pool_delay=pool_delay
        self.owner='22222222-2222-4222-8222-222222222222';self.invocation='native-freshness-fixture'
        self.task='freshness-task';self.attempt=self.task+'-a1';self.checkpoint='fixture:original-checkpoint'
        invocation={'invocation_id':self.invocation,'automation_id':None,'conversation_id':None,
                    'execution_surface':'managed','started_at_utc':self.utc()}
        # Synthetic ownership setup only. Actual closeout/reporting checks below
        # execute the production lease, continuity and final response gates.
        with patch.object(leasev2.terminal_capability_api,'validate_verified',return_value={}):
            self.current=leasev2.acquire(leasev2.initialize('fixture/project','refs/heads/main'),
                self.owner,self.utc(),invocation=invocation,terminal_capability=object(),ttl=1200)
        self.revision='1'*40;self.history={self.revision:copy.deepcopy(self.current)};self.owned_revision=self.revision
        self.inventory_revision='2'*40
        self.item={'anomaly_id':'original-open','fix_key':'original-fix','status':'admitted_open',
            'backlog_ref':self.checkpoint,'problem':'Original failure','cause':'UNKNOWN',
            'evidence_refs':[self.checkpoint],'correction_refs':[],'verification_revision':None,'deferral':None}
        self.inventory={'schema':'execution-rca-inventory/v1','invocation_id':self.invocation,
            'owner_id':self.owner,'generation':1,'owned_lease_revision':self.owned_revision,
            'checkpoint_ref':self.checkpoint,'material':[self.item]}
        self.inventory_history={self.inventory_revision:copy.deepcopy(self.inventory)}
        self.inventory_store=SimpleNamespace(read=lambda:(self.inventory_revision,copy.deepcopy(self.inventory)),
            read_revision=lambda revision:copy.deepcopy(self.inventory_history[revision]),
            _git=Mock(side_effect=lambda *args:self.inventory_revision))
        self.lease=GitLeaseStore.__new__(GitLeaseStore)
        self.lease.repo=Path('/isolated-fixture');self.lease.remote='origin';self.lease.ref='refs/heads/cdc/lease'
        self.lease.store_id='sha256:'+'3'*64
        self.lease.read=lambda:(self.revision,copy.deepcopy(self.current))
        self.lease.read_revision=lambda revision:copy.deepcopy(self.history[revision])
        self.lease.compare_and_swap=self.cas
        unknown={'value':None,'unknown_reason':'UNKNOWN'}
        observation={'schema':'operation-observation/v1','observation_ref':'fixture:original-operation',
            'comparison_group':'fixture','elapsed_seconds':10,
            'tokens':{'value':None,'provenance':'unknown','source':None,'basis':None},'budget_ref':'fixture:original-budget',
            'phases':{key:dict(unknown) for key in ('startup','implementation','validation','wait')},
            'delivery':{key:dict(unknown) for key in ('delivered','escaped_defects')}}
        completed={'started_at_utc':(self.at-timedelta(seconds=10)).isoformat(),
                   'finished_at_utc':self.utc(),'observation':observation}
        self.binding={'schema':'execution-reporting-binding/v1','inventory_revision':self.inventory_revision,
            'report':reporting.capture(self.invocation,'final','Исходный результат UNKNOWN и открытая причина сохранены.',
                                       completed_operation=completed,clock=lambda:self.at),
            'material_ids':['original-open'],'claimed_resolved_ids':[]}
        self.request={'schema':'managed-host-finish/v2','handle_root':'/isolated-fixture/handles',
            'handle_id':'44444444-4444-4444-8444-444444444444','checkpoint_ref':self.checkpoint,
            'output_refs':['out:result'],'evidence_refs':['evidence:checks'],'reporting_binding':copy.deepcopy(self.binding)}
        self.saved={'task_id':self.task,'attempt_id':self.attempt,'handle_id':self.request['handle_id'],
            'owner_id':self.owner,'generation':1,'invocation_id':self.invocation,'state':'owned',
            'lease_repository':'fixture/project','lease_source_ref':'refs/heads/main','publication_ref':'refs/heads/cdc/publication',
            'runtime_launch_id':'original-launch','reservation_token':'original-reservation','repo_root':'/isolated-fixture',
            'plan':{'change_id':'original-scope','base_sha':'a'*40,'coordination_store_id':self.lease.store_id,
                'tasks':[{'id':self.task,'role':'writer','required':True,
                          'expected_outputs':['out:result'],'expected_evidence':['evidence:checks']}]},
            'result_commit':None,'publication':None,'release_receipt':None,'final_response_gate':None,'reporting_binding':None}
        self.snapshots=[];self.gates=[];self.on_publish=None;self.release_calls=0;self.rejections=[]
        self.native=SimpleNamespace(observe=self.observe,rejection=lambda *args:None,
            release_execution_lease=self.release,reject_preparation=self.reject,
            store=SimpleNamespace(read=lambda:('pool',{'tasks':[{'id':self.task,'status':'running',
                'active_attempt_id':self.attempt,'reservation_token':'original-reservation',
                'accepted_result_ref':None,'integrated':False}]})))

    def utc(self):return self.at.isoformat().replace('+00:00','Z')
    def advance(self,seconds):self.at+=timedelta(seconds=seconds)
    def observe(self,*args):return {'status':'awaiting_release','pending_terminal_status':self.status}
    def save(self,session):self.saved=copy.deepcopy(session);self.snapshots.append(copy.deepcopy(session))
    def cas(self,prior,record):
        if prior!=self.revision:raise ValueError('fixture CAS mismatch')
        leasev2.validate(record)
        self.revision=hashlib.sha1((str(len(self.history))+json.dumps(record,sort_keys=True)).encode()).hexdigest()
        self.current=copy.deepcopy(record);self.history[self.revision]=copy.deepcopy(record)
        if (record.get('finalization') or {}).get('state')=='draining':self.advance(self.finalization_delay)
        return self.revision
    def publish(self,session,result):
        self.advance(self.publication_delay)
        if self.on_publish:self.on_publish(session)
        return {'conditional_update':True,'evidence_ref':'original-publication'}
    def release(self,store,revision,repository,source_ref,owner,generation,invocation,task,attempt,at):
        self.release_calls+=1
        released=leasev2.release(self.current,owner,generation,invocation,at)
        revision=self.cas(revision,released)
        return {'release_receipt':{'schema':'execution-release-receipt/v1','lease_revision':revision,
                                   'release':copy.deepcopy(released['last_release'])}}
    def wait(self,*args):return {'status':self.status}
    def complete_pool(self,*args):self.advance(self.pool_delay)
    def reject(self,*args,**kwargs):
        self.rejections.append(copy.deepcopy(kwargs['disposition']))
        if kwargs.get('reconcile'):self.advance(self.pool_delay)
        return {'observation':{'status':'succeeded'},'rejection_ref':'fixture:original-rejection'}

    @contextmanager
    def run(self):
        fixture=self
        class RuntimeDateTime(datetime):
            @classmethod
            def now(cls,tz=None):return fixture.at.astimezone(tz)
        real_ready=leasev2.mark_ready;real_boundary=bridge.final_response_gate.release_boundary
        def checked_ready(*args,**kwargs):
            binding=kwargs['continuity_state']['reporting_binding']
            if binding!=self.saved['reporting_binding']:raise AssertionError('report must persist before mark_ready')
            self.gates.append(copy.deepcopy(binding))
            return real_ready(*args,**kwargs)
        def checked_boundary(*args,**kwargs):
            binding=args[2]['reporting_binding']
            if binding!=self.saved['reporting_binding']:raise AssertionError('report must persist before release gate')
            self.gates.append(copy.deepcopy(binding))
            return real_boundary(*args,**kwargs)
        with ExitStack() as stack:
            replacements={'_utc':self.utc,'_load_session':lambda *args:copy.deepcopy(self.saved),
                '_save_session':self.save,'_runtime':lambda session:self.native,'_lease_store':lambda session:self.lease,
                '_recover_session':lambda *args:(copy.deepcopy(self.saved),self.native,self.lease),
                '_renew_for_result':lambda *args,**kwargs:None,
                '_result':lambda *args:('b'*40,['docs/result.md'],None),'_publish':self.publish,
                '_wait_terminal':self.wait,'_complete_pool':self.complete_pool,
                '_routes':lambda session:('origin',self.lease.store_id),
                'GitDocumentStore':lambda *args,**kwargs:SimpleNamespace(read=lambda:(None,None))}
            self.mocks={name:stack.enter_context(patch.object(bridge,name,side_effect=call)) for name,call in replacements.items()}
            stack.enter_context(patch.object(reporting,'datetime',RuntimeDateTime))
            stack.enter_context(patch.object(reporting,'GitDocumentStore',return_value=self.inventory_store))
            stack.enter_context(patch.object(leasev2,'mark_ready',side_effect=checked_ready))
            stack.enter_context(patch.object(bridge.final_response_gate,'release_boundary',side_effect=checked_boundary))
            capture=stack.enter_context(patch.object(reporting,'capture',wraps=reporting.capture))
            yield capture


class NativeReportFreshnessTests(unittest.TestCase):
    def assert_preserved(self,fixture,initial_request,inventory,history):
        self.assertEqual(fixture.request,initial_request)
        self.assertEqual(fixture.inventory,inventory)
        self.assertEqual(fixture.inventory_history,history)
        self.assertEqual(fixture.history[fixture.owned_revision]['owner_id'],fixture.owner)
        for binding in fixture.gates:
            self.assertEqual({key:value for key,value in binding.items() if key!='report'},
                             {key:value for key,value in fixture.binding.items() if key!='report'})
            self.assertEqual({key:value for key,value in binding['report'].items() if key not in ('report_id','observed_at_utc')},
                             {key:value for key,value in fixture.binding['report'].items() if key not in ('report_id','observed_at_utc')})
        report_ids=[fixture.binding['report']['report_id']]+[binding['report']['report_id'] for binding in fixture.gates]
        self.assertEqual(len(set(report_ids)),len(report_ids))

    def test_delayed_publication_and_finalization_refresh_before_real_mark_ready(self):
        fixture=FinishFixture(publication_delay=193,finalization_delay=160)
        before=copy.deepcopy((fixture.request,fixture.inventory,fixture.inventory_history))
        with fixture.run() as capture:
            result=bridge._finish_locked(fixture.request)
        self.assertTrue(result['managed_finish_allowed']);self.assertTrue(result['scope_complete'])
        self.assertFalse(result['final_response_allowed']);self.assertTrue(result['controller_exit_required'])
        self.assertEqual(capture.call_count,2);self.assertEqual(len(fixture.gates),2)
        self.assertEqual(fixture.gates[0]['report']['observed_at_utc'],fixture.utc())
        self.assert_preserved(fixture,*before)

    def test_delayed_pool_closeout_refreshes_again_before_real_release_boundary(self):
        fixture=FinishFixture(pool_delay=160)
        before=copy.deepcopy((fixture.request,fixture.inventory,fixture.inventory_history))
        with fixture.run() as capture:
            result=bridge._finish_locked(fixture.request)
        self.assertEqual(capture.call_count,2)
        self.assertNotEqual(fixture.gates[0]['report']['observed_at_utc'],fixture.gates[1]['report']['observed_at_utc'])
        self.assertEqual(fixture.gates[1]['report']['observed_at_utc'],fixture.utc())
        self.assertEqual(fixture.saved['final_response_gate']['reporting']['open_rca'],
                         [{key:fixture.item[key] for key in ('anomaly_id','fix_key','status','backlog_ref')}])
        self.assertEqual(fixture.saved['final_response_gate']['reporting']['verified_resolved_ids'],[])
        self.assertTrue(result['managed_finish_allowed']);self.assert_preserved(fixture,*before)

    def test_initial_stale_malformed_or_false_resolved_binding_fails_before_refresh_and_publication(self):
        for kind in ('stale','malformed','false_resolved'):
            with self.subTest(kind=kind):
                fixture=FinishFixture()
                if kind=='stale':fixture.request['reporting_binding']['report']['observed_at_utc']=(fixture.at-timedelta(seconds=193)).isoformat()
                elif kind=='malformed':fixture.request['reporting_binding']['extra']=True
                else:fixture.request['reporting_binding']['claimed_resolved_ids']=['original-open']
                with fixture.run() as capture:
                    with self.assertRaises(ValueError):bridge._finish_locked(fixture.request)
                capture.assert_not_called();fixture.mocks['_publish'].assert_not_called()
                fixture.mocks['_recover_session'].assert_not_called()
                self.assertEqual(fixture.snapshots,[]);self.assertEqual(fixture.release_calls,0)

    def test_new_report_cannot_refresh_changed_inventory_or_false_resolution_into_authority(self):
        for kind in ('inventory_moved','false_resolution'):
            with self.subTest(kind=kind):
                fixture=FinishFixture(publication_delay=193)
                def changed(session):
                    if kind=='inventory_moved':fixture.inventory_revision='9'*40
                    else:session['reporting_binding']['claimed_resolved_ids']=['original-open']
                fixture.on_publish=changed
                with fixture.run() as capture:
                    with self.assertRaisesRegex(ValueError,'hard execution-continuity gate'):bridge._finish_locked(fixture.request)
                self.assertEqual(capture.call_count,1);self.assertEqual(fixture.release_calls,0)
                self.assertEqual(fixture.current['owner_id'],fixture.owner)
                self.assertEqual(fixture.saved['reporting_binding']['inventory_revision'],'2'*40)

    def test_failed_and_unknown_outcomes_never_gain_scope_completion_or_resolution(self):
        for status in ('failed','cancelled','timed_out'):
            with self.subTest(status=status):
                fixture=FinishFixture(status=status,finalization_delay=193)
                original_wait=fixture.wait
                def delayed_wait(*args):fixture.advance(160);return original_wait(*args)
                fixture.wait=delayed_wait
                before=copy.deepcopy((fixture.request,fixture.inventory,fixture.inventory_history))
                with fixture.run() as capture:result=bridge._finish_locked(fixture.request)
                self.assertFalse(result['scope_complete']);self.assertEqual(result['worker_status'],status)
                self.assertEqual(result['release_receipt']['release']['completion_reason'],'resumable_blocker')
                fixture.mocks['_publish'].assert_not_called();fixture.mocks['_complete_pool'].assert_not_called()
                self.assertEqual(capture.call_count,2)
                self.assertEqual(fixture.saved['final_response_gate']['reporting']['verified_resolved_ids'],[])
                self.assert_preserved(fixture,*before)
        fixture=FinishFixture(status='unknown')
        with fixture.run() as capture:
            with self.assertRaisesRegex(ValueError,'terminal worker awaiting'):bridge._finish_locked(fixture.request)
        capture.assert_not_called();fixture.mocks['_publish'].assert_not_called()
        self.assertEqual(fixture.release_calls,0)

    def test_rejected_preparation_refreshes_shared_and_post_release_gates_without_rewriting_disposition(self):
        fixture=FinishFixture(finalization_delay=193,pool_delay=160)
        request={key:copy.deepcopy(fixture.request[key]) for key in ('handle_root','handle_id','checkpoint_ref','reporting_binding')}
        request.update(schema='managed-host-reject-preparation/v1',review_ref='fixture:negative-review')
        before=copy.deepcopy((fixture.request,fixture.inventory,fixture.inventory_history))
        with fixture.run() as capture:result=bridge._reject_preparation_locked(request)
        self.assertTrue(result['managed_finish_allowed']);self.assertFalse(result['scope_complete'])
        self.assertFalse(result['final_response_allowed']);self.assertEqual(capture.call_count,2)
        self.assertEqual(fixture.saved['negative_review']['reporting_binding'],request['reporting_binding'])
        self.assertEqual(fixture.rejections[0],fixture.rejections[1])
        self.assertEqual(fixture.gates[-1]['report']['observed_at_utc'],fixture.utc())
        self.assert_preserved(fixture,*before)


if __name__=='__main__':unittest.main()
