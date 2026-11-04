import hashlib,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import managed_executor_handoff as m

class T(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.repo=self.root/"work";self.remote=self.root/"remote.git";self.other=self.root/"other.git";self.repo.mkdir()
  subprocess.check_call(["git","init","--bare","-q",str(self.remote)])
  subprocess.check_call(["git","init","--bare","-q",str(self.other)])
  def git(*args): return subprocess.check_output(["git","-C",str(self.repo),*args],text=True).strip()
  self.git=git
  git("init","-q");git("config","user.email","cdc@example.invalid");git("config","user.name","CDC")
  (self.repo/"seed").write_text("base");git("add","seed");git("commit","-q","-m","base")
  self.base=git("rev-parse","HEAD")
  git("switch","-q","-c","worker-a")
  (self.repo/"src").mkdir();(self.repo/"src"/"a.txt").write_text("a")
  git("add","src/a.txt");git("commit","-q","-m","result");self.result=git("rev-parse","HEAD")
  git("remote","add","origin",str(self.remote));git("remote","add","alt",str(self.other))
  self.push_worker("origin")
  self.repo_id="example/repository"
  self.remote_id=m.publication_remote_identity(self.repo,"origin")

 def tearDown(self):self.tmp.cleanup()

 def push_worker(self,remote="origin",source="worker-a"):
  subprocess.check_call(["git","-C",str(self.repo),"push","-q","--force",remote,f"{source}:refs/heads/worker-a"])

 def direct(self,base=None,commit=None):
  base=base or self.base;commit=commit or self.result
  return {
   "schema":"managed-executor-handoff/v1","pool_id":"p","change_id":"c","task_id":"t",
   "attempt_id":"a1","parent_invocation_id":"parent","executor_id":"exec",
   "base_sha":base,"assigned_branch":"worker-a","publication_repository":self.repo_id,
   "publication_remote_id":self.remote_id,"transport":"direct_branch",
   "source_result_commit":commit,"direct_result_commit":commit,"artifact_ref":None,
   "changed_paths":["src/a.txt"],"evidence_refs":["tests:green"]}

 def proof(self,h,commit=None,changed=None):
  return {
   "schema":"managed-executor-publication-proof/v1",
   "handoff_ref":m.canonical_handoff_ref(h),"pool_id":h["pool_id"],"task_id":h["task_id"],
   "attempt_id":h["attempt_id"],"base_sha":h["base_sha"],"assigned_branch":h["assigned_branch"],
   "publication_repository":h["publication_repository"],"publication_remote_id":h["publication_remote_id"],
   "published_commit":commit or self.result,"observed_changed_paths":changed or list(h["changed_paths"]),
   "evidence_refs":["git:remote-head","tests:remote-green"],"result_verified":True,
   "authorizes_product_write":False,"authorizes_shared_branch_write":False,
   "authorizes_force_push":False,"authorizes_merge":False,"authorizes_release":False,
   "authorizes_scope_expansion":False,"authorizes_scheduler_mutation":False}

 def validate(self,p,h,**kw):
  return m.validate_publication_proof(
   p,h,self.repo,remote=kw.pop("remote","origin"),
   trusted_repository=kw.pop("trusted_repository",self.repo_id),
   trusted_remote_id=kw.pop("trusted_remote_id",self.remote_id),**kw)

 def make_patch(self,base,commit,path="result.patch"):
  payload=subprocess.check_output(["git","-C",str(self.repo),"diff","--binary",base,commit])
  target=self.repo/path;target.write_bytes(payload);return target,payload

 def artifact_handoff(self,base=None,commit=None,path="result.patch"):
  base=base or self.base;commit=commit or self.result
  target,payload=self.make_patch(base,commit,path);h=self.direct(base,commit)
  h.update(transport="content_artifact",source_result_commit=None,direct_result_commit=None,
   artifact_ref={"path":path,"sha256":"sha256:"+hashlib.sha256(payload).hexdigest(),"format":"unified_diff"})
  return h,target,payload

 def bundle_handoff(self):
  bundle=self.repo/"result.bundle"
  subprocess.check_call(["git","-C",str(self.repo),"bundle","create",str(bundle),"worker-a"],stdout=subprocess.DEVNULL)
  payload=bundle.read_bytes();h=self.direct()
  h.update(transport="content_artifact",direct_result_commit=None,
   artifact_ref={"path":"result.bundle","sha256":"sha256:"+hashlib.sha256(payload).hexdigest(),"format":"git_bundle"})
  return h,bundle,payload

 def test_direct_branch_plan_never_requires_reexecution_or_grants_authority(self):
  h=self.direct();p=m.publication_plan(h)
  self.assertEqual(p["action"],"VERIFY_DIRECT_ASSIGNED_BRANCH");self.assertFalse(p["requires_reexecution"])
  self.assertEqual(p["publication_repository"],self.repo_id);self.assertEqual(p["publication_remote_id"],self.remote_id)
  for name in m.AUTHORITY_FIELDS:self.assertFalse(p[name])

 def test_direct_publication_proof_verifies_bound_authoritative_remote(self):
  h=self.direct();self.assertTrue(self.validate(self.proof(h),h)["result_verified"])

 def test_trusted_identity_is_mandatory(self):
  h=self.direct()
  with self.assertRaisesRegex(ValueError,"trusted publication identity"):
   m.validate_publication_proof(self.proof(h),h,self.repo,remote="origin")

 def test_local_branch_without_remote_publication_is_rejected(self):
  subprocess.check_call(["git","-C",str(self.repo),"push","-q","origin",":refs/heads/worker-a"])
  h=self.direct()
  with self.assertRaisesRegex(ValueError,"authoritative remote branch"):
   self.validate(self.proof(h),h)

 def test_remote_ref_mismatch_is_rejected(self):
  self.push_worker("origin",self.base);h=self.direct()
  with self.assertRaisesRegex(ValueError,"exact authoritative remote branch head"):
   self.validate(self.proof(h),h)

 def test_repointed_origin_is_rejected_by_bound_remote_identity(self):
  h=self.direct();p=self.proof(h)
  self.git("remote","set-url","origin",str(self.other));self.push_worker("origin")
  with self.assertRaisesRegex(ValueError,"remote identity mismatch"):
   self.validate(p,h)

 def test_alternate_remote_with_same_commit_is_rejected(self):
  self.push_worker("alt");h=self.direct();p=self.proof(h)
  with self.assertRaisesRegex(ValueError,"remote identity mismatch"):
   self.validate(p,h,remote="alt")

 def test_same_relative_remote_in_other_checkout_cannot_publish_trusted_result(self):
  self.git("remote","set-url","origin","../remote.git")
  self.remote_id=m.publication_remote_identity(self.repo,"origin")
  h=self.direct();p=self.proof(h)
  other_root=self.root/"other-root";other_root.mkdir()
  other_repo=other_root/"work";other_remote=other_root/"remote.git"
  subprocess.check_call(["git","clone","-q",str(self.repo),str(other_repo)])
  subprocess.check_call(["git","init","--bare","-q",str(other_remote)])
  subprocess.check_call(["git","-C",str(other_repo),"remote","set-url","origin","../remote.git"])
  subprocess.check_call(["git","-C",str(other_repo),"push","-q","origin","worker-a"])
  with self.assertRaisesRegex(ValueError,"remote identity mismatch"):
   m.validate_publication_proof(p,h,other_repo,remote="origin",
    trusted_repository=self.repo_id,trusted_remote_id=self.remote_id)

 def test_fetch_push_split_remote_is_rejected(self):
  h=self.direct();p=self.proof(h)
  self.git("remote","set-url","--add","--push","origin",str(self.other))
  with self.assertRaisesRegex(ValueError,"one identical fetch/push endpoint"):
   self.validate(p,h)

 def test_wrong_trusted_repository_or_remote_id_is_rejected(self):
  h=self.direct();p=self.proof(h)
  with self.assertRaisesRegex(ValueError,"repository identity mismatch"):
   self.validate(p,h,trusted_repository="other/repo")
  with self.assertRaisesRegex(ValueError,"remote identity mismatch"):
   self.validate(p,h,trusted_remote_id="sha256:"+"0"*64)

 def test_identity_failure_does_not_echo_remote_url(self):
  h=self.direct();p=self.proof(h);secret="https://user:secret@example.invalid/private.git"
  self.git("remote","set-url","origin",secret)
  with self.assertRaises(ValueError) as ctx:self.validate(p,h)
  self.assertNotIn("secret",str(ctx.exception));self.assertNotIn("example.invalid",str(ctx.exception))

 def test_direct_result_identity_mismatch_fails_first(self):
  h=self.direct();p=self.proof(h,commit=self.base)
  with self.assertRaisesRegex(ValueError,"direct publication commit mismatch"):self.validate(p,h)

 def test_content_artifact_digest_is_authenticated_and_no_rerun(self):
  h,_,_=self.artifact_handoff();p=m.publication_plan(h,self.repo)
  self.assertEqual(p["action"],"IMPORT_CONTENT_ARTIFACT_TO_ASSIGNED_BRANCH");self.assertFalse(p["requires_reexecution"])

 def test_invalid_unified_diff_fails_before_publication(self):
  artifact=self.repo/"result.patch";artifact.write_bytes(b"not-a-patch");h=self.direct()
  h.update(transport="content_artifact",source_result_commit=None,direct_result_commit=None,
   artifact_ref={"path":"result.patch","sha256":"sha256:"+hashlib.sha256(b"not-a-patch").hexdigest(),"format":"unified_diff"})
  with self.assertRaisesRegex(ValueError,"syntactically valid unified_diff"):m.publication_plan(h,self.repo)

 def test_content_artifact_digest_mismatch_fails_closed(self):
  (self.repo/"result.patch").write_bytes(b"actual");h=self.direct()
  h.update(transport="content_artifact",source_result_commit=None,direct_result_commit=None,
   artifact_ref={"path":"result.patch","sha256":"sha256:"+"0"*64,"format":"unified_diff"})
  with self.assertRaisesRegex(ValueError,"digest mismatch"):m.publication_plan(h,self.repo)

 def test_artifact_path_cannot_escape_evidence_root(self):
  h=self.direct();h.update(transport="content_artifact",source_result_commit=None,direct_result_commit=None,
   artifact_ref={"path":"../escape.patch","sha256":"sha256:"+"0"*64,"format":"unified_diff"})
  with self.assertRaises(ValueError):m.validate_handoff(h)

 def test_publication_proof_binds_handoff_digest_and_identity(self):
  h=self.direct();p=self.proof(h);p["handoff_ref"]="sha256:"+"0"*64
  with self.assertRaisesRegex(ValueError,"handoff_ref mismatch"):self.validate(p,h)
  p=self.proof(h);p["publication_repository"]="other/repo"
  with self.assertRaisesRegex(ValueError,"repository identity mismatch"):self.validate(p,h)

 def test_changed_path_manifest_is_portable_and_exact(self):
  self.git("switch","-q","worker-a");self.git("reset","--hard",self.base)
  (self.repo/"src").mkdir(exist_ok=True);(self.repo/"src"/"Foo").write_text("x")
  self.git("add","src/Foo");self.git("commit","-q","-m","case-path");commit=self.git("rev-parse","HEAD");self.push_worker()
  h=self.direct(self.base,commit);h["changed_paths"]=["src/Foo"];p=self.proof(h,commit=commit,changed=["src/foo"])
  self.assertTrue(self.validate(p,h))
  p=self.proof(h,commit=commit,changed=["src/bar"])
  with self.assertRaisesRegex(ValueError,"changed paths"):self.validate(p,h)

 def test_unified_diff_publication_tree_must_match_authenticated_artifact(self):
  h,_,_=self.artifact_handoff();p=self.proof(h);self.assertTrue(self.validate(p,h,evidence_root=self.repo))
  self.git("switch","-q","worker-a");(self.repo/"other.txt").write_text("other")
  self.git("add","other.txt");self.git("commit","-q","-m","unrelated");unrelated=self.git("rev-parse","HEAD");self.push_worker()
  p=self.proof(h,commit=unrelated,changed=["src/a.txt","other.txt"])
  with self.assertRaisesRegex(ValueError,"handoff manifest|authenticated unified_diff result"):
   self.validate(p,h,evidence_root=self.repo)

 def test_unified_diff_manifest_must_match_authenticated_artifact_paths(self):
  h,_,_=self.artifact_handoff();h["changed_paths"]=["src/other.txt"];p=self.proof(h,changed=["src/other.txt"])
  with self.assertRaisesRegex(ValueError,"actual published Git diff|artifact"):self.validate(p,h,evidence_root=self.repo)

 def test_git_bundle_transport_preserves_source_commit_identity(self):
  h,_,_=self.bundle_handoff();m.publication_plan(h,self.repo);p=self.proof(h)
  self.assertTrue(self.validate(p,h,evidence_root=self.repo))
  p["published_commit"]=self.base
  with self.assertRaisesRegex(ValueError,"preserve source result commit"):self.validate(p,h,evidence_root=self.repo)

 def test_bundle_verification_uses_authenticated_payload_snapshot(self):
  h,bundle,_=self.bundle_handoff();p=self.proof(h);original=m.resolve_artifact
  def resolve_then_swap(handoff,evidence_root):
   payload=original(handoff,evidence_root);bundle.write_bytes(b"swapped-after-authentication");return payload
  with mock.patch.object(m,"resolve_artifact",side_effect=resolve_then_swap):
   self.assertTrue(self.validate(p,h,evidence_root=self.repo))

 def test_authority_escalation_in_proof_is_rejected(self):
  h=self.direct();p=self.proof(h);p["authorizes_merge"]=True
  with self.assertRaisesRegex(ValueError,"must remain false"):self.validate(p,h)

if __name__=="__main__":unittest.main()
