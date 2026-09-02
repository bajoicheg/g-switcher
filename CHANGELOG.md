# Changelog

## 0.8.1 — 2026-09-02

- Fixes the first-run window being visually clipped at the bottom on Windows display scaling/DPI configurations.
- Sizes the outer Win32 window from an explicit 680×500 client area with `AdjustWindowRectEx`, so the title bar and frame no longer consume space reserved for controls.
- Simplifies the first-run composition: smaller shield/title block, shorter correction and undo copy, a direct Settings hint, aligned footer row, and deliberate bottom padding.
- Keeps the existing one-click `OK`, autostart-default, local-only privacy wording, and G-on-shield branding.
- Updates package/Windows metadata, release checks, CI artifact naming, and gated release automation to 0.8.1.

## 0.8.0 — 2026-09-02

- Adds configurable local hotkeys for current-token conversion, previous-token conversion, undo, and Pause/Resume.
- Adds ephemeral Pause/Resume from the tray or hotkey; pause state is intentionally not persisted across application restarts.
- Replaces the single exclusion list with per-application modes: `Auto`, `Manual only`, and `Disabled`; existing 0.7 exclusions migrate to `Disabled`.
- Adds manual conversion of the immediately previous completed token after Space, Enter, Tab, or supported punctuation.
- Keeps only one previous token in volatile process memory and clears it on context changes; no typed-history persistence is introduced.
- Expands Settings UI for application modes and hotkey editing with validation.
- Preserves user dictionary, confidence scoring, fail-open input behavior, and undo with source-layout restoration.
- Updates package/Windows metadata, release checks, CI artifact naming, and gated release automation to 0.8.0.

## 0.7.0 — 2026-09-02

- Adds per-application exclusions by executable name; excluded applications receive no automatic analysis or replacement.
- Adds `Ctrl+Shift+F12` manual conversion for the current in-progress token, independent of automatic detector confidence.
- Adds confidence-scored RU/EN detection with dictionary, n-gram, morphology-style suffix and shape signals while preserving the conservative no-change bias.
- Adds a local per-user dictionary: explicitly added words protect valid source words and can raise a matching opposite-layout candidate to 100% confidence.
- Adds a native Settings window reachable from the tray for automatic correction, autostart, application exclusions and user dictionary management.
- Keeps typed candidate text volatile-only; only explicit settings, executable names and explicitly entered dictionary words are persisted.
- Preserves `Ctrl+Backspace` undo for both automatic and manual conversions.
- Updates Windows version metadata, release checks and CI artifacts to 0.7.0.

## 0.6.1 — 2026-09-02

- Fixes `cdj,jle` → `свободу` and adds regressions for the internal OEM-comma key used as Russian `б`.
- Expands common `свобод-*` Russian word forms while preserving the conservative no-change bias for ambiguous tokens.
- Redesigns the first-run window with a larger G-on-shield image, unified neutral gray background, Segoe UI hierarchy and cleaner spacing.
- Adds visible examples for wrong-layout correction and an explicit `Ctrl+Backspace` instruction for reverting the latest automatic replacement and restoring the prior layout.
- Keeps per-user autostart enabled by default on first run.

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
