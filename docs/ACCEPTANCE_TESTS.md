# G-switcher 2.0.1 acceptance tests

The Windows release gate must test the full path from keyboard hook through focused-control validation, layout selection and verified text replacement in real Win32 controls. Version 2.0.1 additionally requires separate-process, stress and failure-path coverage; automated CI success does not replace the manual real-application compatibility gate.

## Core correction

- `ghbdtn ` → `привет `
- `руддщ ` → `hello `
- `руддщ ghbdtn ` → `hello привет `
- `rjhj,rf ` → `коробка `
- `rjhj,jxrf.` → `коробочка.`
- `cdj,jle ` → `свободу `
- article-derived real Win32 regressions: `cbcntv ` → `систем `, `ghjuhfvv ` → `программ `, `bycnherwbb ` → `инструкции `
- ten-corpus real Win32 regressions: `vfntvfnbrf ` → `математика `, `tdhjgf ` → `европа `, `abpbrf ` → `физика `; valid English `dyer`, `ytd` and `cnf` remain unchanged
- Space, Enter and Tab delimiters are preserved
- immediate Undo restores original text and source layout
- simulated partial `SendInput` delivery resumes from the exact unsent INPUT tail; zero initial delivery fails without destructive progress

## Context generation and stale-state safety

- every pending correction and Undo record is tied to a context generation
- focus/process/thread/layout changes invalidate stale operations
- caret movement invalidates a pending token correction before mutation
- selection/range changes invalidate selected-text conversion and selected-text Undo
- a queued correction never modifies a newly focused field after focus changes
- a stale operation must not switch from a verified adapter to an unverified raw mutation fallback
- Pause invalidates pending correction, selection and Undo state

## Hook dispatch and stress

- low-level keyboard and mouse hooks execute on the dedicated hook thread
- detector scoring, UI Automation and text mutation do not execute inside the low-level hook callback
- the mandatory stress case delivers at least 100,000 callback events
- no stress event is dropped by runtime dispatch
- callbacks slower than 10 ms remain within the configured release-gate allowance; the current release rule requires at least 99% of callbacks at or below 10 ms
- after the 100,000-event stress sequence the hook still receives subsequent events

## Detector v3

- exact known opposite-layout words receive maximum confidence
- exact valid source-language system/user-dictionary words remain unchanged
- baked-in RU/EN frequency scoring favors common language text over keyboard-layout noise
- common n-grams improve plausibility without overriding exact source protection
- code-safe tokens do not enter confidence-based automatic correction
- typed context never exceeds two completed words and is never persisted
- opposite-language context alone cannot force a correction
- known false-positive regressions remain protected
- all 13 article-corpus forms `политик`, `систем`, `спрос`, `программ`, `лиц`, `дел`, `правил`, `команд`, `виде`, `работ`, `инструкции`, `важны`, `норм` restore from their wrong-layout forms under Normal sensitivity with two-word Russian context
- all 55 safe ten-corpus regression forms restore deterministically, while the 19 documented short/source-collision forms remain fail-open

## Sensitivity profiles

- `Conservative`, `Normal` and `Aggressive` are available in Settings
- `Normal` is the default for new and upgraded configuration without an explicit profile
- Conservative threshold is strictly higher than Normal
- Normal threshold is strictly higher than Aggressive
- changing sensitivity takes effect after Save without restart
- sensitivity never disables secure-input protection or code-safe protection

## Verified text adapters

For a separate-process plain Win32 `Edit` control:

- caret/selection state is read through the bounded message adapter
- the exact expected source range is re-verified immediately before replacement
- the resulting full control text is verified after replacement
- a failed or unexpected post-state is not accepted as success

For supported separate-process `RICHEDIT50W`:

- UI Automation TextPattern supplies selection/document state
- selected-text replacement affects only the verified range
- post-state is verified through the UIA document/range view
- selected-text Undo restores exactly the original range

For unsupported/custom controls:

- no raw mutation fallback is attempted merely because a verified adapter is unavailable
- original text is preserved

## Selected-text conversion

Default action: `Ctrl+Shift+F9`.

On a supported focused control with a verified adapter:

- selecting `ghbdtn rfr ltkf` and invoking the action produces `привет как дела`
- the target keyboard layout becomes Russian
- selecting opposite-layout Russian text converts symmetrically to English
- only the selected range is replaced
- the clipboard is unchanged
- no selection means no destructive modification
- unsupported/custom controls fail open without modifying text
- immediate `Ctrl+Backspace` restores the original selected text and source layout
- selected-text Undo is one-shot
- typing/focus changes invalidate stale selected-text Undo state conservatively

## Secure input protection

