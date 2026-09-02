# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 0.9 strengthens automatic detection, adds volatile two-word language context, removes manual EXE typing from application-mode management, and makes the tray tooltip a live runtime-state indicator.

## 0.9 behavior

- Russian ↔ English automatic layout correction.
- Detector v2 with confidence scoring, broader known-word protection, bigram/trigram/4-gram signals, suffix/shape signals, vowel-ratio checks, rare-sequence penalties, consonant-run penalties and repeated-letter penalties.
- Exact system/user-dictionary source matches always win over contextual heuristics.
- Unknown three-letter candidates require a strong contextual signal before automatic correction.
- Volatile context from at most two immediately previous completed words can strengthen an already plausible target-language candidate.
- Context is cleared on focus/process changes, Pause, control-key context changes and Undo; it is never written to disk.
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
- Native Settings process picker enumerates running processes plus already configured applications. `Auto`, `Только вручную`, and `Отключить` buttons manage the mode without typing an EXE name manually.
- Disabled and Manual-only application lists are shown read-only as the resulting policy state.
- Live tray tooltip shows `Auto`, `Manual`, `Disabled` or `Пауза`, plus current process/layout and the latest correction/undo when applicable.
- Local user dictionary for explicitly added words; typed history is not recorded.
- Standard-user operation with fail-open input behavior.
- Single-instance protection.
- Local per-user settings and autostart.
- First-run window with the G-on-shield graphic, examples and undo hint.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory. Version 0.9 retains the current token, at most one previous token for manual previous-word conversion, and at most two completed context words in RAM. Context and previous-token state are cleared on relevant context changes and are never persisted or transmitted.

Persisted data is limited to explicit user configuration: automatic-correction state, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state, typed candidate text, previous-token text and contextual words are not persisted.

## Release assurance

The Windows CI gate runs formatting, unit tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The built EXE is then checked for Windows GUI subsystem, G-switcher version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
