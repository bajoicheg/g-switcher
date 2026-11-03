"""Current execution/report boundaries, not a claim about arbitrary host text."""
import copy,sys,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import command_timestamp
import execution_continuity
import final_response_gate
import test_final_response_gate as legacy

NOW=datetime(2026,10,12,0,16,40,tzinfo=timezone.utc)

class ReportingBoundaryTests(unittest.TestCase):
 def timestamp(self,at=NOW):
  return {'schema':'command-timestamp-request/v1','command_id':'same-long-command','observed_at':at.isoformat(),'time_source':'runtime_clock','already_timestamped_command_ids':['same-long-command']}
 def test_later_substantive_report_is_not_suppressed_for_same_command(self):
  result=command_timestamp.render(self.timestamp(),now=NOW)
  self.assertEqual(result['display'],'[03:16 12.10]')
 def test_inferred_minutes_ahead_of_actual_clock_are_rejected(self):
  with self.assertRaises(ValueError):command_timestamp.render(self.timestamp(NOW+timedelta(minutes=3)),now=NOW)
 def test_each_emission_uses_boundary_clock_even_when_original_observation_is_recent(self):
  result=command_timestamp.render(self.timestamp(NOW-timedelta(seconds=50)),now=NOW)
  self.assertEqual(result['display'],'[03:16 12.10]')
 def test_old_released_lease_alone_cannot_authorize_current_unbound_final(self):
  f=legacy.T();record=f.released()
  result=final_response_gate.evaluate(legacy.INV_ID,record,legacy.continuity(True),{'owner_id':legacy.OWNER,'generation':1},legacy.receipt(record),record,'2026-01-01T10:02:00Z')
  self.assertFalse(result['final_response_allowed'],'release alone must not authorize unbound owner report/RCA closeout')
 def test_current_continuity_requires_authentic_reporting_even_without_material_entries(self):
  state=legacy.continuity(True);state['schema']='execution-continuity/v2'
  try: result=execution_continuity.evaluate(state,now_utc='2026-01-01T10:02:00Z')
  except ValueError:self.fail('current continuity schema must return a failed-closed reporting disposition')
  self.assertFalse(result['final_response_allowed'])
  self.assertIn('report',result['reason'])