For a native `EDIT` control with password state and for recognized Windows credential/secure targets:

- `ghbdtn ` remains exactly `ghbdtn `
- no automatic correction occurs
- current-word manual conversion does nothing
- previous-word manual conversion does nothing
- selected-text conversion does nothing
- Undo-related text replacement does not operate on the secure field
- transient candidate/context/previous/Undo state is cleared on entry
- original user input is passed through unchanged
- protection applies in Auto and Manual-only modes and for all sensitivity profiles

For the separate-process password fixture:

- UI Automation `IsPassword` is observed as true
- no text-bearing UIA property is required to make the secure-input decision
- automatic handling does not change the field layout
- selected-text hotkey does not modify the password control or its layout

For an unverified non-plain control, secure-state uncertainty is fail-open: no mutation is allowed.

## Hung and closing target failure paths

The mandatory separate-process failure harness must cover both cases below.

Hung target:

- the helper UI thread is deliberately blocked
- the target becomes unresponsive to a bounded `WM_NULL` liveness probe
- a verified range replacement attempt returns false within the bounded gate timeout
- the original text remains unchanged after the target UI thread recovers

Closing/disappearing target:

- the target process is terminated while a verified mutation attempt is pending
- the operation returns false within the bounded gate timeout
- no other/newly focused control is modified

Recovery:

- after the hung and closing-target failures, a fresh separate-process `Edit` control still accepts a normal verified replacement
- failure handling must not poison global adapter/runtime state

## Configurable hotkeys

Default actions are:

- selected text: `Ctrl+Shift+F9`
- current word: `Ctrl+Shift+F12`
- previous word: `Ctrl+Shift+F10`
- undo: `Ctrl+Backspace`
- Pause/Resume: `Ctrl+Shift+F11`

Acceptance requirements:

- each action can be reassigned to another supported modifier/key combination
- changes take effect without restart
- malformed combinations are rejected by Settings
- a combination already assigned to another action is rejected by Settings
- matching requires the configured modifier set rather than a prefix/superset match
- queued manual correction must not synthetically re-press Ctrl/Shift/Alt after the user has already released those modifiers
- immediate Undo after previous-word manual conversion must work even when the queued correction executes after hotkey key-up events

## Current-word manual conversion

- with an in-progress `ghbdtn` token in English layout, the configured current-word hotkey converts it to `привет` without inserting a delimiter
- manual conversion operates even when the automatic detector would keep an ambiguous token
- manual conversion switches the focused control to the target layout
- immediate configured Undo restores the original token and source layout
- current-word conversion is available in `Auto` and `Manual only`, but not `Disabled`, Pause or secure input

## Previous-word manual conversion

With automatic correction disabled or an intentionally uncorrected token:

- type `ghbdtn `, then invoke the configured previous-word action → `привет `
- delimiter is restored after conversion
- immediate configured Undo restores the original token, delimiter and source layout
- only the immediately previous completed token is eligible
- typing the next visible token invalidates the previous-token record
- changing focus/process context invalidates the previous-token record
- the previous token is never written to persistent configuration

## Per-application modes and process picker

- executable matching is case-insensitive
- an unlisted executable operates in `Auto`
- `Manual only` tracks tokens and permits explicit conversion but performs no automatic replacement
- `Disabled` receives original keystrokes unchanged and permits no text conversion
- entering `Disabled` clears stale candidate, previous-token, context and Undo state
- if an executable appears in both lists, `Disabled` wins
- Settings process picker includes running and previously configured process basenames
- selecting `Auto`, `Только вручную` or `Отключить` updates the resulting policy state without manual EXE typing
- saving a changed application mode takes effect without restart

## Pause / Resume

- tray contains Pause while active and Resume while paused
- configured pause hotkey toggles the same process-local state
- while paused, `ghbdtn ` remains unchanged and no explicit conversion action modifies text
- entering Pause clears candidate, previous-token, context, Undo and pending correction/selection state and invalidates the active generation
- resuming does not resurrect pre-pause state
- restarting G-switcher always starts active

## User dictionary

- explicitly entered words survive restart as per-user configuration
- duplicate entries are normalized
- normal typing never learns persistent dictionary words
- a correct dictionary word is protected from automatic rewriting
- an opposite-layout candidate mapping exactly to a dictionary word receives maximum confidence

## Correction sound

- new configuration defaults to sound enabled at 20%
- first-run and Settings each expose sound on/off and 0–100% volume in 5% steps
- a confirmed automatic correction plays one signal
- confirmed current-word, previous-word and selected-text conversions play one signal
- failed/refused corrections, Pause, secure input and Undo remain silent
- 0% produces no playback even when sound is enabled
- generated PCM has a valid RIFF/WAVE header and bounded duration
- PCM peak amplitude rises with the configured percentage and values above 100% are clamped
- playback does not change the Windows master volume and requires no external file

