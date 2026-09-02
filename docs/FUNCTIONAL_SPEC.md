# G-switcher 0.8 functional specification

## Product model

G-switcher runs in the current Windows user session and observes keyboard events only to maintain the current candidate token. Version 0.8 may additionally retain exactly one immediately previous completed token so the user can manually convert it after a delimiter. Candidate and previous-token text are volatile-only and are never persisted.

The default decision rule is fail-safe: if evidence is ambiguous, leave the user's text unchanged. Automatic correction is performed only when the detector reaches the configured internal confidence threshold.

## Layout behavior

Supported pair: Russian and English. Other installed layouts are not modified automatically.

A correction targets the actual focused input control, not merely the top-level foreground window. The application requests a concrete target input locale and confirms it before injecting corrected physical key events.

The user's configured Windows layout shortcut is irrelevant to G-switcher correction.

## Boundaries and editing

Space, Enter and Tab are token boundaries. Supported punctuation may also terminate a token. Ambiguous OEM keys are interpreted contextually because the same physical key may be punctuation in one layout and a letter in the other.

Backspace updates the current candidate state instead of discarding all prior context. Cursor-moving operations, focus changes and unrelated command shortcuts invalidate transient text state when the runtime cannot prove that it remains applicable.

When a token reaches a boundary without automatic replacement, G-switcher may retain that token plus its delimiter as the single previous-token record. Typing the next visible token, changing process/focus context, entering Disabled mode, or pausing clears stale previous-token state.

## Detection and confidence

Signals may include:

- exact source-language dictionary match;
- exact opposite-layout dictionary match;
- source-language protection for valid common words;
- explicit user-dictionary match;
- word-frequency weight;
- character bigram and trigram score;
- morphology hints for common RU and EN inflections;
- penalties for punctuation introduced by opposite-layout mapping;
- token length and case pattern;
- code-safe classification.

A valid source-language word receives a strong preservation prior. An exact recognized target word receives maximum confidence. Lower-confidence heuristic candidates are corrected only when they meet the default threshold. Unexpected punctuation in an opposite-layout candidate is not silently discarded before scoring.

## Configurable hotkeys

Version 0.8 stores explicit per-user hotkey definitions for four actions. Defaults are:

- current-token manual conversion: `Ctrl+Shift+F12`;
- previous-token manual conversion: `Ctrl+Shift+F10`;
- undo: `Ctrl+Backspace`;
- Pause/Resume: `Ctrl+Shift+F11`.

Settings accepts Ctrl/Shift/Alt combinations with F1–F12, letters, digits, Space or Backspace. The action key event itself is suppressed only when G-switcher successfully recognizes it as a configured action.

## Manual conversion

Current-token conversion maps the in-progress RU/EN token to the opposite physical-key interpretation without requiring detector confidence. It does not insert a delimiter.

Previous-token conversion operates only on the immediately previous completed token retained in volatile memory. It removes that token and its delimiter, writes the opposite-layout text, then restores the original delimiter. It does not search the document or retain a text history.

Both manual conversion paths use the same focused-control and layout-switch safety checks as automatic correction. A successful conversion can be reverted by the configured undo hotkey while focus/caret state remains compatible.

## Per-application modes

Executable basename matching is case-insensitive. Each application effectively has one of three modes:

- `Auto` — automatic detection plus both manual conversion actions;
- `Manual only` — candidate tracking and manual conversion remain available, but automatic replacement is disabled;
- `Disabled` — G-switcher does not build/score candidates and neither automatic nor manual conversion is performed.

Applications not present in either configured list use `Auto`. If a basename appears in both lists, `Disabled` wins. Existing 0.7 `ExcludedApps` entries migrate to `Disabled` when the new setting is first loaded.

## Pause / Resume

Pause can be toggled from the tray or the configured hotkey. While paused, G-switcher does not build candidates or perform corrections; original keyboard input passes through unchanged.

Pause clears transient candidate, previous-token, undo and pending-correction state. Pause state is intentionally process-local and resets to active on every new G-switcher start. It is not written to the registry.

## User dictionary

The user dictionary contains only words explicitly entered in Settings. It is never populated automatically from typing.

A dictionary word written correctly in its own layout is protected from automatic correction. If an opposite-layout candidate maps exactly to an explicitly stored word, that target receives maximum detector confidence. Dictionary entries are stored locally per user.

## Case

Preserve lower case, Initial capital and ALL CAPS. Mixed case that resembles identifiers is handled conservatively by code-safe mode.

## Code-safe mode

Automatic correction is suppressed for tokens resembling technical identifiers, including common forms of URLs, email addresses, paths, IP/CIDR values, hostnames/domains, GUID/UUID values, hexadecimal strings/hashes, variable names, command-line switches, and mixed alpha-numeric identifiers.

Code-safe behavior is fail-open: the original text is never swallowed merely because correction was refused. Manual conversion remains an explicit user action except in Disabled mode or while paused.

## Undo

Immediately after a successful automatic, current-token manual, or previous-token manual correction, the configured undo hotkey can restore the original physical-key token, delimiter (if any), and source layout when focus remains compatible. Undo state is transient and one-shot.

## Settings

The tray Settings window exposes:

- automatic correction on/off;
- per-user autostart on/off;
- Disabled application basenames;
- Manual-only application basenames;
- explicit user-dictionary words;
- four editable hotkey definitions.

Settings take effect in the running process after Save and do not require elevation. Invalid hotkey syntax blocks Save with a local warning.

## Privilege model

The application runs as a standard user and does not require elevation for normal use. If Windows integrity rules prevent input injection into an elevated target, G-switcher fails open and avoids partial correction where possible.

## Privacy

Normal operation has no network dependency. Current candidate text and the single previous-token record are held only in volatile process memory and are not written to disk. Pause state is also volatile.

Persistent configuration is restricted to explicit user choices: booleans, executable basenames, user-dictionary entries, hotkey definitions and autostart state. Diagnostic functionality, if added later, must be content-free by default.
