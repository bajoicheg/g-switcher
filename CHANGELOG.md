# Changelog

## 2.0.1 - 2026-09-09

- Hardens pending correction and Undo with generation-bound focus/process/thread/layout/caret/range validation so stale operations fail open instead of modifying a new context.
- Moves low-level keyboard and mouse hooks to a dedicated hook thread and keeps detector scoring, UI Automation and mutation work outside the callback.
- Adds verified cross-process text adapters: bounded marshalled messages for plain Win32 `Edit` and UI Automation TextPattern plus range-local verified replacement for supported RichEdit controls; clipboard fallback remains absent.
- Extends secure-input protection with metadata-only UI Automation `IsPassword` checks while continuing to exclude native password and credential targets from automatic/manual/selection/Undo mutation.
- Adds bounded liveness preflights for text adapters so hung, closing or disappearing targets fail open rather than entering unbounded or guessed mutation paths.
- Strengthens Code-safe runtime tracking for technical sequences containing digits and common separators without changing the 2.0.0 detector thresholds or generated frequency layer.
- Adds mandatory separate-process E2E for Edit/RichEdit/password controls, focus-race invalidation and a 100,000-callback stress gate with dropped-event/latency assertions.
- Adds a dedicated failure-path E2E that deliberately hangs a target UI thread and terminates a target process during mutation; both cases must leave text unchanged and a fresh target must remain usable afterward.
- Adds a guided `scripts/manual-compatibility-v201.ps1` recorder and keeps the public release blocked until the real-application matrix for Notepad, Word, Edge, Chrome, Telegram Desktop, VS Code and Windows Terminal is completed.
- Updates README, functional specification, acceptance tests, security model and release plan for the 2.0.1 safety contract. The checked ZIP includes 2.0.1 release notes and compatibility matrix in addition to the normal documentation and SHA-256 sidecars.

## 2.0.0 - 2026-09-05

- Starts the 2.0 public-release line strictly from the reviewed 1.0.10 source and preserves its detector thresholds, generated frequency layer, collision policy and Win32 E2E regressions.
- Adds a short in-memory PCM correction signal after confirmed successful token and selected-text conversions. Sound is enabled by default at 20%, with an on/off checkbox and 0–100% amplitude control on first launch and in Settings.
- Keeps failed/refused corrections, secure native input, Pause and Undo silent.
- Redesigns Settings from a 900×855 to a 900×680 client area and centers both dialogs inside the Windows work area for practical 1366×768 use.
- Rejects duplicate hotkeys across actions and displays GUI-subsystem startup failures in a native Windows dialog.
- Makes Windows version resources and the release gate derive their expected value from the Cargo package version, removing duplicated version literals.
- Commits the CI-generated dependency lockfile and enforces `--locked` across tests, Clippy and release builds.
- Adds waveform, sound-default and duplicate-hotkey regressions.
- Publishes both a standalone EXE and a verified ZIP with SHA-256 sidecars; the ZIP includes README, changelog and third-party data attribution.

## 1.0.10 - 2026-09-04

- Adds a reproducible generated RU/EN surface-form frequency layer from OpenSubtitles2018 data pinned to a specific source commit, with CC BY 3.0 attribution recorded in `THIRD_PARTY_DATA.md`.
- Embeds 28,235 Russian and 27,801 English 4+ letter source-protection forms (56,036 total) and deterministically promotes 26,990 frequent wrong-layout target forms under the existing confidence thresholds.
- Deliberately excludes generated three-letter forms and generated prefixes shorter than four letters after safety regressions showed that short forms such as `vbh`/`мир` require context.
- Defines precedence as explicit source > curated source > curated target > generated source/target, preserving established corrections such as `cath` → `сфер` while explicit English `here` remains fail-open.
- Keeps nine generated cross-layout collisions fail-open and adds exhaustive regression coverage across every embedded generated source form and every promoted target form.
- Extends real Win32 hook-to-EDIT E2E with representative everyday forms including `знаешь`, `домой`, `машина`, `wanted` and `looking`, while retaining the exact `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет ` gate.
- Runtime remains fully local-only: the generator is development-time tooling and no frequency data is downloaded during normal application operation.

## 1.0.9 - 2026-09-04

- Restores basic everyday Russian vocabulary missing from the curated detector model, including `мама`, `мыла`, `раму` and closely related forms, without lowering global confidence thresholds.
- Adds permanent unit and real Win32 E2E gates for `Vfvf` → `Мама`, `vskf` → `мыла`, `hfve` → `раму`, and the exact sequence `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет `.
- Preserves all 1.0.8 UI/autostart fixes and previous mixed-language/collision safety behavior.

