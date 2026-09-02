# G-switcher 0.6 development plan

The 0.6 implementation is split into reviewable gates so that each layer remains independently testable on Windows CI.

## PR 1 — Core decision engine

- Physical RU/EN key mapping independent of the user's manual layout shortcut.
- Conservative source-language protection.
- Code-safe token classification.
- Editable candidate state with reversible Backspace handling.
- Undo record state machine.
- Regression tests for known layout and false-positive cases.

## PR 2 — Windows runtime

- Low-level keyboard hook.
- Focused-control discovery.
- Explicit RU/EN HKL selection and confirmation.
- Physical-key correction injection with fail-open handling.
- Single-instance, tray, first-run and per-user autostart.

## PR 3 — Windows end-to-end release gate

- Real Win32 edit control.
- Real hook → detector → HKL → SendInput path.
- Space/Enter/Tab/punctuation matrix.
- Code-safe and Undo scenarios.
- Release artifact and PE checks.

A production 0.6.0 release is created only after all three gates are green on Windows CI.
