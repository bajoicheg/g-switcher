# G-switcher 2.0.1 — release notes

2.0.1 is a safety and cross-process input hardening release. It does not change the core RU/EN detector thresholds inherited by the 2.0 line.

- Moves low-level keyboard/mouse hooks to a dedicated hook thread and keeps heavy correction work outside the callback.
- Adds generation-bound focus/process/thread/layout/caret/range checks so stale pending corrections and Undo operations fail open instead of modifying a new context.
- Uses verified, bounded text adapters for Win32 `Edit` and supported RichEdit controls; range replacement is checked before and after mutation and does not use the clipboard.
- Adds a verified modern-control UIA adapter for Chromium/WebView2/Electron-style editable controls: UIA `TextPattern` binds exact caret/selection state and writable `ValuePattern` performs a fully verified value update. Password, read-only and unverifiable controls remain untouched.
- Adds native secure-input checks plus metadata-only UI Automation `IsPassword` verification; protected or unverified controls are left unchanged.
- Adds bounded target-liveness preflights so hung, closing or disappearing text targets fail open before mutation/UIA paths.
- Strengthens Code-safe handling for technical tokens that include digits and common separators without changing detector thresholds.
- Adds mandatory same-process and separate-process Windows E2E coverage for automatic correction, manual conversion, selected text, Undo, password fields, focus races and RichEdit selection.
- Adds a 100,000-callback stress release gate with zero dropped-event requirement and a 10 ms callback latency gate.
- Adds controlled failure-path E2E that hangs a target UI thread and terminates a target process during a verified mutation attempt; both must return without changing text, and a fresh target must remain usable afterward.
- Keeps CI read-only: normalization is checked for reproducibility and may not rewrite or push the release branch.
- Publishes a checked Windows x64 EXE/ZIP with SHA-256 sidecars only after automated gates and the committed manual compatibility matrix pass.

Edge and Chrome ordinary editable fields are part of the intended 2.0.1 support claim. A safe no-op there is a useful safety fallback but **not** a successful compatibility result; Auto, Manual, Selected text and Undo must be validated as working before public promotion.

The publication workflow validates `COMPATIBILITY_2.0.1.md` on the exact release commit before creating `v2.0.1`. Every required application row must contain a concrete version and Windows build, and each behavior result must satisfy the support claim; `PENDING`, `UNKNOWN`, blank values, and `FAIL` block publication.

The release artifact is not Authenticode-signed. Verify the attached SHA-256 before use.
