# G-switcher acceptance tests

The Windows release gate must test the full path from keyboard hook through focused-control layout selection and input injection into a real Win32 edit control.

## Core correction

- `ghbdtn ` → `привет `
- `руддщ ` → `hello `
- `руддщ ghbdtn ` → `hello привет `
- `cdj,jle ` → `свободу `
- the same cases using Enter instead of Space
- `ghbdtn` + Tab → `привет` + Tab

## Detector v2 and confidence scoring

- an exact known opposite-layout word has confidence 100
- a valid source-language system/user-dictionary word remains unchanged regardless of a plausible opposite mapping or context
- lower-confidence heuristic candidates remain unchanged below the default threshold
- a user-dictionary target exact match receives confidence 100
- a user-dictionary source exact match is protected from automatic correction
- code-safe tokens do not enter confidence-based automatic correction
- richer n-gram/suffix/shape scoring does not regress known RU/EN corrections
- common technical English words such as `json`, `http`, `docker`, `linux`, `vpn`, `edr` and `soc` remain unchanged
- unknown three-letter candidates remain unchanged without a strong context signal

## Volatile contextual detector

- at most two immediately previous completed words participate in automatic detector context
- same-language recent context can raise an otherwise sub-threshold plausible opposite-layout candidate above the correction threshold
- an opposite-language context does not force that correction
- exact source system/user-dictionary matches are never overridden by context
- successful completed corrections can become context for the following word
- process/focus changes clear contextual words
- entering Pause clears contextual words
- unrelated Ctrl/Alt command context clears contextual words
- Undo clears contextual words conservatively
- contextual words are never written to persistent Settings or transmitted

## Configurable hotkeys

Default actions are:

- current word: `Ctrl+Shift+F12`
- previous word: `Ctrl+Shift+F10`
- undo: `Ctrl+Backspace`
- Pause/Resume: `Ctrl+Shift+F11`

Acceptance requirements:

- each action can be reassigned in Settings to another supported modifier/key combination
- the changed combination takes effect without restarting G-switcher
- a malformed combination is rejected by Settings and is not persisted
- action matching requires the configured modifier set rather than a prefix/superset match
- ordinary unrelated Ctrl/Alt shortcuts still invalidate stale transient text state

## Current-word manual conversion

- with an in-progress `ghbdtn` token in English layout, the configured current-word hotkey converts it to `привет` without inserting a delimiter
- manual conversion operates even when the automatic detector would keep an ambiguous token
- manual conversion switches the focused control to the target layout
- immediate configured Undo restores the original token and source layout
- current-word conversion is available in `Auto` and `Manual only`, but not `Disabled`

## Previous-word manual conversion

With automatic correction disabled or an intentionally uncorrected token:

- type `ghbdtn `, then invoke the configured previous-word action → `привет `
- Space is restored after conversion
- Enter, Tab and supported punctuation are restored after conversion
- immediate configured Undo restores the original token, delimiter and source layout
- only the immediately previous completed token is eligible
- typing the next visible token invalidates the previous-token record
- changing focus/process context invalidates the previous-token record
- the previous token is never written to persistent configuration

## Per-application modes and process picker

- executable matching is case-insensitive
- an unlisted executable operates in `Auto`
- `Manual only` tracks tokens and permits current/previous manual conversion but performs no automatic replacement
- `Disabled` receives original keystrokes unchanged and permits neither automatic nor manual conversion
- entering `Disabled` clears stale candidate, previous-token, context and undo state
- if an executable appears in both lists, `Disabled` wins
- a 0.7 `ExcludedApps` entry loads as `Disabled` after upgrade
- Settings process picker includes currently running process basenames
- previously configured Disabled/Manual-only processes remain selectable even when they are not currently running
- the last process observed by the runtime is preferred in the picker when available
- selecting `Auto` removes the process from both explicit mode lists
- selecting `Только вручную` moves the process to Manual-only and removes it from Disabled
- selecting `Отключить` moves the process to Disabled and removes it from Manual-only
- Disabled and Manual-only lists are read-only resulting-state views; normal mode management requires no manual EXE typing
- saving a changed application mode takes effect without restarting G-switcher

## Tray state indicator

