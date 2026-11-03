"""Runtime pin change may preserve one authenticated already-released failure."""
import copy,json,sys,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import test_released_terminal_boot_recovery as fixtures
from git_document_store import GitDocumentStore
import unknown_recovery as recovery
import operation_intent as operation

class ReleasedRegistryMigrationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixtures.ReleasedBootTerminalTests.setUpClass()
  cls.addClassCleanup(fixtures.ReleasedBootTerminalTests.doClassCleanups)
 def setUp(self):
  self.native=fixtures.ReleasedBootTerminalTests('test_authentic_released_failure_issues_sealed_proof_without_state_or_source_effects')
  self.native.setUp();self.addCleanup(self.native.doCleanups)
  s=self.native.session;f=self.native.fixture
  start=json.loads((f.root/'start.json').read_text())
  finished=json.loads((f.root/'finished.json').read_text())['finished']
  self.store=GitDocumentStore(f.repo,'origin','refs/heads/cdc/registry-'+uuid.uuid4().hex,f.store_id)
  self.document={'schema':'cdc-vps-control/v1','registry_digest':'sha256:'+'a'*64,'tasks':{'closure':{'state':'terminal_pending','task':{'id':'closure','schema':'cdc-vps-task/v2','source_sha':s['plan']['base_sha'],'role':'writer','budget':{'ci_starts':0}},'budget':{'spent':17,'outcome':'UNKNOWN','reservations':['original']},'operation':{'handle_id':s['handle_id'],'attempt_id':s['attempt_id'],'start_request':start,'start_request_digest':operation._hash(start),'finish_result':finished},'result':None}},'queue':{'items':[{'original_id':'queued-original','state':'acked'}]}}
  self.revision=self.store.compare_and_swap(None,self.document);self.old=self.document['registry_digest'];self.new='sha256:'+'b'*64
 def migrate(self,proofs):
  return recovery.migrate_intake_registry_cas(self.store,self.revision,self.old,self.new,terminal_reconciliations=proofs)
 def test_authentic_released_original_allows_only_registry_digest_change(self):
  proof=self.native.verify();result=self.migrate({'closure':proof});expected=copy.deepcopy(self.document);expected['registry_digest']=self.new
  self.assertEqual(result['document'],expected);self.assertEqual(self.store.read()[1],expected)
  self.assertEqual(result['document']['tasks']['closure']['state'],'terminal_pending')
  self.assertEqual(result['document']['tasks'],self.document['tasks']);self.assertEqual(result['document']['queue'],self.document['queue'])
 def test_missing_or_serialized_proof_cannot_cross_active_migration_barrier(self):
  with self.assertRaisesRegex(ValueError,'active attempts'):recovery.migrate_intake_registry_cas(self.store,self.revision,self.old,self.new)
  with self.assertRaises(ValueError):self.migrate({'closure':dict(self.native.verify())})
  self.assertEqual(self.store.read(),(self.revision,self.document))
 def test_foreign_handle_or_additional_unknown_attempt_stays_blocked(self):
  proof=self.native.verify();bad=copy.deepcopy(self.document);bad['tasks']['closure']['operation']['handle_id']=str(uuid.uuid4())
  self.revision=self.store.compare_and_swap(self.revision,bad)
  with self.assertRaises(ValueError):self.migrate({'closure':proof})
  bad['tasks']['closure']['operation']['handle_id']=self.native.session['handle_id'];bad['tasks']['other']={'state':'unknown','task':{'id':'other'}}
  self.revision=self.store.compare_and_swap(self.revision,bad)
  with self.assertRaises(ValueError):self.migrate({'closure':proof})
  self.assertEqual(self.store.read()[1],bad)
 def test_fresh_native_cas_revalidates_root_custody_instead_of_saved_proof(self):
  proof=self.native.verify();read=self.store.read;calls=0
  def read_and_revoke():
   nonlocal calls
   calls+=1
   if calls==2:self.native.record['release_ref']='sha256:'+'0'*64
   return read()
  self.store.read=read_and_revoke
  with self.assertRaises(ValueError):self.migrate({'closure':proof})
  self.assertEqual(read(),(self.revision,self.document))

if __name__=='__main__':unittest.main()
