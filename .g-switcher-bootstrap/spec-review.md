# Restart-persistent Word admission: independent SPEC review

Verdict: **PASS for the refrozen source-level SPEC.** Source-only independent SPEC review of the frozen proposal, not execution acceptance. No compiler, tests, CI, installed Word experiment, launch, product change, or remote mutation performed. No CDC version change.

## Actual a2 failure and narrow Clippy correction

Previous source SPEC is preserved separately in spec-review-d592-historical.md. Authenticated recovered a2 protocol logs record named baseline RED expected101,13 core GREEN,42 portable library tests and typed Windows compilation success, then actual Clippy rejection `items_after_test_module` in registry_store. Those outcomes apply to a2 source only; revised compilation/Clippy/full Windows execution is not yet evidence.

Only proposed source delta is moving the identical three cfg(test) registry fixture functions before mod tests, plus surrounding blankline relocation. Independent comparison confirms all function/test/production bodies unchanged and the other11 Rust files byte-identical. Registry hash is now `bb80842c13919c386b8a1c2de07bdafaaf85ae0618a8dee32651283875e9aff2`; all12 proposed copies/hashes match the new manifest. Normalized host product payload `60794cc8c161604be8df9c2dc4ea2b94b9d64fbf7db04695d8c6557ed3bb417e` contains precisely those12 authored source strings and original/hash bindings. This closes the observed source-order Clippy defect without suppressing the lint or changing admission/ownership/security/mutation behavior. Actual revised checks remain required.

## Targeted corrections verified

Both previously reported blockers are closed in the refrozen payload. `RegistryStore::clear` now retains the expected nonce-bound Idle bytes across the write, RegFlushKey and readback, and invokes `require_exact_idle_readback`. That production predicate returns success only for those exact bytes; foreign valid Idle, missing value and storage errors fail. The added Windows-only real registry regression writes foreign Idle, deletes the value, then writes exact Idle in a disposable namespace and exercises that actual predicate for rejection/rejection/acceptance. Source inspection verifies the test intent; no execution outcome exists.

The shared word_admission Parent/ReaderChild/functions/methods now use `pub(crate)`, making the runtime parent and sibling uia_secure callers valid under Rust visibility rules. BoundedReader::request_guarded also uses `pub(crate)`, matching its Parent argument visibility. Core/private store implementation visibility remains scoped. Actual typed compilation and Clippy are still required evidence; neither is claimed run.

## Admission and ownership traced

Runtime uses actual winword.exe process context to check persistent availability before cached positive UIA security reuse. `secure_input` independently classifies actual HWND process and obtains a durable parent before Word security messages; a timeout yields uncertain completion and retains the marker. Unknown process identity conservatively refuses.

Selection now classifies actual Word before its generic WM_NULL/UIA routing. Word-owned non-_WwG controls are refused, including dialog Edit/RichEdit fallback; native _WwG availability enters the durable native admission path. The prior unguarded Word dialog fallback finding is closed. Public native read/prepare/write calls enter `run_at_generation`, reserve Pending before spawning STA and fresh focus/NativeOM, and complete the parent only after successful join. Context/cache/interface release, final pumping and CoUninitialize are inside the joined lifetime. Spawn failure or panic has no implicit completion and leaves pending. Existing synchronous native wait remains unbounded.

Fresh Word focus/security UIA propagates the exact parent through thread-local value scope and an explicit child ticket. The child is registered after reader admission and before queue submission; caller timeout never completes it. Failed queue submission completes only the never-submitted ticket. Per-request Word MTA interfaces/apartment are dropped before provider closure returns; the reader then explicitly completes its child. Parent completion waits for every exact child and does not consume foreign/duplicate tickets. Panic leaves durable Pending; late replies remain discarded. Word timeout does not authorize a replacement provider or writer. Non-Word persistent automation remains distinct; unavoidable external focus changes between Win32 checks and global UIA calls are acknowledged in the design, not claimed eliminated.

## Persistence and incarnation semantics

Retained Win32 process handles establish image basename, PID, creation FILETIME, live process and HWND binding without UIA. Pending is written under a short named mutex with RegFlushKey and exact readback before provider access. Records are keyed by PID plus birth and include a random operation nonce. Existing Pending/corrupt/unknown records refuse; no timeout, client restart, abandoned mutex or successful unrelated read clears them. HKCU storage and Local mutex scope assume the current user/session and cooperating guarded clients; this is not tamper-proof protection against that user editing registry values or running older unguarded clients.

Absent enrollment requires Word creation later than guarded client creation. A first installation over an existing Word process therefore refuses until genuine new Word birth; existing verified Idle permits healthy switcher restart. Pending/uncertain old incarnation remains blocked. Word exit/new birth does not reset the in-process global active/poison state, so a fresh guarded switcher may also be required. This conservative process-global limitation is documented. No automatic Word termination or unsaved-work discard is added.

## Preserved mutation contract and safety scope

The complete native `Context::replace` body is byte-identical to reviewed diagnostic3407, SHA-256 `ef49ce1f0ed027a9b672543c36b7fb136acd0aa1ebf6e3e2d2bf1e27e314f43c`. Per-character replacement, formatting behavior, fresh focus/security/document/protection/generation and exact text guards, one custom Undo grouping, actual original Undo and existing uncertain latch are not replaced or weakened. The durable parent spans StartCustomRecord, partial writes, postverification, Undo end and teardown; native uncertainty prevents clearing. No new whole-range Text/XML writer, key replay, blind Undo, clipboard, retry or global Word setting exists.

This increment contains repeated access after known Pending/uncertain work across restarts. It does not prevent the first partial replacement, cancel remote Word work, bound Engine/native waits, identify the hang's cause or prove Word recovers. Live input remains possible; stage logs do not prove user typing caused selection movement. Real Word security/mixed-format/Undo/restart acceptance remains pending.

## Proposed tests and evidence boundary

Portable tests cover exact pending restart refusal, child timeout/late completion, stale/duplicate authority, failed persistence, corrupt/missing markers, birth separation and actual held worker ownership. Windows-only tests invoke the actual guarded reader and RegistryStore in disposable test namespaces, retaining Pending across caller timeout and native uncertainty; separate registry tests exercise foreign clear and Idle/re-admission. These are source-level test intentions, not observed passes. The baseline explicitly models old process-local semantics rather than compiling an exact original-product restart executable; no stronger RED provenance should be claimed. Required host RED/GREEN, typed Windows compile/Clippy/full Windows CI and actual Word acceptance must supply subsequent evidence.

## Exact frozen binding

Proposal `word-refusal-bootstrap/restart-guard-proposal/payload.json` SHA-256: `f4600d94f764d10ade4ae29cf6e5c5a473c3ba16efd61089165dd7a747f98ba5`.
Source BASE: `10b7e90dfa9521170c48d9f09e2c5a4d6d77c3c3`; reviewed diagnostic: `3407a2d0570b88864fd265de61a8761999995380`. All 12 manifest contents match proposed product files and payload hashes; all original hashes match exact BASE objects, and every reviewed-original hash matches diagnostic3407 objects. Native original separately binds diagnostic3407; its source baseline hash differs only because this increment carries the previously reviewed diagnostic code forward. No executable acceptance inferred.

| Proposed file | SHA-256 |
| --- | --- |
| `src/windows_runtime/guard_core.rs` | `5c60561b83829409edfed4933b2e179591b927e06045d19e35e41a3c8e8d6c30` |
| `src/windows_runtime/read_worker.rs` | `86b3d3c0176688b5e8b3632a747e0eb9874075513ecc79f81d9a755b094133b9` |
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
