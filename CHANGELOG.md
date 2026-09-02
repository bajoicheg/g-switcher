# Changelog

## 0.9.0 — 2026-09-02

- Introduces Detector v2 with broader RU/EN word protection, richer bigram/trigram/4-gram scoring, suffix/shape signals, vowel-ratio checks, rare-sequence penalties, consonant-run penalties and repeated-letter penalties.
- Makes unknown three-letter automatic corrections context-dependent while preserving immediate 100% confidence for exact opposite-layout dictionary matches.
- Adds a volatile contextual detector using at most two immediately previous completed words; context can strengthen an already plausible candidate but cannot override an exact source dictionary or user-dictionary match.
- Clears contextual words on focus/process changes, Pause, control-key context changes and Undo; contextual text is never persisted or transmitted.
- Replaces manual EXE entry for per-application modes with a native process picker that combines running processes and previously configured applications.
- Adds direct `Auto`, `Только вручную`, and `Отключить` controls; resulting Disabled and Manual-only lists are displayed read-only.
- Adds a live tray tooltip for `Auto`, `Manual`, `Disabled` and `Пауза` states with current process/layout and the latest correction/undo where applicable.
- Preserves existing current-word/previous-word conversion, configurable hotkeys, user dictionary, code-safe behavior, fail-open input and real Win32 E2E coverage.
- Updates package/Windows metadata, release checks, CI artifact naming and gated release automation to 0.9.0.

## 0.8.2 — 2026-09-02

- Redesigns the Settings window after real Windows testing exposed overlapping labels and cramped controls.
- Sizes Settings from an explicit 900×825 client area with `AdjustWindowRectEx`, keeping controls clear of the title bar/frame across display scaling configurations.
- Introduces clear native sections for General, Application modes, User dictionary, and Hotkeys with stronger Segoe UI hierarchy and deliberate vertical spacing.
- Reworks application modes into two balanced columns with explanatory hints and dedicated editors for Disabled and Manual-only processes.
- Reworks hotkeys into a clean 2×2 grid and removes the long defaults line that previously competed with controls.
- Moves Save/Cancel into a dedicated footer area and shortens privacy/status copy to prevent wrapping collisions.
- Preserves all 0.8.1 runtime behavior, settings persistence, privacy guarantees, hotkey validation, per-app modes, and dictionary semantics.
- Updates package/Windows metadata, release checks, CI artifact naming, and gated release automation to 0.8.2.

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
