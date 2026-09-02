# G-switcher security model

G-switcher is designed as a small local desktop utility with a deliberately narrow trust boundary.

- No network activity is required for runtime operation.
- No typed candidate is persisted by the normal runtime.
- Configuration is stored per user.
- Normal operation does not request elevation.
- Input injection failures are fail-open for the user's original keystroke.
- The production binary is built on a Windows CI runner from the reviewed Rust source tree.
- Release artifacts include hashes and are intended to be code-signed in a separate protected release step.
- CI receives read-only repository contents unless a specific release job requires otherwise.
