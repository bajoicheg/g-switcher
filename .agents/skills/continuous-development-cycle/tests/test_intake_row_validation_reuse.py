"""Distinct changed risks: exact per-call row reuse and fresh final custody."""
import copy,pathlib,sys,unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
import unknown_recovery as n
import immutable_history_cache as history_cache
class RowReuseTests(unittest.TestCase):
 def test_exact_canonical_keys_detach_and_do_not_equate_boolean_numeric_rows(self):
  calls=[]
  with patch.object(n,'_validate_prehandle_disposition_row',side_effect=lambda row:calls.append(copy.deepcopy(row))):
   batch=n._DispositionRowValidation();row={'value':1};batch.check(row);batch.check(copy.deepcopy(row))
   row['value']=True;batch.check(row);row['value']='mutated caller'
   self.assertEqual(calls,[{'value':1},{'value':True}]);batch.revalidate()
   self.assertEqual(calls[2:],[{'value':1},{'value':True}])
 def test_capacity_falls_back_failed_rows_never_reuse_and_calls_do_not_share(self):
  calls=[]
  def validate(row):
   calls.append(copy.deepcopy(row))
   if row.get('bad'):raise ValueError('invalid')
  with patch.object(n,'_validate_prehandle_disposition_row',side_effect=validate),patch.object(n,'_DISPOSITION_ROWS_MAX',1):
   batch=n._DispositionRowValidation()
   for row in ({'a':1},{'a':1},{'a':2},{'a':2}):batch.check(row)
   for _ in range(2):
    with self.assertRaises(ValueError):batch.check({'bad':True})
   batch.revalidate();n._DispositionRowValidation().check({'a':1})
   self.assertEqual(calls.count({'a':1}),3);self.assertEqual(calls.count({'a':2}),2);self.assertEqual(calls.count({'bad':True}),2)
  calls.clear()
  with patch.object(n,'_validate_prehandle_disposition_row',side_effect=validate),patch.object(n,'_DISPOSITION_ROWS_BYTES',1):
   batch=n._DispositionRowValidation();batch.check({'a':1});batch.check({'a':1});batch.revalidate()
   self.assertEqual(calls,[{'a':1},{'a':1}])
 def fixture(self):
  from test_native_prehandle_disposition import PrehandleTests
  f=PrehandleTests();f.setUp();self.addCleanup(f.doCleanups);result=f.dispose();row=result['row'];head=result['revision']
  for _ in range(8):head=f.raw_commit({'schema':n.INTAKE_SCHEMA,'tasks':{'task-one':row}},head)
  return f,head,row
 def test_real_git_repeated_tombstone_shared_by_fold_and_guard_keeps_original_liability(self):
  f,head,row=self.fixture();original=n._validate_prehandle_disposition_row;calls=[]
  def counted(value):calls.append(copy.deepcopy(value));return original(value)
  with patch.object(n,'_validate_prehandle_disposition_row',side_effect=counted):
   result=n.validate_intake_dispositions(f.store,head,{'task-one':row},{})
  # Selected-row validation twice, first historical validation and fresh final.
  self.assertLessEqual(len(calls),5)
  self.assertEqual(result['task-one'],row['result']['administrative_disposition'])
  self.assertEqual(result['task-one']['original_row']['budget'],f.row['budget']);self.assertEqual(result['task-one']['original_effect'],'UNKNOWN')
  self.assertEqual(f.store.read()[0],head)
 def test_fresh_final_original_validator_denies_volatile_start_custody_drift(self):
  f,head,row=self.fixture();original=n._DispositionRowValidation.revalidate;calls=[]
  def drift(batch):
   import managed_host_bridge
   with patch.object(managed_host_bridge,'_validate_start',side_effect=ValueError('current route drift')):
    calls.append(True);return original(batch)
  with patch.object(n._DispositionRowValidation,'revalidate',new=drift):
   with self.assertRaisesRegex(ValueError,'current route drift'):n.validate_intake_dispositions(f.store,head,{'task-one':row},{})
  self.assertEqual(calls,[True]);self.assertEqual(f.store.read()[0],head)
 def test_reuse_never_skips_late_object_authentication_replay_or_final_head(self):
  f,head,row=self.fixture();document={'schema':n.INTAKE_SCHEMA,'tasks':{'task-one':row}}
  # A cross-ID replay must fail even though the original disposed row is cached.
  duplicate=copy.deepcopy(document);duplicate['tasks']['different-id']=copy.deepcopy(row)
  bad=f.raw_commit(duplicate,head);restored=f.raw_commit(document,bad)
  with self.assertRaisesRegex(ValueError,'cannot replay'):n.validate_intake_dispositions(f.store,restored,{'task-one':row},{})
  self.assertEqual(history_cache._cache.get(history_cache._context(f.store,'document'))['chain'][-1][0],restored)
  f.doCleanups()
  f,head,row=self.fixture();document={'schema':n.INTAKE_SCHEMA,'tasks':{'task-one':row}}
  read=f.store.read;calls=[]
  def moved():
   revision,value=read();calls.append(True);return ('0'*40 if len(calls)==4 else revision),value
  with patch.object(f.store,'read',side_effect=moved):
   with self.assertRaises(ValueError):n.validate_intake_dispositions(f.store,head,{'task-one':row},{})
  # Later malformed bytes remain rejected, independent of the prior row verdict.
  blob=f.store._git('hash-object','-w','--stdin',input_text=' '+__import__('git_document_store').canonical(document))
  tree=f.store._git('mktree',input_text=f'100644 blob {blob}\tdocument.json\n')
  malformed=f.store._git('commit-tree',tree,'-p',head,input_text='noncanonical\n');f.fixture.git('push','origin',malformed+':'+f.store.ref)
  final=f.raw_commit(document,malformed)
  with self.assertRaisesRegex(ValueError,'canonical'):n.validate_intake_dispositions(f.store,final,{'task-one':row},{})
if __name__=='__main__':unittest.main(verbosity=2)
