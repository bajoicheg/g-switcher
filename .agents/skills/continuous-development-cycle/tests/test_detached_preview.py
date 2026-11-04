"""Detached Git objects cannot be mistaken for assigned completed results."""
import subprocess,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import managed_executor_pool as pool

class DetachedPreviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.repo=Path(self.tmp.name)
  self.git('init','-q','-b','assigned');self.git('config','user.name','Synthetic native preview test');self.git('config','user.email','cdc@example.invalid')
  (self.repo/'product.txt').write_text('preserve');self.git('add','.');self.git('commit','-qm','base');self.base=self.git('rev-parse','HEAD')
  self.task={'role':'writer','branch':'assigned','write_paths':['package']}
 def git(self,*args,input=None):
  return subprocess.check_output(['git','-C',str(self.repo),*args],input=input,text=True,stderr=subprocess.PIPE).strip()
 def commit_tree(self,parent,content):
  self.git('read-tree',parent);blob=self.git('hash-object','-w','--stdin',input=content)
  self.git('update-index','--add','--cacheinfo','100644',blob,'package/VERSION')
  return self.git('commit-tree',self.git('write-tree'),'-p',parent,input='detached preview\n')
 def preview(self,candidate):
  method=getattr(pool,'preview_writer_result',None)
  self.assertIsNotNone(method,'explicit detached preview phase is missing')
  return method(self.task,self.base,candidate,self.repo,package_path='package')
 def test_detached_preview_does_not_require_or_move_assigned_branch(self):
  candidate=self.commit_tree(self.base,'3.5.2\n');result=self.preview(candidate)
  self.assertEqual(self.git('rev-parse','assigned'),self.base)
  self.assertEqual(result['root_tree'],self.git('rev-parse',candidate+'^{tree}'))
  self.assertEqual(result['package_tree'],self.git('rev-parse',candidate+':package'))
  self.assertEqual(result['final_paths'],['package/VERSION'])
  self.assertFalse(result['authorizes_publication'])
 def test_completed_verifier_rejects_preview_before_assigned_adoption(self):
  candidate=self.commit_tree(self.base,'3.5.2\n');self.preview(candidate)
  with self.assertRaisesRegex(ValueError,'assigned branch'):
   pool._verify_writer_result_git(self.task,self.base,candidate,self.repo)
  self.git('update-ref','refs/heads/assigned',candidate,self.base)
  final,touched=pool._verify_writer_result_git(self.task,self.base,candidate,self.repo)
  self.assertEqual(final,touched)
 def test_hidden_out_of_scope_history_is_rejected_even_when_net_product_unchanged(self):
  self.git('read-tree',self.base);blob=self.git('hash-object','-w','--stdin',input='hidden product edit')
  self.git('update-index','--cacheinfo','100644',blob,'product.txt')
  hidden=self.git('commit-tree',self.git('write-tree'),'-p',self.base,input='hidden\n')
  self.git('read-tree',self.base);blob=self.git('hash-object','-w','--stdin',input='3.5.2\n')
  self.git('update-index','--add','--cacheinfo','100644',blob,'package/VERSION')
  result=self.git('commit-tree',self.git('write-tree'),'-p',hidden,input='restore plus package\n')
  with self.assertRaisesRegex(ValueError,'history.*scope'):self.preview(result)

if __name__=='__main__':unittest.main()
