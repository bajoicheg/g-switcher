"""Real Git delivery, authentic stored ownership and forward rollback contracts."""
import copy,json,os,subprocess,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import execution_lease_v2 as lease
import project_setup
from live_target import GitSource
from git_remote_identity import remote_identity
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
try:
    import release_delivery
except ModuleNotFoundError:
    release_delivery=None
PACKAGE=".agents/skills/continuous-development-cycle"
CANONICAL_PACKAGE="src/continuous-development-cycle"
NOW=datetime(2026,10,10,12,0,0,tzinfo=timezone.utc)
OWNER="11111111-1111-4111-8111-111111111111"

class GitDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(release_delivery,"native release delivery is not implemented")
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.canonical=self.root/"canonical";self.work=self.root/"consumer"
        self.remote=self.root/"product.git"
        for repo in (self.canonical,self.work):
            repo.mkdir();self.git(repo,"init","-q","-b","main")
            self.git(repo,"config","user.name","Fixture")
            self.git(repo,"config","user.email","fixture@example.invalid")
        self.git(self.root,"init","--bare","-q",str(self.remote))
        self.git(self.work,"remote","add","origin",str(self.remote))
        self.git(self.work,"remote","add","canonical",str(self.canonical))
        self.bindings={}
        for version in ("2.11.3","2.11.4"):
            self.write(self.canonical,CANONICAL_PACKAGE+"/VERSION",version+"\n")
            self.write(self.canonical,CANONICAL_PACKAGE+"/runner","#!/bin/sh\necho "+version+"\n")
            os.chmod(self.canonical/CANONICAL_PACKAGE/"runner",0o755)
            candidate=self.commit(self.canonical)
            tree=self.git(self.canonical,"rev-parse",candidate+":"+CANONICAL_PACKAGE)
            evidence=dict(schema="cdc-release-evidence/v1",version=version,
                canonical_repository="owner/cdc",status="released",
                candidate_source_commit=candidate,package_tree=tree,
                release_ref="refs/heads/release/v"+version)
            self.write(self.canonical,"release/evidence-"+version+".json",json.dumps(evidence))
            release=self.commit(self.canonical)
            self.git(self.canonical,"update-ref",evidence["release_ref"],release)
            self.bindings[version]=dict(schema="live-target-release/v1",version=version,
                canonical_repository="owner/cdc",release_ref=evidence["release_ref"],
                release_commit=release,package_tree=tree)
        first=self.bindings["2.11.3"]
        self.write(self.work,PACKAGE+"/VERSION","2.11.3\n")
        self.write(self.work,PACKAGE+"/runner","#!/bin/sh\necho 2.11.3\n")
        os.chmod(self.work/PACKAGE/"runner",0o755)
        lock=dict(schema="cdc-consumer-lock/v1",canonical_repository="owner/cdc",
            version=first["version"],release_ref=first["release_ref"],
            release_commit=first["release_commit"],package_tree=first["package_tree"],
            checkpoint_schema="development-work-status/v4",safe_boundary_required=True,
            local_core_modifications_allowed=False)
        self.write(self.work,"docs/cdc-consumer-lock.json",json.dumps(lock))
        request=dict(schema="cdc-init-request/v1",repository="owner/product",branch="main",
            source_head="a"*40,preset="portable",cloud_profile_json=None,
            validation=dict(quick="python -B quick.py",full="python -B full.py",release="python -B release.py"))
        for f in project_setup.initialize(request)["files"]:self.write(self.work,f["path"],f["content"])
        self.write(self.work,"docs/cdc-adoption-2.11.3.md","original acceptance\n")
        self.write(self.work,"docs/budget-history.json",'{"unknown":null,"charged":7}\n')
        self.write(self.work,"product.txt","unmanaged product\n")
        self.source=self.commit(self.work);self.git(self.work,"push","-q","origin","main")
        self.remote_id=remote_identity(self.work,"origin")
        self.canonical_source=GitSource(self.work,"canonical",remote_identity(self.work,"canonical"),clock=lambda:NOW)
        self.lease_store=GitLeaseStore(self.work,"origin","refs/heads/cdc/lease")
        record=lease.initialize("owner/product","refs/heads/main")
        rev=self.lease_store.compare_and_swap(None,record)
        invocation=dict(invocation_id="fixture-managed",automation_id=None,conversation_id="fixture",
            execution_surface="managed",started_at_utc="2026-10-10T11:59:58Z")
        with mock.patch.object(lease.terminal_capability_api,"validate_verified",return_value={}):
            record=lease.acquire(record,OWNER,"2026-10-10T11:59:59Z",invocation=invocation,terminal_capability=object())
            rev=self.lease_store.compare_and_swap(rev,record,ownership_capability=object())
        self.ownership=dict(expected_revision=rev,repository="owner/product",source_ref="refs/heads/main",
            owner_id=OWNER,generation=1,invocation_id="fixture-managed")
        self.attempt=GitDocumentStore(self.work,"origin","refs/heads/cdc/delivery-attempts",self.remote_id,
            protected_refs=["refs/heads/main"])
        self.assembly=GitDocumentStore(self.work,"origin","refs/heads/cdc/delivery-assembly",self.remote_id,
            protected_refs=["refs/heads/main",self.attempt.ref])
        self.delivery=release_delivery.GitReleaseDelivery(self.work,"origin","refs/heads/main",
            self.remote_id,self.canonical_source,"owner/cdc",self.lease_store,self.ownership,
            self.attempt,self.assembly,clock=lambda:NOW)

    @staticmethod
    def git(repo,*args,input=None):
        return subprocess.check_output(["git","-C",str(repo),*args],input=input,text=True,stderr=subprocess.PIPE).strip()
    @staticmethod
    def write(repo,path,text):
        dest=repo/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    def commit(self,repo):
        self.git(repo,"add",".");self.git(repo,"commit","-q","--allow-empty","-m","fixture")
        return self.git(repo,"rev-parse","HEAD")
    def prepare(self,**kwargs):
        return self.delivery.prepare(self.bindings["2.11.4"],expected_head=self.source,
            transaction_id="delivery-fixture",operation_budget=100,**kwargs)
    def remote_head(self):
        return self.git(self.work,"ls-remote","origin","refs/heads/main").split()[0]

    def test_detached_candidate_preserves_head_worktree_controls_and_modes(self):
        before=self.git(self.work,"status","--porcelain")
        prepared=self.prepare();state=prepared["state"];candidate=state["candidate_commit"]
        self.assertEqual(self.remote_head(),self.source)
        self.assertEqual(self.git(self.work,"rev-parse","HEAD"),self.source)
        self.assertEqual(self.git(self.work,"status","--porcelain"),before)
        self.assertEqual(self.git(self.work,"rev-list","--parents","-n","1",candidate).split(),[candidate,self.source])
        self.assertEqual(self.git(self.work,"rev-parse",candidate+":"+PACKAGE),self.bindings["2.11.4"]["package_tree"])
        for path in ("docs/development-cycle.yaml","docs/work-status/current.md","docs/budget-history.json","product.txt"):
            self.assertEqual(self.git(self.work,"rev-parse",candidate+":"+path),self.git(self.work,"rev-parse",self.source+":"+path))
        self.assertTrue(self.git(self.work,"ls-tree",candidate,"--",PACKAGE+"/runner").startswith("100755"))
        self.assertFalse(prepared["authorizes_product_write"])

    def test_forward_publish_reuses_existing_durable_attempt_and_exact_readback(self):
        p=self.prepare();result=self.delivery.publish(p)
        self.assertEqual(result["action"],"PUBLISHED")
        self.assertEqual(self.remote_head(),p["state"]["candidate_commit"])
        self.assertFalse(result["force_push"])
        self.assertEqual(len(self.attempt.read()[1]["attempts"]),1)

    def test_rollback_is_new_forward_commit_preserving_current_controls_and_old_audit(self):
        p=self.prepare();self.delivery.publish(p);current=p["state"]["candidate_commit"]
        restored=self.delivery.prepare(self.bindings["2.11.3"],expected_head=current,
            transaction_id="rollback-fixture",operation_budget=100,rollback_from=self.source)
        candidate=restored["state"]["candidate_commit"]
        self.assertEqual(self.git(self.work,"rev-parse",candidate+"^"),current)
        self.assertEqual(self.git(self.work,"rev-parse",candidate+":"+PACKAGE),self.bindings["2.11.3"]["package_tree"])
        audit=self.git(self.work,"show",candidate+":docs/cdc-adoption-2.11.3.md")
        self.assertTrue(audit.startswith("original acceptance\n"))
        self.assertIn(self.source,audit)
        self.delivery.publish(restored)
        self.assertEqual(self.remote_head(),candidate)

    def test_stale_owner_and_insufficient_operation_budget_write_no_assembly(self):
        with self.assertRaises(ValueError):
            self.delivery.prepare(self.bindings["2.11.4"],expected_head=self.source,
                transaction_id="low-budget",operation_budget=1)
        self.assertEqual(self.assembly.read(),(None,None))
        self.ownership["expected_revision"]="0"*40
        stale=release_delivery.GitReleaseDelivery(self.work,"origin","refs/heads/main",self.remote_id,
            self.canonical_source,"owner/cdc",self.lease_store,self.ownership,self.attempt,self.assembly,clock=lambda:NOW)
        with self.assertRaises(ValueError): stale.prepare(self.bindings["2.11.4"],expected_head=self.source,
            transaction_id="stale-owner",operation_budget=100)
        self.assertEqual(self.remote_head(),self.source);self.assertEqual(self.assembly.read(),(None,None))

    def test_moved_release_between_assembly_and_publication_rejected(self):
        p=self.prepare();b=self.bindings["2.11.4"]
        self.git(self.canonical,"update-ref",b["release_ref"],self.commit(self.canonical))
        with self.assertRaises(ValueError):self.delivery.publish(p)
        self.assertEqual(self.remote_head(),self.source);self.assertEqual(self.attempt.read(),(None,None))

    def test_unresolved_original_submission_prevents_new_candidate_or_replay(self):
        p=self.prepare();pub=self.delivery.publisher
        pub._prepare(p["state"]);pub._transition(p["state"],"submitted",{"prepared"})
        assembly_before=self.assembly.read()[0]
        with self.assertRaisesRegex(ValueError,"pending|reconcile"):
            self.delivery.prepare(self.bindings["2.11.4"],expected_head=self.source,
                transaction_id="replacement",operation_budget=100)
        self.assertEqual(self.assembly.read()[0],assembly_before)
        with mock.patch.object(pub,"_push",side_effect=AssertionError("must not replay")):
            result=self.delivery.publish(p)
        self.assertEqual(result["action"],"RECONCILE_UNKNOWN")

    def test_lost_push_reply_is_confirmed_once_without_duplicate_effect(self):
        p=self.prepare();push=self.delivery.publisher._push
        def lost_reply(expected,candidate):
            push(expected,candidate)
            raise ValueError("lost response")
        with mock.patch.object(self.delivery.publisher,"_push",side_effect=lost_reply) as m:
            result=self.delivery.publish(p)
        self.assertEqual(result["action"],"CONFIRMED_FROM_READBACK");self.assertEqual(m.call_count,1)
        self.assertEqual(self.remote_head(),p["state"]["candidate_commit"])

    def test_unaccepted_rollback_and_stale_source_rejected(self):
        with self.assertRaises(ValueError):
            self.delivery.prepare(self.bindings["2.11.3"],expected_head=self.source,
                transaction_id="wrong-history",operation_budget=100,rollback_from=self.bindings["2.11.4"]["release_commit"])
        self.write(self.work,"product.txt","new product");new=self.commit(self.work)
        self.git(self.work,"push","-q","origin","main")
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.remote_head(),new)


    def test_existing_publication_reconciles_original_submitted_journal(self):
        p=self.prepare();pub=self.delivery.publisher
        pub._prepare(p["state"]);pub._transition(p["state"],"submitted",{"prepared"})
        self.git(self.work,"push","-q","origin",p["state"]["candidate_commit"]+":refs/heads/main")
        with mock.patch.object(pub,"_push",side_effect=AssertionError("must not replay")):
            result=self.delivery.publish(p)
        self.assertEqual(result["published_head"],p["state"]["candidate_commit"])
        self.assertEqual(self.attempt.read()[1]["attempts"][p["state"]["publication_claim"]["effect_id"]]["status"],"confirmed")
        self.assertEqual(pub.pending_attempts(),[])

    def test_raw_audit_bytes_and_staged_product_index_are_preserved(self):
        # Literal multiple trailing line breaks are part of historical acceptance.
        audit="original acceptance"+chr(10)*3
        self.write(self.work,"docs/cdc-adoption-2.11.3.md",audit)
        self.source=self.commit(self.work);self.git(self.work,"push","-q","origin","main")
        self.write(self.work,"product.txt","staged later product")
        self.git(self.work,"add","product.txt");index_before=self.git(self.work,"write-tree")
        p=self.prepare();self.delivery.publish(p);current=p["state"]["candidate_commit"]
        restored=self.delivery.prepare(self.bindings["2.11.3"],expected_head=current,
            transaction_id="rollback-raw-audit",operation_budget=100,rollback_from=self.source)
        raw=subprocess.check_output(["git","-C",str(self.work),"show",restored["state"]["candidate_commit"]+":docs/cdc-adoption-2.11.3.md"])
        self.assertTrue(raw.startswith(audit.encode()))
        self.assertEqual(self.git(self.work,"write-tree"),index_before)

    def test_forward_and_rollback_preserve_crlf_and_bare_cr_audit_bytes(self):
        paths = ['docs/cdc-adoption-2.11.3.md', 'docs/cdc-adoption-2.11.4.md']
        history = b'original acceptance\r\nrecord retained\rlast\r\n\r\n'
        for path in paths:
            (self.work/path).write_bytes(history)
        self.source=self.commit(self.work);self.git(self.work,'push','-q','origin','main')
        p=self.prepare()
        raw=subprocess.check_output(['git','-C',str(self.work),'show',p['state']['candidate_commit']+':'+paths[1]])
        self.assertTrue(raw.startswith(history))
        self.delivery.publish(p)
        restored=self.delivery.prepare(self.bindings['2.11.3'],expected_head=p['state']['candidate_commit'],
            transaction_id='rollback-newline-bytes',operation_budget=100,rollback_from=self.source)
        raw=subprocess.check_output(['git','-C',str(self.work),'show',restored['state']['candidate_commit']+':'+paths[0]])
        self.assertTrue(raw.startswith(history))
        self.delivery.publish(restored)

    def test_lease_revision_change_at_actual_assembly_push_blocks_effect(self):
        original=self.delivery.assembly_store._git
        changed=False
        def lose_owner(*args,**kwargs):
            nonlocal changed
            if "push" in args and not changed:
                changed=True
                rev,record=self.lease_store.read()
                renewed=lease.renew(record,OWNER,1,"fixture-managed","2026-10-10T12:00:00Z",activity_ref="fixture:renew")
                self.lease_store.compare_and_swap(rev,renewed)
            return original(*args,**kwargs)
        with mock.patch.object(self.delivery.assembly_store,"_git",side_effect=lose_owner):
            with self.assertRaises(ValueError):self.prepare()
        self.assertTrue(changed);self.assertEqual(self.assembly.read(),(None,None))
        self.assertEqual(self.remote_head(),self.source)

    def test_source_symlink_mode_lock_is_rejected_before_assembly(self):
        oid=self.git(self.work,'rev-parse',self.source+':docs/cdc-consumer-lock.json')
        self.git(self.work,'update-index','--cacheinfo','120000,'+oid+',docs/cdc-consumer-lock.json')
        self.git(self.work,'commit','-q','-m','unsupported lock mode')
        self.source=self.git(self.work,'rev-parse','HEAD')
        self.git(self.work,'push','-q','origin','main')
        with self.assertRaisesRegex(ValueError,'regular control'):
            self.prepare()
        self.assertEqual(self.assembly.read(),(None,None))
        self.assertEqual(self.attempt.read(),(None,None))
        self.assertEqual(self.remote_head(),self.source)

    def test_fabricated_owner_callback_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"GitLeaseStore"):
            release_delivery.GitReleaseDelivery(self.work,"origin","refs/heads/main",self.remote_id,
                self.canonical_source,"owner/cdc",lambda:True,self.ownership,self.attempt,self.assembly,clock=lambda:NOW)


    def test_actual_unresolved_guard_blocks_assembly_and_publication(self):
        import operation_intent as op
        p=self.prepare()
        rev,record=self.lease_store.read()
        intent=json.loads((ROOT/"templates/operation-intent.json").read_text())
        intent["binding"]["repository"]="owner/product";intent["source_ref"]="refs/heads/main"
        intent["operation_key"]=op.operation_key(intent["binding"])
        intent["created_at_utc"]=intent["updated_at_utc"]="2026-10-10T12:00:00Z"
        receipt=op.verify_readback(intent,copy.deepcopy(intent),"fixture:intent","2026-10-10T12:00:00Z")
        intent=op.transition(intent,"submitting","2026-10-10T12:00:00Z",receipt=receipt)
        guarded=lease.set_guard(record,OWNER,1,"fixture-managed","2026-10-10T12:00:00Z",intent,"fixture:submitting")
        newrev=self.lease_store.compare_and_swap(rev,guarded)
        self.delivery.ownership["expected_revision"]=newrev
        with self.assertRaisesRegex(ValueError,"guard"):self.prepare()
        with self.assertRaisesRegex(ValueError,"guard"):self.delivery.publish(p)
        self.assertEqual(self.remote_head(),self.source)
        self.assertEqual(self.attempt.read(),(None,None))

    def test_active_checkpoint_and_incompatible_policy_block_delivery(self):
        import yaml
        adapter=project_setup._yaml((self.work/"docs/development-cycle.yaml").read_text())
        cp,body=project_setup._checkpoint((self.work/"docs/work-status/current.md").read_text())
        cp["lease_state"]="active";cp["execution_continuity"]["invocation_id"]="old-active"
        self.write(self.work,"docs/work-status/current.md",project_setup._render_checkpoint(cp,body))
        self.source=self.commit(self.work);self.git(self.work,"push","-q","origin","main")
        with self.assertRaises(ValueError):self.prepare()
        cp["lease_state"]="released";cp["execution_continuity"]["invocation_id"]=None
        adapter["policy"]["skill_max_version_exclusive"]="2.11.4"
        from validate_adapter import validate_adapter
        cp["policy_digest"]=validate_adapter(adapter,skill_version="2.11.3")["policy_digest"]
        self.write(self.work,"docs/development-cycle.yaml",yaml.safe_dump(adapter,sort_keys=False))
        self.write(self.work,"docs/work-status/current.md",project_setup._render_checkpoint(cp,body))
        self.source=self.commit(self.work);self.git(self.work,"push","-q","origin","main")
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.assembly.read(),(None,None))

if __name__=="__main__":unittest.main()