## Settings UI

- Settings is reachable from the tray menu
- automatic correction can be enabled or disabled
- sensitivity profile can be selected
- correction sound can be enabled/disabled and its volume selected
- autostart can be enabled or disabled
- application mode is managed through the process picker
- user-dictionary words can be edited as one entry per line
- all five action hotkeys can be edited
- Save updates the running process without elevation
- Cancel/close does not persist edits
- UI states that detector context is volatile
- UI accurately scopes secure-input wording to protected/verified controls
- Settings client area is 900×680 and all controls fit without clipping on a 1366×768 desktop work area
- first-run close does not mark onboarding complete or silently overwrite choices
- visible Settings version is `2.0.1`

## Punctuation and editing

- `ghbdtn/` → `привет/`
- `ghbdtn,` → `привет,`
- `ghbdtn.` → `привет.`
- `rjhj,rf ` → `коробка `
- `rjhj,jxrf.` → `коробочка.`
- `cdj,jle ` → `свободу `; the internal physical comma key is the Russian letter `б`, not a boundary
- punctuation is never lost when correction fails
- Backspace reconstructs the remaining candidate correctly
- deleting the entire candidate leaves an empty candidate
- caret movement invalidates stale correction state

## False-positive protection

These examples remain unchanged when typed correctly:

- `беру`
- `берут`
- `ещё`
- `еще`
- `ёлка`
- `всё`
- `моё`
- `объект`
- `подъезд`
- `hello`
- `the`
- `then`
- `json`
- `http`
- `docker`
- `linux`
- `vpn`
- `edr`
- `soc`

## Case and code-safe behavior

- `Ghbdtn ` → `Привет `
- `GHBDTN ` → `ПРИВЕТ `
- `Руддщ ` → `Hello `
- `РУДДЩ ` → `HELLO `

The following classes are not automatically rewritten:

- `HOST-SRV-01`
- `10.20.30.40`
- `10.20.0.0/16`
- `C:\Windows\System32`
- `/usr/local/bin`
- `user@example.test`
- `https://example.test/path`
- `550e8400-e29b-41d4-a716-446655440000`
- `sha256:abcdef0123456789`
- `SomeVariable42`
- `some_variable`
- `--background`

Runtime candidate tracking must preserve digits and common technical separators long enough for Code-safe classification so such tokens are not split into misleading word fragments.

## Manual compatibility gate

`COMPATIBILITY_2.0.1.md` is a release blocker until every intended application row is completed with an exact application version and Windows build.

Required applications:

- Notepad
- Microsoft Word
- Microsoft Edge
- Google Chrome
- Telegram Desktop
- Visual Studio Code
- Windows Terminal

For each writable target, test Auto, Manual current word, Selected text, Undo, caret/focus race handling, Pause/application modes and password/sensitive-field behavior where available. Unsupported controls must be recorded as `UNSUPPORTED/FAIL-OPEN`, not `PASS`. Do not use real credentials or secrets.

The repository helper `scripts/manual-compatibility-v201.ps1` may be used to detect application versions and create a local result matrix. `-ScaffoldOnly` must produce a complete PENDING matrix without user interaction; Windows CI smoke-tests this helper.

## Release gate

A releasable 2.0.1 candidate requires one successful Windows CI run on the exact release commit containing:

- read-only 2.0.1 normalization/hardening reproducibility check
- `cargo fmt --all -- --check`
- all Cargo resolution/build commands use the committed lockfile through `--locked`
- all unit/integration tests, including frequency-layer, sound-wave, settings, Code-safe and article-corpus regressions
- `scripts/manual-compatibility-v201.ps1 -ScaffoldOnly` smoke test
- ignored real same-process Win32 hook-to-EDIT E2E
- ignored separate-process Edit/RichEdit/password E2E with focus-race and 100,000-callback stress coverage
- mandatory hung/closing-target failure-path E2E
- `cargo clippy --locked --all-targets -- -D warnings`
- optimized `g-switcher.exe` build
- Windows GUI subsystem and `2.0.1` branding/version checks derived from the Cargo package version
- generated SHA-256 sidecars for standalone EXE and ZIP
- ZIP contents include README, changelog, `RELEASE_NOTES_2.0.1.md`, `COMPATIBILITY_2.0.1.md` and third-party data attribution
- uploaded artifact named `g-switcher-2.0.1-windows-x64`

Public promotion additionally requires the completed manual compatibility matrix and a final release review. Automated green CI alone is not release authorization.
