
#!/usr/bin/env python3
from __future__ import annotations
import copy, hashlib, json, os, shutil, subprocess, sys, tempfile, time, uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = os.environ["CDC_REPOSITORY"]
SOURCE_REF = os.environ["CDC_SOURCE_REF"]
TARGET_VERSION = "2.12.0"
TARGET_RELEASE_REF = "refs/heads/release/v2.12.0"
TARGET_RELEASE_COMMIT = "540d42b5a8b06b11d7aeae78585cffbff99da231"
TARGET_PACKAGE_TREE = "247facf39eadf073883c5f1fe3b4a291278da7f8"
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
RUN_KEY = f"{RUN_ID}-{RUN_ATTEMPT}"
DRY_RUN = False
MODE = "adopt"
EXPECTED_SOURCE = "e2159a7856ea12b4c6237820965263f5d6f92a4b"
ROOT = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
TMP = Path(os.environ["RUNNER_TEMP"]) / ("cdc-2120-adoption-" + RUN_KEY)
TMP.mkdir(parents=True, exist_ok=True)
OUT = TMP / "evidence"
OUT.mkdir(exist_ok=True)
CANON = TMP / "g-cdc"
ADOPT = TMP / "adopt"

def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def run(*args, cwd=ROOT, env=None, check=True, input_text=None):
    p = subprocess.run([str(x) for x in args], cwd=cwd, env=env, text=True,
                       input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError(f"command failed: {args[0]} {args[1] if len(args)>1 else ''}")
    return p.stdout.strip(), p.returncode

def git(*args, cwd=ROOT, env=None, check=True, input_text=None):
    return run("git", *args, cwd=cwd, env=env, check=check, input_text=input_text)

def remote_head(ref):
    out, _ = git("ls-remote", "--refs", "origin", ref)
    rows = [x for x in out.splitlines() if x.strip()]
    if len(rows) != 1:
        raise RuntimeError(f"ref {ref} must resolve once")
    sha, got = rows[0].split("\t")
    if got != ref or len(sha) != 40:
        raise RuntimeError(f"bad ref result for {ref}")
    return sha

def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

# Canonical CDC clone first; all package-owned imports come from the immutable release.
run("git", "clone", "-q", "--no-checkout", "https://github.com/bajoicheg/g-cdc.git", str(CANON), cwd=TMP)
git("fetch", "-q", "--no-tags", "origin", TARGET_RELEASE_COMMIT, cwd=CANON)
git("checkout", "-q", "--detach", TARGET_RELEASE_COMMIT, cwd=CANON)
pkg_tree, _ = git("rev-parse", f"{TARGET_RELEASE_COMMIT}:src/continuous-development-cycle", cwd=CANON)
if pkg_tree != TARGET_PACKAGE_TREE:
    raise RuntimeError("canonical package tree mismatch")
# Verify exact published release/evidence endpoints immediately before controls.
release_rows = git("ls-remote", "--refs", "origin", TARGET_RELEASE_REF, cwd=CANON)[0].splitlines()
assert release_rows == [TARGET_RELEASE_COMMIT + "\t" + TARGET_RELEASE_REF]
evidence_ref = "refs/heads/cdc/release-evidence/v2.12.0"
evidence_commit = "b72435542f40ec3f5b195f357c968c2346ab4f8f"
assert git("ls-remote", "--refs", "origin", evidence_ref, cwd=CANON)[0] == evidence_commit + "\t" + evidence_ref
git("fetch", "-q", "--no-tags", "origin", evidence_commit, cwd=CANON)
evidence = json.loads(git("show", evidence_commit + ":release/evidence-2.12.0.json", cwd=CANON)[0])
assert (evidence["version"], evidence["release_commit"], evidence["package_tree"], evidence["status"]) == (TARGET_VERSION, TARGET_RELEASE_COMMIT, TARGET_PACKAGE_TREE, "released")
assert git("merge-base", "--is-ancestor", TARGET_RELEASE_COMMIT, evidence_commit, cwd=CANON, check=False)[1] == 0
assert git("rev-parse", evidence_commit + ":src/continuous-development-cycle", cwd=CANON)[0] == TARGET_PACKAGE_TREE
(OUT / "release-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
SCRIPTS = CANON / "src/continuous-development-cycle/scripts"
sys.path.insert(0, str(SCRIPTS))

from active_package import verify
witness = verify(CANON / "src/continuous-development-cycle", CANON / "src/continuous-development-cycle", expected_version=TARGET_VERSION, expected_package_tree=TARGET_PACKAGE_TREE)
if not witness["matched"]:
    raise RuntimeError("Loaded canonical package witness failed")
(OUT / "active-package.json").write_text(json.dumps(witness, indent=2)+"\n")
import execution_continuity
import execution_lease_v2 as leasev2
import final_response_gate
import git_lease_store
import managed_executor_pool as pool
import managed_executor_runtime as runtime
import migration_transaction as migration
from consumer_adoption import GitConsumerAdoptionPublisher, assess as assess_adoption
from git_document_store import GitDocumentStore
from git_object_integrity import git_object_environment
from git_remote_identity import isolated_remote_args, remote_identity
from managed_executor_store import GitManagedExecutorStore, coordination_store_id_for_endpoint
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24

class MultiDocLeaseStore:
    """Equivalent durable lease CAS preserving every non-lease coordination path."""
    def __init__(self, repo: Path, remote: str, ref: str):
        self.repo = repo
        self.remote = remote
        self.ref = ref
        self.store_id = remote_identity(repo, remote)
        self._pending_aux = {}
        git("check-ref-format", ref, cwd=repo)

    def _env(self, **extra):
        return git_object_environment(
            GIT_TERMINAL_PROMPT="0",
            GIT_AUTHOR_NAME="CDC 2.12.0 managed rollout",
            GIT_AUTHOR_EMAIL="cdc@example.invalid",
            GIT_COMMITTER_NAME="CDC 2.12.0 managed rollout",
            GIT_COMMITTER_EMAIL="cdc@example.invalid",
            **extra,
        )

    def _git(self, *args, env=None, input_text=None, check=True):
        return git(*args, cwd=self.repo, env=env or self._env(), input_text=input_text, check=check)

    def _remote_revision(self):
        if remote_identity(self.repo, self.remote) != self.store_id:
            raise ValueError("coordination remote identity drift")
        out, _ = self._git("ls-remote", "--refs", self.remote, self.ref)
        rows = [x for x in out.splitlines() if x.strip()]
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("ambiguous coordination ref")
        sha, ref = rows[0].split("\t")
        if ref != self.ref or len(sha) != 40:
            raise ValueError("invalid coordination revision")
        return sha

    def _fetch(self, revision=None):
        config, alias = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "fetch", "--no-tags", "--no-write-fetch-head", "--refmap=", alias, self.ref)
        if revision and self._git("cat-file", "-t", revision)[0] != "commit":
            raise ValueError("coordination revision is not a commit")

    def _read_lease_at(self, revision):
        self._fetch(revision)
        raw, code = self._git("show", f"{revision}:lease.json", check=False)
        if code:
            raise ValueError("coordination revision lacks lease.json")
        value = json.loads(raw)
        git_lease_store.validate_coordination_record(value)
        return value

    def read(self):
        revision = self._remote_revision()
        if revision is None:
            return None, None
        value = self._read_lease_at(revision)
        if self._remote_revision() != revision:
            raise ValueError("coordination ref moved during read")
        return revision, value

    def read_revision(self, revision):
        current, _ = self.read()
        if current is None:
            raise ValueError("coordination history absent")
        self._fetch(revision)
        base, code = self._git("merge-base", revision, current, check=False)
        if code or base != revision:
            raise ValueError("historical revision not authoritative ancestry")
        return self._read_lease_at(revision)

    def _commit_tree(self, expected, updates, message):
        if self._remote_revision() != expected:
            raise ValueError("stale expected coordination revision")
        self._fetch(expected)
        idx = TMP / ("index-" + uuid.uuid4().hex)
        env = self._env(GIT_INDEX_FILE=str(idx))
        self._git("read-tree", f"{expected}^{{tree}}", env=env)
        for path, payload in updates.items():
            if isinstance(payload, (dict, list)):
                data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            else:
                data = str(payload)
                if not data.endswith("\n"):
                    data += "\n"
            blob, _ = self._git("hash-object", "-w", "--stdin", input_text=data)
            self._git("update-index", "--add", "--cacheinfo", "100644", blob, path, env=env)
        tree, _ = self._git("write-tree", env=env)
        commit, _ = self._git("commit-tree", tree, "-p", expected, input_text=message + "\n")
        config, alias = isolated_remote_args(self.repo, self.remote, self.store_id)
        self._git(*config, "-c", "push.followTags=false", "push", "--porcelain", alias, f"{commit}:{self.ref}")
        if self._remote_revision() != commit:
            raise ValueError("coordination CAS did not become authoritative")
        try:
            idx.unlink()
        except FileNotFoundError:
            pass
        return commit

    def compare_and_swap(self, expected_revision, record, *, ownership_capability=None):
        current, previous = self.read()
        if current != expected_revision or previous is None:
            raise ValueError("stale expected coordination revision")
        git_lease_store.validate_coordination_transition(
            previous, record, ownership_capability=ownership_capability
        )
        updates = {"lease.json": json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)}
        updates.update(self._pending_aux)
        self._pending_aux = {}
        return self._commit_tree(expected_revision, updates, "Update managed CDC ownership")

    def cas_aux_update(self, expected_revision, updates):
        current, record = self.read()
        if current != expected_revision or record is None:
            raise ValueError("stale coordination revision for auxiliary update")
        return self._commit_tree(expected_revision, updates, "Update CDC rollout coordination")

    def set_pending_aux(self, updates):
        if self._pending_aux:
            raise ValueError("pending auxiliary updates already set")
        self._pending_aux = dict(updates)

    def find_invocation_ownership(self, repository, source_ref, invocation_id):
        current, _ = self.read()
        revisions, _ = self._git("rev-list", "--first-parent", current)
        matches = []
        for rev in revisions.splitlines()[:10000]:
            rec = self._read_lease_at(rev)
            inv = rec.get("invocation")
            if (rec.get("schema") == "execution-lease/v2"
                and rec.get("repository") == repository
                and rec.get("source_ref") == source_ref
                and rec.get("owner_id") is not None
                and isinstance(inv, dict)
                and inv.get("invocation_id") == invocation_id):
                matches.append({"revision": rev, "owner_id": rec["owner_id"],
                                "generation": rec["generation"], "record": rec})
        identities = {(x["owner_id"], x["generation"]) for x in matches}
        if len(identities) > 1:
            raise ValueError("managed invocation appears under multiple lease identities")
        return matches[-1] if matches else None

    def find_release_receipt(self, owner_id, generation, invocation_id):
        current, _ = self.read()
        revisions, _ = self._git("rev-list", "--first-parent", current)
        for rev in revisions.splitlines()[:10000]:
            rec = self._read_lease_at(rev)
            rel = rec.get("last_release")
            if (rec.get("owner_id") is None and isinstance(rel, dict)
                and rel.get("owner_id") == owner_id and rel.get("generation") == generation
                and rel.get("invocation_id") == invocation_id and rec.get("generation") == generation):
                return {
                    "release_receipt": {"schema":"execution-release-receipt/v1",
                                        "lease_revision":rev,"release":copy.deepcopy(rel)},
                    "release_record":rec,
                    "current_revision":current,
                }
        raise ValueError("exact historical lease release was not found")

