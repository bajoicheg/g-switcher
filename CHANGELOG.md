# Changelog

## 0.6.0 — 2026-09-02

- Delivers the fresh-root Rust implementation of G-switcher for Windows.
- Adds conservative Russian ↔ English wrong-layout correction with explicit focused-control HKL switching.
- Preserves Space, Enter, Tab and supported punctuation, including the `rjhj,rf` → `коробка` OEM-key case.
- Protects known false positives and technical/code-like tokens from automatic rewriting.
- Supports editable candidate state, Backspace recovery and one-shot Ctrl+Backspace undo with source-layout restoration.
- Adds single-instance protection, first-run UI, per-user autostart and tray controls.
- Uses the G-on-shield application/tray icon and G-switcher Windows version metadata.
- Adds a real Win32 `WH_KEYBOARD_LL` → detector → HKL → `SendInput` → EDIT end-to-end release gate.
- Adds final release checks for GUI subsystem, Windows metadata, legacy-brand residue and SHA-256 generation.
- Publishes the checked Windows x64 EXE and SHA-256 file as a CI artifact.

## 0.6.0-rc2

- Starts the new G-switcher repository root.
- Establishes a specification-first Rust production line.
- Carries forward the validated product behavior as acceptance requirements.
- Keeps the existing G-on-shield visual assets unchanged.
- Makes Windows CI the production build environment.
- Adds the first pure-Rust 0.6 core implementation: physical RU/EN mapping, conservative detection, code-safe classification, editable candidate state and transient Undo state.
- Adds regression tests for known layout corrections, false positives, technical tokens, Backspace recovery and Undo invalidation.
