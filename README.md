# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 0.8 extends the Rust implementation with configurable hotkeys, temporary Pause/Resume, per-application operating modes and previous-word manual conversion.

## 0.8 behavior

- Russian ↔ English automatic layout correction.
- Confidence-scored detector with a conservative default threshold.
- Preserves Space, Enter, Tab and supported punctuation.
- Context-aware OEM punctuation so tokens such as `rjhj,rf` → `коробка` and `cdj,jle` → `свободу` remain correctable.
- Editable input state with Backspace recovery.
- Explicit target layout selection for the focused input control.
- Code-safe mode for commands, URLs, paths, identifiers, hashes and similar technical text.
- Configurable manual-current-word hotkey; default `Ctrl+Shift+F12`.
- Manual conversion of the immediately previous completed word; default `Ctrl+Shift+F10`.
- Configurable undo hotkey; default `Ctrl+Backspace`, including restoration of the previous layout.
- Pause/Resume from the tray or configurable hotkey; default `Ctrl+Shift+F11`. Pause is intentionally reset at each application start.
- Per-application modes by executable basename: `Auto`, `Manual only`, and `Disabled`.
- Native Settings window for automatic correction, autostart, app modes, user dictionary and hotkeys.
- Local user dictionary for explicitly added words; typed history is not recorded.
- Standard-user operation with fail-open input behavior.
- Single-instance protection.
- Local per-user settings and autostart.
- First-run window with the G-on-shield graphic, examples and undo hint.
- Tray UI using the same G-on-shield artwork.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory for the current token. Version 0.8 can additionally retain exactly one immediately previous completed token in RAM so the user can manually convert it after a delimiter. That previous-token state is cleared on context changes and is never written to disk.

Persisted data is limited to explicit user configuration: automatic-correction state, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state and typed candidate/previous-token text are not persisted.

## Release assurance

The Windows CI gate runs formatting, unit tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The built EXE is then checked for Windows GUI subsystem, G-switcher version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