def deep_fill(dst, src):
    for k, v in src.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
        elif isinstance(dst[k], dict) and isinstance(v, dict):
            deep_fill(dst[k], v)

def parse_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise RuntimeError("checkpoint frontmatter missing")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise RuntimeError("checkpoint frontmatter terminator missing")
    head = text[4:marker]
    body = text[marker+5:]
    return yaml.safe_load(head), body

def write_frontmatter(path, data, body):
    encoded = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000).rstrip()
    path.write_text("---\n" + encoded + "\n---\n" + body, encoding="utf-8")

# Pin exact live source and short-circuit an already complete adoption.
source_head = remote_head(SOURCE_REF)
if source_head != EXPECTED_SOURCE:
    raise RuntimeError("Source moved before atomic adoption; reconcile")
git("fetch", "-q", "--no-tags", "origin", SOURCE_REF)
lock_raw, code = git("show", f"{source_head}:docs/cdc-consumer-lock.json", check=False)
if code == 0:
    lock = json.loads(lock_raw)
    if (lock.get("version") == TARGET_VERSION and lock.get("package_tree") == TARGET_PACKAGE_TREE
            and lock.get("release_commit") == TARGET_RELEASE_COMMIT):
        observed_tree, _ = git("rev-parse", f"{source_head}:.agents/skills/continuous-development-cycle")
        if observed_tree == TARGET_PACKAGE_TREE:
            print(json.dumps({"status":"ALREADY_ADOPTED","source_head":source_head}, sort_keys=True))
            raise SystemExit(0)