## 1.0.8 - 2026-09-04

- Fixes first-run text overlap by replacing the fragile split description/privacy controls with four explicit bounded lines in one control.
- Makes the first-run autostart choice authoritative in both directions: unchecked now removes an existing `HKCU\...\Run` entry instead of silently preserving it.
- Initializes the first-run autostart checkbox from the actual Windows Run state, matching Settings.
- Removes stale hard-coded Settings version text; first-run/Settings UI version labels now come from `CARGO_PKG_VERSION`.
- Restores the G-switcher application icon in the Settings title bar and tightens the privacy subtitle wording.
- Detector/runtime behavior from 1.0.7 is otherwise unchanged.

## 1.0.7 — 2026-09-04

- Audits Detector v3 against the exact novel body of Leo Tolstoy's `War and Peace` from the official Tolstoy.ru DOCX: 342,237 eligible Russian word occurrences and 11,594 eligible Latin-layout occurrences after documented short/ALL-CAPS exclusions.
- Raises automatic RU→EN wrong-layout restoration on the full novel to 340,059/342,237 (99.3636%) while preserving 342,237/342,237 correct Russian occurrences and 11,594/11,594 correct Latin-layout occurrences with zero false automatic corrections in the corpus.
- Scopes opposite-target prefix holding to the punctuation/OEM input path. True Space/Enter/Tab word boundaries no longer suppress complete words such as `gmth` → `пьер`, while internal OEM sequences still preserve `rjhj,rf` → `коробка` and `rjhj,jxrf.` → `коробочка.`.
- Adds explicit source protection for Russian forms and common French/German/Latin-layout words observed in the mixed-language novel; valid-source collisions such as `here`/`her` remain fail-open instead of being forced to `руку`/`рук`.
- Adds permanent detector regressions and real Win32 boundary E2E coverage for `пьер`, while retaining existing OEM, collision, secure-input, Undo and application-mode gates.
- Removes the Tolstoy.ru download and full-novel audit tooling from the production branch; normal runtime remains local-only with no network or telemetry behavior.
- Updates package, Windows/UI metadata, CI artifact naming, release checks and gated release automation to 1.0.7.

## 1.0.6 — 2026-09-04

- Audits Detector v3 against ten additional large Russian Wikipedia articles: `Земля`, `Человек`, `Европа`, `СССР`, `Российская империя`, `Первая мировая война`, `Солнечная система`, `Компьютер`, `Математика` and `Физика`. The normalized corpus contains 31,738 unique testable Russian word forms.
- Improves automatic restoration on that corpus from 31,658/31,738 (99.7479%) in 1.0.5 to 31,716/31,738 (99.9307%). The remaining 22 occurrences / 19 unique forms are intentionally fail-open because they collide with valid English tokens or are ambiguous three-character sequences.
- Adds 55 safe corpus-derived Russian target forms without lowering global confidence thresholds.
- Adds source-language protections for `dyer`, `ytd`, `cnf`, `lev` and `ren`, while preserving the existing `keys` protection.
- Adds permanent regression coverage for all 55 safe forms and the 19 intentional KEEP forms, plus real Win32 hook-to-EDIT E2E for `математика`, `европа`, `физика` and English `dyer`/`ytd`/`cnf`.
- Keeps Wikipedia retrieval and corpus processing strictly in temporary QA automation; normal G-switcher runtime remains local-only with no network or telemetry behavior.
- Updates package, Windows/UI metadata, CI artifact naming, release checks and gated release automation to 1.0.6.

## 1.0.5 — 2026-09-04

- Audits Detector v3 against five large Russian Wikipedia articles: `Россия`, `Москва`, `Вторая мировая война`, `Интернет` and `Вселенная`. After normalization and intentional ALL-CAPS/code-safe exclusions, the corpus contains 23,336 unique testable Russian word forms.
- Improves automatic restoration from 23,105/23,336 (99.0101%) to 23,332/23,336 (99.9829%). The remaining four occurrences are deliberate source-language protections: `луны` maps to valid English `keys` three times and `рук` maps to valid English `her` once.
- Adds 151 corpus-derived regression forms, including final gaps `нефти`, `наук` and `сфер`, without lowering global confidence thresholds.
- Adds a narrow OEM-only detector fallback for known Russian targets while arbitrary punctuation remains fail-open.
- Adds real Win32 hook-to-EDIT E2E coverage for the OEM-only `жэхэ` case and anti-regressions preserving valid English `keys` and `her`.
- Updates package/Windows/UI metadata, release checks, CI artifact naming, documentation and gated release automation to 1.0.5.

