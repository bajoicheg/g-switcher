"""Offline real-Git protocol tests, without native/provider side effects."""
import copy, hashlib, json, pathlib, subprocess, sys, tempfile, unittest
from unittest.mock import patch
HERE=pathlib.Path(__file__).resolve().parents[1]
BASE=HERE
sys.path.insert(0,str(BASE/'scripts'));sys.path.insert(0,str(HERE/'scripts'))
import git_document_store as native
from git_remote_identity import remote_identity
class TaskShardedDocumentTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.repo=pathlib.Path(self.temp.name)
  self.git('init','.');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
  self.git('remote','add','origin',str(self.repo));self.identity=remote_identity(self.repo,'origin')
  self.store=native.GitDocumentStore(self.repo,'origin','refs/heads/cdc/sharded',self.identity,task_shards=True)
 def git(self,*args,data=None):
  return subprocess.run(['git','-C',str(self.repo),*args],input=data,text=True,capture_output=True,check=True).stdout.strip()
 def document(self,count=3,width=100):
  return {'schema':'cdc-vps-control/v1','registry_digest':'original-registry','queue':{'spent':5,'unknown':'UNKNOWN'},'tasks':{
   f'task-{i}':{'task':{'id':f'task-{i}','goal':'ё'*width},'state':'queued','operation':None,'result':None,'budget':{'spent':i,'events':[]}} for i in range(count)}}
 def raw_commit(self,manifest,entries,parent):
  task_tree=self.git('mktree',data=''.join(entries));blob=self.git('hash-object','-w','--stdin',data=native.canonical(manifest))
  tree=self.git('mktree',data=f'100644 blob {blob}\tdocument.json\n040000 tree {task_tree}\ttasks\n')
  return self.git('commit-tree',tree,'-p',parent,data='malicious fixture\n')
 def test_large_logical_document_has_bounded_physical_head_and_legacy_caps(self):
  document=self.document(32,70000)
  with self.assertRaisesRegex(ValueError,'4 MiB'):native.canonical(document)
  revision=self.store.compare_and_swap(None,document)
  self.assertEqual(self.store.read(),(revision,document));self.assertGreater(len(self.store.canonical(document).encode()),native.MAX_BYTES)
  self.assertLess(len(self.git('show',revision+':document.json').encode()),4096)
  self.assertEqual(self.git('ls-tree','--name-only',revision).splitlines(),['document.json','tasks'])
  legacy=native.GitDocumentStore(self.repo,'origin',self.store.ref,self.identity)
  with self.assertRaises(ValueError):legacy.read()
 def test_mixed_history_detached_rows_and_reuse(self):
  legacy=native.GitDocumentStore(self.repo,'origin',self.store.ref,self.identity);old=self.document();first=legacy.compare_and_swap(None,old)
  migrated=self.store.compare_and_swap(first,old);changed=copy.deepcopy(old);changed['tasks']['task-0']['task']['goal']='changed'
  head=self.store.compare_and_swap(migrated,changed)
  self.assertEqual(list(self.store._read_document_objects([first,migrated,head])),[old,old,changed]);self.assertEqual(self.store.read_revision(first),old)
  name=hashlib.sha256(b'task-1').hexdigest()+'.json'
  self.assertEqual(self.git('rev-parse',migrated+':tasks/'+name),self.git('rev-parse',head+':tasks/'+name))
  loaded=self.store.read()[1];loaded['tasks']['task-1']['budget']['spent']=999;self.assertEqual(self.store.read()[1],changed)
  self.assertEqual(self.git('rev-list','--parents',head).splitlines()[0],head+' '+migrated)
 def test_stale_cas_and_interrupted_preparation_never_publish(self):
  document=self.document();first=self.store.compare_and_swap(None,document)
  with self.assertRaisesRegex(ValueError,'stale'):self.store.compare_and_swap(None,document)
  original=self.store._git
  def fault(*args,**kwargs):
   if args and args[0]=='mktree':raise ValueError('injected preparation failure')
   return original(*args,**kwargs)
  with patch.object(self.store,'_git',side_effect=fault):
   with self.assertRaisesRegex(ValueError,'preparation'):self.store.compare_and_swap(first,document)
  self.assertEqual(self.store.read(),(first,document))
 def test_lost_push_reply_keeps_atomic_proposal_without_retry(self):
  document=self.document();first=self.store.compare_and_swap(None,document);changed=copy.deepcopy(document);changed['queue']['spent']=6
  original=self.store._git;pushes=[]
  def lost(*args,**kwargs):
   value=original(*args,**kwargs)
   if 'push' in args:pushes.append(args);raise ValueError('injected lost reply')
   return value
  with patch.object(self.store,'_git',side_effect=lost):
   with self.assertRaisesRegex(ValueError,'lost reply'):self.store.compare_and_swap(first,changed)
  head,loaded=self.store.read();self.assertNotEqual(head,first);self.assertEqual(loaded,changed);self.assertEqual(len(pushes),1)
  self.assertEqual(self.git('rev-list','--parents',head).splitlines()[0],head+' '+first)
 def test_forged_manifest_index_and_blob_are_denied(self):
  document=self.document();head=self.store.compare_and_swap(None,document);manifest=json.loads(self.git('show',head+':document.json'));lines=self.git('ls-tree',head+':tasks').splitlines(True)
  for kind in ('missing','extra','wrong_name','wrong_digest','wrong_count','extra_manifest','duplicate_id'):
   with self.subTest(kind=kind):
    changed=copy.deepcopy(manifest);entries=list(lines)
    if kind=='missing':entries.pop()
    elif kind=='extra':entries.append(lines[0].replace('.json','.extra'))
    elif kind=='wrong_name':entries[0]=entries[0].split('\t')[0]+'\t'+'0'*64+'.json\n'
    elif kind=='wrong_digest':changed['logical_sha256']='0'*64
    elif kind=='wrong_count':changed['task_count']+=1
    elif kind=='extra_manifest':changed['authority']='fake'
    else:entries[1]=entries[0].split('\t')[0]+'\t'+entries[1].split('\t')[1]
    bad=self.raw_commit(changed,entries,head);self.git('update-ref',self.store.ref,bad)
    with self.assertRaises(ValueError):self.store.read()
    self.git('update-ref',self.store.ref,head)
 def test_row_metadata_task_and_logical_limits_stop_before_push(self):
  good=self.document();head=self.store.compare_and_swap(None,good)
  for kind in ('row','metadata','count','logical'):
   changed=self.document();limit=patch.object(native,'MAX_LOGICAL_BYTES',native.MAX_LOGICAL_BYTES)
   if kind=='row':changed['tasks']['task-0']['task']['goal']='x'*native.MAX_BYTES
   elif kind=='metadata':changed['queue']['padding']='x'*native.MAX_BYTES
   elif kind=='count':limit=patch.object(native,'MAX_TASK_SHARDS',2)
   else:limit=patch.object(native,'MAX_LOGICAL_BYTES',200)
   with self.subTest(kind=kind),limit:
    with self.assertRaises(ValueError):self.store.compare_and_swap(head,changed)
   self.assertEqual(self.store.read(),(head,good))
 def test_optin_is_boolean_and_requires_supported_schema(self):
  for value in (1,'yes',None):
   with self.assertRaises(ValueError):native.GitDocumentStore(self.repo,'origin',self.store.ref,self.identity,task_shards=value)
  for document in ({'schema':'other','tasks':{}},{'schema':'cdc-vps-control/v1','tasks':[]},{'schema':'cdc-vps-control/v1','tasks':{1:{}}}):
   with self.assertRaises(ValueError):self.store.compare_and_swap(None,document)
  self.assertIsNone(self.store._remote_revision())

