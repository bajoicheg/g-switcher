# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 1.0.4 improves Detector v3 coverage using a synthetic wrong-layout corpus derived from a long Russian information-security article. The audit isolated 13 residual common Russian word forms under Normal sensitivity; all are now deterministic local target recognition while the 1.0.3 partial-`SendInput` reliability fix remains unchanged.

## 1.0.4 behavior

- Russian ↔ English automatic layout correction.
- Detector v3 combines conservative layout heuristics with a baked-in local RU/EN frequency model, common n-gram scoring, word-shape signals, exact known-word protection and volatile two-word context.
- The built-in common-word lexicons include everyday, technical, colloquial and common obscene vocabulary in both languages.
- Recognized frequent source-language words such as `truth`, `fuck`, `пизда`, `бля`, `блять`, `хуй` and `ебать` are protected from automatic rewriting; wrong-layout forms of recognized target words receive deterministic target recognition.
- Article-corpus regression coverage includes the common Russian forms `политик`, `систем`, `спрос`, `программ`, `лиц`, `дел`, `правил`, `команд`, `виде`, `работ`, `инструкции`, `важны` and `норм`.
- OEM-key candidate tracking supports words whose opposite-layout form begins with punctuation-looking keys, including `,kz` → `бля`, `rjhj,rf` → `коробка`, `rjhj,jxrf.` → `коробочка.` and `cdj,jle` → `свободу`.
- Three sensitivity profiles control the heuristic confidence threshold: `Conservative`, `Normal` and `Aggressive`. `Normal` is the default.
- Exact user-dictionary source matches protect valid text; explicit user-dictionary target matches receive maximum confidence.
- Context is limited to at most two immediately previous completed words, remains RAM-only, and is cleared on relevant focus/process/control changes and Undo.
- Native selected-text conversion for supported Win32 Edit/RichEdit controls; default hotkey `Ctrl+Shift+F9`.
- Selected-text conversion uses the physical Russian/English keyboard mapping directly and does not use or modify the clipboard.
- Password, PIN, OTP and credential/secure input controls are excluded from G-switcher processing.
- Configurable current-word, previous-word, Undo, Pause and selected-text hotkeys.
- Per-application modes by executable basename: `Auto`, `Manual only`, and `Disabled`.
- Native Settings process picker enumerates running processes plus already configured applications.
- Settings reserve a 900×855 client area and provide dedicated two-line help regions for sensitivity and Pause instead of forcing long Russian text into one-line rectangles.
- The Pause label is shortened, footer controls are moved down, and long help text is split deliberately so it cannot overlap adjacent controls.
- The first-run window gets additional bottom space and a shorter Settings hint so the separator, autostart row and copyright footer remain visually separated.
- Read-only application-mode lists remain clean; the editable user dictionary keeps normal scrolling.
- Live tray tooltip shows the active mode, current process/layout and the latest correction/undo when applicable.
- Partial `SendInput` delivery resumes from the first unsent INPUT instead of abandoning a correction after already-delivered Backspace events; zero initial progress still fails open without modifying text.
- Standard-user operation with fail-open input behavior.
- Single-instance protection, per-user settings and autostart.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory. G-switcher retains the current candidate token, at most one previous token for manual previous-word conversion, and at most two completed context words in RAM. These values are cleared on relevant context changes and are never persisted or transmitted.

Selected text is read only when the user invokes the selected-text hotkey, only from the currently focused supported Win32 text control, and only for the duration required to replace that selection. The clipboard is not used. Secure/password/PIN/OTP/credential fields are excluded from G-switcher processing.

Persisted data is limited to explicit user configuration: automatic-correction state, sensitivity profile, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state, typed candidate text, previous-token text, contextual words and selected text are not persisted.

## Release assurance

The Windows CI gate runs formatting, unit/integration tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The E2E covers automatic correction and Undo, Pause, Manual-only/Disabled modes, selected-text conversion and Undo, password EDIT protection, OEM-key regressions, and article-derived `cbcntv` → `систем`, `ghjuhfvv` → `программ`, and `bycnherwbb` → `инструкции` cases. The built EXE is then checked for Windows GUI subsystem, G-switcher 1.0.4 version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
