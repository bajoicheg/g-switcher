"""New data projection must share authentication, never truncate it or grant authority."""
import copy
import pathlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
import immutable_history_cache as cache
import unknown_recovery as native

class IntakePreparationProjectionTests(unittest.TestCase):
 def setUp(self):
  from test_intake_combined_validation import CombinedValidationTests
  self.fixture=CombinedValidationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  self.store=self.fixture.store
 def project(self,revision=None):
  return native.validate_intake_dispositions_projecting(self.store,revision or self.fixture.head,self.fixture.retired,self.fixture.cancelled,'queue-one')
 def test_mixed_full_authentication_and_detached_selected_projection_share_one_walk(self):
  read=self.store._read_document_objects;walks=[]
  def counted(revisions):
   if len(revisions)>1:walks.append(tuple(revisions))
   yield from read(revisions)
  with patch.object(self.store,'_read_document_objects',side_effect=counted):retired,projection=self.project()
  self.assertEqual(len(walks),1)
  self.assertEqual(retired,self.fixture.validate())
  expected=[(sha,{'tasks':{'queue-one':copy.deepcopy(doc['tasks']['queue-one'])} if 'queue-one' in doc['tasks'] else {}}) for sha,doc in native._history(self.store)]
  self.assertEqual(projection['documents'],expected);self.assertEqual(projection['chain'][-1][0],self.fixture.head)
  self.assertEqual(projection['task_id'],'queue-one');self.assertEqual(projection['revision'],self.fixture.head)
  projection['documents'][-1][1]['tasks']['queue-one']['task']['goal']='caller mutation'
  self.assertEqual(self.project()[1]['documents'],expected)
  self.assertEqual(cache._cache.get(cache._context(self.store,'document'))['documents'],[])
 def test_projection_never_escapes_object_semantic_or_final_head_denial(self):
  f=self.fixture
  for kind in ('noncanonical','semantic','head'):
   with self.subTest(kind=kind),patch.object(cache,'_cache',cache._HistoryCache()):
    if kind=='noncanonical':
     bad=f.commit(' '+__import__('git_document_store').canonical(f.document),f.head)
     tip=f.commit(f.document,bad);f.publish(tip)
     with self.assertRaises(ValueError):self.project(tip)
     f.publish(f.head)
    elif kind=='semantic':
     original=f.retired;f.retired=copy.deepcopy(original);f.retired['post-one']['task']['goal']='substituted'
     try:
      with self.assertRaises(ValueError):self.project()
     finally:f.retired=original
    else:
     read=self.store.read;calls=[]
     def moved():
      revision,doc=read();calls.append(1);return ('0'*40 if len(calls)==4 else revision),doc
     with patch.object(self.store,'read',side_effect=moved):
      with self.assertRaises(ValueError):self.project()
 def test_projection_capacity_falls_back_without_changing_dispositions_or_authentication(self):
  with patch.object(native,'_PREPARATION_PROJECTION_MAX_BYTES',64):retired,projection=self.project()
  self.assertIsNone(projection);self.assertEqual(retired,self.fixture.validate())

if __name__=='__main__':unittest.main()
