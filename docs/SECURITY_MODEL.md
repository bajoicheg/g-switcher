# G-switcher security model

G-switcher is designed as a small local desktop utility with a deliberately narrow trust boundary.

- No network activity is required for runtime operation.
- No typed candidate is persisted by the normal runtime.
- Configuration is stored per user.
- Version 0.7 persists only explicit configuration: automatic-correction state, excluded executable basenames, explicit user-dictionary words and autostart state.
- The user dictionary is never learned automatically from typing.
- Per-application exclusions are matched locally against the focused process executable basename.
- Excluded processes receive no automatic or manual conversion; input passes through unchanged.
- Normal operation does not request elevation.
- Input injection failures are fail-open for the user's original keystroke.
- Manual conversion uses the same focused-control, layout-switch and integrity boundaries as automatic conversion.
- The production binary is built on a Windows CI runner from the reviewed Rust source tree.
- Release artifacts include hashes and are intended to be code-signed in a separate protected release step.
- CI receives read-only repository contents unless a specific release job requires otherwise.
