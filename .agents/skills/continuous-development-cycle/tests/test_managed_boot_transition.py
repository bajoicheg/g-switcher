"""A different boot needs independently protected original-host evidence."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))

class BootTransitionTests(unittest.TestCase):
 def module(self):
  spec=importlib.util.find_spec('managed_boot_transition')
  self.assertIsNotNone(spec,'released original failure needs a package-owned boot-transition verifier')
  import managed_boot_transition
  return managed_boot_transition
 def fixture(self,m):
  request={'identity':{'pool_id':'pool','task_id':'task','attempt_id':'attempt'}}
  release={'lease_revision':'a'*40,'release':{'at_utc':'2026-10-30T11:15:20Z'}}
  observation={'boot_id':'11111111-1111-4111-8111-111111111111','status':'failed','quiescent':True,'quiescence_proof':{'observed_at_utc':'2026-10-30T11:16:41Z'}}
  current={'boot_id':'22222222-2222-4222-8222-222222222222','machine_id':'a'*32,'pid_namespace':'pid:[4026531836]','boot_epoch_us':1793362350000000}
  record={'schema':'managed-original-boot-transition/v1','task_id':'task','attempt_id':'attempt','pool_id':'pool','request_ref':m._digest(request),'release_ref':m._digest(release),'original_boot_id':observation['boot_id'],'current_host':current,'last_original_journal_epoch_us':1793359211000000,'observed_at_utc':'2026-10-30T14:00:00Z'}
  return request,release,observation,current,record
 def check(self,m,record,request,observation,release,current):
  with mock.patch.object(m,'_read_root_record',return_value=record),mock.patch.object(m,'_current_host',return_value=current),mock.patch.object(m,'_now',return_value='2026-10-30T14:00:01Z'):
   return m.authenticate(Path('/root/protected.json'),request,observation,release)
 def test_authentic_original_failure_retains_both_boots_and_request_binding(self):
  m=self.module();q,r,o,h,d=self.fixture(m)
  proof=self.check(m,d,q,o,r,h)
  self.assertEqual(proof.evidence['original_boot_id'],o['boot_id'])
  self.assertEqual(proof.evidence['current_boot_id'],h['boot_id'])
  self.assertFalse(proof.evidence['authorizes_release'])
  self.assertFalse(proof.evidence['authorizes_start'])
 def test_foreign_host_namespace_boot_or_release_never_qualifies(self):
  m=self.module();q,r,o,h,d=self.fixture(m)
  for key,value in [('machine_id','b'*32),('pid_namespace','pid:[123]'),('boot_id','33333333-3333-4333-8333-333333333333'),('boot_epoch_us',h['boot_epoch_us']+10000000)]:
   with self.subTest(key=key):
    changed={**h,key:value}
    with self.assertRaises(ValueError):self.check(m,d,q,o,r,changed)
  with self.assertRaises(ValueError):self.check(m,d,q,o,{**r,'lease_revision':'b'*40},h)
 def test_stale_future_or_preboot_incomplete_evidence_stays_blocked(self):
  m=self.module();q,r,o,h,d=self.fixture(m)
  for patch in [{'observed_at_utc':'2026-10-30T13:00:00Z'},{'observed_at_utc':'2026-10-30T14:00:02Z'},{'last_original_journal_epoch_us':1},{'last_original_journal_epoch_us':h['boot_epoch_us']+1}]:
   with self.subTest(patch=patch),self.assertRaises(ValueError):self.check(m,{**d,**patch},q,o,r,h)
 def test_success_nonterminal_and_same_boot_cannot_use_failure_recovery(self):
  m=self.module();q,r,o,h,d=self.fixture(m)
  for patch in [{'status':'succeeded'},{'quiescent':False},{'boot_id':h['boot_id']}]:
   with self.subTest(patch=patch),self.assertRaises(ValueError):self.check(m,d,q,{**o,**patch},r,h)
 def test_root_producer_requires_matching_actual_journal_boot_and_machine(self):
  m=self.module();q,r,o,h,d=self.fixture(m)
  def journal(boot,machine):
   return subprocess.CompletedProcess([],0,json.dumps({'_BOOT_ID':boot.replace('-',''),'_MACHINE_ID':machine,'__REALTIME_TIMESTAMP':str(d['last_original_journal_epoch_us'])})+'\n','')
  with mock.patch.object(m.os,'geteuid',return_value=0),mock.patch.object(m,'_current_host',return_value=h),mock.patch.object(m,'_now',return_value=d['observed_at_utc']):
   with mock.patch.object(m.subprocess,'run',return_value=journal(o['boot_id'],h['machine_id'])) as run:
    actual=m.collect(request=q,observation=o,release_receipt=r)
    self.assertEqual(actual,d)
    self.assertIn('--boot='+o['boot_id'].replace('-',''),run.call_args.args[0])
   for boot,machine in [(o['boot_id'],'b'*32),('3'*32,h['machine_id'])]:
    with self.subTest(boot=boot,machine=machine),mock.patch.object(m.subprocess,'run',return_value=journal(boot,machine)),self.assertRaises(ValueError):m.collect(request=q,observation=o,release_receipt=r)
 def test_unprivileged_producer_and_unprotected_or_symlink_file_are_denied(self):
  m=self.module();q,r,o,h,d=self.fixture(m)
  with mock.patch.object(m.os,'geteuid',return_value=1000),self.assertRaises(ValueError):m.collect(request=q,observation=o,release_receipt=r)
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'proof.json';p.write_text(json.dumps(d));link=p.with_name('link');link.symlink_to(p)
   for path in (p,link):
    with self.subTest(path=path),self.assertRaises(ValueError):m._read_root_record(path)

if __name__=='__main__':unittest.main()
