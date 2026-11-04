"""NEW streaming transport risks only; no old native/history acceptance methods."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import json,os,subprocess,tempfile,unittest
from unittest.mock import patch
P=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P/'scripts' if (P/'scripts').is_dir() else P/'candidate/sdk/scripts'))
import git_document_store as g
from git_remote_identity import remote_identity
REAL_POPEN=subprocess.Popen
HELPER=r'''
import sys,time
role,mode,log=sys.argv[1:];out=sys.stdout.buffer
for line in sys.stdin.buffer:
 if line==b'\n':
  out.write(b' missing\n');out.flush()
  if mode=='nonzero':sys.exit(7)
  continue
 oid=line.strip()
 if role=='check':
  if mode=='hang':time.sleep(60)
  if mode=='eof':sys.exit(0)
  if mode=='missing':answer=oid+b' missing\n'
  elif mode=='oversize':answer=oid+b' blob 4194305\n'
  elif mode=='wrongtype':answer=oid+b' tree 3\n'
  elif mode=='longheader':answer=b'x'*300+b'\n'
  else:answer=oid+b' blob 3\n'
  out.write(answer);out.flush()
 else:
  with open(log,'ab') as f:f.write(line)
  header=oid+b' blob 3\n'
  if mode=='changed':header=oid+b' tree 3\n'
  out.write(header)
  if mode=='truncated':out.write(b'{}');out.flush();sys.exit(0)
  out.write(b'{}\n\n')
  if mode=='extra':out.write(b'EXTRA\n')
  out.flush()
'''
@unittest.skipUnless(os.name=='posix','Persistent pipe path is POSIX only; original fallback retained elsewhere')
class HistorySessionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.repo=Path(self.tmp.name);self.git('init','.');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid');self.git('remote','add','origin',str(self.repo));self.store=g.GitDocumentStore(self.repo,'origin','refs/heads/cdc/session',remote_identity(self.repo,'origin'))
 def git(self,*args,data=None):return subprocess.run(['git','-C',str(self.repo),*args],input=data,capture_output=True,check=True).stdout.decode().strip()
 def commit(self,payload,parent=None):
  blob=self.git('hash-object','-w','--stdin',data=payload);tree=self.git('mktree',data=f'100644 blob {blob}\tdocument.json\n'.encode());return self.git('commit-tree',tree,*(['-p',parent] if parent else []),data=b'fixture\n')
 def tracked(self,processes):
  def start(args,*a,**kw):
   proc=REAL_POPEN(args,*a,**kw)
   if 'cat-file' in args and any(x in args for x in ('--batch','--batch-check')):processes.append(proc)
   return proc
  return start
 def fake(self,mode,processes):
  def start(args,*a,**kw):
   role='check' if '--batch-check' in args else 'body';proc=REAL_POPEN([sys.executable,'-B','-u','-c',HELPER,role,mode,str(self.repo/'body-requests')],*a,**kw);processes.append(proc);return proc
  return start
 def assert_reaped(self,processes):
  self.assertTrue(processes)
  for proc in processes:self.assertIsNotNone(proc.poll())
 def test_real_multibatch_preserves_original_facts_with_one_process_pair(self):
  revisions=[];facts=[]
  for n in range(35):
   fact={'id':'original-'+str(n),'status':'UNKNOWN' if n%2 else 'succeeded','spent':n,'nested':['über']};facts.append(fact);revisions.append(self.commit(g.canonical(fact).encode(),revisions[-1] if revisions else None))
  processes=[]
  with patch.object(g.subprocess,'Popen',side_effect=self.tracked(processes)):actual=list(self.store._read_document_objects(revisions+[revisions[0]]))
  self.assertEqual(actual,facts+[facts[0]]);self.assertEqual(len(processes),2);self.assert_reaped(processes);actual[0]['nested'].append('changed');self.assertEqual(actual[-1]['nested'],['über'])
 def test_early_close_reaps_pair_and_next_call_owns_new_processes(self):
  rev=self.commit(b'{"UNKNOWN":null,"spent":7}\n');processes=[]
  with patch.object(g.subprocess,'Popen',side_effect=self.tracked(processes)):
   stream=self.store._read_document_objects([rev]*33);self.assertEqual(next(stream),{'UNKNOWN':None,'spent':7});self.assertEqual(len(processes),2);self.assertTrue(all(p.poll() is None for p in processes));stream.close();self.assert_reaped(processes)
   self.assertEqual(self.store._read_document_object(rev),{'UNKNOWN':None,'spent':7});self.assertEqual(len(processes),4)
  self.assert_reaped(processes)
 def test_size_type_and_header_failures_never_request_any_body(self):
  for mode in ('oversize','wrongtype','longheader','missing','eof'):
   with self.subTest(mode=mode):
    log=self.repo/'body-requests'
    if log.exists():log.unlink()
    processes=[]
    with patch.object(g.subprocess,'Popen',side_effect=self.fake(mode,processes)),self.assertRaises(ValueError):
     with g._ObjectBatchSession(self.repo) as session:session.read(['1'*40],'blob',g.MAX_BYTES)
    self.assertFalse(log.exists() and log.read_bytes());self.assert_reaped(processes)
 def test_changed_truncated_and_extra_body_protocol_is_rejected_and_reaped(self):
  for mode in ('changed','truncated','extra'):
   with self.subTest(mode=mode):
    processes=[]
    with patch.object(g.subprocess,'Popen',side_effect=self.fake(mode,processes)),self.assertRaises(ValueError):
     with g._ObjectBatchSession(self.repo) as session:session.read(['1'*40],'blob',g.MAX_BYTES)
    self.assert_reaped(processes)
 def test_timeout_nonzero_exit_and_consumer_failure_close_all_children(self):
  for mode in ('hang','nonzero'):
   with self.subTest(mode=mode):
    processes=[]
    with patch.object(g,'_BATCH_TIMEOUT',0.1 if mode=='hang' else 20),patch.object(g.subprocess,'Popen',side_effect=self.fake(mode,processes)),self.assertRaises(ValueError):
     with g._ObjectBatchSession(self.repo) as session:session.read(['1'*40],'blob',g.MAX_BYTES)
    self.assert_reaped(processes)
  bad=self.commit(b'{"a":1,"a":1}\n');processes=[]
  with patch.object(g.subprocess,'Popen',side_effect=self.tracked(processes)),self.assertRaises(ValueError):list(self.store._read_document_objects([bad]))
  self.assert_reaped(processes)
 def test_original_batch_limit_and_nonposix_fallback_are_retained(self):
  rev=self.commit(b'{}\n');sizes=[];read=g._ObjectBatchSession.read
  def counted(self,specs,*args):sizes.append(len(specs));return read(self,specs,*args)
  with patch.object(g._ObjectBatchSession,'read',counted):self.assertEqual(list(self.store._read_document_objects([rev]*33)),[{}]*33)
  self.assertEqual(sizes,[16,16,16,16,1,1])
  with patch.object(g.os,'name','nt'),patch.object(self.store,'_batch_objects',wraps=self.store._batch_objects) as fallback:
   self.assertEqual(list(self.store._read_document_objects([rev])),[{}]);self.assertEqual(fallback.call_count,2)
if __name__=='__main__':unittest.main(verbosity=2)
