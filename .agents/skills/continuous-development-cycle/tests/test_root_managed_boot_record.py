"""Root filesystem custody requires separate Linux root acceptance, not booleans."""
import functools,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import managed_boot_transition as boots

def _as_root(method):
 @functools.wraps(method)
 def check(self):
  if os.geteuid()==0:return method(self)
  # This mandatory gate has no skip/fake-root fallback. Hosted Linux qualification
  # must supply its existing passwordless sudo; personal runs may use root.
  result=subprocess.run(['/usr/bin/sudo','-n',sys.executable,'-B',__file__,
   self.__class__.__name__+'.'+method.__name__,'-v'],capture_output=True,text=True,timeout=30)
  self.assertEqual(result.returncode,0,result.stderr)
 return check

class RootBootRecordTests(unittest.TestCase):
 def setUp(self):
  if os.geteuid()!=0:return
  self.root=Path(tempfile.mkdtemp(prefix='cdc-boot-record-test-',dir='/run'))
  self.addCleanup(shutil.rmtree,self.root)
  self.path=self.root/'proof.json';self.record={'probe':'protected actual bytes'}
 @_as_root
 def test_real_protected_root_file_roundtrip(self):
  boots.write_record(self.path,self.record,group_id=1000)
  self.assertEqual(boots._read_root_record(self.path),self.record)
  self.assertEqual(self.path.stat().st_uid,0)
  self.assertEqual(self.path.stat().st_mode&0o777,0o640)
 @_as_root
 def test_normal_access_time_update_does_not_invalidate_protected_bytes(self):
  boots.write_record(self.path,self.record,group_id=1000)
  os.utime(self.path,ns=(1,self.path.stat().st_mtime_ns))
  self.assertEqual(boots._read_root_record(self.path),self.record)
 @_as_root
 def test_duplicate_write_retains_original_bytes(self):
  boots.write_record(self.path,self.record,group_id=1000);before=self.path.read_bytes()
  with self.assertRaises(FileExistsError):boots.write_record(self.path,{'replacement':True},group_id=1000)
  self.assertEqual(self.path.read_bytes(),before)
 @_as_root
 def test_symlink_hardlink_and_writable_parent_never_authorize(self):
  boots.write_record(self.path,self.record,group_id=1000)
  alias=self.root/'alias';alias.symlink_to(self.path)
  with self.assertRaises(ValueError):boots._read_root_record(alias)
  alias.unlink();os.link(self.path,alias)
  with self.assertRaises(ValueError):boots._read_root_record(self.path)
  alias.unlink();self.root.chmod(0o770)
  with self.assertRaises(ValueError):boots._read_root_record(self.path)

if __name__=='__main__':unittest.main()
