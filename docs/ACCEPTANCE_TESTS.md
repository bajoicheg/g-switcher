# G-switcher 1.0.6 acceptance tests

The Windows release gate must test the full path from keyboard hook through focused-control layout selection and text replacement in a real Win32 edit control.

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

## Selected-text conversion

Default action: `Ctrl+Shift+F9`.

On a supported focused native Edit/RichEdit control:

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

For a native `EDIT` control with password state and for recognized credential/PIN/OTP/secure targets:

- `ghbdtn ` remains exactly `ghbdtn `
- no automatic correction occurs
- current-word manual conversion does nothing
- previous-word manual conversion does nothing
- selected-text conversion does nothing
- Undo-related text replacement does not operate on the secure field
- transient candidate/context/previous/Undo state is cleared on entry
- original user input is passed through unchanged
- protection applies in Auto and Manual-only modes and for all sensitivity profiles

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
- entering Pause clears candidate, previous-token, context, Undo and pending correction/selection state
- resuming does not resurrect pre-pause state
- restarting G-switcher always starts active

## User dictionary

- explicitly entered words survive restart as per-user configuration
- duplicate entries are normalized
- normal typing never learns persistent dictionary words
- a correct dictionary word is protected from automatic rewriting
- an opposite-layout candidate mapping exactly to a dictionary word receives maximum confidence

## Settings UI

- Settings is reachable from the tray menu
- automatic correction can be enabled or disabled
- sensitivity profile can be selected
- autostart can be enabled or disabled
- application mode is managed through the process picker
- user-dictionary words can be edited as one entry per line
- all five action hotkeys can be edited
- Save updates the running process without elevation
- Cancel/close does not persist edits
- UI states that detector context is volatile
- UI states that password/PIN/OTP/secure input is not processed
- visible Settings version is `1.0.4`

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

## Release gate

A releasable `v1.0.4` requires one successful Windows CI run on merged `main` containing:

- `cargo fmt --all -- --check`
- all unit/integration tests, including the 13 article-corpus regressions
- ignored real Win32 hook-to-EDIT E2E with automatic correction, article-derived cases, Undo, Pause, Manual-only, Disabled, selected-text conversion/Undo and password EDIT protection
- `cargo clippy --all-targets -- -D warnings`
- optimized `g-switcher.exe` build
- Windows GUI subsystem and `1.0.4` branding/version checks
- generated SHA-256 sidecar
- uploaded artifact named `g-switcher-1.0.4-windows-x64`

Only that successful `main` push artifact may be used by the `v1.0.4` release workflow.
