"""Native exact-release delivery through existing assembly, ownership and publication."""
from __future__ import annotations
import argparse,copy,json,os,re,subprocess,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from consumer_lock import validate as validate_lock
import consumer_adoption as adoption
import migration_transaction as migration
import execution_lease_v2 as lease
from git_document_store import GitDocumentStore
from git_lease_store import GitLeaseStore
from git_object_integrity import git_object_environment
from git_remote_identity import repository_root
from parallel_task_planner import portable_path_key
from live_target import GitSource,verify_release_binding,_sha,_stamp,_identity,_release_binding
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24
from version_convergence import validate_target
import project_setup

PACKAGE=".agents/skills/continuous-development-cycle"
LOCK="docs/cdc-consumer-lock.json"
ADAPTER="docs/development-cycle.yaml"
CHECKPOINT="docs/work-status/current.md"
OWNERSHIP_FIELDS={"expected_revision","repository","source_ref","owner_id","generation","invocation_id"}

def _utc(): return datetime.now(timezone.utc)
def _json(raw):
    def invalid(_): raise ValueError("invalid JSON numeric constant")
    try:return json.loads(raw,object_pairs_hook=project_setup._unique,parse_constant=invalid)
    except (json.JSONDecodeError,RecursionError,TypeError):raise ValueError("invalid delivery JSON") from None

class _CheckedStore(GitDocumentStore):
    def __init__(self,original,guard,protected):
        self.guard=guard
        super().__init__(original.repo,original.remote,original.ref,original.store_id,protected_refs=protected)
    def _git(self,*args,**kwargs):
        if "push" in args:self.guard()
        return super()._git(*args,**kwargs)

class _CheckedPublisher(adoption.GitConsumerAdoptionPublisher):
    def __init__(self,*args,guard,**kwargs):
        self.guard=guard
        super().__init__(*args,**kwargs)
    def _git(self,*args,**kwargs):
        if "push" in args:self.guard()
        return super()._git(*args,**kwargs)

