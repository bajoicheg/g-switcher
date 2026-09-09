# G-switcher 2.0.1 — compatibility matrix

This matrix is part of the 2.0.1 release gate. A blank or `PENDING` manual result is **not** treated as supported.

## Automated Windows CI coverage

| Target | Automatic correction | Manual current word | Selected text | Undo | Secure-input guard | Gate |
|---|---:|---:|---:|---:|---:|---|
| Separate-process Win32 `Edit` | CI | CI | CI | CI | N/A | mandatory |
| Separate-process `RICHEDIT50W` | not claimed | not claimed | CI | CI | UIA metadata checked | mandatory |
| Separate-process password `Edit` | blocked | blocked | blocked | blocked | CI: native + UIA `IsPassword` | mandatory |
| Same-process Win32 `Edit` regression fixture | CI | CI | CI | CI | CI | mandatory |
| Hung/closing separate-process text target | mutation adapter fails open | mutation adapter fails open | mutation adapter fails open | N/A | bounded liveness preflight | mandatory |

`CI` means the behavior is exercised by an automated Windows release-gate test. It does not imply compatibility with every control implemented by an application.

The dedicated failure-path E2E deliberately blocks the helper UI thread and, in a separate case, terminates the helper process during a verified mutation attempt. Both cases must return without changing the target text within a bounded timeout, and a fresh target must remain writable afterward. This gate covers the verified text-mutation adapter itself; it does not claim full application-level Auto/Manual/Undo compatibility for arbitrary hung controls.

## Manual application matrix

Record the exact application version and Windows build used for the check. Test with ordinary editable text; do not enter real credentials or secrets.

| Application | Version tested | Windows build | Auto | Manual current word | Selected text | Undo | Password/sensitive fields | Result / notes |
|---|---|---|---|---|---|---|---|---|
| Notepad | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |
| Microsoft Word | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |
| Microsoft Edge | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |
| Google Chrome | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |
| Telegram Desktop | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |
| Visual Studio Code | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |
| Windows Terminal | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | release blocker until checked |

Result semantics are intentionally strict:

- `Auto`, `Manual current word`, `Selected text`: final release values are only `PASS` or `UNSUPPORTED/FAIL-OPEN`. `N/A` is not accepted for these text-operation columns.
- `Undo`, `Password/sensitive fields`: final release values are `PASS`, `UNSUPPORTED/FAIL-OPEN`, or `N/A` when the case is genuinely not applicable.
- `FAIL` and `PENDING` always block publication.
- `UNSUPPORTED/FAIL-OPEN` means the operation is unsupported **and was verified to preserve original input / avoid swallowing the action**; it is not a synonym for “not tested”.
- Application version and Windows build must identify the actual tested environment; `UNKNOWN`, `N/A`, `NOT INSTALLED`, and similar placeholders do not satisfy the release gate.

## Required manual cases

For every application above where a writable text control is available:

1. Type `ghbdtn ` under the English layout and record whether automatic correction produces `привет ` without touching adjacent text.
2. In Manual-only mode, type `ghbdtn`, invoke the configured current-word hotkey, then Undo; verify exact text and source-layout restoration.
3. Select `ghbdtn rfr ltkf`, invoke selected-text conversion, then Undo; verify the exact selected range only is changed and restored.
4. Move the caret with the mouse and arrow keys between typing and a word boundary; verify no stale correction changes text at the new position.
5. Switch focus to a different field/window while a correction could be pending; verify neither field is modified by stale state.
6. Open a password/PIN/credential field when one exists; verify automatic, manual, selected-text and Undo actions do not modify the field and do not change its layout.
7. Exercise Pause/Resume and application modes (`Auto`, `Manual only`, `Disabled`).
8. For unsupported controls, confirm original input is preserved and hotkeys are not swallowed; record `UNSUPPORTED/FAIL-OPEN` rather than `PASS`.

## Release rule

2.0.1 must not be promoted from draft solely because the automated CI is green. The manual rows above must be completed for the intended public compatibility claim, and every observed failure that can corrupt text or touch a protected field is a release blocker.
