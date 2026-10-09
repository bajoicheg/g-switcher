# Word transaction design: independent technical QUALITY review

Verdict: **PASS as a containment and investigation design; not implementation acceptance.** No blocking false causal or atomicity claim found in the reviewed design. A replacement mutation adapter remains blocked on the concrete gates below. Read-only review; no tests, launches, product edits, or remote writes performed.

## What the evidence establishes

Exact Git source `3407a2d0570b88864fd265de61a8761999995380` forwards ordinary keyboard events with `CallNextHookEx` while the runtime processes queued events under the Engine mutex. The native adapter makes separate character writes, checks evolving text and selection between them, and waits synchronously for its STA including interface release and apartment teardown. Thus live Word input and partial mutation are permitted by the implementation; the mutex does not serialize Word's independent input.

Log 2 records two **attempts** at character writes followed by `replace-selection-moved`, an attempted custom Undo end, retained uncertainty, and later refusals. Log 3 records a successful earlier transaction, then three attempts followed by the same refusal sequence. The trace precedes each property put and does not record selection coordinates, input events, or document changes. It cannot prove which puts completed, that user typing caused the mismatch, or that the mismatch caused the eventual Word hang. Word's own selection behavior, AutoCorrect, IME, add-ins, and external changes remain unresolved possibilities. Logged PIDs identify the switcher process, not authenticated Word process identity.

The new user report establishes recurrence after restart and Word remaining unresponsive after another client restart. It does not locate the blocked server call. Log 2's later fresh switcher PID reaches a successful context operation, then times out in fresh UIA focus before native window acquisition for that request. This is a separate observed read failure; it does not identify the server deadlock. No supplied evidence proves killing/restarting the client cancels Word work or recovers Word.

The process-local uncertainty latch does reset on restart. The design correctly treats this as lost client knowledge, not proven server quiescence. EndCustomRecord is grouping, not rollback, and the current code retains uncertainty when writes or subsequent checks are unresolved.

## Immediate existing containment

In the exact source, `Engine::on_key_event` obtains the focused target through Win32 APIs, identifies the process, and returns for `AppMode::Disabled` **before** `secure_input`, adapter admission, and `uia_password_state`. The settings UI provides `Отключить` and labels this mode `Отключено — без анализа и горячих клавиш`. A configured `winword.exe` exclusion therefore prevents new Word analysis and correction requests through this path while other application modes remain independently configured. It does not cancel an already outstanding request; an Engine already blocked in NativeOM may not reach the exclusion check. Stopping the client and allowing Word recovery, then configuring exclusion before further Word use, is containment, not an adapter fix or guaranteed Word recovery.

## Concrete gates before implementing or enabling a replacement writer

1. **Cross-restart ownership and persistence need an executable protocol.** PID plus process creation time is the right identity scope, but unknown identity, unreadable/corrupt state, abandoned ownership, broker death, and failed persistence must deny access. Obtain birth identity with Win32 process queries rather than COM; authenticate user/session and broker IPC, and retain an actual process handle where possible to establish true exit and avoid PID reuse. Write-ahead state must be durably recorded before StartCustomRecord or any other side effect; acknowledged clearing must be tied to exact operation identity and completed verification/Undo closure. A fresh client must consult it before both Word focus/security UIA and NativeOM. A durable marker alone contains uncertain writes but cannot prove an old read provider has completed. A surviving broker can acknowledge exact completion; if it dies with a pending call, remain blocked until genuine Word process exit or an independently specified, safe reconciliation. No timer expiry, successful unrelated read, abandoned mutex, or new client process clears that state.

2. **One InsertXML call is feasible as an experiment, not demonstrated formatting preservation or atomicity.** Microsoft's APIs provide range XML export and XML replacement, but do not promise all-or-nothing execution, rollback, bounded duration, or preservation of every formatting/document dependency. Define an actual allowlisted package/fragment grammar from Word-exported samples, exact UTF-16 text mapping, and rejection of unsupported structures before writing. Local run properties alone do not capture effective formatting inherited from styles, defaults, themes, language, and paragraph context. Import may normalize representation or affect dependencies. Actual Word round trips must prove supported mixed formatting, selection, document metadata scope, and both one ordinary Undo and the switcher's stored original-text Undo. XML parser limits, entity/network refusal, relationships, and imported style scope need explicit handling. The proposed exclusion of paragraph marks means paragraph-delimited corrections may be refused; preserve this restriction rather than silently expanding the subset. Failed verification cannot undo damage already committed, so fidelity must be established before enabling the writer.