- active automatic mode is represented as `Auto` in the tray tooltip
- Manual-only mode is represented as `Manual`
- Disabled mode is represented as `Disabled`
- Pause is represented prominently as `Пауза`
- when active, tooltip may include current process basename and RU/EN layout
- a successful correction updates the latest-operation hint to the target language
- successful Undo updates the latest-operation hint to the restored source language
- changing process clears stale latest-operation text
- tray status is process-local and is not persisted

## Pause / Resume

- tray contains a Pause action while active and a Resume action while paused
- the configured pause hotkey toggles the same process-local state
- while paused, `ghbdtn ` remains `ghbdtn ` and no manual action changes it
- entering Pause clears current candidate, previous-token, context, undo and pending-correction state
- resuming does not resurrect pre-pause transient state
- restarting G-switcher always starts active; Pause is not persisted

## User dictionary

- explicitly entered words survive restart as per-user configuration
- duplicate entries are normalized without creating duplicate records
- normal typing never adds words to the persistent dictionary
- a correct dictionary word is protected from automatic rewriting
- an opposite-layout candidate mapping exactly to a dictionary word receives maximum confidence

## Settings UI

- Settings is reachable from the tray menu
- automatic correction can be enabled or disabled
- autostart can be enabled or disabled
- application mode is managed through a process picker and direct Auto/Manual-only/Disabled actions
- Disabled and Manual-only executable lists are shown read-only
- user-dictionary words can be edited as one entry per line
- all four action hotkeys can be edited
- Save updates the running process without requiring restart or elevation
- Cancel/close does not persist edits
- the UI states that contextual detector words are kept only in volatile memory
- the UI states that Pause is temporary and not persisted

## Punctuation

- `ghbdtn/` → `привет/`
- `ghbdtn,` → `привет,`
- `ghbdtn.` → `привет.`
- `rjhj,rf ` → `коробка `
- `cdj,jle ` → `свободу `; the internal physical comma key is the Russian letter `б`, not a boundary
- `руддщ.` → `hello.`
- punctuation is never lost when correction fails

## Editing

- type `ghbdtn/`, Backspace, Space → `привет `
- multiple Backspace operations reconstruct the remaining candidate correctly
- deleting the entire candidate leaves an empty candidate
- caret movement invalidates stale correction state

## False-positive protection

These examples must remain unchanged when typed correctly:

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

## Case

- `Ghbdtn ` → `Привет `
- `GHBDTN ` → `ПРИВЕТ `
- `Руддщ ` → `Hello `
- `РУДДЩ ` → `HELLO `

## Code-safe

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

An explicit manual conversion may operate on non-Disabled text because it is user initiated; automatic code-safe protection remains conservative.

## Undo

- after `ghbdtn ` becomes `привет `, immediate configured Undo restores `ghbdtn ` and the original input locale
- current-word and previous-word manual conversion produce the same one-shot undo capability
- Undo is rejected after focus moves to another control
- Undo is rejected after unrelated text is typed

## First-run UX

- the G-on-shield artwork is prominent and substantially larger than the tray icon
- the whole client area, including text/icon areas, uses one consistent neutral gray system background
- the dialog uses Windows-native Segoe UI typography with a clear visual hierarchy
- the dialog includes short `ghbdtn → привет` and `руддщ → hello` examples
- autostart is checked by default
- the dialog stays centered on the primary display and requires only one `OK` action

## Layout matrix

- Russian + US English
- Russian + UK English
- Russian + English plus a third installed layout
- manual Windows layout shortcut set to Win+Space, Ctrl+Shift, Alt+Shift or another supported configuration: G-switcher behavior remains identical

## Privilege boundary

- normal target at the same integrity level: correction works
- elevated target from standard-user G-switcher: original input is preserved without unsafe partial replacement where possible

## Process and privacy behavior

- second instance does not install a second keyboard hook
- tray exit removes the hook
- first-run state is per-user
- per-user autostart does not require local administrator rights
- current candidate, the single previous-token record and at most two context words are volatile-only
- process enumeration for Settings is local and is not persisted as history
- tray runtime status is volatile-only
- Pause state is volatile-only
- persistent Settings contain only explicit user configuration, not typed history
