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

- [ ] Add and run failing tests for native-coordinate suffix planning, terminal paragraph exclusion, surrogate boundaries and unsupported/changed contexts.
- [ ] Implement native IDispatch/VARIANT ownership and guarded Word context; use existing windows bindings where possible.
- [ ] Wire selected text, caret snapshot, suffix/range mutation and Undo through the current selection API; Word adapter uses native UTF16 coordinates consistently.
- [ ] Review complete writer/failure behavior, then run exact-candidate Windows Rust CI.
- [ ] In installed Word validate Auto/F12/F9, multiple paragraphs, mixed formatting, Unicode, native Ctrl+Z and G-switcher Undo. Check Edge/Chrome/Telegram/Notepad regressions and actual versions.

The same branch contains only a settings group clearance correction plus this evidence/plan so far. Word runtime is not repaired by this preparation commit. Draft PR28 and public-promotion/manual gates remain unchanged; no scheduler mutation.