class GitReleaseDelivery:
    """An already managed owner explicitly assembles/publishes; this acquires no lease."""
    def __init__(self,repo,remote,source_ref,source_identity,canonical_source,
                 canonical_repository,lease_store,ownership,attempt_store,assembly_store,*,clock=_utc):
        self.repo=repository_root(Path(repo));self.clock=clock
        self.remote=remote;self.source_ref=source_ref
        if type(lease_store) is not GitLeaseStore:
            raise ValueError("authentic GitLeaseStore is required")
        if not isinstance(ownership,dict) or set(ownership)!=OWNERSHIP_FIELDS:
            raise ValueError("exact managed ownership binding required")
        if ownership["source_ref"]!=source_ref:raise ValueError("owner source ref mismatch")
        self.ownership=copy.deepcopy(ownership);self.lease_store=lease_store
        if not isinstance(canonical_source,GitSource) or canonical_source.repo!=self.repo:
            raise ValueError("native canonical GitSource must share the consumer object cache")
        self.canonical_source=canonical_source;self.canonical_repository=canonical_repository
        self.source=GitSource(self.repo,remote,_identity(source_identity),clock=clock)
        if type(attempt_store) is not GitDocumentStore or type(assembly_store) is not GitDocumentStore:
            raise ValueError("authentic dedicated GitDocumentStore records required")
        for store in (attempt_store,assembly_store):
            if store.repo!=self.repo or store.store_id!=source_identity:
                raise ValueError("delivery store/cache endpoint mismatch")
        protected=[source_ref,attempt_store.ref,assembly_store.ref]
        if lease_store.store_id==source_identity:
            if portable_path_key(lease_store.ref) in {portable_path_key(x) for x in protected}:
                raise ValueError("lease coordination must remain isolated")
            protected.append(lease_store.ref)
        self.attempt_store=_CheckedStore(attempt_store,self._check_owner,[source_ref,assembly_store.ref,*protected[3:]])
        self.assembly_store=_CheckedStore(assembly_store,self._check_owner,[source_ref,attempt_store.ref,*protected[3:]])
        self._publishing_binding=None
        self.publisher=_CheckedPublisher(self.repo,remote,source_ref,source_identity,
            self.attempt_store,self.assembly_store,clock=lambda:_stamp(self.clock()),
            guard=self._publication_guard)

    def _check_owner(self):
        b=self.ownership
        return lease.check(self.lease_store,b["expected_revision"],b["repository"],b["source_ref"],
            b["owner_id"],b["generation"],b["invocation_id"],_stamp(self.clock()),action="product_write")

    def _verify_release(self,binding):
        return verify_release_binding(self.canonical_source,binding,canonical_repository=self.canonical_repository,clock=self.clock)

    def _publication_guard(self):
        if self._publishing_binding is None:raise ValueError("publication release binding is missing")
        self._verify_release(self._publishing_binding)
        self._check_owner()

    def _git(self,*args,input_text=None,index=None,raw=False):
        env=git_object_environment(GIT_TERMINAL_PROMPT="0",GIT_AUTHOR_NAME="CDC delivery",
            GIT_AUTHOR_EMAIL="cdc@example.invalid",GIT_COMMITTER_NAME="CDC delivery",GIT_COMMITTER_EMAIL="cdc@example.invalid")
        if index is not None:env["GIT_INDEX_FILE"]=str(index)
        try:
            data=input_text.encode("utf-8") if isinstance(input_text,str) else input_text
            p=subprocess.run(["git","-C",str(self.repo),*args],input=data,
                capture_output=True,env=env,timeout=30)
            output=p.stdout if raw else p.stdout.decode("utf-8").rstrip("\n")
        except (OSError,subprocess.SubprocessError,UnicodeError):raise ValueError("delivery Git operation unavailable") from None
        if p.returncode:raise ValueError("delivery Git object operation failed")
        return output

    def _read_bytes(self,commit,path):return self._git("cat-file","blob",_sha(commit)+":"+path,raw=True)
    def _read(self,commit,path):return self._read_bytes(commit,path).decode("utf-8")
    def _object(self,commit,path,kind):
        oid=_sha(self._git("rev-parse",_sha(commit)+":"+path))
        if self._git("cat-file","-t",oid)!=kind:raise ValueError("delivery object type mismatch")
        entry=self._git("ls-tree",commit,"--",path)
        if not entry.startswith(("100644 blob ","100755 blob ") if kind=="blob" else ("040000 tree ",)):
            raise ValueError("delivery requires regular control files and a package tree")
        return oid

    def _controls(self,commit,version):
        adapter=project_setup._yaml(self._read(commit,ADAPTER))
        checkpoint,_=project_setup._checkpoint(self._read(commit,CHECKPOINT))
        validate_adapter(adapter,skill_version=version)
        validate_checkpoint_24(checkpoint,adapter,skill_version=version)
        if (adapter["repository"]["remote"]!=self.ownership["repository"] or
                checkpoint["repository"]!=self.ownership["repository"] or
                checkpoint["branch"]!=self.source_ref.removeprefix("refs/heads/") or
                adapter["checkpoint"]["path"]!=CHECKPOINT or
                checkpoint["schema"]!="development-work-status/v4"):
            raise ValueError("delivery controls do not bind the current consumer")
        if checkpoint["lease_state"]!="released" or project_setup._existing_operation(checkpoint) is not None:
            raise ValueError("consumer checkpoint is not a released reconciled boundary")
        return adapter,checkpoint

    def _current_lock(self,commit):
        self._object(commit,LOCK,"blob")
        value=_json(self._read(commit,LOCK))
        try:validate_lock(value)
        except (TypeError,KeyError):raise ValueError("invalid consumer release lock") from None
        if value["canonical_repository"]!=self.canonical_repository:
            raise ValueError("consumer lock canonical repository mismatch")
        if self._object(commit,PACKAGE,"tree")!=value["package_tree"]:
            raise ValueError("current package/lock drift requires separate repair")
        if self._read(commit,PACKAGE+"/VERSION").strip()!=value["version"]:
            raise ValueError("current package VERSION/lock mismatch")
        return value

    def _rollback(self,binding,source,previous):
        _sha(previous)
        if previous==source or not self.source.is_ancestor(previous,source):
            raise ValueError("rollback acceptance must be in current consumer ancestry")
        historic=self._current_lock(previous)
        for name in ("version","release_ref","release_commit","package_tree","canonical_repository"):
            if historic[name]!=binding[name]:raise ValueError("rollback historical acceptance disagrees")
        self._object(previous,"docs/cdc-adoption-"+binding["version"]+".md","blob")
        if not self._read_bytes(previous,"docs/cdc-adoption-"+binding["version"]+".md").strip():
            raise ValueError("rollback historical acceptance audit missing")

    def _pending(self):
        return self.publisher.pending_attempts()

    def prepare(self,binding,*,expected_head,transaction_id,operation_budget,rollback_from=None):
        _sha(expected_head)
        if not isinstance(transaction_id,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",transaction_id):
            raise ValueError("bounded transaction_id required")
        if type(operation_budget) is not int or operation_budget<=0:raise ValueError("operation budget invalid")
        self._check_owner()
        if self._pending():raise ValueError("pending adoption attempt: reconcile original before preparing another")
        proof=self._verify_release(binding);binding=copy.deepcopy(proof["release"])
        snapshot=self.source.pin(self.source_ref)
        if snapshot.revision!=expected_head:raise ValueError("source moved before detached delivery")
        current=self._current_lock(expected_head)
        self._controls(expected_head,current["version"]);self._controls(expected_head,binding["version"])
        if rollback_from is not None:self._rollback(binding,expected_head,rollback_from)
        elif tuple(map(int,binding["version"].split(".")))<tuple(map(int,current["version"].split("."))):
            raise ValueError("version downgrade requires verified rollback acceptance")
        if current["release_commit"]==binding["release_commit"] and current["package_tree"]==binding["package_tree"]:
            raise ValueError("consumer already has this exact release")
        audit="docs/cdc-adoption-"+binding["version"]+".md"
        required=[PACKAGE,LOCK,ADAPTER,CHECKPOINT,audit]
        placeholders=[dict(path=x,object_type="tree" if x==PACKAGE else "blob",object_sha1=binding["package_tree"]) for x in required]
        tx=dict(schema="migration-transaction/v1",transaction_id=transaction_id,source_head=expected_head,
            target_ref=self.source_ref,items=placeholders,completed_paths=[],operation_budget=operation_budget,
            per_item_operations=4,batch_overhead_operations=10,finalization_reserve_operations=4,
            detached_checkpoints=[],final_tree_sha=None,expected_subtree_tree=binding["package_tree"],
            observed_subtree_tree=None,policy_reconciled=True)
        bounded=migration.plan(tx)
        if bounded["action"]!="APPLY_BATCH" or bounded["batch_paths"]!=required:
            raise ValueError("operation budget cannot finish one detached atomic delivery with reserve")
        target_lock={**current,**{k:binding[k] for k in ("version","release_ref","release_commit","package_tree","canonical_repository")}}
        validate_lock(target_lock)
        # Missing audit is normal on forward adoption, but all existing bytes survive.
        exists=self._git("ls-tree",expected_head,"--",audit)
        if exists:self._object(expected_head,audit,"blob")
        previous_audit=self._read_bytes(expected_head,audit) if exists else b""
        audit_record=dict(schema="cdc-delivery-audit/v1",transaction_id=transaction_id,
            mode="rollback" if rollback_from else "adopt",source_head=expected_head,
            previous_acceptance=rollback_from,release_commit=binding["release_commit"],
            package_tree=binding["package_tree"],version=binding["version"])
        appended=previous_audit+(b"\n" if previous_audit and not previous_audit.endswith(b"\n") else b"")
        appended+=("\n"+json.dumps(audit_record,sort_keys=True)+"\n").encode("utf-8")
        fd,path=tempfile.mkstemp(prefix="cdc-delivery-index-");os.close(fd);os.unlink(path)
        index=Path(path)
        try:
            self._git("read-tree",expected_head,index=index)
            old_paths=self._git("ls-files","-z","--",PACKAGE,index=index)
            if old_paths:self._git("update-index","--force-remove","-z","--stdin",input_text=old_paths,index=index)
            self._git("read-tree","--prefix="+PACKAGE+"/",binding["package_tree"],index=index)
            for target,content in ((LOCK,json.dumps(target_lock,sort_keys=True)+"\n"),(audit,appended)):
                blob=_sha(self._git("hash-object","-w","--stdin",input_text=content))
                self._git("update-index","--add","--cacheinfo","100644,"+blob+","+target,index=index)
            tree=_sha(self._git("write-tree",index=index))
            candidate=_sha(self._git("commit-tree",tree,"-p",expected_head,input_text="CDC "+audit_record["mode"]+" "+binding["version"]+"\n"))
        finally:
            for item in (index,Path(str(index)+".lock")):
                if item.exists():item.unlink()
        self._preserved(expected_head,candidate,binding,audit,rollback_from)
        manifest=[dict(path=p,object_type="tree" if p==PACKAGE else "blob",
            object_sha1=self._object(candidate,p,"tree" if p==PACKAGE else "blob")) for p in required]
        tx.update(items=manifest,completed_paths=required,final_tree_sha=tree,observed_subtree_tree=binding["package_tree"])
        record=migration.assembly_record(tx,target_version=binding["version"],target_release_ref=binding["release_ref"],
            target_release_commit=binding["release_commit"],completed_at_utc=_stamp(self.clock()))
        self.source.assert_current(snapshot);self._verify_release(binding);self._check_owner()
        if self._pending():raise ValueError("pending publication appeared during assembly")
        revision,_=self.assembly_store.read()
        revision=self.assembly_store.compare_and_swap(revision,record)
        saved=self.assembly_store.read_revision(revision)
        if saved!=record:raise ValueError("assembly exact durable readback mismatch")
        state=dict(schema=adoption.SCHEMA,source_head=expected_head,target_ref=self.source_ref,
            target_version=binding["version"],target_release_ref=binding["release_ref"],
            target_release_commit=binding["release_commit"],target_package_tree=binding["package_tree"],
            required_paths=required,prepared_paths=required,assembly_manifest=manifest,
            assembly_authority=dict(schema="migration-assembly-authority/v1",store_ref=self.assembly_store.ref,
                store_id=self.assembly_store.store_id,revision=revision,transaction_id=transaction_id,manifest_digest=record["manifest_digest"]),
            final_tree_sha=tree,observed_package_tree=binding["package_tree"],candidate_commit=candidate,
            live_source_head=expected_head,publication_claim=None,published_head=None,readback_package_tree=None)
        state["publication_claim"]=adoption.assess(state)["claim"]
        return dict(schema="cdc-release-delivery/v1",release=binding,rollback_from=rollback_from,state=state,
            authorizes_product_write=False,authorizes_lease_mutation=False,authorizes_external_start=False)

    def _preserved(self,source,candidate,binding,audit,rollback_from):
        current=self._current_lock(source)
        self._controls(source,current["version"])
        if (rollback_from is None and
                tuple(map(int,binding["version"].split(".")))<tuple(map(int,current["version"].split(".")))):
            raise ValueError("version downgrade requires verified rollback acceptance")
        parents=self._git("rev-list","--parents","-n","1",_sha(candidate)).split()
        if parents!=[candidate,source]:raise ValueError("delivery requires a sole direct expected-head parent")
        for p in (ADAPTER,CHECKPOINT):
            if self._object(source,p,"blob")!=self._object(candidate,p,"blob"):
                raise ValueError("delivery must preserve current controls unchanged")
            if self._git("ls-tree",source,"--",p)!=self._git("ls-tree",candidate,"--",p):
                raise ValueError("delivery must preserve current control modes")
        changed=self._git("diff-tree","--no-commit-id","--name-only","-r","-z",source,candidate).split("\0")
        if any(p and p not in {LOCK,audit} and not p.startswith(PACKAGE+"/") for p in changed):
            raise ValueError("delivery changed an unmanaged product path")
        self._controls(candidate,binding["version"])
        lock=self._current_lock(candidate)
        for name in ("version","release_ref","release_commit","package_tree","canonical_repository"):
            if lock[name]!=binding[name]:raise ValueError("delivery target lock disagrees")
        exists=self._git("ls-tree",source,"--",audit)
        prior=self._read_bytes(source,audit) if exists else b""
        result=self._read_bytes(candidate,audit)
        if not result.startswith(prior):raise ValueError("delivery audit history was overwritten")
        try:record=_json(result.splitlines()[-1])
        except (IndexError,ValueError):raise ValueError("delivery audit record missing") from None
        if (record.get("schema")!="cdc-delivery-audit/v1" or record.get("source_head")!=source or
                record.get("previous_acceptance")!=rollback_from or record.get("release_commit")!=binding["release_commit"] or
                record.get("package_tree")!=binding["package_tree"] or record.get("version")!=binding["version"] or
                record.get("mode")!=("rollback" if rollback_from else "adopt")):
            raise ValueError("delivery audit binding mismatch")
        if rollback_from is not None:self._rollback(binding,source,rollback_from)

    def publish(self,prepared):
        fields={"schema","release","rollback_from","state","authorizes_product_write","authorizes_lease_mutation","authorizes_external_start"}
        if not isinstance(prepared,dict) or set(prepared)!=fields or prepared["schema"]!="cdc-release-delivery/v1":
            raise ValueError("invalid prepared delivery")
        if any(prepared[k] is not False for k in fields if k.startswith("authorizes_")):
            raise ValueError("prepared data cannot grant authority")
        state=prepared["state"];adoption.validate(state)
        binding=prepared["release"];self._verify_release(binding);self._check_owner()
        expected=[PACKAGE,LOCK,ADAPTER,CHECKPOINT,"docs/cdc-adoption-"+binding["version"]+".md"]
        if state["required_paths"]!=expected or state["prepared_paths"]!=expected:
            raise ValueError("delivery exact required path set mismatch")
        for name,key in (("target_version","version"),("target_release_ref","release_ref"),
                         ("target_release_commit","release_commit"),("target_package_tree","package_tree")):
            if state[name]!=binding[key]:raise ValueError("publication exact release binding mismatch")
        for pending in self._pending():
            if pending["effect_id"]!=state["publication_claim"]["effect_id"]:
                raise ValueError("reconcile another original pending attempt before publication")
        self._preserved(state["source_head"],state["candidate_commit"],binding,expected[-1],prepared["rollback_from"])
        self._publishing_binding=copy.deepcopy(binding)
        try:return self.publisher.publish(state)
        finally:self._publishing_binding=None

def plan(request):
    """Validate proposed delivery data; live verification and managed authority are still required."""
    fields={"schema","source_head","canonical_repository","canonical_source_identity","release",
            "current_lock","rollback_from","operation_budget"}
    if not isinstance(request,dict) or set(request)!=fields or request.get("schema")!="cdc-delivery-request/v1":
        raise ValueError("invalid delivery request fields")
    _sha(request["source_head"]);_identity(request["canonical_source_identity"])
    binding=request["release"];current=request["current_lock"]
    try:
        validate_lock(current)
        if not isinstance(binding,dict):raise ValueError("invalid proposed release")
        target=dict(schema="version-convergence-target/v1",target_version=binding.get("version"),
            target_package_fingerprint="git-tree:"+str(binding.get("package_tree")),
            checkpoint_schema="development-work-status/v4",safe_boundary_required=True)
        validate_target(target);_release_binding(binding,target,request["canonical_repository"])
        if binding["schema"]=="live-target-release/v2":
            from live_target import _evidence_binding
            _evidence_binding(binding,request["canonical_source_identity"])
        if (not isinstance(request["canonical_repository"],str) or
                not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",request["canonical_repository"]) or
                current["canonical_repository"]!=request["canonical_repository"]):
            raise ValueError("delivery configured canonical repository mismatch")
    except (TypeError,KeyError,AttributeError):raise ValueError("invalid proposed release/consumer lock") from None
    if type(request["operation_budget"]) is not int or request["operation_budget"]<=0:
        raise ValueError("invalid operation budget")
    previous=request["rollback_from"]
    if previous is not None:_sha(previous)
    if previous is None and tuple(map(int,binding["version"].split(".")))<tuple(map(int,current["version"].split("."))):
        raise ValueError("downgrade requires historical rollback acceptance")
    checks=["fresh_configured_canonical_release_and_evidence","fresh_consumer_source",
            "authentic_invocation_bound_owner_without_guard","compatible_unchanged_controls",
            "reconciled_original_attempt_journal","durable_exact_assembly_and_conditional_readback"]
    if previous is not None:checks.append("verified_historical_consumer_acceptance")
    return dict(schema="cdc-delivery-plan/v1",action="VERIFY_RELEASE_AND_OWNERSHIP",
        mode="rollback" if previous is not None else "adopt",source_head=request["source_head"],
        release=copy.deepcopy(binding),rollback_from=previous,required_live_checks=checks,
        publication_prerequisites_satisfied=False,authorizes_product_write=False,
        authorizes_ref_move=False,authorizes_force_push=False,authorizes_external_start=False,
        authorizes_lease_mutation=False,authorizes_adoption=False,authorizes_release=False,
        authorizes_scheduler_write=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("input")
    args=parser.parse_args(argv)
    try:
        result=plan(_json(Path(args.input).read_text(encoding="utf-8")))
        print(json.dumps(result,sort_keys=True,allow_nan=False));return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print("FAIL: "+str(exc),file=sys.stderr);return 2

if __name__=="__main__":raise SystemExit(main())


