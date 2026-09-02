# G-switcher 0.7 functional specification

## Product model

G-switcher runs in the current Windows user session and observes keyboard events only to maintain the current candidate token. Text is not persisted. When a boundary is reached, the candidate is evaluated as written and under the opposite RU/EN physical-key interpretation.

The default decision rule is fail-safe: if evidence is ambiguous, leave the user's text unchanged. Version 0.7 exposes a numerical confidence score internally and applies automatic correction only when the configured default threshold is met.

## Layout behavior

Supported automatic pair: Russian and English. Other installed layouts are not modified automatically.

A correction targets the actual focused input control, not merely the top-level foreground window. The application requests a concrete target input locale and confirms it before injecting corrected physical key events.

The user's configured manual layout shortcut is irrelevant to automatic correction.

## Boundaries and editing

Always evaluate on Space, Enter and Tab.

Unambiguous punctuation may trigger immediate evaluation. Ambiguous OEM keys are interpreted contextually because the same physical key may be punctuation in one layout and a letter in the other.

Backspace updates the candidate state instead of discarding all prior context. Multiple Backspace operations must remain reversible while the caret stays within the current token.

Cursor-moving operations, mouse focus changes and command shortcuts invalidate the candidate unless the runtime can prove the caret remains within it.

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

A valid source-language word receives a strong preservation prior. An exact recognized target word receives maximum confidence. Lower-confidence heuristic candidates are corrected only when they meet the default confidence threshold. An opposite-layout candidate containing unexpected punctuation must not silently drop that punctuation before scoring.

## Manual conversion

`Ctrl+Shift+F12` converts the current in-progress RU/EN candidate to the opposite physical-key interpretation without requiring the automatic confidence threshold. The same focused-control and layout-switch safety checks used by automatic correction still apply.

Manual conversion does not bypass application exclusions. It is undoable with immediate `Ctrl+Backspace` while focus and caret state remain compatible.

## Per-application exclusions

Users may configure executable basenames such as `powershell.exe` or `code.exe`. Matching is case-insensitive.

When the focused input belongs to an excluded process:

- G-switcher does not build or score a candidate;
- no automatic or manual conversion is performed;
- stale candidate and undo state is discarded;
- the original input passes through unchanged.

Only executable basenames explicitly entered by the user are persisted.

## User dictionary

The user dictionary contains only words explicitly entered in Settings. It is not populated automatically from typing.

A dictionary word written correctly in its own layout is protected from automatic correction. If an opposite-layout candidate maps exactly to an explicitly stored word, that target receives maximum detector confidence. Dictionary entries are stored locally per user.

## Case

Preserve these case patterns:

- lower case;
- Initial capital;
- ALL CAPS.

Mixed case that resembles identifiers is handled conservatively by code-safe mode.

## Code-safe mode

Automatic correction is suppressed for tokens resembling technical identifiers, including common forms of:

- URLs and email addresses;
- Windows and Unix paths;
- IP addresses and CIDR;
- hostnames and domains;
- GUID/UUID values;
- hexadecimal strings and hashes;
- variable names, snake_case and common CamelCase identifiers;
- command-line switches;
- mixed alpha-numeric secrets or identifiers.

Code-safe behavior is fail-open: the original text is never swallowed merely because correction was refused.

## Undo

Immediately after an automatic or manual correction, Ctrl+Backspace reverts the last correction if the caret and focus are still compatible with that correction record. The record contains only the minimum transient information required to restore the word and layout, and is cleared when it becomes stale.

## Settings

The tray menu exposes a native Settings window. Version 0.7 settings include:

- automatic correction on/off;
- per-user autostart on/off;
- excluded executable names;
- explicit user-dictionary words;
- visible documentation of `Ctrl+Shift+F12` manual conversion and `Ctrl+Backspace` undo.

Settings take effect in the running process after Save and do not require elevation.

## Privilege model

The application runs as a standard user and must not require elevation for normal use. If Windows integrity rules prevent input injection into an elevated target, G-switcher leaves the original input untouched.

## Privacy

Normal operation has no network dependency. Candidate text is held only in volatile memory for the current token and is not written to disk. Persistent configuration is restricted to settings explicitly controlled by the user: booleans, executable basenames and user-dictionary entries. Diagnostic functionality, if added later, must be content-free by default.
