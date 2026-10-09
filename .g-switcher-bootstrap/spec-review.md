# Restart-persistent Word admission: targeted independent SPEC review

Verdict: **PASS for the frozen test-only correction.** No concrete source-level blocker found. This carries forward the previously approved restart-guard production scope; it is not a runtime repair or revised execution acceptance. No compilation, tests, launch, remote mutation or product integration performed in this review.

## Actual a4 failure and causal fixture correction

The prior source review is preserved in spec-review-f460-historical.md and archive-a4. Parent-recovered authenticated a4 Windows job 113937102137, run 37965022335, recorded 43 passing and one failing failuree2e test: stalled_metadata_returns_none_and_never_queues_a_replacement observed three provider invocations instead of two. The old fixture repeatedly submitted fresh requests while waiting for a successful response. A fresh request whose provider had already completed could time out under scheduling load; a later retry then legitimately invoked the provider again. The count failure does not establish a replacement was queued while the original provider remained pending.

The new fixture synchronizes actual provider entry through a channel and holds it on a condition variable until after the caller has returned None and a second request has been refused. The invocation count remains exactly one before release. It captures the exact old in_flight completion token, verifies it is not complete, releases the provider, and waits only for that token's completion. Recovery then makes one fresh request on its separate response channel, requires Some(44), and retains the exact total count of two. Waiting for completion no longer submits requests; no retry can itself create a third invocation. Generous bounded scheduling deadlines do not weaken the held-provider refusal or counts. This is an implementable deterministic lifecycle fixture, with actual execution still required.

## Exact scope and evidence boundary

Independent byte comparison against archive-a4/product-payload.json confirms that only this named test body changed: the entire preceding production/test prefix and following suffix are identical, and the other eleven Rust files are identical. Source-base, reviewed-diagnostic, original and reviewed-original hash maps are unchanged. Thus persistent Pending/uncertainty, ReaderChild teardown ownership, fresh Word identity/security checks, native replacement/formatting/Undo safeguards and conservative restart semantics retain their prior source review. The native mutation body and the reader runtime have no changes.

All twelve current product files exactly match the authored manifest strings and payload hashes. The normalized host payload exactly matches those twelve strings and the authored manifest identity. Its required_green_tests contains seventeen unique nonempty names: the thirteen existing core cases plus all four generic reader cases. This records test selection, not observed compilation or passes. Actual previous core/registry/typed checks remain historical evidence for their exact earlier bytes; revised hosted checks/full Windows and real Word acceptance remain pending. No hang-fix, first-partial-write prevention, Word atomicity, server recovery or XML integration claim is made.

## Frozen bindings

Authored payload SHA-256: `7c1a9ddd1b584757891ccf78775fbe6cd42f34d78b5e3c8647250eb01f713f87`.

Normalized host product-payload.json SHA-256: `c8b09922736517792b993f038da12648661df468d5642f505df1a76218d870fc`.

Source BASE: `10b7e90dfa9521170c48d9f09e2c5a4d6d77c3c3`; reviewed diagnostic: `3407a2d0570b88864fd265de61a8761999995380`.

| Proposed file | SHA-256 |
| --- | --- |
| `src/windows_runtime/guard_core.rs` | `5c60561b83829409edfed4933b2e179591b927e06045d19e35e41a3c8e8d6c30` |
| `src/windows_runtime/read_worker.rs` | `11ae0f0df193ea398dcc51b4426fd57052372b0f66a73bd672b4b946b03bf4a1` |
| `src/windows_runtime/registry_store.rs` | `bb80842c13919c386b8a1c2de07bdafaaf85ae0618a8dee32651283875e9aff2` |
| `src/windows_runtime/requirements_tests.rs` | `b75587213f09b8766e5b87873f3967cafd90b42387357d97eb26b8bc0f2a90c8` |
| `src/windows_runtime/secure_input.rs` | `74fcc65f7a2b878955aed79951d39568939db35f6b6790c2d42ed4670b37c7c6` |
| `src/windows_runtime/selection.rs` | `a0b70c96f717318344b1f704b07a6730c2235636e773e6d093d93a46fba948f5` |
| `src/windows_runtime/uia_secure.rs` | `96b1100e62fd14f56dfa91589de0df807f7a59726d265170ea71d478ca0aee7b` |
| `src/windows_runtime/win32_identity.rs` | `28afc2561d1b716d8695fc6076bad61f4e21ca301050df540667d17d053a8eaf` |
| `src/windows_runtime/word_admission.rs` | `b5fda079e60a64c19aaa75ed1e5c4fff1e2d0fcb36447f9a6875e168be1191f1` |
| `src/windows_runtime/word_focus.rs` | `057c37e651748629d6dde19b3b7f2682b1b7f2ec95f44926314acbc536584e61` |
| `src/windows_runtime/word_native.rs` | `b23de30d0492a2ba6543adaf27319f424e8efd99f7065a757883beedf5d66f86` |
| `src/windows_runtime_v201.rs` | `ce5dcfde016c7bd6608fde45a4da30cfac564530525e0cad0232a53def71a152` |
