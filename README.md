# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

The 0.6 development line starts from a new repository root and a specification-first implementation. Production releases are built from Rust on Windows CI.

## 0.6 goals

- Russian ↔ English automatic layout correction.
- Preserve Space, Enter, Tab and punctuation exactly.
- Context-aware OEM punctuation so tokens such as `rjhj,rf` remain correctable.
- Editable input state with Backspace recovery.
- Explicit target layout selection for the focused input control.
- Code-safe mode for commands, URLs, paths, identifiers, hashes and similar technical text.
- Undo of the most recent automatic correction.
- Standard-user operation; elevated target windows use fail-open behavior.
- Single-instance protection.
- Local configuration and per-user autostart.
- First-run window and tray UI using the existing G-on-shield artwork.
- No network access in normal operation.

See `docs/FUNCTIONAL_SPEC.md` and `docs/ACCEPTANCE_TESTS.md`.
