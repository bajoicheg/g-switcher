# Word native adapter implementation plan

Confirmed installed Word16.0.5569.1000 returns E_NOTIMPL for Legacy.SetValue, while AccessibleObjectFromWindow(OBJID_NATIVEOM, IID_IDispatch), exact native Range.Duplicate/SetRange(0,6) and Range.Text replacement succeed. This is provider evidence, not full product acceptance.

## Requirements

- Add src/windows_runtime/word_native.rs and select it for _WwG before modern Legacy/Value routing in selection.rs; no fallback to whole-value Legacy.SetValue for Word.
- Bind every operation to focused HWND/PID, UIA password/enabled/focusable/RuntimeId checks and native Window.Hwnd root. Bind the fixed Document identity; use Window.Selection, never global ActiveDocument/Selection.
- Keep native story positions separate from UIA scalar-prefix offsets. Support main text story first; refuse unverifiable offsets, protected/read-only documents, tracked revisions and non-contiguous selections.
- Read and replace bounded exact expected ranges through independent native duplicates. Exclude Word's final paragraph from a full-document selection without removing internal paragraph/control characters.
- Equal-length keyboard conversion must preserve per-character formatting. Use range-local character operations and one native UndoRecord; refuse unsafe character-position transformations. Never reset the whole document or use clipboard/SendInput.
- Revalidate focus, document, selection and expected text immediately before writing. Verify exact resulting text/caret; constrain any rollback to the exact observed state. Release COM/VARIANT/BSTR resources on success and errors; do not log document text.

## Execution

- [x] Reproduce the installed Word Legacy.SetValue failure (E_NOTIMPL/no replacement); add native-coordinate, delimiter, routing and refusal regression tests. Compiler/test validation is a separate managed gate.
- [x] Prepare a typed windows0.59 NativeOM adapter in an isolated payload; all COM objects remain in one operation STA with message pumping and synchronous completion.
- [x] Wire selected text, caret snapshot, suffix/range mutation and G-switcher Undo through existing selection interfaces, with Word-only CRLF normalization. Publication and exact-candidate Windows/installed-Word validation remain pending.
- [ ] Review complete writer/failure behavior, then run exact-candidate Windows Rust CI.
- [ ] In installed Word validate Auto/F12/F9, multiple paragraphs, mixed formatting, Unicode, native Ctrl+Z and G-switcher Undo. Check Edge/Chrome/Telegram/Notepad regressions and actual versions.

The same branch contains only a settings group clearance correction plus this evidence/plan so far. Word runtime is not repaired by this preparation commit. Draft PR28 and public-promotion/manual gates remain unchanged; no scheduler mutation.

## Prepared adapter boundaries

The initial adapter accepts responsive `_WwG` controls owned by WINWORD only. It verifies focused HWND/PID/root and UIA metadata, native Window root, canonical document COM identity, main story, editable non-tracking document and current selection. It rejects documents containing fields, tables, content controls or existing revisions; non-BMP coordinate ambiguity; replacements exceeding128native units; unequal lengths; and changed paragraph/tab positions. Terminal document paragraph is preserved. Paragraph/tab delimiters can remain unchanged in a conversion; only changed BMP characters are written through an independent native range, grouped in one Word custom Undo record. It never sets Font or global Word flags.

Runtime verification reads exact source/post text and caret, with bounded target-progress checks between character writes. It does not repeat the diagnostic probe's per-character font-property snapshots. The installed-Word12property/mixed-format/native-Undo checks must be repeated against the compiled candidate before compatibility acceptance; probe evidence alone is insufficient.

A provider call may block the runtime dispatch thread; there is deliberately no timeout that returns while an STA mutation remains live. Any unverified side effect or custom-record end disables further Word operations until application restart, without automatic rollback, Legacy fallback or blind retry. This failure boundary is conservative and does not claim an unchanged document. No document text is logged.

Word readiness currently uses synchronous read-only NativeOM availability validation before admitting correction hotkeys; this preserves unsupported-context refusal and must be measured for typing latency. The operation captures the runtime generation before preflight and checks generation/pause state before every native side effect. Unpause hotkey availability remains readable while paused.

Runtime cancellation policy is registered through immutable generation/paused callbacks before hook installation. The shared selection module has no runtime-parent dependency; standalone E2E imports leave Word unsupported until an actual runtime policy is supplied. Plain Edit and existing UIA adapters keep their interfaces and behavior.

Managed run37628467515 passed all7portable native planner tests, but publication was blocked by the baseline Windows-only compatibility binary having no Linux main. The portable gate now runs library tests only; typed Windows all-target compile/clippy and the complete dependent Windows test/E2E workflow remain mandatory. Build objects and test binaries are outside the evidence artifact.