3. **Asynchronous admission is a larger behavioral change than persistent refusal.** Release the Engine before broker waits; send values, not COM interfaces. Fresh operation-bound policy and input sequence must reach the broker before every side effect, and stale replies must not change current Engine/Undo state. Coalescing can reduce races but does not eliminate the final precheck-to-commit window or interleaving with Word input. A single visible text commit still includes other potentially effectful calls such as Undo start/end and caret placement. Keep existing security, focus, document/protection, generation, exact suffix/rest/delimiter, and actual original Undo safeguards; fail closed rather than use a whole-range plain Text fallback, key replay, blind Undo, or a second writer.

The smallest implementable next product change is restart-persistent fail-closed Word uncertainty/admission, with the existing mutation and formatting behavior unchanged and Word excluded during investigation. Broker isolation and the restricted XML writer should be separate reviewed increments. The design's broker-first direction is reasonable if preserving responsiveness during Word stalls is included in that increment, but no client architecture proves Word itself is recovered.

## Required evidence for those gates

Portable protocol tests should exercise durable-write failure, crash at each admission/side-effect/clear boundary, restart, PID reuse, stale completion, and pending reader ownership without replacement. Actual Windows/Word tests must cover mixed effective formatting and one Undo, continuous typing/IME/mouse or focus changes, protected/password/unsupported documents, failed or stalled COM calls, and continued Chrome responsiveness across client restart. CI compilation cannot establish these empirical Word properties. Do not advertise an atomic transaction or a measured hang fix before that evidence exists.

## Primary API references checked

- [Range.InsertXML](https://learn.microsoft.com/en-us/office/vba/api/word.range.insertxml): replaces range text with supplied XML; no documented atomicity/cancellation guarantee.
- [Range.WordOpenXML](https://learn.microsoft.com/en-us/office/vba/api/word.range.wordopenxml): exports XML necessary to represent the range; no promised byte-stable import round trip.
- [Range.Text](https://learn.microsoft.com/en-us/office/vba/api/word.range.text): plain text and range replacement, insufficient evidence for mixed-format preservation.
- [UI Automation threading](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading): separate windowless MTA guidance; this does not establish Word server health.

## Exact review binding

| Source / evidence | SHA-256 |
| --- | --- |
| `src/windows_runtime/word_native.rs` | `a6170ce005e7fcc7e685f9abf05f41c3b1d9fb69be5003916662f295808cf9ca` |
| `src/windows_runtime/word_focus.rs` | `416730f45aec6a5cd8588f8265a7737b087e22b7da98d6eed40d6c2f56456c35` |
| `src/windows_runtime/read_worker.rs` | `0090f7afd1e66e587b9cc0832c320d63de63e801820f0ea1f9c371d91efd090e` |
| `src/windows_runtime/word_native_plan.rs` | `36553da4992eb9de0480bdd088b991d1615021fc61ccfcedc323ddf58e8a93e0` |
| `src/windows_runtime/selection.rs` | `0b4c8b5ce9e57e8ac18c33cf580f4907e7863e2e8dea06c61fd43c4a3e6a2367` |
| `src/windows_runtime_v201.rs` | `daa180ece96ee3af5b5dc0ae56b70a7daf12054cd451aaddb0ea5703c0ebed7e` |
| `src/windows_runtime/ui/settings_dialog.rs` | `4bed56c360d9b6a2cd9947989d8dc9c9b7856c36bd0d708b257ac4737a689abb` |
| `word-refusal-bootstrap/word-transaction-design-spec.md` | `72f84e62765566e7aede48a54932a8841540a94fbe40f59c3590d7e8cdf4b8eb` |
| `upload/GSwitcher-Word-Runtime(1).log` | `b4b61834f33b4cddde2d23c5390d1aacf2ec01f022c702c65e41e75ea053ea57` |
| `upload/GSwitcher-Word-Runtime(2).log` | `ce6b5886c9d3640c7c7959415ceccdebe5517ee808e5d09c0c70c51f8ec30638` |
| `upload/GSwitcher-Word-Runtime(3).log` | `ff48021345a0477f6daddd709bd2d2abbd0fd09c072e75d46a6691be02a59ada` |