class ShardedPreservationTests(unittest.TestCase):
 setUp=TaskShardedDocumentTests.setUp
 git=TaskShardedDocumentTests.git
 document=TaskShardedDocumentTests.document
 raw_commit=TaskShardedDocumentTests.raw_commit
 def test_native_disposition_and_preparation_projection_read_mixed_format_history(self):
  sys.path.insert(0,str(BASE/'tests'))
  from test_intake_combined_validation import CombinedValidationTests
  import unknown_recovery as recovery
  import immutable_history_cache as cache
  fixture=CombinedValidationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  store=fixture.store
  # Constructor remains the SDK's exact original type; no wrapper/subclass.
  sharded=native.GitDocumentStore(store.repo,store.remote,store.ref,store.store_id,task_shards=True)
  expected=fixture.validate()
  # This historical negative fixture intentionally shares semantic contracts;
  # use immutable fixture construction, never bypass production transition checks.
  tree=sharded._write_task_tree(fixture.document,sharded.canonical(fixture.document))
  head=sharded._git('commit-tree',tree,'-p',fixture.head,input_text='mixed storage fixture\n')
  fixture.publish(head)
  with patch.object(cache,'_cache',cache._HistoryCache()):
   actual,projection=recovery.validate_intake_dispositions_projecting(sharded,head,fixture.retired,fixture.cancelled,'queue-one')
   self.assertEqual(actual,expected)
   self.assertEqual(projection['revision'],head)
   self.assertEqual(projection['documents'][-1][1],{'tasks':{'queue-one':fixture.document['tasks']['queue-one']}})
   self.assertEqual(sharded.read_revision(fixture.anchor),fixture.base_document)
   self.assertEqual(recovery._history(sharded)[-1],(head,fixture.document))
 def test_task_blob_and_aggregate_caps_checked_before_body_materialization(self):
  document=self.document();head=self.store.compare_and_swap(None,document);manifest=json.loads(self.git('show',head+':document.json'))
  entries=self.git('ls-tree',head+':tasks').splitlines(True)
  large=self.git('hash-object','-w','--stdin',data='x'*(native.MAX_BYTES+1))
  entries[0]='100644 blob '+large+'\t'+entries[0].split('\t')[1]
  bad=self.raw_commit(manifest,entries,head);self.git('update-ref',self.store.ref,bad)
  original=subprocess.run;requests=[]
  def observed(args,*a,**k):
   if '--batch' in args:requests.append(k.get('input',b''))
   return original(args,*a,**k)
  with patch.object(native.subprocess,'run',side_effect=observed):
   with self.assertRaises(ValueError):self.store.read()
  self.assertFalse(any(large.encode() in request for request in requests))
  self.git('update-ref',self.store.ref,head);requests.clear()
  task_ids=[line.split()[2].encode() for line in self.git('ls-tree',head+':tasks').splitlines()]
  with patch.object(native,'MAX_LOGICAL_BYTES',len(native.canonical(manifest).encode())+500),patch.object(native.subprocess,'run',side_effect=observed):
   with self.assertRaisesRegex(ValueError,'aggregate'):self.store.read()
  self.assertFalse(any(oid in request for oid in task_ids for request in requests))

 def test_sharded_sha256_repository_uses_complete_object_ids(self):
  child=self.repo/'sha256';child.mkdir()
  subprocess.run(['git','-C',str(child),'init','--object-format=sha256','.'],check=True,capture_output=True)
  subprocess.run(['git','-C',str(child),'remote','add','origin',str(child)],check=True,capture_output=True)
  store=native.GitDocumentStore(child,'origin','refs/heads/cdc/sha256',remote_identity(child,'origin'),task_shards=True)
  original=self.document();first=store.compare_and_swap(None,original)
  changed=copy.deepcopy(original);changed['queue']['spent']=7
  second=store.compare_and_swap(first,changed)
  self.assertEqual(len(first),64);self.assertEqual(len(second),64)
  self.assertEqual(store.read(),(second,changed));self.assertEqual(store.read_revision(first),original)

if __name__=='__main__':unittest.main()
