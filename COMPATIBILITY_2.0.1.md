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

The table below records the first real Windows 11 compatibility pass (build 22631) plus the focused Notepad retest of the corrected CI #325 release candidate. **Safe fail-open observations for mainstream target applications are evidence of the current gap, not an acceptable final support claim. Edge and Chrome must work for ordinary editable web fields before public 2.0.1 promotion.**

| Application | Version tested | Windows build | Auto | Manual current word | Selected text | Undo | Password/sensitive fields | Result / notes |
|---|---|---|---|---|---|---|---|---|
| Notepad | 11.2607.14.0 | 22631 | PASS | PASS | PASS | PASS | UNSUPPORTED/FAIL-OPEN | Initial Auto/Selected/Undo passed; CI #325 focused retest confirmed Manual, Undo and Auto all PASS. No destructive behavior in the tested protected-field case. |
| Microsoft Word | PENDING | 22631 | PENDING | PENDING | PENDING | PENDING | PENDING | Required desktop Word is not yet tested. The first pass used Microsoft 365 Word PWA in Chrome and therefore cannot satisfy the desktop Word row. |
| Microsoft Edge | 152.0.4191.66 | 22631 | PENDING | PENDING | PENDING | PENDING | PASS | First candidate safely no-op'd ordinary web fields; this is now treated as a release blocker. New Chromium UIA TextPattern + ValuePattern adapter is under validation and must be retested to PASS. Password/sensitive no-op remains expected protection behavior. |
| Google Chrome | 152.0.7977.77 | 22631 | PENDING | PENDING | PASS | PENDING | PASS | On runtime candidate `b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576`, the focused Selected-text retest PASSed after the Chromium post-state stabilization fix, and the dedicated password guard PASSed for Auto/Manual/Selected no-op. Auto, Manual current word, Undo, Focus/caret and Pause still require an exact-current-runtime manual retest before release. Later CDC-only commits do not change runtime behavior. |
| Telegram Desktop | 7.2.5 | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PENDING | User confirmed ordinary text remained unchanged; protected-field applicability/result was not separately confirmed. This row may be revisited after Chromium/Electron adapter validation. |
| Visual Studio Code | PENDING | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PENDING | User confirmed ordinary text remained unchanged. Recorder reported 18.5.0, which is not accepted as verified VS Code version evidence; tooling now prefers the VS Code uninstall registration to avoid an unrelated Code.exe on PATH. Electron compatibility will be retested after the Chromium adapter is proven in browsers. |
| Windows Terminal | 1.24.11911.0 | 22631 | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | UNSUPPORTED/FAIL-OPEN | N/A | PENDING | User confirmed ordinary text remained unchanged; protected-input scenario was not separately confirmed. |

### Supplemental observation — Word PWA

The first pass also exercised **Microsoft 365 Word PWA in Chrome** on Windows build 22631. Its ordinary Auto/Manual/Selected operations were observed as unchanged safe no-ops. That observation is no longer accepted as a satisfactory browser compatibility outcome; the new Chromium adapter must be validated against this class of web editor as well. It is still intentionally **not** substituted for the required Microsoft Word desktop row.

Result semantics are intentionally strict and are based on the **observed safety behavior**, not simply on whether a conversion happened:

- `Auto`, `Manual current word`, `Selected text`: final release values are `PASS`, except where an application/control is explicitly outside the supported compatibility claim.
- `PASS` means the capability behaved exactly as required. For `Password/sensitive fields`, **no text mutation and no layout change is the expected PASS behavior**.
- `UNSUPPORTED/FAIL-OPEN` means the control does not support the conversion, while the original input remains unchanged and no destructive side effect occurs. This is a safety result, **not evidence that the switcher works there**.
- For mainstream supported targets such as Edge and Chrome ordinary editable fields, `UNSUPPORTED/FAIL-OPEN` is a release blocker for 2.0.1.
- `FAIL` means the observed behavior violates the requirement: wrong/corrupted/lost text, stale or wrong target mutation, an unwanted layout change, destructive hotkey handling, or another required safety/property failure.
- `Undo`, `Password/sensitive fields`: final release values are `PASS`, `UNSUPPORTED/FAIL-OPEN`, or `N/A` when the case is genuinely not applicable.
- `FAIL` and `PENDING` always block publication.
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
8. For a truly unsupported control outside the supported claim, confirm original input is preserved and no destructive action occurs; record `UNSUPPORTED/FAIL-OPEN`.

## Persisted focused Chrome evidence

PR evidence records a manual Chrome retest on Windows 11 / Chrome 152.0.7977.77 for runtime candidate `b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576`: Selected-text no longer rolls back and the dedicated password test remains unchanged for Auto, Manual and Selected actions. These exact observations are now reflected in the matrix above. Earlier Auto/Manual/Undo/Focus/Pause PASS observations were on an older runtime candidate and are intentionally not promoted to final PASS here without a retest after the Selected-path runtime fix.

## Remaining manual blockers

Before public promotion, the following evidence is still required:

1. Edge ordinary editable web field: Auto, Manual, Selected and Undo must PASS with the new Chromium adapter.
2. Chrome ordinary editable web field: Selected and password protection are confirmed PASS on runtime candidate `b127b67e98bdaf3fa7b2fd726ce6b91cbf1b3576`; Auto, Manual current word, Undo, Focus/caret and Pause still require exact-current-runtime manual retest.
3. Microsoft Word **desktop** version + functional row.
4. Exact Visual Studio Code version and retest after Electron/Chromium adapter validation.
5. Telegram Desktop protected-field result, or `N/A` with confirmation that no applicable protected field was available in the tested scenario.
6. Visual Studio Code protected-field result, or `N/A` when genuinely not applicable.
7. Windows Terminal protected-input result, or `N/A` when genuinely not applicable.

## Release rule

2.0.1 must not be promoted from draft solely because the automated CI is green. In particular, safe no-op behavior in Edge or Chrome ordinary text fields is **not** sufficient: G-switcher must actually perform the required corrections there while protected fields remain untouched. The manual rows above must be completed for the intended public compatibility claim, and every observed failure that can corrupt text or touch a protected field is a release blocker.
