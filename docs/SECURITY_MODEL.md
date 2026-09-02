# G-switcher security model

G-switcher is designed as a small local desktop utility with a deliberately narrow trust boundary.

- No network activity is required for runtime operation.
- Current candidate text is never persisted by the normal runtime.
- Version 0.8 may retain exactly one immediately previous completed token in process memory for previous-word manual conversion; it is never written to disk and is cleared when context becomes stale.
- Pause state is process-local, clears transient correction state, and is never persisted.
- Configuration is stored per user.
- Persisted configuration is limited to explicit choices: automatic-correction state, Disabled/Manual-only executable basenames, explicit user-dictionary words, hotkey definitions and autostart state.
- The user dictionary is never learned automatically from typing.
- Per-application modes are matched locally against the focused process executable basename.
- `Manual only` disables automatic replacement while preserving explicit manual actions; `Disabled` performs neither automatic nor manual conversion.
- Existing 0.7 exclusions migrate locally to the `Disabled` mode.
- Normal operation does not request elevation.
- Input injection failures are fail-open for the user's original keystroke where Windows permits safe recovery.
- Automatic and manual conversion use the same focused-control, layout-switch and integrity boundaries.
- Hotkeys are matched locally and no global online service is involved.
- The production binary is built on a Windows CI runner from the reviewed Rust source tree.
- Release artifacts include hashes and are intended to be code-signed in a separate protected release step.
- CI receives read-only repository contents unless a specific release job requires release publication rights.
