# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 1.0.1 is a corrective release for the 1.0 line. It fixes the first-run and Settings layouts observed on real Windows, substantially expands built-in Russian/English word protection, and fixes wrong-layout words whose Russian form begins on an OEM punctuation key.

## 1.0.1 behavior

- Russian ↔ English automatic layout correction.
- Detector v3 combines conservative layout heuristics with a baked-in local RU/EN frequency model, common n-gram scoring, word-shape signals, exact known-word protection and volatile two-word context.
- The built-in common-word lexicons are substantially broader than in 1.0.0 and include everyday, technical, colloquial and common obscene vocabulary in both languages.
- A recognized frequent source-language word is protected from automatic rewriting. Examples include `truth`, `information`, `company`, `fuck`, `пизда`, `бля`, `блять`, `хуй`, `ебать` and many others.
- A wrong-layout token that maps to a recognized frequent target word receives deterministic target recognition rather than relying on weaker statistical scoring.
- Short ambiguous words remain context-sensitive where necessary; broadening the dictionary does not intentionally bypass the existing conservative three-letter policy.
- OEM-key candidate tracking supports words whose opposite-layout form begins with punctuation-looking keys, including `,kz` → `бля`, while retaining existing `rjhj,rf` → `коробка` and `cdj,jle` → `свободу` behavior.
- Three sensitivity profiles control the heuristic confidence threshold: `Conservative`, `Normal` and `Aggressive`. `Normal` is the default.
- Exact user-dictionary source matches protect valid text; explicit user-dictionary target matches receive maximum confidence.
- Context is limited to at most two immediately previous completed words, remains RAM-only, and is cleared on relevant focus/process/control changes and Undo.
- Native selected-text conversion for supported Win32 Edit/RichEdit controls; default hotkey `Ctrl+Shift+F9`.
- Selected-text conversion uses the physical Russian/English keyboard mapping directly and does not use or modify the clipboard.
- Selected-text conversion has one-shot `Ctrl+Backspace` Undo and restores the source layout.
- Password, PIN, OTP and credential/secure input controls are excluded from automatic correction, manual conversion, selected-text conversion and Undo-related text processing.
- Configurable manual-current-word hotkey; default `Ctrl+Shift+F12`.
- Manual conversion of the immediately previous completed word; default `Ctrl+Shift+F10`.
- Configurable undo hotkey; default `Ctrl+Backspace`, including restoration of the previous layout.
- Pause/Resume from the tray or configurable hotkey; default `Ctrl+Shift+F11`. Pause resets at each application start.
- Per-application modes by executable basename: `Auto`, `Manual only`, and `Disabled`.
- Native Settings process picker enumerates running processes plus already configured applications.
- The Settings window uses a 900×825 client area with more vertical spacing, taller application-mode lists, and a genuinely multiline user-dictionary editor.
- Read-only application-mode lists no longer show useless always-visible vertical scrollbars; the editable dictionary keeps normal scrolling.
- Mixed UI wording such as `hotkey`, `clipboard`, `Secure` and `Pause / Resume` has been replaced with clearer Russian labels where practical.
- The first-run window has additional vertical room so the Settings hint no longer runs into the separator/footer area.
- Live tray tooltip shows the active mode, current process/layout and the latest correction/undo when applicable.
- Standard-user operation with fail-open input behavior.
- Single-instance protection, per-user settings and autostart.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory. G-switcher retains the current candidate token, at most one previous token for manual previous-word conversion, and at most two completed context words in RAM. These values are cleared on relevant context changes and are never persisted or transmitted.

Selected text is read only when the user invokes the selected-text hotkey, only from the currently focused supported Win32 text control, and only for the duration required to replace that selection. The clipboard is not used. Secure/password/PIN/OTP/credential fields are excluded from G-switcher processing.

Persisted data is limited to explicit user configuration: automatic-correction state, sensitivity profile, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state, typed candidate text, previous-token text, contextual words and selected text are not persisted.

## Release assurance

The Windows CI gate runs formatting, unit/integration tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The E2E covers automatic correction and Undo, Pause, Manual-only/Disabled modes, selected-text conversion and Undo, password EDIT protection, and the OEM-leading `,kz` → `бля` regression. The built EXE is then checked for Windows GUI subsystem, G-switcher 1.0.1 version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
