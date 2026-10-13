# G-switcher 2.0.1 release plan

The 2.0 line is based strictly on the reviewed 1.0.10 source. Version 2.0.1 keeps the detector thresholds, generated frequency data, collision handling and established Win32 regressions from 2.0.0 and concentrates on safety, cross-process correctness and release assurance.

## Gate 1 — Context and mutation safety

- Bind pending correction and Undo state to a context generation.
- Re-check focus HWND, process, UI thread, keyboard layout and exact caret/selection state before mutation.
- Fail open when context is stale rather than modifying a new field/window.
- Use verified text adapters only; no clipboard fallback and no raw mutation fallback when adapter availability is lost.
- Keep loss-aware partial `SendInput` delivery and zero-progress fail-open behavior for paths that still use `SendInput`.

## Gate 2 — Hook/runtime isolation

- Run low-level keyboard and mouse hooks on a dedicated hook thread.
- Keep detector scoring, UI Automation and mutation outside hook callbacks.
- Record callback/dropped-event metrics.
- Require a 100,000-callback stress gate and verify the hook still receives events afterward.

## Gate 3 — Secure input and cross-process adapters

- Keep native password/credential protections.
- Add metadata-only UI Automation `IsPassword` verification without reading text-bearing properties for the secure-input decision.
- Use bounded marshalled messages for plain Win32 `Edit`.
- Use UI Automation TextPattern plus verified range-local replacement for supported RichEdit.
- Add bounded target-liveness preflight so hung/closing/disappearing targets fail open.

## Gate 4 — Failure-path E2E

- Exercise a separate-process `Edit`, `RICHEDIT50W` and password fixture.
- Verify automatic correction, manual current word, selected text, Undo and focus-race behavior where claimed.
- Deliberately hang the target UI thread and prove mutation returns within a bounded timeout with original text unchanged.
- Terminate the target process during a verified mutation attempt and prove fail-open behavior.
- Verify a fresh target remains usable after both failures.

## Gate 5 — Code-safe and regression assurance

- Preserve the 2.0.0 detector thresholds and generated frequency layer.
- Keep digits and technical separators in the runtime candidate long enough for Code-safe classification.
- Retain existing article, ten-corpus, War and Peace, OEM punctuation, false-positive, hotkey, sound and settings regressions.

## Gate 6 — Release and documentation

- Commit the dependency lockfile and run Cargo resolution/build commands with `--locked`.
- Keep normalization/hardening CI read-only and reproducible.
- Run formatting, unit/integration tests, same-process E2E, cross-process E2E, failure-path E2E, Clippy with warnings denied and optimized release build.
- Verify GUI subsystem, dynamic 2.0.1 version metadata, branding policy and checksums.
- Produce a standalone EXE and Windows x64 ZIP with SHA-256 sidecars.
- Include README, changelog, `RELEASE_NOTES_2.0.1.md`, `COMPATIBILITY_2.0.1.md` and third-party attribution in the package.
- Smoke-test `scripts/manual-compatibility-v201.ps1 -ScaffoldOnly` in Windows CI.

## Gate 7 — Manual application compatibility

Before public promotion, complete `COMPATIBILITY_2.0.1.md` for:

- Notepad
- Microsoft Word
- Microsoft Edge
- Google Chrome
- Telegram Desktop
- Visual Studio Code
- Windows Terminal

Record exact application versions and Windows build. Check Auto, Manual current word, Selected text, Undo, focus/caret invalidation, Pause/application modes and password/sensitive-field behavior where available. Unsupported controls are recorded as `UNSUPPORTED/FAIL-OPEN`, not as `PASS`.

The PR remains Draft until this manual matrix is complete and the final release review is finished. The EXE remains unsigned until an Authenticode certificate or trusted signing service is configured; SHA-256 verification is mandatory for the unsigned artifact.
