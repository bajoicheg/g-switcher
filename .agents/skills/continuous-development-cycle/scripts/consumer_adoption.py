#!/usr/bin/env python3
"""Fail-closed atomic consumer adoption publication planning."""
from __future__ import annotations
import argparse,copy,hashlib,json,re,secrets,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

from git_document_store import GitDocumentStore
from git_object_integrity import git_object_environment
from git_remote_identity import isolated_remote_args,remote_identity,repository_root
from parallel_task_planner import portable_path_key
import migration_transaction as migration

SCHEMA="consumer-adoption-publication/v1"
REQUIRED_STATIC_PATHS={
    ".agents/skills/continuous-development-cycle",
    "docs/cdc-consumer-lock.json",
    "docs/development-cycle.yaml",
    "docs/work-status/current.md",
}
SHA=re.compile(r"^[0-9a-f]{40}$");DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER=re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

def _sha(v,n,nullable=False):
    if v is None and nullable:return
    if not isinstance(v,str) or not SHA.fullmatch(v):raise ValueError(n+" invalid")

def _path(v):
    if not isinstance(v,str) or not v or v.startswith("/") or v.endswith("/") or any(x in {"",".",".."} for x in v.split("/")):raise ValueError("adoption path invalid")
    return v

def validate(s):
    fields={"schema","source_head","target_ref","target_version","target_release_ref","target_release_commit",
            "target_package_tree","required_paths","prepared_paths","assembly_manifest","assembly_authority",
            "final_tree_sha","observed_package_tree","candidate_commit","live_source_head","publication_claim",
            "published_head","readback_package_tree"}
    if not isinstance(s,dict) or set(s)!=fields or s.get("schema")!=SCHEMA:raise ValueError("atomic adoption state invalid")
    _sha(s["source_head"],"source_head");_sha(s["target_package_tree"],"target_package_tree");_sha(s["live_source_head"],"live_source_head")
    _sha(s["target_release_commit"],"target_release_commit")
    if not isinstance(s["target_ref"],str) or not s["target_ref"].startswith("refs/heads/"):raise ValueError("target_ref invalid")
    if not isinstance(s["target_release_ref"],str) or not s["target_release_ref"].startswith("refs/heads/release/"):raise ValueError("target_release_ref invalid")
    if not isinstance(s["target_version"],str) or not SEMVER.fullmatch(s["target_version"]):raise ValueError("target_version invalid")
    for n in ("final_tree_sha","observed_package_tree","candidate_commit","published_head","readback_package_tree"):_sha(s[n],n,True)
    if not isinstance(s["required_paths"],list) or not s["required_paths"]:raise ValueError("required_paths invalid")
    required=[_path(x) for x in s["required_paths"]]
    prepared=[_path(x) for x in s["prepared_paths"]] if isinstance(s["prepared_paths"],list) else (_ for _ in ()).throw(ValueError("prepared_paths invalid"))
    if len(required)!=len(set(required)) or len(prepared)!=len(set(prepared)):raise ValueError("duplicate adoption path")
    required_core=REQUIRED_STATIC_PATHS|{"docs/cdc-adoption-"+s["target_version"]+".md"}
    if not required_core<=set(required):raise ValueError("atomic adoption required core path missing")
    if not set(prepared)<=set(required):raise ValueError("prepared path outside required set")
    manifest=s["assembly_manifest"]
    if not isinstance(manifest,list) or len(manifest)!=len(required):raise ValueError("assembly_manifest must cover every required path exactly once")
    manifest_paths=[]
    for item in manifest:
        if not isinstance(item,dict) or set(item)!={"path","object_type","object_sha1"}:raise ValueError("assembly manifest item invalid")
        path=_path(item["path"]);manifest_paths.append(path)
        if item["object_type"] not in {"blob","tree"}:raise ValueError("assembly manifest object_type invalid")
        _sha(item["object_sha1"],"assembly manifest object")
    if len(manifest_paths)!=len(set(manifest_paths)) or set(manifest_paths)!=set(required):
        raise ValueError("assembly_manifest path set mismatch")
    package=[x for x in manifest if x["path"]==".agents/skills/continuous-development-cycle"]
    if len(package)!=1 or package[0]["object_type"]!="tree" or package[0]["object_sha1"]!=s["target_package_tree"]:
        raise ValueError("assembly manifest package tree mismatch")
    authority=s["assembly_authority"]
    afields={"schema","store_ref","store_id","revision","transaction_id","manifest_digest"}
    if not isinstance(authority,dict) or set(authority)!=afields or authority.get("schema")!="migration-assembly-authority/v1":
        raise ValueError("assembly authority invalid")
    if not isinstance(authority["store_ref"],str) or not authority["store_ref"].startswith("refs/heads/cdc/"):
        raise ValueError("assembly authority store_ref invalid")
    if not isinstance(authority["store_id"],str) or not DIGEST.fullmatch(authority["store_id"]):
        raise ValueError("assembly authority store_id invalid")
    if not isinstance(authority["revision"],str) or not re.fullmatch(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$",authority["revision"]):
        raise ValueError("assembly authority revision invalid")
    if not isinstance(authority["transaction_id"],str) or not authority["transaction_id"].strip():
        raise ValueError("assembly authority transaction_id invalid")
    if not isinstance(authority["manifest_digest"],str) or not DIGEST.fullmatch(authority["manifest_digest"]):
        raise ValueError("assembly authority manifest_digest invalid")
    if authority["manifest_digest"]!=_manifest_digest(manifest):
        raise ValueError("assembly authority digest does not bind supplied manifest")
    claim=s["publication_claim"]
    if claim is not None:
        if not isinstance(claim,dict) or set(claim)!={"effect_id","expected_head","intended_head","target_ref","manifest_digest",
                                                      "assembly_store_ref","assembly_store_id","assembly_revision","transaction_id"}:raise ValueError("publication claim invalid")
        if not isinstance(claim["effect_id"],str) or not DIGEST.fullmatch(claim["effect_id"]):raise ValueError("publication effect id invalid")
        _sha(claim["expected_head"],"claim expected_head");_sha(claim["intended_head"],"claim intended_head")
        if not isinstance(claim["manifest_digest"],str) or not DIGEST.fullmatch(claim["manifest_digest"]):raise ValueError("publication manifest digest invalid")
        authority=s["assembly_authority"]
        if (claim["target_ref"]!=s["target_ref"] or claim["manifest_digest"]!=_manifest_digest(s["assembly_manifest"])
                or claim["assembly_store_ref"]!=authority["store_ref"] or claim["assembly_store_id"]!=authority["store_id"]
                or claim["assembly_revision"]!=authority["revision"] or claim["transaction_id"]!=authority["transaction_id"]):
            raise ValueError("publication claim binding mismatch")
    return s

def _manifest_digest(manifest):
    raw=json.dumps(manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def _claim(s):
    manifest_digest=_manifest_digest(s["assembly_manifest"])
    authority=s["assembly_authority"]
    payload={"target_ref":s["target_ref"],"expected_head":s["source_head"],"intended_head":s["candidate_commit"],
             "target_version":s["target_version"],"target_release_ref":s["target_release_ref"],
             "target_release_commit":s["target_release_commit"],"target_package_tree":s["target_package_tree"],
             "manifest_digest":manifest_digest,"assembly_store_ref":authority["store_ref"],
             "assembly_store_id":authority["store_id"],"assembly_revision":authority["revision"],
             "transaction_id":authority["transaction_id"]}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"effect_id":"sha256:"+digest,"expected_head":s["source_head"],"intended_head":s["candidate_commit"],
            "target_ref":s["target_ref"],"manifest_digest":manifest_digest,
            "assembly_store_ref":authority["store_ref"],"assembly_store_id":authority["store_id"],
            "assembly_revision":authority["revision"],"transaction_id":authority["transaction_id"]}

def assess(s):
    validate(s)
    common={"schema":"consumer-adoption-publication-plan/v1","authorizes_ref_move":False,"authorizes_force_push":False,
            "authorizes_product_write":False,"publication_prerequisites_satisfied":False}
    missing=[p for p in s["required_paths"] if p not in s["prepared_paths"]]
    if missing:return {**common,"action":"PREPARE_DETACHED","missing_paths":missing,"reason":"shared_ref_must_remain_unchanged"}
    if s["final_tree_sha"] is None:return {**common,"action":"BUILD_FINAL_TREE","missing_paths":[],"reason":"all_required_paths_prepared_detached"}
    if s["observed_package_tree"] is None:return {**common,"action":"VERIFY_PACKAGE_TREE","missing_paths":[],"reason":"exact_target_subtree_not_observed"}
    if s["observed_package_tree"]!=s["target_package_tree"]:return {**common,"action":"REJECT_PACKAGE_DRIFT","missing_paths":[],"reason":"target_package_tree_mismatch"}
    if s["candidate_commit"] is None:return {**common,"action":"BUILD_CANDIDATE_COMMIT","missing_paths":[],"reason":"detached_tree_verified"}
    if s["live_source_head"]!=s["source_head"]:return {**common,"action":"REPLAN_FRESH_HEAD","missing_paths":[],"reason":"shared_ref_moved_before_publication"}
    expected=_claim(s)
    if s["publication_claim"] is None:return {**common,"action":"CLAIM_CONDITIONAL_PUBLISH","missing_paths":[],"claim":expected,"reason":"exact_candidate_ready"}
    if s["publication_claim"]!=expected:raise ValueError("publication claim does not bind exact candidate")
    if s["published_head"] is None:
        return {**common,"action":"READY_CONDITIONAL_FAST_FORWARD","missing_paths":[],"claim":expected,
                "publication_prerequisites_satisfied":True,"reason":"one_shared_ref_effect_required"}
    if s["published_head"]!=s["candidate_commit"]:
        return {**common,"action":"RECONCILE_PUBLICATION","missing_paths":[],"claim":expected,"reason":"published_head_not_exact_candidate"}
    if s["readback_package_tree"] is None:
        return {**common,"action":"READBACK_PUBLISHED_PACKAGE","missing_paths":[],"claim":expected,"reason":"publication_requires_exact_readback"}
    if s["readback_package_tree"]!=s["target_package_tree"]:
        return {**common,"action":"RECOVERY_REQUIRED","missing_paths":[],"claim":expected,"reason":"published_package_tree_mismatch"}
    return {**common,"action":"COMPLETE","missing_paths":[],"claim":expected,"publication_prerequisites_satisfied":True,
            "reason":"single_conditional_publish_and_exact_readback"}

ATTEMPT_SCHEMA="consumer-adoption-attempts/v1"
ATTEMPT_STATES={"prepared","submitted","unknown","confirmed","rejected","aborted"}

def _now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

class GitConsumerAdoptionPublisher:
    """Publish one fully assembled consumer adoption by durable, non-replayed Git CAS."""

    def __init__(self,repo,remote,target_ref,remote_id,attempt_store,assembly_store,*,clock=None,
                 package_path=".agents/skills/continuous-development-cycle"):
        self.repo=repository_root(repo)
        self.remote=remote
        self.target_ref=target_ref
        self.remote_id=remote_id
        self.attempt_store=attempt_store
        self.assembly_store=assembly_store
        self.clock=clock or _now_utc
        self.package_path=package_path
        if not isinstance(target_ref,str) or not target_ref.startswith("refs/heads/"):
            raise ValueError("consumer target_ref invalid")
        self._git("check-ref-format",target_ref)
        _path(package_path)
        if not isinstance(attempt_store,GitDocumentStore):
            raise ValueError("consumer adoption publication requires GitDocumentStore attempt journal")
        if not isinstance(assembly_store,GitDocumentStore):
            raise ValueError("consumer adoption publication requires authoritative GitDocumentStore assembly record")
        if attempt_store.store_id!=remote_id or assembly_store.store_id!=remote_id:
            raise ValueError("consumer adoption store remote identity mismatch")
        if portable_path_key(attempt_store.ref)==portable_path_key(target_ref):
            raise ValueError("consumer adoption attempt ref must be isolated from product ref")
        if portable_path_key(assembly_store.ref) in {portable_path_key(target_ref),portable_path_key(attempt_store.ref)}:
            raise ValueError("consumer adoption assembly ref must be isolated from product and attempt refs")
        if remote_identity(self.repo,self.remote)!=self.remote_id:
            raise ValueError("consumer adoption remote identity drift")

    def _git(self,*args,input_text=None,check=True):
        env=git_object_environment(GIT_TERMINAL_PROMPT="0",
            GIT_AUTHOR_NAME="CDC adoption",GIT_AUTHOR_EMAIL="cdc@example.invalid",
            GIT_COMMITTER_NAME="CDC adoption",GIT_COMMITTER_EMAIL="cdc@example.invalid")
        try:
            p=subprocess.run(["git","-C",str(self.repo),*args],input=input_text,text=True,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=30)
        except (OSError,subprocess.SubprocessError):
            raise ValueError("consumer adoption Git transport unavailable") from None
        if check and p.returncode:
            raise ValueError("consumer adoption Git command failed")
        return p.stdout.rstrip("\n"),p.returncode

    def _remote_head(self):
        if remote_identity(self.repo,self.remote)!=self.remote_id:
            raise ValueError("consumer adoption remote identity drift")
        config,alias=isolated_remote_args(self.repo,self.remote,self.remote_id)
        out,_=self._git(*config,"ls-remote","--refs",alias,self.target_ref)
        rows=[x for x in out.splitlines() if x.strip()]
        if len(rows)!=1:
            raise ValueError("consumer target ref must resolve exactly once")
        parts=rows[0].split("\t")
        if len(parts)!=2 or parts[1]!=self.target_ref or not SHA.fullmatch(parts[0]):
            raise ValueError("consumer target ref response invalid")
        return parts[0]

    def _package_tree(self,commit):
        out,_=self._git("rev-parse",f"{commit}:{self.package_path}")
        if not SHA.fullmatch(out):
            raise ValueError("consumer candidate package tree invalid")
        return out

    def _resolve_assembly(self,state):
        authority=state["assembly_authority"]
        if self.assembly_store.ref!=authority["store_ref"] or self.assembly_store.store_id!=authority["store_id"]:
            raise ValueError("assembly authority does not match configured authoritative store")
        record=self.assembly_store.read_revision(authority["revision"])
        migration.validate_assembly_record(record)
        expected={
            "transaction_id":authority["transaction_id"],"source_head":state["source_head"],
            "target_ref":state["target_ref"],"target_version":state["target_version"],
            "target_release_ref":state["target_release_ref"],"target_release_commit":state["target_release_commit"],
            "final_tree_sha":state["final_tree_sha"],"expected_subtree_tree":state["target_package_tree"],
            "manifest_digest":authority["manifest_digest"],
        }
        for name,value in expected.items():
            if record.get(name)!=value:
                raise ValueError("authoritative assembly transaction binding mismatch: "+name)
        if record["manifest"]!=state["assembly_manifest"]:
            raise ValueError("caller assembly manifest does not match authoritative transaction manifest")
        return record

    def _verify_candidate(self,state):
        plan=assess(state)
        assembly=self._resolve_assembly(state)
        if plan["action"]!="READY_CONDITIONAL_FAST_FORWARD":
            raise ValueError("consumer adoption candidate is not ready for conditional publication")
        if state["target_ref"]!=self.target_ref:
            raise ValueError("consumer adoption target ref mismatch")
        candidate=state["candidate_commit"];source=state["source_head"]
        kind,_=self._git("cat-file","-t",candidate)
        if kind!="commit":
            raise ValueError("consumer adoption candidate must be a commit")
        _,code=self._git("merge-base","--is-ancestor",source,candidate,check=False)
        if code!=0:
            raise ValueError("consumer adoption candidate must fast-forward expected source")
        root_tree,_=self._git("rev-parse",candidate+"^{tree}")
        if root_tree!=state["final_tree_sha"]:
            raise ValueError("consumer adoption candidate root tree does not match detached final tree")
        manifest={item["path"]:item for item in assembly["manifest"]}
        for path in state["required_paths"]:
            _,code=self._git("cat-file","-e",f"{candidate}:{path}",check=False)
            if code!=0:
                raise ValueError("consumer adoption candidate missing required path: "+path)
            object_sha,_=self._git("rev-parse",f"{candidate}:{path}")
            object_type,_=self._git("cat-file","-t",object_sha)
            expected=manifest[path]
            if object_sha!=expected["object_sha1"] or object_type!=expected["object_type"]:
                raise ValueError("consumer adoption candidate object identity mismatch: "+path)
        lock_raw,_=self._git("show",f"{candidate}:docs/cdc-consumer-lock.json")
        try:lock=json.loads(lock_raw)
        except json.JSONDecodeError as exc:raise ValueError("consumer lock JSON invalid") from exc
        expected_lock={
            "version":state["target_version"],
            "package_tree":state["target_package_tree"],
            "release_ref":state["target_release_ref"],
            "release_commit":state["target_release_commit"],
        }
        for name,value in expected_lock.items():
            if lock.get(name)!=value:
                raise ValueError("consumer lock target binding mismatch: "+name)
        tree=self._package_tree(candidate)
        if tree!=state["target_package_tree"]:
            raise ValueError("consumer adoption candidate package tree mismatch")
        return plan

    def _initial_journal(self):
        return {"schema":ATTEMPT_SCHEMA,"remote_id":self.remote_id,"target_ref":self.target_ref,
                "attempt_store_ref":self.attempt_store.ref,"attempts":{}}

    def _read_journal(self):
        revision,state=self.attempt_store.read()
        if state is None:
            return revision,self._initial_journal()
        initial=self._initial_journal()
        if (not isinstance(state,dict) or set(state)!=set(initial) or state["schema"]!=ATTEMPT_SCHEMA
                or state["remote_id"]!=self.remote_id or state["target_ref"]!=self.target_ref
                or state["attempt_store_ref"]!=self.attempt_store.ref or not isinstance(state["attempts"],dict)):
            raise ValueError("consumer adoption attempt journal identity mismatch")
        for effect_id,a in state["attempts"].items():
            fields={"effect_id","expected_head","intended_head","target_package_tree","target_release_ref",
                    "target_release_commit","manifest_digest","assembly_store_ref","assembly_store_id",
                    "assembly_revision","transaction_id","status",
                    "prepared_at_utc","submitted_at_utc","resolved_at_utc"}
            if (not isinstance(a,dict) or set(a)!=fields or a["effect_id"]!=effect_id
                    or not isinstance(effect_id,str) or not DIGEST.fullmatch(effect_id)
                    or a["status"] not in ATTEMPT_STATES):
                raise ValueError("consumer adoption attempt invalid")
            for name in ("expected_head","intended_head","target_package_tree","target_release_commit"):_sha(a[name],name)
            if not isinstance(a["target_release_ref"],str) or not a["target_release_ref"].startswith("refs/heads/release/"):
                raise ValueError("consumer adoption attempt target_release_ref invalid")
            if not isinstance(a["manifest_digest"],str) or not DIGEST.fullmatch(a["manifest_digest"]):
                raise ValueError("consumer adoption attempt manifest digest invalid")
            if not isinstance(a["assembly_store_ref"],str) or not a["assembly_store_ref"].startswith("refs/heads/cdc/"):
                raise ValueError("consumer adoption attempt assembly_store_ref invalid")
            if not isinstance(a["assembly_store_id"],str) or not DIGEST.fullmatch(a["assembly_store_id"]):
                raise ValueError("consumer adoption attempt assembly_store_id invalid")
            if not isinstance(a["assembly_revision"],str) or not re.fullmatch(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$",a["assembly_revision"]):
                raise ValueError("consumer adoption attempt assembly_revision invalid")
            if not isinstance(a["transaction_id"],str) or not a["transaction_id"].strip():
                raise ValueError("consumer adoption attempt transaction_id invalid")
            if not isinstance(a["prepared_at_utc"],str) or not a["prepared_at_utc"].endswith("Z"):
                raise ValueError("consumer adoption attempt prepared timestamp invalid")
            for name in ("submitted_at_utc","resolved_at_utc"):
                if a[name] is not None and (not isinstance(a[name],str) or not a[name].endswith("Z")):
                    raise ValueError("consumer adoption attempt timestamp invalid")
            if a["status"]=="prepared" and (a["submitted_at_utc"] is not None or a["resolved_at_utc"] is not None):
                raise ValueError("prepared adoption attempt has impossible timestamps")
            if a["status"] in {"submitted","unknown","confirmed","rejected"} and a["submitted_at_utc"] is None:
                raise ValueError("submitted-derived adoption attempt missing submission time")
            if a["status"] in {"confirmed","rejected","aborted"} and a["resolved_at_utc"] is None:
                raise ValueError("resolved adoption attempt missing resolution time")
        return revision,state

    def _attempt_fields(self,state):
        claim=state["publication_claim"]
        return {"effect_id":claim["effect_id"],
                "expected_head":state["source_head"],"intended_head":state["candidate_commit"],
                "target_package_tree":state["target_package_tree"],
                "target_release_ref":state["target_release_ref"],"target_release_commit":state["target_release_commit"],
                "manifest_digest":claim["manifest_digest"],"assembly_store_ref":claim["assembly_store_ref"],
                "assembly_store_id":claim["assembly_store_id"],"assembly_revision":claim["assembly_revision"],
                "transaction_id":claim["transaction_id"]}

    def _prepare(self,state):
        expected=self._attempt_fields(state)
        for _ in range(6):
            revision,journal=self._read_journal()
            existing=journal["attempts"].get(expected["effect_id"])
            if existing is not None:
                if any(existing[k]!=v for k,v in expected.items()):
                    raise ValueError("consumer adoption attempt identity collision")
                return copy.deepcopy(existing)
            attempt={**expected,"status":"prepared","prepared_at_utc":self.clock(),
                     "submitted_at_utc":None,"resolved_at_utc":None}
            changed=copy.deepcopy(journal);changed["attempts"][expected["effect_id"]]=attempt
            try:
                self.attempt_store.compare_and_swap(revision,changed)
                return copy.deepcopy(attempt)
            except ValueError:
                continue
        raise ValueError("consumer adoption attempt journal contention")

    def _transition(self,state,status,allowed):
        effect_id=state["publication_claim"]["effect_id"]
        for _ in range(6):
            revision,journal=self._read_journal()
            attempt=journal["attempts"].get(effect_id)
            if attempt is None:
                raise ValueError("consumer adoption attempt missing")
            if attempt["status"] not in allowed:
                raise ValueError("consumer adoption attempt transition invalid")
            changed=copy.deepcopy(journal);item=changed["attempts"][effect_id]
            item["status"]=status
            if status=="submitted":
                item["submitted_at_utc"]=self.clock()
            if status in {"confirmed","rejected","aborted"}:
                item["resolved_at_utc"]=self.clock()
            try:
                self.attempt_store.compare_and_swap(revision,changed)
                return copy.deepcopy(item)
            except ValueError:
                continue
        raise ValueError("consumer adoption attempt transition contention")

    def _push(self,expected,candidate):
        if self._remote_head()!=expected:
            raise ValueError("consumer target ref moved before publication")
        config,alias=isolated_remote_args(self.repo,self.remote,self.remote_id)
        _,code=self._git(*config,"-c","push.followTags=false","push","--porcelain",alias,
                         f"{candidate}:{self.target_ref}",check=False)
        if code!=0:
            raise ValueError("consumer conditional publication transport failed")

    def _exact_readback(self,state):
        current=self._remote_head()
        if current!=state["candidate_commit"]:
            return False
        return self._package_tree(current)==state["target_package_tree"]

    def publish(self,state):
        self._verify_candidate(state)
        current=self._remote_head()
        if current==state["candidate_commit"]:
            if not self._exact_readback(state):
                raise ValueError("consumer published candidate package readback mismatch")
            return {"schema":"consumer-adoption-publication-result/v1","action":"OBSERVED_EXISTING",
                    "published_head":current,"package_tree":state["target_package_tree"],
                    "conditional_update":False,"force_push":False,"replay_allowed":False}
        if current!=state["source_head"]:
            return {"schema":"consumer-adoption-publication-result/v1","action":"REPLAN_FRESH_HEAD",
                    "published_head":current,"package_tree":None,
                    "conditional_update":False,"force_push":False,"replay_allowed":False}

        attempt=self._prepare(state)
        if attempt["status"] in {"submitted","unknown"}:
            if self._exact_readback(state):
                self._transition(state,"confirmed",{attempt["status"]})
                return {"schema":"consumer-adoption-publication-result/v1","action":"CONFIRMED_FROM_READBACK",
                        "published_head":state["candidate_commit"],"package_tree":state["target_package_tree"],
                        "conditional_update":True,"force_push":False,"replay_allowed":False}
            return {"schema":"consumer-adoption-publication-result/v1","action":"RECONCILE_UNKNOWN",
                    "published_head":self._remote_head(),"package_tree":None,
                    "conditional_update":False,"force_push":False,"replay_allowed":False}
        if attempt["status"]=="confirmed":
            if not self._exact_readback(state):
                raise ValueError("confirmed adoption attempt no longer matches target ref")
            return {"schema":"consumer-adoption-publication-result/v1","action":"CONFIRMED",
                    "published_head":state["candidate_commit"],"package_tree":state["target_package_tree"],
                    "conditional_update":True,"force_push":False,"replay_allowed":False}
        if attempt["status"] in {"rejected","aborted"}:
            return {"schema":"consumer-adoption-publication-result/v1","action":"TERMINAL_NO_REPLAY",
                    "published_head":current,"package_tree":None,
                    "conditional_update":False,"force_push":False,"replay_allowed":False}

        if self._remote_head()!=state["source_head"]:
            self._transition(state,"aborted",{"prepared"})
            return {"schema":"consumer-adoption-publication-result/v1","action":"REPLAN_FRESH_HEAD",
                    "published_head":self._remote_head(),"package_tree":None,
                    "conditional_update":False,"force_push":False,"replay_allowed":False}

        self._transition(state,"submitted",{"prepared"})
        try:
            self._push(state["source_head"],state["candidate_commit"])
        except ValueError:
            try:
                after=self._remote_head()
            except ValueError:
                revision,journal=self._read_journal()
                item=journal["attempts"][state["publication_claim"]["effect_id"]]
                if item["status"]=="submitted":
                    changed=copy.deepcopy(journal)
                    changed["attempts"][item["effect_id"]]["status"]="unknown"
                    try:self.attempt_store.compare_and_swap(revision,changed)
                    except ValueError:pass
                return {"schema":"consumer-adoption-publication-result/v1","action":"RECONCILE_UNKNOWN",
                        "published_head":None,"package_tree":None,
                        "conditional_update":False,"force_push":False,"replay_allowed":False}
            if after==state["candidate_commit"] and self._exact_readback(state):
                self._transition(state,"confirmed",{"submitted"})
                return {"schema":"consumer-adoption-publication-result/v1","action":"CONFIRMED_FROM_READBACK",
                        "published_head":after,"package_tree":state["target_package_tree"],
                        "conditional_update":True,"force_push":False,"replay_allowed":False}
            if after==state["source_head"]:
                self._transition(state,"rejected",{"submitted"})
                return {"schema":"consumer-adoption-publication-result/v1","action":"REJECTED",
                        "published_head":after,"package_tree":None,
                        "conditional_update":False,"force_push":False,"replay_allowed":False}
            revision,journal=self._read_journal()
            item=journal["attempts"][state["publication_claim"]["effect_id"]]
            if item["status"]=="submitted":
                changed=copy.deepcopy(journal);changed["attempts"][item["effect_id"]]["status"]="unknown"
                try:self.attempt_store.compare_and_swap(revision,changed)
                except ValueError:pass
            return {"schema":"consumer-adoption-publication-result/v1","action":"RECONCILE_UNKNOWN",
                    "published_head":after,"package_tree":None,
                    "conditional_update":False,"force_push":False,"replay_allowed":False}

        if not self._exact_readback(state):
            revision,journal=self._read_journal()
            item=journal["attempts"][state["publication_claim"]["effect_id"]]
            if item["status"]=="submitted":
                changed=copy.deepcopy(journal);changed["attempts"][item["effect_id"]]["status"]="unknown"
                try:self.attempt_store.compare_and_swap(revision,changed)
                except ValueError:pass
            return {"schema":"consumer-adoption-publication-result/v1","action":"RECONCILE_UNKNOWN",
                    "published_head":self._remote_head(),"package_tree":None,
                    "conditional_update":True,"force_push":False,"replay_allowed":False}
        self._transition(state,"confirmed",{"submitted"})
        return {"schema":"consumer-adoption-publication-result/v1","action":"PUBLISHED",
                "published_head":state["candidate_commit"],"package_tree":state["target_package_tree"],
                "conditional_update":True,"force_push":False,"replay_allowed":False}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("state");a=p.parse_args(argv)
    try:r=assess(json.loads(Path(a.state).read_text(encoding="utf-8")))
    except (OSError,ValueError,json.JSONDecodeError) as e:print("FAIL:",e,file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0 if r["action"] not in {"REJECT_PACKAGE_DRIFT","RECOVERY_REQUIRED"} else 1
if __name__=="__main__":raise SystemExit(main())
