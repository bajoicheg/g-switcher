"""Two new package-boundary cases; existing history/native suites are reused."""
from pathlib import Path
import importlib,importlib.util,json,os,platform,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(os.environ.get('CDC_TEST_SDK',str(Path(__file__).resolve().parents[1])))
sys.path.insert(0,str(ROOT/'scripts'))
import git_document_store as g

class PackagedDecoder(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.repo=Path(self.temp.name)
        self.env=dict(os.environ,GIT_AUTHOR_NAME='CDC fixture',GIT_AUTHOR_EMAIL='fixture@example.invalid',GIT_COMMITTER_NAME='CDC fixture',GIT_COMMITTER_EMAIL='fixture@example.invalid')
        self.git('init','--quiet');self.store=g.GitDocumentStore.__new__(g.GitDocumentStore);self.store.repo=self.repo
    def git(self,*args,payload=None):
        run=subprocess.run(['git','-C',str(self.repo),*args],input=payload,capture_output=True,env=self.env,check=True)
        return run.stdout.decode().strip()
    def commit(self,payload):
        blob=self.git('hash-object','-w','--stdin',payload=payload.encode())
        tree=self.git('mktree',payload=('100644 blob '+blob+'\tdocument.json\n').encode())
        return self.git('commit-tree',tree,payload=b'New decoder package fixture\n')
    @unittest.skipUnless(sys.implementation.name=='cpython' and sys.version_info[:2]==(3,12) and platform.system()=='Linux' and platform.machine()=='x86_64' and platform.libc_ver()[0]=='glibc', 'optional pinned manylinux CPython3.12 decoder')
    def test_bundled_decoder_retains_exact_values_and_original_rejections(self):
        self.assertIsNot(g._json_loads,json.loads)
        vendor=importlib.import_module('_cdc_vendor.orjson')
        self.assertEqual(vendor.__version__,'3.12.0')
        self.assertEqual(Path(vendor.__file__).resolve().parent,(ROOT/'scripts/_cdc_vendor/orjson').resolve())
        valid=[{'a':[1e-7,-0.0,True,None],'unicode':'Привет𝄞é'}, {'integer':2**100}]
        with patch.object(g,'_json_loads',wraps=g._json_loads) as parse:
            for value in valid:
                with self.subTest(value=value):self.assertEqual(self.store._read_document_object(self.commit(g.canonical(value))),value)
            for payload,message in [('{"a":1e-7}\n','canonical JSON'),('{"a":1,"a":2}\n','duplicate coordination JSON key'),('{"a":{"a":1,"a":2},"z":}\n','duplicate coordination JSON key')]:
                with self.subTest(payload=payload):
                    with self.assertRaisesRegex(ValueError,message):self.store._read_document_object(self.commit(payload))
            self.assertEqual(parse.call_count,5)
    def test_missing_native_extension_uses_unchanged_stdlib_decoder(self):
        value={'a':[1e-7,2**100],'unicode':'Привет𝄞'};revision=self.commit(g.canonical(value))
        code='''import importlib.abc,json,sys
sys.dont_write_bytecode=True
class MissingNativeExtension(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('_cdc_vendor.orjson'):raise ImportError('Unsupported platform fixture')
sys.meta_path.insert(0,MissingNativeExtension());sys.path.insert(0,sys.argv[1])
from pathlib import Path
import git_document_store as g
assert g._json_loads is json.loads
store=g.GitDocumentStore.__new__(g.GitDocumentStore);store.repo=Path(sys.argv[2]);print(g.canonical(store._read_document_object(sys.argv[3])),end='')
'''
        done=subprocess.run([sys.executable,'-B','-c',code,str(ROOT/'scripts'),str(self.repo),revision],capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'},timeout=20)
        self.assertEqual(done.returncode,0,done.stderr);self.assertEqual(done.stdout,g.canonical(value))
if __name__=='__main__':unittest.main(verbosity=2)
