# G-switcher 2.0.0 release plan

The 2.0.0 line is based strictly on the reviewed 1.0.10 source. Detector thresholds, generated frequency data, collision handling and existing Win32 regressions remain unchanged unless a failing test proves a defect.

## Gate 1 — Runtime and configuration

- Generate a short correction PCM signal entirely in memory.
- Persist sound enabled/disabled and 0–100% amplitude, defaulting to enabled at 20%.
- Play only after confirmed successful token or selected-text replacement.
- Keep failed/refused corrections, secure native input, Pause and Undo silent.

## Gate 2 — Native UI quality

- Expose sound state and volume on first launch and in Settings.
- Fit Settings in a 900×680 client area for a typical 1366×768 work area.
- Center first-run and Settings dialogs inside the desktop work area.
- Reject conflicting hotkeys before persistence.
- Present startup failures in a visible native dialog.

## Gate 3 — Release assurance

- Commit the CI-generated dependency lockfile and run all resolution/build commands with `--locked`.
- Run formatting, all unit/integration tests, Clippy with warnings denied and the ignored real Win32 hook-to-EDIT E2E.
- Verify GUI subsystem, dynamic 2.0.0 version metadata, branding policy and checksums.
- Produce a standalone EXE and a ZIP containing the identical EXE, checksum, README, changelog and third-party data attribution.
- Publish `v2.0.0` only from the successful checked `main` workflow artifact.

The EXE remains unsigned until an Authenticode certificate or trusted signing service is configured. SHA-256 verification is mandatory for the unsigned public artifact.