class NativeReportingInventoryTests(unittest.TestCase):
 def start_native(self):
  import test_managed_host_bridge as native
  import managed_host_bridge as bridge
  import reporting_contract as reporting
  from git_document_store import GitDocumentStore
  self.native=native.ManagedHostBridgeTests();self.native.setUp()
  self.bridge=bridge;self.reporting=reporting
  self.handle=bridge.start(self.native.start_request())
  self.session=bridge._load_session(str(self.native.root/'handles'),self.handle['handle_id'])
  self.lease_store=bridge._lease_store(self.session)
  self.owned_revision,self.owned=self.lease_store.read()
  self.store=GitDocumentStore(self.native.repo,'origin',reporting.inventory_ref(self.handle['invocation_id']),self.native.store_id)
 def setUp(self):
  self.start_native();self.addCleanup(self.native.doCleanups)
  self.inv=self.handle['invocation_id'];self.cp='actual-native-test:checkpoint'
  self.doc={'schema':'execution-rca-inventory/v1','invocation_id':self.inv,'owner_id':self.handle['owner_id'],'generation':self.handle['generation'],'owned_lease_revision':self.owned_revision,'checkpoint_ref':self.cp,'material':[]}
  self.item={'anomaly_id':'observed-clock-inference','fix_key':'owner-reporting-rca-backlog-enforcement','status':'admitted_open','backlog_ref':'https://github.com/example/project/issues/113','problem':'Synthetic timestamp inferred instead of runtime clock','cause':'Missing read at emission boundary','evidence_refs':['public:synthetic-observed-inferred-time'],'correction_refs':[],'verification_revision':None,'deferral':None}
 def binding(self,doc=None):
  doc=doc or self.doc;rev,_=self.store.read();rev=self.store.compare_and_swap(rev,doc)
  request=self.reporting.capture(self.inv,'final','Подготовка проверена; открытые исправления сохранены.',clock=lambda:NOW)
  return {'schema':'execution-reporting-binding/v1','inventory_revision':rev,'report':request,'material_ids':[item['anomaly_id'] for item in doc['material']],'claimed_resolved_ids':[]}
 def check(self,binding):
  authority=self.reporting.authenticate(self.lease_store,binding,self.inv,self.cp)
  return authority.check(binding,now=NOW)
 def test_actual_owned_git_inventory_keeps_admitted_open_visible(self):
  self.doc['material']=[self.item];result=self.check(self.binding())
  self.assertEqual(result['open_rca'][0]['status'],'admitted_open')
  self.assertIn('owner-reporting-rca-backlog-enforcement (admitted_open)',result['report']['text'])
 def test_false_resolved_without_verification_receipt_is_rejected(self):
  self.doc['material']=[self.item];binding=self.binding();binding['claimed_resolved_ids']=[self.item['anomaly_id']]
  with self.assertRaisesRegex(ValueError,'false resolved'):self.check(binding)
 def test_missing_durable_admission_is_rejected(self):
  self.item['status']='diagnosed';self.doc['material']=[self.item]
  with self.assertRaisesRegex(ValueError,'admission'):self.check(self.binding())
 def test_resolved_status_without_correction_and_verification_is_rejected(self):
  self.item['status']='verified_resolved';self.doc['material']=[self.item]
  with self.assertRaisesRegex(ValueError,'verification'):self.check(self.binding())
 def test_omitted_material_inventory_is_rejected(self):
  self.doc['material']=[self.item];binding=self.binding();binding['material_ids']=[]
  with self.assertRaisesRegex(ValueError,'omitted'):self.check(binding)
 def test_stale_inventory_revision_is_rejected(self):
  binding=self.binding();self.doc['material']=[self.item];self.binding()
  with self.assertRaisesRegex(ValueError,'stale'):self.check(binding)
 def test_unowned_or_substituted_original_revision_is_rejected(self):
  self.doc['owner_id']='another-owner'
  with self.assertRaisesRegex(ValueError,'owned lease'):self.check(self.binding())
 def test_caller_boolean_is_not_native_reporting_authority(self):
  state=legacy.continuity(True);state.update(schema='execution-continuity/v2',reporting_binding=self.binding(),invocation_id=self.inv,checkpoint_ref=self.cp)
  result=execution_continuity.evaluate(state,reporting_authority=True,now_utc=NOW.isoformat())
  self.assertFalse(result['final_response_allowed'])
  self.assertIn('native reporting authority',result['reason'])
 def test_current_inventory_cannot_erase_authentic_material_history(self):
  self.doc['material']=[self.item];self.binding()
  self.doc['material']=[]
  with self.assertRaisesRegex(ValueError,'material history'):self.check(self.binding())
 def test_local_raw_digest_label_cannot_claim_verified_resolution(self):
  from git_document_store import GitDocumentStore
  import hashlib
  ref=self.store.ref+'-verification-'+hashlib.sha256(self.item['fix_key'].encode()).hexdigest()[:24]
  verification=GitDocumentStore(self.native.repo,'origin',ref,self.native.store_id)
  receipt={'schema':'rca-verification-receipt/v1','invocation_id':self.inv,'anomaly_id':self.item['anomaly_id'],'fix_key':self.item['fix_key'],'correction_refs':['caller:correction'],'regression_exit_code':0,'evidence_refs':self.item['evidence_refs'],'raw_terminal_digest':'sha256:'+'0'*64}
  rev=verification.compare_and_swap(None,receipt)
  self.item.update(status='verified_resolved',correction_refs=receipt['correction_refs'],verification_revision=rev);self.doc['material']=[self.item]
  with self.assertRaisesRegex(ValueError,'raw terminal'):self.check(self.binding())
 def test_exact_raw_regression_receipt_binds_correction_and_rejects_tampering(self):
  from git_document_store import GitDocumentStore
  import hashlib,subprocess
  start=datetime.now(timezone.utc);argv=['git','-C',str(self.native.repo),'diff','--check']
  proc=subprocess.run(argv,capture_output=True);end=datetime.now(timezone.utc)
  stdout,stderr=proc.stdout.decode(),proc.stderr.decode()
  self.assertEqual(proc.returncode,0,stderr)
  commit=self.native.base;tree=self.native.git('rev-parse',commit+'^{tree}')
  raw={'argv':argv,'stdout':stdout,'stderr':stderr,'return_code':proc.returncode,'started_at_utc':start.isoformat(),'finished_at_utc':end.isoformat(),'source_commit':commit,'root_tree':tree}
  self.item.update(status='verified_resolved',correction_refs=['git:'+commit])
  receipt={'schema':'rca-verification-receipt/v2','invocation_id':self.inv,'anomaly_id':self.item['anomaly_id'],'fix_key':self.item['fix_key'],'correction_refs':self.item['correction_refs'],'regression_exit_code':proc.returncode,'evidence_refs':self.item['evidence_refs'],'raw_terminal_digest':self.reporting._digest(raw),'raw_terminal':raw}
  verification=GitDocumentStore(self.native.repo,'origin',self.store.ref+'-verification-'+hashlib.sha256(self.item['fix_key'].encode()).hexdigest()[:24],self.native.store_id)
  rev=verification.compare_and_swap(None,receipt);self.item['verification_revision']=rev;self.doc['material']=[self.item]
  self.assertEqual(self.check(self.binding())['verified_resolved_ids'],[self.item['anomaly_id']])
  receipt['raw_terminal']['stdout']='altered after interpretation'
  rev=verification.compare_and_swap(rev,receipt);self.item['verification_revision']=rev
  with self.assertRaisesRegex(ValueError,'bytes'):self.check(self.binding())
 def test_continuation_requires_actual_current_inventory_and_emits_report(self):
  from continuation_cycle import decide
  import json
  request=json.loads((Path(__file__).resolve().parents[1]/'templates/continuation-cycle.json').read_text())
  binding=self.binding();request['schema']='continuation-cycle/v2';request['terminal_state']['invocation_id']=self.inv
  request['reporting_context']={'schema':'execution-continuity/v2','invocation_id':self.inv,'checkpoint_ref':self.cp,'reporting_binding':binding}
  authority=self.reporting.authenticate(self.lease_store,binding,self.inv,self.cp)
  result=decide(request,reporting_authority=authority,now_utc=NOW.isoformat())
  self.assertTrue(result['progress_update_emitted']);self.assertFalse(result['final_response_allowed']);self.assertIn('[03:16 12.10]',result['reporting']['report']['text'])
  self.doc['material']=[self.item];self.binding()
  with self.assertRaisesRegex(ValueError,'stale'):decide(request,reporting_authority=authority,now_utc=NOW.isoformat())

if __name__=='__main__':unittest.main()
