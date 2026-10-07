# Live Fleet target resolution

`scripts/live_target.py` reads the configured live registry and verifies its target against an immutable canonical Git release. It never adopts a package, operates a scheduler, updates a remote ref, or grants those authorities. A successful observation is a read-time fact, not a lock against subsequent changes. Re-resolve at the next decision boundary and retain normal ownership, pause, guard, budget and authorization gates.

## Authority and migration

Deployment configuration supplies the registry endpoint identity, exact `refs/heads/` registry ref, document paths, canonical endpoint identity and canonical repository name. Bind endpoints with the existing `git_remote_identity` normalization during a trusted setup step. Do not derive expected identity from an unchecked alias during resolution. The textual repository name and version are insufficient to trust an arbitrary endpoint.

The existing `fleet-registry/v1` and embedded `version-convergence-target/v1` remain unchanged. If a standalone target path is configured, that document is required and must exactly equal the embedded target. Neither document can choose another source: both are read at the same exact live registry commit.

A required companion document, by default `fleet/target-release.json`, uses `live-target-release/v1` with exactly these fields:

| Field | Meaning |
| --- | --- |
| `schema` | `live-target-release/v1` |
| `version` | Exact stable target version |
| `canonical_repository` | Independently configured canonical repository name |
| `release_ref` | `refs/heads/release/v` followed by the version |
| `release_commit` | Immutable full Git SHA-1 release commit |
| `package_tree` | Full Git SHA-1 tree matching the target's `git-tree:` fingerprint |

Read this companion from the same registry revision. Publish registry, standalone target when used, and companion together in one authorized registry commit after the canonical release is verified. Missing legacy provenance deliberately fails closed; no README, prompt version or matching labels silently substitute for this binding. This migration grants no consumer adoption or scheduler authority and does not modify product source/coordination refs.

## Resolution checks

The resolver pins fresh live registry and canonical release refs, reads documents only by pinned commit, and rejects ref movement before returning. The canonical release ref must equal the companion's release commit, including when it moved before this wake. At that commit, the package tree and `VERSION` must match; `release/evidence-<version>.json` must be `cdc-release-evidence/v1`, have `status: released`, and agree on repository, release ref, version and tree. An optional evidence `release_commit` must agree too. Its `candidate_source_commit` must be an actual ancestor with the same package tree. This verifies declared release provenance in the trusted canonical repository; it does not rerun release tests or create release approval.

Freshness measures the transport's independently observed live-read time, including elapsed resolution time, not the age of an immutable release commit. Both observations must be at or before the caller's current UTC clock and at most `max_age_seconds` old (default 300). Unknown/malformed, stale or future observations, duplicate JSON keys, missing objects, unsafe paths, SHA/tree/version/provenance disagreement and changed endpoint identities raise `ValueError`. No stale snapshot or local HEAD fallback is available.

## Python API and actual transport capabilities

```python
from live_target import GitSource, resolve_live_target

# trusted_config is deployment policy, independently established before this read.
registry = GitSource(cache_repo, "fleet", trusted_config["registry_endpoint_identity"])
canonical = GitSource(cache_repo, "canonical", trusted_config["canonical_endpoint_identity"])
resolved = resolve_live_target(
    registry, canonical,
    registry_ref=trusted_config["registry_ref"],
    canonical_repository=trusted_config["canonical_repository"],
    registry_path="fleet/registry.json",
    target_path="fleet/target.json",  # omit for an embedded-only v1 target
    release_path="fleet/target-release.json",
)
```

`GitSource` uses real `ls-remote`, fetch and Git object reads. Fetch changes only the local object cache: no product or remote-tracking ref and no `FETCH_HEAD` update. It checks effective fetch/push endpoint identity, exact ref, commit type and post-read identity. Transport diagnostics do not disclose credential-bearing URLs. Only SHA-1 package bindings and exact branch refs are supported by this version.

`resolve_live_target` also accepts a caller-supplied `RegistrySource` protocol with these operations:

| Operation | Required capability |
| --- | --- |
| `identity()` | Return the independently trusted and freshly checked opaque endpoint identity, or fail |
| `pin(ref)` | Perform a real fresh remote read and return `Revision(revision, ref, source_identity, observed_at_utc)` |
| `read_file(snapshot, path)` | Read the document at that actual remote commit, without substituting current branch/local content |
| `assert_current(snapshot)` | Freshly re-read endpoint/ref and fail if either changed |

Canonical `ReleaseSource` additionally provides `tree_oid(snapshot, path, revision=None)` and `is_ancestor(ancestor, descendant)` using exact remote objects. `GitSource` implements both protocols. A private registry accessible through a real connector can supply the narrow registry protocol while canonical provenance uses real Git. No connector or host API is fabricated here; the caller must supply authorized capabilities, independent identity/time observations and fresh pre/post ref readbacks. A locally reconstructed commit must never be labeled with a remote commit SHA. Inability to prove any read or binding is a blocker.

The returned `live-target-resolution/v1` contains the compatible `registry`/`target`, verified `release`, exact registry ref/revision, both source identities and observation times. `authorizes_adoption` and `authorizes_scheduler_write` are always false. Do not cache this result as continuing authorization.

Watchdog prompts must load current project AGENTS, adapter, consumer lock, checkpoint and separate coordination state at verified live revisions. Prompts identify configured authority and resolver instructions; they never carry a mutable CDC target version.

## Explicit separate evidence provenance (v2)

`live-target-release/v1` remains the exact six-field colocated-evidence contract. A split release uses `live-target-release/v2` with those same fields plus `evidence_binding`: exactly `schema: canonical-release-evidence-binding/v1`, `source_identity`, `ref`, `commit`, `path`. The identity must equal the independently configured canonical endpoint; ref is an exact branch ref, commit is the exact pinned SHA, and path must equal `release/evidence-<version>.json`. No alternate endpoint, alias, unpinned main fallback or substituted snapshot is supported. Prefer an independently published immutable evidence branch; a moved ref is rejected even when its new bytes agree.

The resolver performs a fresh pin/read/recheck of evidence through the same canonical source. Evidence commit must descend from the immutable release and retain the exact package tree. Released evidence must explicitly bind `release_commit`; candidate ancestry/tree and all prior release/VERSION/repository/schema checks remain mandatory. Registry, release and evidence observations are all checked for identity/ref movement and freshness before returning. The v2 result adds `evidence_observation` with actual identity/ref/revision/time; it grants no adoption, scheduler or source-write permission. Legacy v1 input and output remain unchanged and fail closed when colocated evidence is absent.
