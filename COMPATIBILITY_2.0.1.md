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

The table below records the first real Windows 11 compatibility pass (build 22631) plus the focused Notepad retest of the corrected CI #325 release candidate. A required row remains `PENDING` when the original observation does not prove the exact required application/control.

| Application | Version tested | Windows build | Auto | Manual current word | Selected text | Undo | Password/sensitive fields | Result / notes |
|---|---|---|---|---|---|---|---|---|
| Notepad | 11.2607.14.0 | 22631 | PASS | PASS | PASS | PASS | UNSUPPORTED/FAIL-OPEN | Initial Auto/Selected/Undo passed; CI #325 focused retest confirmed Manual, Undo and Auto all PASS. No destructive behavior in the tested protected-field case. |
| Microsoft Word | PENDING | 22631 | PENDING | PENDING | PENDING | PENDING | PENDING | Required desktop Word is not yet tested. The first pass used Microsoft 365 Word PWA in Chrome and therefore cannot satisfy the desktop Word row. |
| Microsoft Edge | 152.0.4191.66 | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PASS | User confirmed ordinary text remained unchanged for Auto/Manual/Selected; password/sensitive test was also an unchanged safe no-op with no G-switcher action. |
| Google Chrome | 152.0.7977.77 | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PASS | User confirmed ordinary text remained unchanged for Auto/Manual/Selected; password/sensitive test was also an unchanged safe no-op with no G-switcher action. |
| Telegram Desktop | 7.2.5 | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PENDING | User confirmed ordinary text remained unchanged; protected-field applicability/result was not separately confirmed. |
| Visual Studio Code | PENDING | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PENDING | User confirmed ordinary text remained unchanged. Recorder reported 18.5.0, which is not accepted as verified VS Code version evidence; tooling now prefers the VS Code uninstall registration to avoid an unrelated Code.exe on PATH. |
| Windows Terminal | 1.24.11911.0 | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PENDING | User confirmed ordinary text remained unchanged; protected-input scenario was not separately confirmed. |

### Supplemental observation — Word PWA

The first pass also exercised **Microsoft 365 Word PWA in Chrome** on Windows build 22631. Its ordinary Auto/Manual/Selected operations were observed as unchanged safe no-ops. This is evidence about the Chrome-hosted web control only and is intentionally **not** substituted for the required Microsoft Word desktop row.

Result semantics are intentionally strict and are based on the **observed safety behavior**, not simply on whether a conversion happened:

- `Auto`, `Manual current word`, `Selected text`: final release values are only `PASS` or `UNSUPPORTED/FAIL-OPEN`. `N/A` is not accepted for these text-operation columns.
- `PASS` means the capability behaved exactly as required. For `Password/sensitive fields`, **no text mutation and no layout change is the expected PASS behavior**.
- `UNSUPPORTED/FAIL-OPEN` means the ordinary text control does not support the conversion, while the original input remains unchanged and no destructive side effect occurs. A safe no-op belongs here, not under `FAIL`.
- `FAIL` means the observed behavior violates the requirement: wrong/corrupted/lost text, stale or wrong target mutation, an unwanted layout change, destructive hotkey handling, or another required safety/property failure.
- `Undo`, `Password/sensitive fields`: final release values are `PASS`, `UNSUPPORTED/FAIL-OPEN`, or `N/A` when the case is genuinely not applicable.
- `FAIL` and `PENDING` always block publication.
- `UNSUPPORTED/FAIL-OPEN` is not a synonym for “not tested”. The safe no-op must actually have been observed.
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
8. For unsupported controls, confirm original input is preserved and no destructive action occurs; record `UNSUPPORTED/FAIL-OPEN` rather than `PASS` or `FAIL`.

## Remaining manual blockers

Before public promotion, the following evidence is still required:

1. Microsoft Word **desktop** version + functional row.
2. Exact Visual Studio Code version for the already observed safe fail-open behavior.
3. Telegram Desktop protected-field result, or `N/A` with confirmation that no applicable protected field was available in the tested scenario.
4. Visual Studio Code protected-field result, or `N/A` when genuinely not applicable.
5. Windows Terminal protected-input result, or `N/A` when genuinely not applicable.

## Release rule

2.0.1 must not be promoted from draft solely because the automated CI is green. The manual rows above must be completed for the intended public compatibility claim, and every observed failure that can corrupt text or touch a protected field is a release blocker.
