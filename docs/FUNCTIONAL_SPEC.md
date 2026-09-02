# G-switcher 0.6 functional specification

## Product model

G-switcher runs in the current Windows user session and observes keyboard events only to maintain the current candidate token. Text is not persisted. When a boundary is reached, the candidate is evaluated as written and under the opposite RU/EN physical-key interpretation.

The default decision rule is fail-safe: if evidence is ambiguous, leave the user's text unchanged.

## Layout behavior

Supported automatic pair: Russian and English. Other installed layouts are not modified automatically.

A correction targets the actual focused input control, not merely the top-level foreground window. The application requests a concrete target input locale and confirms it before injecting corrected physical key events.

The user's configured manual layout shortcut is irrelevant to automatic correction.

## Boundaries and editing

Always evaluate on Space, Enter and Tab.

Unambiguous punctuation may trigger immediate evaluation. Ambiguous OEM keys are interpreted contextually because the same physical key may be punctuation in one layout and a letter in the other.

Backspace updates the candidate state instead of discarding all prior context. Multiple Backspace operations must remain reversible while the caret stays within the current token.

Cursor-moving operations, mouse focus changes and command shortcuts invalidate the candidate unless the runtime can prove the caret remains within it.

## Detection

Signals may include:

- exact source-language dictionary match;
- exact opposite-layout dictionary match;
- source-language protection for valid common words;
- word-frequency weight;
- character n-gram score;
- morphology hints for common RU and EN inflections;
- penalties for punctuation introduced by opposite-layout mapping;
- token length and case pattern;
- code-safe classification.

A valid source-language word receives a strong preservation prior. An opposite-layout candidate containing unexpected punctuation must not silently drop that punctuation before scoring.

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

Immediately after an automatic correction, Ctrl+Backspace reverts the last correction if the caret and focus are still compatible with that correction record. The record contains only the minimum transient information required to restore the word and layout, and is cleared when it becomes stale.

## Privilege model

The application runs as a standard user and must not require elevation for normal use. If Windows integrity rules prevent input injection into an elevated target, G-switcher leaves the original input untouched.

## Privacy

Normal operation has no network dependency. Candidate text is held only in volatile memory for the current token and is not written to disk. Diagnostic functionality, if added later, must be content-free by default.