lease_store = MultiDocLeaseStore(ROOT, "origin", "refs/heads/cdc/coordination")
initial_lease_revision, initial_lease = lease_store.read()
if initial_lease is None:
    raise RuntimeError("live execution lease is absent")
if initial_lease.get("repository") != REPO or initial_lease.get("source_ref") != SOURCE_REF:
    raise RuntimeError("lease binding disagrees with rollout target")
if initial_lease.get("owner_id") is not None or initial_lease.get("external_guard") is not None:
    raise RuntimeError("consumer is not at a released/no-guard safe boundary")
if initial_lease.get("finalization") is not None:
    raise RuntimeError("released safe boundary has unexpected finalization state")
prior_generation = initial_lease["generation"]

# Start a real package-owned managed supervisor. The controller performs the atomic
# adoption while this exact running attempt supplies the terminal-lifecycle capability.
store_ref = f"refs/heads/cdc/managed-rollout-state/2.12.0-{RUN_KEY}"
store_id = coordination_store_id_for_endpoint(
    git("remote", "get-url", "origin")[0], repo_root=ROOT
)
task_id = "cdc-2120-adoption"
attempt_id = "attempt-1"
plan = {
    "schema":"managed-executor-pool-plan/v1",
    "pool_id":f"cdc-2120-rollout-{RUN_KEY}",
    "change_id":"cdc-2.12.0-consumer-adoption",
    "parent_invocation_id":f"github-actions:{RUN_ID}:{RUN_ATTEMPT}",
    "base_sha":source_head,
    "integrator_id":"managed-rollout-controller",
    "coordination_ref":store_ref,
    "coordination_store_id":store_id,
    "max_parallel":1,
    "total_runtime_budget_seconds":1200,
    "total_cost_budget_units":10,
    "tasks":[{
        "id":task_id,
        "role":"writer",
        "required":True,
        "dependencies":[],
        "executor_id":"managed-rollout-worker",
        "branch":f"cdc-managed-rollout-worker-{RUN_ID}-{RUN_ATTEMPT}",
        "worktree":f"worktrees/cdc-managed-rollout-{RUN_ID}-{RUN_ATTEMPT}",
        "write_paths":[
            ".agents/skills/continuous-development-cycle",
            "AGENTS.md",
            "docs/cdc-consumer-lock.json",
            "docs/development-cycle.yaml",
            "docs/work-status/current.md",
            "docs/cdc-adoption-2.12.0.md",
        ],
        "expected_outputs":["consumer-adoption:2.12.0"],
        "expected_evidence":["exact-package-tree","atomic-readback"],
        "backend_preferences":["local_command"],
        "max_runtime_seconds":900,
        "max_cost_units":1,
    }],
}
owner = str(uuid.uuid4())
rt = None
try:
    managed_store = GitManagedExecutorStore(
        ROOT, "origin", store_ref, plan, protected_refs=[SOURCE_REF]
    )
    mrev, mstate = managed_store.read()
    if mrev is None:
        mrev = managed_store.compare_and_swap(None, pool.initial_state(plan, parallel_capable=False))
    backend = runtime.LocalCommandBackend(TMP / "managed-journal")
    rt = runtime.ManagedExecutorRuntime(plan, managed_store, ROOT, backend)
    receipt = rt.start(
        mrev, task_id, attempt_id,
        reservation_token=f"reserve:{RUN_KEY}",
        argv=[sys.executable, "-c", "import time; time.sleep(850)"],
    )
    deadline = time.monotonic() + 30
    while True:
        obs = rt.observe(task_id, attempt_id)
        if obs["status"] == "running":
            break
        if obs["status"] not in {"starting"} or time.monotonic() >= deadline:
            raise RuntimeError("managed supervisor did not become live")
        time.sleep(0.2)

    acquired = rt.acquire_execution_lease(
        lease_store, initial_lease_revision, REPO, SOURCE_REF, owner,
        task_id, attempt_id, now(), ttl=1200
    )
    lease_revision = acquired["revision"]
    lease_record = acquired["record"]
    generation = acquired["generation"]
    invocation_id = acquired["invocation"]["invocation_id"]

    # Assemble candidate completely detached from the shared source ref.
    git("worktree", "add", "--quiet", "--detach", str(ADOPT), source_head)
    git("config", "user.name", "CDC 2.12.0 managed rollout", cwd=ADOPT)
    git("config", "user.email", "cdc@example.invalid", cwd=ADOPT)

    dst_pkg = ADOPT / ".agents/skills/continuous-development-cycle"
    shutil.rmtree(dst_pkg)
    shutil.copytree(CANON / "src/continuous-development-cycle", dst_pkg, symlinks=True)

    # Consumer lock.
    lock_path = ADOPT / "docs/cdc-consumer-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock.update(
        version=TARGET_VERSION,
        release_ref=TARGET_RELEASE_REF,
        release_commit=TARGET_RELEASE_COMMIT,
        package_tree=TARGET_PACKAGE_TREE,
    )
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Adapter: retain project-specific values and fill only newly required released controls.
    adapter_path = ADOPT / "docs/development-cycle.yaml"
    adapter = yaml.safe_load(adapter_path.read_text(encoding="utf-8"))
    template = yaml.safe_load((CANON / "src/continuous-development-cycle/templates/development-cycle.yaml").read_text(encoding="utf-8"))
    deep_fill(adapter, template)
    # Preserve legacy strictness; new reuse/cycle contracts are enabled explicitly.
    adapter["quality"] = {"default_level": "FULL", "max_validation_cycles": 2}
    adapter["policy"]["revision"] = "2026-10-07-cdc-2.12.0-atomic-adoption"
    adapter["policy"]["skill_min_version"] = TARGET_VERSION
    adapter["convergence"]["target_version"] = TARGET_VERSION
    adapter["convergence"]["target_package_fingerprint_ref"] = "https://github.com/bajoicheg/g-cdc/tree/" + TARGET_RELEASE_COMMIT + "/src/continuous-development-cycle"
    adapter_path.write_text(yaml.safe_dump(adapter, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8")
    binding = validate_adapter(adapter, skill_version=TARGET_VERSION)

    # Provenance and adoption note.
    agents_path = ADOPT / "AGENTS.md"
    agents = agents_path.read_text(encoding="utf-8")
    provenance = f"""## CDC 2.12.0 authoritative provenance

Use canonical `bajoicheg/g-cdc` **v2.12.0**, release `{TARGET_RELEASE_REF}`, commit `{TARGET_RELEASE_COMMIT}`, exact package tree `{TARGET_PACKAGE_TREE}`. The immutable package is vendored at `.agents/skills/continuous-development-cycle/`; lower-version CDC statements below are historical. The owner requested the latest released CDC on 2026-10-07. Exact stable evidence is refs/heads/cdc/release-evidence/v2.12.0, commit b72435542f40ec3f5b195f357c968c2346ab4f8f, path release/evidence-2.12.0.json. Project quality default FULL preserves legacy strictness; validation cycles and evidence reuse are explicit. Product/runtime gates, unfinished UI/Word repair and scheduler pause are preserved. Global Fleet target is not changed.

"""
    if not agents.startswith("## CDC 2.12.0 authoritative provenance"):
        agents_path.write_text(provenance + agents, encoding="utf-8")

    adoption_path = ADOPT / "docs/cdc-adoption-2.12.0.md"
    adoption_path.write_text(
        f"""# CDC 2.12.0 managed process-only adoption

Canonical release: `{TARGET_RELEASE_REF}`
Release commit: `{TARGET_RELEASE_COMMIT}`
Exact package tree: `{TARGET_PACKAGE_TREE}`
Source base: `{source_head}`

Prior UI/Word prepared attempt 19599cc1-2f55-556c-852f-ea8c5a9316c9 never launched a runtime or acquired a lease; artifact 11492088368 retains the exact request. Its base-specific preparation is superseded by this atomic adoption and the authorized repair resumes on the new base.

This adoption is assembled detached from the shared source ref and published once by the released 2.12.0 conditional fast-forward/readback path. Project product behavior, product acceptance/release gates, and owner-paused scheduler state are preserved. Live coordination ownership is authoritative over checkpoint projections.
""",
        encoding="utf-8",
    )

    # Checkpoint remains a projection of the pre-existing product task, but policy binding
    # and live-owner projection are reconciled for the completed process-only adoption.
    checkpoint_path = ADOPT / "docs/work-status/current.md"
    checkpoint, checkpoint_body = parse_frontmatter(checkpoint_path)
    checkpoint["policy_revision"] = binding["policy_revision"]
    checkpoint["policy_digest"] = binding["policy_digest"]
    checkpoint["observed_at_utc"] = now()
    checkpoint["active_executor"] = "none"
    if checkpoint.get("phase") != "waiting_external":
        checkpoint["lease_state"] = "released"
    checkpoint["executor_heartbeat_at_utc"] = None
    checkpoint["execution_lease_until_utc"] = None
    if isinstance(checkpoint.get("control"), dict):
        checkpoint["control"]["execution_lease_revision"] = None
        checkpoint["control"]["executor_id"] = None
        checkpoint["control"]["lease_generation"] = generation
    if isinstance(checkpoint.get("execution_continuity"), dict):
        checkpoint["execution_continuity"]["invocation_id"] = None
        checkpoint["execution_continuity"]["meaningful_progress"] = True
        checkpoint["execution_continuity"]["primitive_steps_since_progress"] = 0
        checkpoint["execution_continuity"]["last_progress_ref"] = "docs/cdc-adoption-2.12.0.md"
    section = f"""## CDC 2.12.0 process-only adoption — managed atomic publication

This branch now binds canonical CDC **2.12.0** at `{TARGET_RELEASE_REF}`, release commit `{TARGET_RELEASE_COMMIT}`, package tree `{TARGET_PACKAGE_TREE}`. The migration was assembled detached and is published only after exact package/policy/checkpoint/provenance validation. Product gates and scheduler state are unchanged.

"""
    write_frontmatter(checkpoint_path, checkpoint, section + "\n## Unfinished authorized repair\n\nFirst-run text clipping and slow Word correction: prepared immutable payload 7d4d1986e07c9c18012f4c430f100cd158e4d22842f309df7e6b12b5ab324203 at orchestration commit 549adc01b91e7bc4516f8f79cba29753afa97be1. Continue on this adopted base; keep whole-range/focus/protection checks, mixed formatting and one Undo. Product repair effective quality FULL (Word text mutation); adoption reuses released CDC1116 tests with exact installation/consumer compatibility checks, no fabricated new suite run.\n\n" + checkpoint_body)

    # Validate the actual vendored package and project binding before commit/publication.
    subprocess.run(
        [sys.executable, "-B", str(dst_pkg / "scripts/validate_package.py")],
        cwd=ADOPT, check=True
    )
    validate_adapter(yaml.safe_load(adapter_path.read_text(encoding="utf-8")), skill_version=TARGET_VERSION)
    cp_check, _ = parse_frontmatter(checkpoint_path)
    validate_checkpoint_24(cp_check, yaml.safe_load(adapter_path.read_text(encoding="utf-8")))

    allowed_prefix = ".agents/skills/continuous-development-cycle/"
    allowed_exact = {
        "AGENTS.md",
        "docs/cdc-consumer-lock.json",
        "docs/development-cycle.yaml",
        "docs/work-status/current.md",
        "docs/cdc-adoption-2.12.0.md",
    }
    git("add", "-A", cwd=ADOPT)
    changed, _ = git("diff", "--cached", "--name-only", cwd=ADOPT)
    for path in changed.splitlines():
        if path not in allowed_exact and not path.startswith(allowed_prefix):
            raise RuntimeError("process-only adoption escaped allowed paths: " + path)
    git("commit", "-q", "-m", "chore(cdc): adopt canonical CDC 2.12.0 at managed safe boundary [skip ci]", cwd=ADOPT)
    candidate, _ = git("rev-parse", "HEAD", cwd=ADOPT)
    candidate_tree, _ = git("rev-parse", "HEAD^{tree}", cwd=ADOPT)
    observed_package_tree, _ = git("rev-parse", "HEAD:.agents/skills/continuous-development-cycle", cwd=ADOPT)
    if observed_package_tree != TARGET_PACKAGE_TREE:
        raise RuntimeError("detached candidate package tree mismatch")

    for path in ["src", "tests", "Cargo.toml", "Cargo.lock", "build.rs", "assets", "rust-toolchain.toml", ".github/workflows/windows-ci.yml"]:
        if git("rev-parse", f"{source_head}:{path}")[0] != git("rev-parse", f"{candidate}:{path}", cwd=ADOPT)[0]:
            raise RuntimeError("Process adoption changed protected product input: " + path)

    # Refresh lease with the candidate as observable activity before the product write.
    lease_record = leasev2.renew(
        lease_record, owner, generation, invocation_id, now(),
        activity_ref="git:" + candidate, ttl=1200
    )
    lease_revision = lease_store.compare_and_swap(lease_revision, lease_record)
    leasev2.check(
        lease_store, lease_revision, REPO, SOURCE_REF, owner, generation, invocation_id,
        now(), action="product_write"
    )

    required_paths = [
        ".agents/skills/continuous-development-cycle",
        "docs/cdc-consumer-lock.json",
        "docs/development-cycle.yaml",
        "docs/work-status/current.md",
        "docs/cdc-adoption-2.12.0.md",
        "AGENTS.md",
    ]
    manifest = []
    for path in required_paths:
        oid, _ = git("rev-parse", f"{candidate}:{path}", cwd=ADOPT)
        typ, _ = git("cat-file", "-t", oid, cwd=ADOPT)
        manifest.append({"path":path,"object_type":typ,"object_sha1":oid})

    txn_id = f"cdc-2.12.0-{REPO.replace('/','-')}-{source_head[:12]}-{RUN_KEY}"
    txn = {
        "schema":"migration-transaction/v1",
        "transaction_id":txn_id,
        "source_head":source_head,
        "target_ref":SOURCE_REF,
        "items":copy.deepcopy(manifest),
        "completed_paths":required_paths.copy(),
        "operation_budget":100,
        "per_item_operations":1,
        "batch_overhead_operations":0,
        "finalization_reserve_operations":1,
        "detached_checkpoints":[],
        "final_tree_sha":candidate_tree,
        "expected_subtree_tree":TARGET_PACKAGE_TREE,
        "observed_subtree_tree":TARGET_PACKAGE_TREE,
        "policy_reconciled":True,
    }
    if migration.plan(txn)["action"] != "READY_TO_ADVANCE_REF":
        raise RuntimeError("detached migration did not reach publication boundary")
    assembly = migration.assembly_record(
        txn,
        target_version=TARGET_VERSION,
        target_release_ref=TARGET_RELEASE_REF,
        target_release_commit=TARGET_RELEASE_COMMIT,
        completed_at_utc=now(),
    )

    (OUT / "assembly-manifest.json").write_text(json.dumps(assembly, indent=2)+"\n")
    remote_id = remote_identity(ROOT, "origin")
    assembly_ref = f"refs/heads/cdc/adoption-assembly/2.12.0-{RUN_KEY}"
    attempt_ref = f"refs/heads/cdc/adoption-attempts/2.12.0-{RUN_KEY}"
    assembly_store = GitDocumentStore(ROOT, "origin", assembly_ref, remote_id, protected_refs=[SOURCE_REF])
    arev, existing = assembly_store.read()
    if arev is None:
        arev = assembly_store.compare_and_swap(None, assembly)
    else:
        if existing != assembly:
            raise RuntimeError("assembly ref already exists with different record")
    attempt_store = GitDocumentStore(ROOT, "origin", attempt_ref, remote_id, protected_refs=[SOURCE_REF, assembly_ref])

    state = {
        "schema":"consumer-adoption-publication/v1",
        "source_head":source_head,
        "target_ref":SOURCE_REF,
        "target_version":TARGET_VERSION,
        "target_release_ref":TARGET_RELEASE_REF,
        "target_release_commit":TARGET_RELEASE_COMMIT,
        "target_package_tree":TARGET_PACKAGE_TREE,
        "required_paths":required_paths,
        "prepared_paths":required_paths.copy(),
        "assembly_manifest":copy.deepcopy(assembly["manifest"]),
        "assembly_authority":{
            "schema":"migration-assembly-authority/v1",
            "store_ref":assembly_ref,
            "store_id":remote_id,
            "revision":arev,
            "transaction_id":txn_id,
            "manifest_digest":assembly["manifest_digest"],
        },
        "final_tree_sha":candidate_tree,
        "observed_package_tree":TARGET_PACKAGE_TREE,
        "candidate_commit":candidate,
        "live_source_head":source_head,
        "publication_claim":None,
        "published_head":None,
        "readback_package_tree":None,
    }
    claim_plan = assess_adoption(state)
    if claim_plan["action"] != "CLAIM_CONDITIONAL_PUBLISH":
        raise RuntimeError("unexpected adoption claim plan: " + claim_plan["action"])
    state["publication_claim"] = claim_plan["claim"]
    publisher = GitConsumerAdoptionPublisher(
        ROOT, "origin", SOURCE_REF, remote_id, attempt_store, assembly_store
    )
    publication_started = True
    result = publisher.publish(state)
    publication_confirmed = result["action"] in {"PUBLISHED","CONFIRMED_FROM_READBACK","CONFIRMED","OBSERVED_EXISTING"}
    if result["action"] not in {"PUBLISHED","CONFIRMED_FROM_READBACK","CONFIRMED","OBSERVED_EXISTING"}:
        raise RuntimeError("atomic publication not confirmed: " + result["action"])
    if remote_head(SOURCE_REF) != candidate:
        raise RuntimeError("shared source ref did not read back exact candidate")
    pub_tree, _ = git("rev-parse", f"{candidate}:.agents/skills/continuous-development-cycle", cwd=ADOPT)
    if pub_tree != TARGET_PACKAGE_TREE:
        raise RuntimeError("published package tree readback mismatch")

    # Record coordination convergence while still owned.
    adoption_evidence = {
        "schema":"cdc-consumer-adoption-evidence/v1",
        "repository":REPO,
        "source_ref":SOURCE_REF,
        "source_head":candidate,
        "source_base":source_head,
        "release":{
            "schema":"live-target-release/v1",
            "version":TARGET_VERSION,
            "canonical_repository":"bajoicheg/g-cdc",
            "release_ref":TARGET_RELEASE_REF,
            "release_commit":TARGET_RELEASE_COMMIT,
            "package_tree":TARGET_PACKAGE_TREE,
        },
        "package_tree":TARGET_PACKAGE_TREE,
        "policy_digest":binding["policy_digest"],
        "checkpoint_schema":"development-work-status/v4",
        "status":"applied_verified",
        "observed_at_utc":now(),
        "safe_boundary":{
            "prior_generation":prior_generation,
            "prior_explicitly_released":initial_lease.get("last_release") is not None,
            "prior_guard":None,
            "recovery_kind":"released_safe_boundary",
            "adopting_generation":generation,
            "invocation_id":invocation_id,
        },
        "checks":{
            "exact_package_subtree":"PASS",
            "consumer_lock":"PASS",
            "adapter_semantic_digest":"PASS",
            "checkpoint_v4_readback":"PASS",
            "changed_path_containment":"PASS: vendored CDC, AGENTS.md and docs only",
            "product_source_changes":0,
            "detached_tree_before_ref_move":"PASS",
            "atomic_conditional_fast_forward":"PASS",
            "published_readback":"PASS",
        },
        "scheduler_mutations":0,
        "product_scope_preserved":checkpoint.get("active_change", ""),
        "next_action":"Resume the pre-existing product task under CDC 2.12.0; scheduler pause remains authoritative.",
    }
    fleet_target = {
        "schema":"version-convergence-target/v1",
        "target_version":TARGET_VERSION,
        "target_package_fingerprint":"git-tree:"+TARGET_PACKAGE_TREE,
        "checkpoint_schema":"development-work-status/v4",
        "safe_boundary_required":True,
    }
    current_revision, current_lease = lease_store.read()
    if current_lease.get("owner_id") != owner or current_lease.get("generation") != generation:
        raise RuntimeError("managed adoption lost exact lease before coordination evidence")
    lease_revision = lease_store.cas_aux_update(
        current_revision,
        {
            "fleet-target.json":json.dumps(fleet_target, indent=2, ensure_ascii=False),
            "adoptions/cdc-2.12.0.json":json.dumps(adoption_evidence, indent=2, ensure_ascii=False),
        }
    )
    lease_record = lease_store.read()[1]

    # Transactional finalization. The final release CAS also refreshes Fleet snapshot.
    checkpoint_ref = f"https://github.com/{REPO}/blob/{candidate}/docs/work-status/current.md"
    lease_record = leasev2.begin_finalization(
        lease_record, owner, generation, invocation_id, now(), pending_shared_writes=False
    )
    lease_revision = lease_store.compare_and_swap(lease_revision, lease_record)
    lease_record = leasev2.record_checkpoint(
        lease_record, owner, generation, invocation_id, now(),
        checkpoint_ref=checkpoint_ref, pending_shared_writes=False
    )
    lease_revision = lease_store.compare_and_swap(lease_revision, lease_record)
    lease_record = leasev2.reconcile_finalization(
        lease_record, owner, generation, invocation_id, now(), external_reconciliation="none"
    )
    lease_revision = lease_store.compare_and_swap(lease_revision, lease_record)

    progress_refs = ["git:"+candidate, "adoption:cdc-2.12.0"]
    continuity = {
        "schema":"execution-continuity/v1",
        "invocation_id":invocation_id,
        "current_state":"COMPLETE",
        "requested_terminal_outcome":"scope_complete",
        "runnable_next_action":False,
        "meaningful_progress_refs":progress_refs,
        "primitive_steps":[],
        "external_binding":None,
        "blocker":None,
        "checkpoint_ref":checkpoint_ref,
        "next_action":None,
        "lease_release_required":False,
        "lease_released":False,
        "terminal_state":{
            "schema":"terminal-state/v2",
            "invocation_id":invocation_id,
            "scope_id":"cdc-2.12.0-consumer-adoption:"+REPO,
            "observed_head":candidate,
            "decision":"COMPLETE",
            "runnable_actions":[],
            "pending_external":None,
            "blocker":None,
            "meaningful_progress_refs":progress_refs,
            "completion_evidence_refs":["scope:atomic-adoption-verified"],
            "checkpoint_ref":checkpoint_ref,
            "lease_released":False,
        },
    }
    decision = execution_continuity.evaluate(continuity, now_utc=now())
    if not decision["final_response_allowed"]:
        raise RuntimeError("continuity pre-release rejected: " + decision["reason"])
    lease_record = leasev2.mark_ready(
        lease_record, owner, generation, invocation_id, now(), continuity_state=continuity
    )
    lease_revision = lease_store.compare_and_swap(lease_revision, lease_record)

    try:
        snap_raw, code = git("show", f"{lease_revision}:fleet-project-snapshot.json", check=False)
        snapshot = json.loads(snap_raw) if code == 0 else None
    except Exception:
        snapshot = None
    if isinstance(snapshot, dict):
        snapshot["observed_at_utc"] = now()
        snapshot["product_head"] = candidate
        snapshot["cdc_version"] = TARGET_VERSION
        snapshot["package_fingerprint"] = "git-tree:" + TARGET_PACKAGE_TREE
        snapshot["policy_revision"] = binding["policy_revision"]
        snapshot["coordination"]["generation"] = generation
        snapshot["coordination"]["owner_active"] = False
        snapshot["coordination"]["guard_present"] = False
        snapshot["progress"]["observed_at_utc"] = now()
        snapshot["progress"]["last_meaningful_progress_at_utc"] = now()
        snapshot["progress"]["last_activity_at_utc"] = now()
        refs = list(snapshot["progress"].get("evidence_refs", []))
        for ref in ["git:"+candidate, "adoptions/cdc-2.12.0.json", "actions:"+RUN_ID]:
            if ref not in refs:
                refs.append(ref)
        snapshot["progress"]["evidence_refs"] = refs
        lease_store.set_pending_aux({
            "fleet-project-snapshot.json":json.dumps(snapshot, indent=2, ensure_ascii=False)
        })

    (OUT / "adoption-evidence.json").write_text(json.dumps(adoption_evidence, indent=2)+"\n")
    released = rt.release_execution_lease(
        lease_store, lease_revision, REPO, SOURCE_REF, owner, generation, invocation_id,
        task_id, attempt_id, now()
    )
    (OUT / "release-receipt.json").write_text(json.dumps(released["release_receipt"], indent=2)+"\n")
    release_record = lease_store.read_revision(released["release_receipt"]["lease_revision"])
    post = copy.deepcopy(continuity)
    post["lease_release_required"] = True
    post["lease_released"] = True
    post["terminal_state"]["lease_released"] = True
    gate = final_response_gate.evaluate(
        invocation_id, released["record"], post,
        {"owner_id":owner,"generation":generation},
        released["release_receipt"], release_record, now()
    )
    if not gate["final_response_allowed"]:
        raise RuntimeError("managed final-response gate rejected: " + gate["reason"])

    # Stop sentinel only after durable lease release, then prove process quiescence.
    rt.cancel(task_id, attempt_id)
    deadline = time.monotonic() + 30
    while True:
        obs = rt.observe(task_id, attempt_id)
        if obs.get("quiescent") is True:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("managed sentinel did not become quiescent after release")
        time.sleep(0.2)

    final_head = remote_head(SOURCE_REF)
    final_lock_raw, _ = git("show", f"{final_head}:docs/cdc-consumer-lock.json")
    final_lock = json.loads(final_lock_raw)
    if final_head != candidate or final_lock.get("version") != TARGET_VERSION or final_lock.get("package_tree") != TARGET_PACKAGE_TREE:
        raise RuntimeError("final source/lock readback mismatch")
    final_lease_revision, final_lease = lease_store.read()
    if final_lease.get("owner_id") is not None or final_lease.get("external_guard") is not None:
        raise RuntimeError("final coordination is not released/no-guard")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("candidate_sha=" + candidate + "\n")
    print(json.dumps({
        "status":"ADOPTED",
        "repository":REPO,
        "source_ref":SOURCE_REF,
        "source_base":source_head,
        "source_head":candidate,
        "package_tree":TARGET_PACKAGE_TREE,
        "policy_digest":binding["policy_digest"],
        "lease_generation":generation,
        "lease_revision":final_lease_revision,
        "release_receipt_revision":released["release_receipt"]["lease_revision"],
        "scheduler_mutations":0,
        "final_response_gate":"GREEN",
    }, sort_keys=True))

except BaseException as error:
    if DRY_RUN or isinstance(error, SystemExit) and error.code == 0:
        raise
    # A terminal controller error must not silently orphan a known-safe lease.
    # An uncertain publication is preserved for provider reconciliation instead.
    current_revision, current_record = lease_store.read()
    if current_record.get("owner_id") != owner:
        if rt is not None:
            # No lease from this controller: cancel only the exact known runtime;
            # any unreadable/unknown backend record remains a durable blocker.
            try:
                observation = rt.observe(task_id, attempt_id)
                if observation.get("status") in {"starting", "running"}:
                    rt.cancel(task_id, attempt_id)
                    deadline = time.monotonic() + 30
                    while not rt.observe(task_id, attempt_id).get("quiescent"):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("unowned exact supervisor requires recovery")
                        time.sleep(.2)
            except Exception as cleanup_error:
                print(json.dumps({"status":"PREOWNERSHIP_RECOVERY_REQUIRED", "error_type":type(cleanup_error).__name__, "pool_ref":store_ref, "attempt_id":attempt_id}))
        raise
    recovered_hold = rt.reconcile_execution_lease_hold(lease_store, task_id, attempt_id)
    if recovered_hold["status"] != "owned":
        raise RuntimeError("Unexpected exact hold while own lease remains") from error
    generation = recovered_hold["owned_marker"]["generation"]
    invocation_id = recovered_hold["owned_marker"]["invocation_id"]
    failed_head = remote_head(SOURCE_REF)
    unknown_publication = bool(globals().get("publication_started") and not globals().get("publication_confirmed"))
    failure = {"schema":"g-switcher-managed-maintenance-failure/v1", "run_id":RUN_ID,
               "mode":MODE, "observed_at_utc":now(), "source_head":failed_head,
               "error_type":type(error).__name__, "publication_outcome_unknown":unknown_publication,
               "next_action":"Reconcile the exact immutable adoption-attempt journal before any retry" if unknown_publication else "Diagnose this exact failed job and correct the bounded maintenance attempt"}
    failure_revision = lease_store.cas_aux_update(current_revision, {"maintenance/failure-"+RUN_KEY+".json":failure})
    if unknown_publication:
        print(json.dumps({"status":"BLOCKED_PUBLICATION_RECONCILIATION", "checkpoint_revision":failure_revision}))
        raise
    # No publication was submitted, or the package publisher confirmed it and
    # exact readback completed. There is no unresolved downstream effect here.
    record = lease_store.read()[1]
    if record.get("external_guard") is not None:
        raise RuntimeError("failure finalization requires external guard reconciliation") from error
    failure_checkpoint = f"https://github.com/{REPO}/blob/{failure_revision}/maintenance/failure-{RUN_KEY}.json"
    if record["finalization"]["state"] not in {"active", "failed"}:
        record = leasev2.fail_finalization(record, owner, generation, invocation_id, now(), failure=failure_checkpoint)
        failure_revision = lease_store.compare_and_swap(failure_revision, record)
    record = leasev2.begin_finalization(record, owner, generation, invocation_id, now(), pending_shared_writes=False)
    revision = lease_store.compare_and_swap(failure_revision, record)
    record = leasev2.record_checkpoint(record, owner, generation, invocation_id, now(), checkpoint_ref=failure_checkpoint, pending_shared_writes=False)
    revision = lease_store.compare_and_swap(revision, record)
    record = leasev2.reconcile_finalization(record, owner, generation, invocation_id, now(), external_reconciliation="none")
    revision = lease_store.compare_and_swap(revision, record)
    evidence = [failure_checkpoint, "actions:"+RUN_ID+":"+MODE+":failed"]
    next_action = failure["next_action"]
    blocked = {"schema":"execution-continuity/v1", "invocation_id":invocation_id,
               "current_state":"BLOCKED", "requested_terminal_outcome":"blocked",
               "runnable_next_action":False, "meaningful_progress_refs":[], "primitive_steps":[],
               "external_binding":None, "blocker":"managed-maintenance-failed", "checkpoint_ref":failure_checkpoint,
               "next_action":next_action, "lease_release_required":False, "lease_released":False,
               "blocker_proof":{"schema":"blocked-state-proof/v1", "dependency_id":"managed-maintenance-failed",
                                "category":"worker_terminal", "observed_at_utc":now(), "max_age_seconds":120,
                                "evidence_refs":evidence, "next_action":next_action,
                                "recheck_trigger":"corrected bounded maintenance attempt", "same_invocation_work_exhausted":True},
               "terminal_state":{"schema":"terminal-state/v2", "invocation_id":invocation_id,
                                 "scope_id":"cdc-2.12.0-maintenance-attempt:"+REPO,
                                 "observed_head":failed_head, "decision":"BLOCKED", "runnable_actions":[],
                                 "pending_external":None, "blocker":{"code":"managed-maintenance-failed", "evidence_refs":evidence,
                                 "next_action":next_action, "recheck_trigger":"corrected bounded maintenance attempt"},
                                 "meaningful_progress_refs":[], "completion_evidence_refs":[],
                                 "checkpoint_ref":failure_checkpoint, "lease_released":False}}
    record = leasev2.mark_ready(record, owner, generation, invocation_id, now(), continuity_state=blocked)
    revision = lease_store.compare_and_swap(revision, record)
    released_error = rt.release_execution_lease(lease_store, revision, REPO, SOURCE_REF, owner, generation,
                                                invocation_id, task_id, attempt_id, now())
    blocked["lease_release_required"] = True
    blocked["lease_released"] = True
    blocked["terminal_state"]["lease_released"] = True
    checked_release = lease_store.read_revision(released_error["release_receipt"]["lease_revision"])
    error_gate = final_response_gate.evaluate(invocation_id, released_error["record"], blocked,
                                             {"owner_id":owner,"generation":generation},
                                             released_error["release_receipt"], checked_release, now())
    if not error_gate["final_response_allowed"]:
        raise RuntimeError("failure release gate rejected") from error
    rt.cancel(task_id, attempt_id)
    deadline = time.monotonic() + 30
    while not rt.observe(task_id, attempt_id).get("quiescent"):
        if time.monotonic() >= deadline:
            raise RuntimeError("failure supervisor did not become quiescent after release") from error
        time.sleep(0.2)
    print(json.dumps({"status":"FAILED_RELEASED", "release_receipt":released_error["release_receipt"]}))
    raise
