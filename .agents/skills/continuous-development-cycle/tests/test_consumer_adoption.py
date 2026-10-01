from pathlib import Path
import copy,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from consumer_adoption import assess,GitConsumerAdoptionPublisher,_manifest_digest
import migration_transaction as migration
from git_document_store import GitDocumentStore
from git_remote_identity import endpoint_identity

A="a"*40;B="b"*40;TREE="c"*40;REL="9"*40
REQ=[".agents/skills/continuous-development-cycle","docs/cdc-consumer-lock.json","docs/development-cycle.yaml","docs/work-status/current.md","docs/cdc-adoption-2.11.3.md"]

def fake_manifest(paths=REQ,package_tree=TREE):
 out=[]
 for i,path in enumerate(paths):
  out.append({"path":path,"object_type":"tree" if path==REQ[0] else "blob",
              "object_sha1":package_tree if path==REQ[0] else format(i+1,"040x")})
 return out

def fake_authority(manifest=None):
 manifest=manifest or fake_manifest()
 return {"schema":"migration-assembly-authority/v1","store_ref":"refs/heads/cdc/adoption-assembly",
         "store_id":"sha256:"+"1"*64,"revision":"e"*40,"transaction_id":"migration-test",
         "manifest_digest":_manifest_digest(manifest)}

def state():
 return {"schema":"consumer-adoption-publication/v1","source_head":A,"target_ref":"refs/heads/main","target_version":"2.11.3",
  "target_release_ref":"refs/heads/release/v2.11.3","target_release_commit":REL,
  "target_package_tree":TREE,"required_paths":REQ,"prepared_paths":[],"assembly_manifest":fake_manifest(),
  "assembly_authority":fake_authority(),
  "final_tree_sha":None,"observed_package_tree":None,
  "candidate_commit":None,"live_source_head":A,"publication_claim":None,"published_head":None,"readback_package_tree":None}

class T(unittest.TestCase):
 def ready(self):
  d=state();d["prepared_paths"]=REQ[:];d["final_tree_sha"]="d"*40;d["observed_package_tree"]=TREE;d["candidate_commit"]=B
  claim=assess(d)["claim"];d["publication_claim"]=claim;return d
 def test_partial_adoption_never_moves_shared_ref(self):
  d=state();d["prepared_paths"]=[REQ[0]]
  r=assess(d);self.assertEqual(r["action"],"PREPARE_DETACHED");self.assertFalse(r["publication_prerequisites_satisfied"]);self.assertFalse(r["authorizes_ref_move"])
 def test_version_only_preparation_is_still_detached(self):
  d=state();d["prepared_paths"]=[REQ[0],REQ[1]]
  self.assertEqual(assess(d)["action"],"PREPARE_DETACHED")
 def test_exact_tree_and_full_metadata_reaches_one_publish_boundary(self):
  d=state();d["prepared_paths"]=REQ[:];d["final_tree_sha"]="d"*40;d["observed_package_tree"]=TREE;d["candidate_commit"]=B
  r=assess(d);self.assertEqual(r["action"],"CLAIM_CONDITIONAL_PUBLISH");self.assertFalse(r["authorizes_ref_move"])
  d["publication_claim"]=r["claim"];r=assess(d);self.assertEqual(r["action"],"READY_CONDITIONAL_FAST_FORWARD");self.assertTrue(r["publication_prerequisites_satisfied"]);self.assertFalse(r["authorizes_force_push"])
 def test_live_head_move_replans_before_publication(self):
  d=state();d["prepared_paths"]=REQ[:];d["final_tree_sha"]="d"*40;d["observed_package_tree"]=TREE;d["candidate_commit"]=B;d["live_source_head"]="e"*40
  self.assertEqual(assess(d)["action"],"REPLAN_FRESH_HEAD")
 def test_wrong_package_tree_blocks_candidate_publication(self):
  d=state();d["prepared_paths"]=REQ[:];d["final_tree_sha"]="d"*40;d["observed_package_tree"]="e"*40
  self.assertEqual(assess(d)["action"],"REJECT_PACKAGE_DRIFT")
 def test_complete_requires_exact_published_head_and_readback(self):
  d=self.ready();d["published_head"]=B
  self.assertEqual(assess(d)["action"],"READBACK_PUBLISHED_PACKAGE")
  d["readback_package_tree"]=TREE;self.assertEqual(assess(d)["action"],"COMPLETE")
 def test_wrong_published_head_reconciles_not_retries(self):
  d=self.ready();d["published_head"]="f"*40
  self.assertEqual(assess(d)["action"],"RECONCILE_PUBLICATION")


class GitPublisherTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.remote=self.root/"remote.git";self.work=self.root/"work"
  self.git(self.root,"init","--bare","-q",str(self.remote))
  self.git(self.root,"init","-q",str(self.work))
  self.git(self.work,"config","user.email","cdc@example.invalid")
  self.git(self.work,"config","user.name","CDC test")
  self.git(self.work,"remote","add","origin",str(self.remote))
  self.required=[
   ".agents/skills/continuous-development-cycle",
   "docs/cdc-consumer-lock.json","docs/development-cycle.yaml",
   "docs/work-status/current.md","docs/cdc-adoption-2.11.3.md"]
  self.write(".agents/skills/continuous-development-cycle/VERSION","2.11.2\n")
  self.write("docs/cdc-consumer-lock.json","{}\n")
  self.write("docs/development-cycle.yaml","policy: base\n")
  self.write("docs/work-status/current.md","base\n")
  self.write("docs/cdc-adoption-2.11.3.md","prepared\n")
  self.git(self.work,"add",".");self.git(self.work,"commit","-qm","source")
  self.source=self.git(self.work,"rev-parse","HEAD")
  self.git(self.work,"branch","-M","main")
  self.git(self.work,"push","-q","origin","main")
  self.release_ref="refs/heads/release/v2.11.3";self.release_commit="9"*40
  self.write(".agents/skills/continuous-development-cycle/VERSION","2.11.3\n")
  self.write("docs/cdc-consumer-lock.json",'{}\n')
  self.write("docs/development-cycle.yaml","policy: 2.11.3\n")
  self.write("docs/work-status/current.md","candidate\n")
  self.write("docs/cdc-adoption-2.11.3.md","complete\n")
  self.git(self.work,"add",".");self.git(self.work,"commit","-qm","candidate-prep")
  preliminary=self.git(self.work,"rev-parse","HEAD")
  self.package_tree=self.git(self.work,"rev-parse",preliminary+":.agents/skills/continuous-development-cycle")
  lock={"schema":"cdc-consumer-lock/v1","canonical_repository":"owner/cdc","version":"2.11.3",
        "release_ref":self.release_ref,"release_commit":self.release_commit,"package_tree":self.package_tree,
        "checkpoint_schema":"development-work-status/v4","safe_boundary_required":True,
        "local_core_modifications_allowed":False}
  import json
  self.write("docs/cdc-consumer-lock.json",json.dumps(lock,sort_keys=True)+"\n")
  self.git(self.work,"add","docs/cdc-consumer-lock.json");self.git(self.work,"commit","--amend","-qm","candidate")
  self.candidate=self.git(self.work,"rev-parse","HEAD")
  self.final_tree=self.git(self.work,"rev-parse",self.candidate+"^{tree}")
  self.manifest=self.manifest_for(self.candidate)
  self.remote_id=endpoint_identity(str(self.remote))
  self.store=GitDocumentStore(self.work,"origin","refs/heads/cdc/adoption-attempts",self.remote_id,
                              protected_refs=["refs/heads/main"])
  self.assembly_store=GitDocumentStore(self.work,"origin","refs/heads/cdc/adoption-assembly",self.remote_id,
                                       protected_refs=["refs/heads/main","refs/heads/cdc/adoption-attempts"])
  tx={"schema":"migration-transaction/v1","transaction_id":"migration-publisher-test",
      "source_head":self.source,"target_ref":"refs/heads/main",
      "items":copy.deepcopy(self.manifest),"completed_paths":[x["path"] for x in self.manifest],
      "operation_budget":100,"per_item_operations":1,"batch_overhead_operations":0,
      "finalization_reserve_operations":1,"detached_checkpoints":[],
      "final_tree_sha":self.final_tree,"expected_subtree_tree":self.package_tree,
      "observed_subtree_tree":self.package_tree,"policy_reconciled":True}
  self.assembly_record=migration.assembly_record(
      tx,target_version="2.11.3",target_release_ref=self.release_ref,
      target_release_commit=self.release_commit,completed_at_utc="2026-10-01T04:59:00Z")
  self.assembly_revision=self.assembly_store.compare_and_swap(None,self.assembly_record)
  self.publisher=GitConsumerAdoptionPublisher(
      self.work,"origin","refs/heads/main",self.remote_id,self.store,self.assembly_store,
      clock=lambda:"2026-10-01T05:00:00Z")
 def git(self,cwd,*args):
  p=subprocess.run(["git","-C",str(cwd),*args],text=True,capture_output=True,check=True)
  return p.stdout.strip()
 def write(self,path,text):
  p=self.work/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding="utf-8")
 def manifest_for(self,commit):
  out=[]
  for path in self.required:
   sha=self.git(self.work,"rev-parse",commit+":"+path)
   typ=self.git(self.work,"cat-file","-t",sha)
   out.append({"path":path,"object_type":typ,"object_sha1":sha})
  return out
 def authorize_manifest(self,manifest,final_tree,transaction_id):
  tx={"schema":"migration-transaction/v1","transaction_id":transaction_id,
      "source_head":self.source,"target_ref":"refs/heads/main",
      "items":copy.deepcopy(manifest),"completed_paths":[x["path"] for x in manifest],
      "operation_budget":100,"per_item_operations":1,"batch_overhead_operations":0,
      "finalization_reserve_operations":1,"detached_checkpoints":[],
      "final_tree_sha":final_tree,"expected_subtree_tree":self.package_tree,
      "observed_subtree_tree":self.package_tree,"policy_reconciled":True}
  record=migration.assembly_record(tx,target_version="2.11.3",target_release_ref=self.release_ref,
      target_release_commit=self.release_commit,completed_at_utc="2026-10-01T05:01:00Z")
  current,_=self.assembly_store.read();revision=self.assembly_store.compare_and_swap(current,record)
  return {"schema":"migration-assembly-authority/v1","store_ref":self.assembly_store.ref,
          "store_id":self.assembly_store.store_id,"revision":revision,
          "transaction_id":record["transaction_id"],"manifest_digest":record["manifest_digest"]}
 def ready_state(self):
  d={"schema":"consumer-adoption-publication/v1","source_head":self.source,"target_ref":"refs/heads/main",
     "target_version":"2.11.3","target_release_ref":self.release_ref,"target_release_commit":self.release_commit,
     "target_package_tree":self.package_tree,
     "required_paths":self.required[:],"prepared_paths":self.required[:],"assembly_manifest":copy.deepcopy(self.manifest),
     "assembly_authority":{"schema":"migration-assembly-authority/v1","store_ref":self.assembly_store.ref,
                           "store_id":self.assembly_store.store_id,"revision":self.assembly_revision,
                           "transaction_id":self.assembly_record["transaction_id"],
                           "manifest_digest":self.assembly_record["manifest_digest"]},
     "final_tree_sha":self.final_tree,"observed_package_tree":self.package_tree,
     "candidate_commit":self.candidate,"live_source_head":self.source,
     "publication_claim":None,"published_head":None,"readback_package_tree":None}
  d["publication_claim"]=assess(d)["claim"]
  self.assertEqual(assess(d)["action"],"READY_CONDITIONAL_FAST_FORWARD")
  return d
 def remote_head(self):
  return self.git(self.work,"ls-remote","--refs","origin","refs/heads/main").split("\t")[0]
 def attempt(self,state):
  _,journal=self.store.read()
  return None if journal is None else journal["attempts"].get(state["publication_claim"]["effect_id"])
 def test_real_publish_is_one_conditional_fast_forward_with_exact_readback(self):
  d=self.ready_state();r=self.publisher.publish(d)
  self.assertEqual(r["action"],"PUBLISHED");self.assertTrue(r["conditional_update"])
  self.assertFalse(r["force_push"]);self.assertFalse(r["replay_allowed"])
  self.assertEqual(self.remote_head(),self.candidate)
  self.assertEqual(self.publisher._package_tree(self.remote_head()),self.package_tree)
  self.assertEqual(self.attempt(d)["status"],"confirmed")
  self.assertEqual(self.attempt(d)["manifest_digest"],d["publication_claim"]["manifest_digest"])
  self.assertEqual(self.attempt(d)["assembly_revision"],self.assembly_revision)
 def test_remote_head_move_replans_without_attempt_or_push(self):
  self.git(self.work,"checkout","-q","main")
  self.write("other.txt","concurrent\n");self.git(self.work,"add","other.txt");self.git(self.work,"commit","-qm","concurrent")
  moved=self.git(self.work,"rev-parse","HEAD");self.git(self.work,"push","-q","origin","main")
  d=self.ready_state();r=self.publisher.publish(d)
  self.assertEqual(r["action"],"REPLAN_FRESH_HEAD");self.assertEqual(r["published_head"],moved)
  self.assertIsNone(self.attempt(d));self.assertEqual(self.remote_head(),moved)
 def test_lost_push_reply_after_actual_push_confirms_from_readback_without_replay(self):
  d=self.ready_state();original=self.publisher._push;calls=[]
  def lost(expected,candidate):
   calls.append((expected,candidate));original(expected,candidate);raise ValueError("lost reply")
  self.publisher._push=lost
  r=self.publisher.publish(d)
  self.assertEqual(r["action"],"CONFIRMED_FROM_READBACK");self.assertEqual(len(calls),1)
  self.assertEqual(self.remote_head(),self.candidate);self.assertEqual(self.attempt(d)["status"],"confirmed")
  r2=self.publisher.publish(d)
  self.assertEqual(r2["action"],"OBSERVED_EXISTING");self.assertEqual(len(calls),1)
 def test_unknown_attempt_is_not_replayed_while_source_is_unchanged(self):
  d=self.ready_state();push_calls=[];real_head=self.publisher._remote_head
  self.publisher._push=lambda expected,candidate:(push_calls.append((expected,candidate)) or (_ for _ in ()).throw(ValueError("transport unknown")))
  calls={"n":0}
  def flaky_head():
   calls["n"]+=1
   if calls["n"]==3:raise ValueError("readback unavailable")
   return real_head()
  self.publisher._remote_head=flaky_head
  r=self.publisher.publish(d)
  self.assertEqual(r["action"],"RECONCILE_UNKNOWN");self.assertEqual(len(push_calls),1)
  self.publisher._remote_head=real_head
  r2=self.publisher.publish(d)
  self.assertEqual(r2["action"],"RECONCILE_UNKNOWN");self.assertEqual(len(push_calls),1)
  self.assertEqual(self.remote_head(),self.source);self.assertEqual(self.attempt(d)["status"],"unknown")
 def test_candidate_missing_required_path_fails_before_shared_ref_move(self):
  self.git(self.work,"checkout","-q","--detach",self.source)
  self.write(".agents/skills/continuous-development-cycle/VERSION","2.11.3\n")
  self.write("docs/cdc-consumer-lock.json",'{}\n')
  self.write("docs/development-cycle.yaml","policy: 2.11.3\n")
  self.write("docs/work-status/current.md","candidate\n")
  missing="docs/cdc-adoption-2.11.3.md"
  (self.work/missing).unlink(missing_ok=True)
  self.git(self.work,"add","-A");self.git(self.work,"commit","-qm","missing adoption evidence")
  candidate=self.git(self.work,"rev-parse","HEAD")
  tree=self.git(self.work,"rev-parse",candidate+":.agents/skills/continuous-development-cycle")
  final=self.git(self.work,"rev-parse",candidate+"^{tree}")
  d=self.ready_state();d.update(candidate_commit=candidate,target_package_tree=tree,observed_package_tree=tree,final_tree_sha=final)
  d["assembly_manifest"]=copy.deepcopy(self.manifest)
  d["publication_claim"]=None;d["publication_claim"]=assess(d)["claim"]
  with self.assertRaisesRegex(ValueError,"authoritative assembly transaction binding mismatch|missing required path|object identity mismatch"):
   self.publisher.publish(d)
  self.assertEqual(self.remote_head(),self.source);self.assertIsNone(self.attempt(d))
 def test_candidate_root_tree_must_match_prepared_detached_tree(self):
  d=self.ready_state();d["final_tree_sha"]="f"*40
  with self.assertRaisesRegex(ValueError,"authoritative assembly transaction binding mismatch|root tree"):
   self.publisher.publish(d)
  self.assertEqual(self.remote_head(),self.source);self.assertIsNone(self.attempt(d))
 def test_adoption_provenance_path_tracks_target_version(self):
  d=state();d["target_version"]="2.11.4"
  d["required_paths"]=[p.replace("cdc-adoption-2.11.3.md","cdc-adoption-2.11.4.md") for p in d["required_paths"]]
  d["prepared_paths"]=d["required_paths"][:];d["assembly_manifest"]=fake_manifest(d["required_paths"])
  d["assembly_authority"]=fake_authority(d["assembly_manifest"])
  d["final_tree_sha"]="d"*40;d["observed_package_tree"]=TREE;d["candidate_commit"]=B
  self.assertEqual(assess(d)["action"],"CLAIM_CONDITIONAL_PUBLISH")
  bad=copy.deepcopy(d);bad["required_paths"]=[p.replace("cdc-adoption-2.11.4.md","cdc-adoption-2.11.3.md") for p in bad["required_paths"]]
  bad["prepared_paths"]=bad["required_paths"][:];bad["assembly_manifest"]=fake_manifest(bad["required_paths"])
  bad["assembly_authority"]=fake_authority(bad["assembly_manifest"])
  with self.assertRaisesRegex(ValueError,"required core path"):assess(bad)
 def test_required_core_paths_cannot_be_shrunk_by_caller(self):
  d=self.ready_state();d["required_paths"]=[d["required_paths"][0]];d["prepared_paths"]=d["required_paths"][:]
  d["assembly_manifest"]=[x for x in d["assembly_manifest"] if x["path"] in d["required_paths"]]
  d["publication_claim"]=None
  with self.assertRaisesRegex(ValueError,"required core path"):
   assess(d)
 def test_each_stale_core_blob_is_rejected_before_publication_attempt(self):
  good=self.ready_state()
  for path in [p for p in self.required if p!=".agents/skills/continuous-development-cycle"]:
   with self.subTest(path=path):
    self.git(self.work,"checkout","-q","--detach",self.candidate)
    old=self.git(self.work,"show",self.source+":"+path)
    self.write(path,old+"\n" if old and not old.endswith("\n") else old)
    self.git(self.work,"add",path);self.git(self.work,"commit","-qm","stale "+path.replace("/","-"))
    stale=self.git(self.work,"rev-parse","HEAD")
    d=copy.deepcopy(good);d["candidate_commit"]=stale;d["final_tree_sha"]=self.git(self.work,"rev-parse",stale+"^{tree}")
    d["publication_claim"]=None;d["publication_claim"]=assess(d)["claim"]
    with self.assertRaisesRegex(ValueError,"authoritative assembly transaction binding mismatch|object identity mismatch"):
     self.publisher.publish(d)
    self.assertEqual(self.remote_head(),self.source);self.assertIsNone(self.attempt(d))
 def test_regenerated_stale_manifest_cannot_replace_authoritative_detached_transaction(self):
  for path in ["docs/development-cycle.yaml","docs/work-status/current.md","docs/cdc-adoption-2.11.3.md"]:
   with self.subTest(path=path):
    self.git(self.work,"checkout","-q","--detach",self.candidate)
    self.write(path,"stale-but-self-consistent\n")
    self.git(self.work,"add",path);self.git(self.work,"commit","-qm","self-consistent stale "+path.replace("/","-"))
    stale=self.git(self.work,"rev-parse","HEAD")
    manifest=self.manifest_for(stale)
    d=self.ready_state();d["candidate_commit"]=stale;d["final_tree_sha"]=self.git(self.work,"rev-parse",stale+"^{tree}")
    d["assembly_manifest"]=manifest
    d["assembly_authority"]=copy.deepcopy(d["assembly_authority"])
    d["assembly_authority"]["manifest_digest"]=_manifest_digest(manifest)
    d["publication_claim"]=None;d["publication_claim"]=assess(d)["claim"]
    with self.assertRaisesRegex(ValueError,"authoritative assembly transaction binding mismatch|transaction manifest"):
     self.publisher.publish(d)
    self.assertEqual(self.remote_head(),self.source);self.assertIsNone(self.attempt(d))

 def test_semantically_stale_consumer_lock_is_rejected_even_when_manifest_matches(self):
  self.git(self.work,"checkout","-q","--detach",self.candidate)
  import json
  bad={"schema":"cdc-consumer-lock/v1","canonical_repository":"owner/cdc","version":"2.11.2",
       "release_ref":"refs/heads/release/v2.11.2","release_commit":"8"*40,"package_tree":self.package_tree,
       "checkpoint_schema":"development-work-status/v4","safe_boundary_required":True,"local_core_modifications_allowed":False}
  self.write("docs/cdc-consumer-lock.json",json.dumps(bad,sort_keys=True)+"\n")
  self.git(self.work,"add","docs/cdc-consumer-lock.json");self.git(self.work,"commit","-qm","semantic stale lock")
  stale=self.git(self.work,"rev-parse","HEAD")
  d=self.ready_state();d["candidate_commit"]=stale;d["final_tree_sha"]=self.git(self.work,"rev-parse",stale+"^{tree}")
  d["assembly_manifest"]=self.manifest_for(stale)
  d["assembly_authority"]=self.authorize_manifest(d["assembly_manifest"],d["final_tree_sha"],"semantic-stale-lock")
  d["publication_claim"]=None;d["publication_claim"]=assess(d)["claim"]
  with self.assertRaisesRegex(ValueError,"consumer lock target binding mismatch"):
   self.publisher.publish(d)
  self.assertEqual(self.remote_head(),self.source);self.assertIsNone(self.attempt(d))
 def test_attempt_journal_must_be_remote_bound_and_ref_isolated(self):
  fake="sha256:"+"0"*64
  with self.assertRaisesRegex(ValueError,"remote identity mismatch"):
   GitConsumerAdoptionPublisher(self.work,"origin","refs/heads/main",fake,self.store,self.assembly_store)
  product_store=GitDocumentStore(self.work,"origin","refs/heads/cdc/main",self.remote_id)
  with self.assertRaisesRegex(ValueError,"isolated"):
   GitConsumerAdoptionPublisher(self.work,"origin","refs/heads/cdc/main",self.remote_id,product_store,self.assembly_store)


if __name__=="__main__":unittest.main()
