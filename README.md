# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 0.6 is a fresh-root Rust implementation built and tested on Windows CI.

## 0.6 behavior

- Russian ↔ English automatic layout correction.
- Preserves Space, Enter, Tab and supported punctuation.
- Context-aware OEM punctuation so tokens such as `rjhj,rf` → `коробка` and `cdj,jle` → `свободу` remain correctable.
- Editable input state with Backspace recovery.
- Explicit target layout selection for the focused input control.
- Code-safe mode for commands, URLs, paths, identifiers, hashes and similar technical text.
- Ctrl+Backspace undo of the most recent automatic correction, including restoration of the previous layout.
- Standard-user operation with fail-open input behavior.
- Single-instance protection.
- Local per-user settings and autostart.
- First-run window with a large G-on-shield graphic, unified neutral gray background, examples and a visible undo hint.
- Tray UI using the same G-on-shield artwork.
- No network access in normal runtime operation.

## Release assurance

The Windows CI gate runs formatting, unit tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The built EXE is then checked for Windows GUI subsystem, G-switcher version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
