"""Real Git regressions for lease CAS on existing multi-document refs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import execution_lease_v2 as lease
from git_lease_store import GitLeaseStore

class MultiDocumentLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.remote=self.root/'remote.git'
        subprocess.run(['git','init','--bare','-q',str(self.remote)],check=True)
        self.git('init','-q');self.git('config','user.email','cdc@example.invalid');self.git('config','user.name','CDC')
        self.git('remote','add','origin',str(self.remote))
        self.store=GitLeaseStore(self.repo,'origin','refs/heads/cdc/coordination')
        self.record=lease.initialize('test/project','refs/heads/main')
        self.initial=self.store.compare_and_swap(None,self.record)
    def git(self,*args,input=None):
        return subprocess.check_output(['git','-C',str(self.repo),*args],input=input,text=True,stderr=subprocess.PIPE).strip()
    def topology(self,mode='100644'):
        a=self.git('hash-object','-w','--stdin',input='neighbor\n')
        subtree=self.git('mktree',input=f'100644 blob {a}\tnested.json\n')
        leaseblob=self.git('hash-object','-w','--stdin',input=json.dumps(self.record))
        rows=[f'{mode} blob {leaseblob}\tlease.json',f'100755 blob {a}\trunner',f'120000 blob {a}\tlink',f'100644 blob {a}\tname\twith\nnewline',f'040000 tree {subtree}\tcheckpoint']
        tree=self.git('mktree','-z',input='\0'.join(rows)+'\0')
        commit=self.git('commit-tree',tree,'-p',self.initial,input='Existing coordination topology\n')
        self.git('push','-q','origin',commit+':'+self.store.ref)
        return commit
    def neighbors(self,revision):
        rows=self.git('ls-tree','-z',revision).split('\0')
        return sorted(x for x in rows if x and x.split('\t',1)[1]!='lease.json')
    def test_cas_preserves_neighbor_modes_objects_and_nested_tree(self):
        before=self.topology();r,d=self.store.read();after=self.store.compare_and_swap(r,d)
        self.assertEqual(self.neighbors(before),self.neighbors(after))
        self.assertEqual(self.git('rev-parse',after+'^'),before)
    def test_historical_multidocument_record_is_readable(self):
        before=self.topology();self.assertEqual(self.store.read_revision(before),self.record)
    def assert_raw_neighbor_preserved(self,name):
        blob=self.git('hash-object','-w','--stdin',input='neighbor\n').encode('ascii')
        leaseblob=self.git('hash-object','-w','--stdin',input=json.dumps(self.record)).encode('ascii')
        rows=[b'100644 blob '+leaseblob+b'\tlease.json',b'100644 blob '+blob+b'\t'+name]
        def raw(*args,input=None):
            return subprocess.check_output(['git','-C',str(self.repo),*args],input=input,stderr=subprocess.PIPE)
        tree=raw('mktree','-z',input=b'\0'.join(rows)+b'\0').decode('ascii').strip()
        before=self.git('commit-tree',tree,'-p',self.initial,input='Binary filename neighbor\n')
        self.git('push','-q','origin',before+':'+self.store.ref)
        revision,record=self.store.read();after=self.store.compare_and_swap(revision,record)
        def neighbors(revision):
            return sorted(row for row in raw('ls-tree','-z',revision).split(b'\0')
                          if row and row.split(b'\t',1)[1]!=b'lease.json')
        self.assertEqual(neighbors(before),neighbors(after))
        self.assertEqual(self.store.read_revision(before),self.record)
    def test_cas_preserves_carriage_return_filename_bytes(self):
        self.assert_raw_neighbor_preserved(b'name\rwith-cr\r\n')
    def test_cas_preserves_non_utf8_filename_bytes(self):
        self.assert_raw_neighbor_preserved(b'name\xffnon-utf8')
    def test_stale_cas_cannot_delete_competing_documents(self):
        before=self.topology()
        with self.assertRaisesRegex(ValueError,'stale'):
            self.store.compare_and_swap(self.initial,self.record)
        self.assertEqual(self.store.read()[0],before)
        self.assertEqual(len(self.neighbors(before)),4)
    def test_subdirectory_store_reads_root_lease_and_history(self):
        before=self.topology();nested=self.repo/'nested';nested.mkdir()
        store=GitLeaseStore(nested,'origin',self.store.ref)
        self.assertEqual(store.read(),(before,self.record))
        self.assertEqual(store.read_revision(before),self.record)
        after=store.compare_and_swap(before,self.record)
        self.assertEqual(self.neighbors(before),self.neighbors(after))

    def test_subdirectory_cas_cannot_select_nested_lease_or_delete_root_neighbors(self):
        neighbor=self.git('hash-object','-w','--stdin',input='neighbor')
        root_lease=self.git('hash-object','-w','--stdin',input=json.dumps(self.record))
        nested_record=lease.initialize('test/unrelated','refs/heads/main')
        nested_lease=self.git('hash-object','-w','--stdin',input=json.dumps(nested_record))
        subtree=self.git('mktree',input=f'100644 blob {nested_lease}\tlease.json\n100644 blob {neighbor}\tnested-document.json\n')
        tree=self.git('mktree',input=f'100644 blob {root_lease}\tlease.json\n040000 tree {subtree}\tnested\n100755 blob {neighbor}\troot-document\n')
        before=self.git('commit-tree',tree,'-p',self.initial,input='Root and nested leases')
        self.git('push','-q','origin',before+':'+self.store.ref)
        nested=self.repo/'nested';nested.mkdir();store=GitLeaseStore(nested,'origin',self.store.ref)
        revision,record=store.read();after=store.compare_and_swap(revision,record)
        self.assertEqual(self.neighbors(before),self.neighbors(after))
        self.assertEqual(record,self.record)
        self.assertEqual(store.read_revision(before),self.record)
        self.assertEqual(self.store.read()[1],self.record)

    def test_current_symlink_lease_rejected(self):
        self.topology(mode='120000')
        with self.assertRaisesRegex(ValueError,'regular'):
            self.store.read()
    def test_historical_symlink_lease_rejected(self):
        old=self.topology(mode='120000')
        blob=self.git('hash-object','-w','--stdin',input=json.dumps(self.record))
        tree=self.git('mktree',input=f'100644 blob {blob}\tlease.json\n')
        current=self.git('commit-tree',tree,'-p',old,input='Repair regular lease\n')
        self.git('push','-q','origin',current+':'+self.store.ref)
        with self.assertRaisesRegex(ValueError,'regular'):
            self.store.read_revision(old)

if __name__=='__main__':unittest.main()