## 1.0.4 — 2026-09-03

- Audits Detector v3 against a synthetic RU→EN wrong-layout corpus derived from a long Russian information-security article: 1,566 unique Russian word forms, with 13 residual misses isolated under Normal sensitivity and two-word Russian context.
- Adds the common forms `политик`, `систем`, `спрос`, `программ`, `лиц`, `дел`, `правил`, `команд`, `виде`, `работ`, `инструкции`, `важны` and `норм` to deterministic local Russian target recognition.
- Locks all 13 article-derived wrong-layout forms in integration regression coverage and adds real Win32 hook→EDIT E2E cases for `cbcntv` → `систем`, `ghjuhfvv` → `программ` and `bycnherwbb` → `инструкции`.
- Preserves the 1.0.3 loss-aware partial `SendInput` delivery fix and OEM-prefix behavior for `rjhj,rf` → `коробка`, `rjhj,jxrf.` → `коробочка.`, `cdj,jle` → `свободу` and `,kz` → `бля`.
- Updates package/Windows/UI metadata, release checks, CI artifact naming, documentation and gated release automation to 1.0.4.

## 1.0.3 — 2026-09-03

- Fixes destructive truncation when Windows accepts only part of a correction `SendInput` batch: delivery now resumes from the first unsent INPUT with bounded retry instead of abandoning already-started Backspace/retype sequences.
- Keeps zero-progress injection fail-open: if the first `SendInput` call inserts nothing, the original text is left untouched.
- Adds `коробочка` to deterministic local target recognition and locks `rjhj,jxrf.` → `коробочка.` in detector and real Win32 E2E coverage.
- Adds pure regression tests for partial/zero-progress input delivery.
- Updates package/Windows metadata, release checks, CI artifact naming and gated release automation to 1.0.3.

## 1.0.2 — 2026-09-03

- Hardens the Settings layout against clipping by increasing the client area and reserving dedicated multi-line regions for sensitivity and Pause help.
- Shortens long Russian UI labels and moves footer controls down to keep spacing stable on real Windows.
- Adds more bottom room to the first-run window while preserving 1.0.1 detector/runtime behavior.
- Updates package/Windows metadata, release checks, CI artifact naming and gated release automation to 1.0.2.

## 1.0.1 — 2026-09-03

- Fixes clipping in the first-run Settings hint and restores deliberate spacing between the hint, separator, autostart row, action button, and copyright footer.
- Expands the Settings client area and increases vertical space for application-mode state and the user dictionary.
- Removes always-visible vertical scrollbars from read-only Disabled/Manual-only lists while keeping normal scrolling for the editable dictionary.
- Replaces mixed English/Russian Settings copy with clearer Russian wording where practical.
- Substantially expands built-in Russian and English common-word lexicons, including everyday, technical, colloquial, and common obscene vocabulary.
- Treats a recognized built-in frequent source word as deterministic preservation evidence and a recognized opposite-layout target as maximum-confidence correction evidence.
- Adds regressions for `truth`, `fuck`, `пизда`, `бля`, `блять`, `хуй`, `ебать`, and related vocabulary while preserving context-sensitive handling of intentionally ambiguous short words.
- Fixes OEM-prefix tracking for wrong-layout words whose Russian form begins on a physical punctuation key; the real Win32 E2E now covers `,kz ` → `бля `.
- Updates package/Windows metadata, release checks, CI artifact naming, and gated release automation to 1.0.1.

## 1.0.0 — 2026-09-02

- Adds native selected-text conversion for supported Win32 Edit/RichEdit controls without clipboard use, with one-shot Undo and source-layout restoration.
- Adds secure-input protection for password/PIN/OTP/credential controls across automatic, manual, selected-text, and Undo-related processing.
- Introduces Detector v3 with a baked-in local RU/EN frequency model and Conservative/Normal/Aggressive sensitivity profiles.
- Extends the real Win32 hook-to-EDIT E2E to selected-text conversion, secure password EDIT behavior, application modes, Pause, and manual Undo.
- Keeps typed candidates, selected text, previous-token state, and contextual words volatile-only and never persists or transmits them.
- Updates package/Windows metadata, release checks, CI artifact naming, and gated release automation to 1.0.0.

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
- Updates package/Windows metadata, release checks, CI artifact naming and gated release automation to 0.8.0.

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