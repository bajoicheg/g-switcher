# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 1.0.0 adds selected-text conversion, hard secure-input protection, Detector v3 with a baked-in local frequency model, and configurable Conservative / Normal / Aggressive sensitivity profiles.

## 1.0.0 behavior

- Russian ↔ English automatic layout correction.
- Detector v3 combines the existing conservative layout heuristics with a baked-in local RU/EN frequency model, common n-gram scoring, word-shape signals, exact known-word protection and volatile two-word context.
- Three sensitivity profiles control only the confidence threshold: `Conservative`, `Normal` and `Aggressive`. `Normal` is the default and preserves the intended balance for upgrades.
- Exact system/user-dictionary source matches continue to protect valid text from false corrections.
- Context is limited to at most two immediately previous completed words, remains RAM-only, and is cleared on relevant focus/process/control changes and Undo.
- Native selected-text conversion for supported Win32 Edit/RichEdit controls; default hotkey `Ctrl+Shift+F9`.
- Selected-text conversion uses the physical Russian/English keyboard mapping directly and does not use or modify the clipboard.
- Selected-text conversion has one-shot `Ctrl+Backspace` Undo and restores the source layout.
- Password, PIN, OTP and credential/secure input controls are excluded from automatic correction, manual conversion, selected-text conversion and Undo-related text processing. Input itself remains fail-open: G-switcher simply passes the user's original keystrokes through.
- Configurable manual-current-word hotkey; default `Ctrl+Shift+F12`.
- Manual conversion of the immediately previous completed word; default `Ctrl+Shift+F10`.
- Configurable undo hotkey; default `Ctrl+Backspace`, including restoration of the previous layout.
- Pause/Resume from the tray or configurable hotkey; default `Ctrl+Shift+F11`. Pause is intentionally reset at each application start.
- Per-application modes by executable basename: `Auto`, `Manual only`, and `Disabled`.
- Native Settings process picker enumerates running processes plus already configured applications. `Auto`, `Только вручную`, and `Отключить` buttons manage the mode without typing an EXE name manually.
- Settings expose sensitivity and all hotkeys, including selected-text conversion.
- Disabled and Manual-only application lists are shown read-only as the resulting policy state.
- Live tray tooltip shows `Auto`, `Manual`, `Disabled` or `Пауза`, plus current process/layout and the latest correction/undo when applicable.
- Local user dictionary for explicitly added words; typed history is not recorded.
- Preserves Space, Enter, Tab and supported punctuation.
- Context-aware OEM punctuation keeps cases such as `rjhj,rf` → `коробка` and `cdj,jle` → `свободу` correctable.
- Editable input state with Backspace recovery.
- Explicit target layout selection for the focused input control.
- Code-safe mode for commands, URLs, paths, identifiers, hashes and similar technical text.
- Standard-user operation with fail-open input behavior.
- Single-instance protection.
- Local per-user settings and autostart.
- First-run window with the G-on-shield graphic, examples and undo hint.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory. Version 1.0.0 retains the current candidate token, at most one previous token for manual previous-word conversion, and at most two completed context words in RAM. These values are cleared on relevant context changes and are never persisted or transmitted.

Selected text is read only when the user invokes the selected-text hotkey, only from the currently focused supported Win32 text control, and only for the duration required to replace that selection. The clipboard is not used. Secure/password/PIN/OTP/credential fields are excluded from G-switcher processing.

Persisted data is limited to explicit user configuration: automatic-correction state, sensitivity profile, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state, typed candidate text, previous-token text, contextual words and selected text are not persisted.

## Release assurance

The Windows CI gate runs formatting, unit tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The Win32 E2E covers automatic correction and Undo, Pause, Manual-only/Disabled modes, selected-text conversion and Undo, and password EDIT protection. The built EXE is then checked for Windows GUI subsystem, G-switcher 1.0.0 version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
