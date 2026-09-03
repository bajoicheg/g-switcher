# G-switcher 1.0.1 functional specification

## Product model

G-switcher runs in the current Windows user session and observes keyboard events only to maintain the current candidate token. It may additionally retain exactly one immediately previous completed token for manual previous-word conversion and at most two completed context words for Detector v3. All typed state is volatile-only and is never persisted or transmitted.

The default decision rule is conservative: if evidence is ambiguous, leave the user's text unchanged. Automatic correction is performed only when Detector v3 reaches the confidence threshold selected by the current sensitivity profile.

## Layout behavior

Supported pair: Russian and English. Other installed layouts are not modified automatically.

A correction targets the actual focused input control, not merely the top-level foreground window. The application requests a concrete target input locale and confirms it before injecting corrected physical key events.

The user's configured Windows layout shortcut is irrelevant to G-switcher correction.

## Boundaries and editing

Space, Enter and Tab are token boundaries. Supported punctuation may also terminate a token. Ambiguous OEM keys are interpreted contextually because the same physical key may be punctuation in one layout and a letter in the other.

A punctuation-looking OEM key may start or continue a candidate when the prospective physical-key sequence maps to a known prefix in the opposite language. This is required for cases such as English-layout `,kz` → Russian `бля`, where the first physical key normally produces a comma in English but `б` in Russian.

Backspace updates the current candidate state instead of discarding all prior context. Cursor-moving operations, focus changes and unrelated command shortcuts invalidate transient text state when the runtime cannot prove that it remains applicable.

When a token reaches a boundary without automatic replacement, G-switcher may retain that token plus its delimiter as the single previous-token record. Typing the next visible token, changing process/focus context, entering Disabled mode, entering a secure input control, or pausing clears stale previous-token state.

## Detector v3 and sensitivity

Detector v3 combines:

- exact source-language dictionary protection;
- exact opposite-layout dictionary recognition;
- explicit user-dictionary matches;
- baked-in local RU/EN common-word and word-frequency priors;
- common bigram/trigram scoring;
- morphology and word-shape signals;
- punctuation penalties;
- token length and case pattern;
- code-safe classification;
- at most two volatile previous context words.

The built-in common-word lexicons include broad everyday, technical, colloquial and common obscene vocabulary in both Russian and English. A recognized built-in frequent source-language word is deterministic preservation evidence and must not be automatically rewritten. A mapped target that is a recognized built-in frequent word is deterministic recognition evidence and receives maximum confidence. This protects valid words such as `truth`, `fuck`, `пизда`, `бля`, `блять`, `хуй` and `ебать` while also recognizing their wrong-layout forms.

Short ambiguous words remain context-sensitive where required. The broad common-word layer must not silently convert intentionally ambiguous three-letter tokens merely because a plausible target exists; context-sensitive regression cases remain part of the detector contract.

Unexpected punctuation introduced by opposite-layout mapping is not silently discarded before scoring.

Sensitivity changes the heuristic confidence threshold only:

- `Conservative` — highest threshold and lowest false-positive risk;
- `Normal` — default balance;
- `Aggressive` — lower threshold for more automatic corrections.

The frequency model and common-word lexicons are compiled into the executable. No runtime network lookup, cloud model, remote dictionary or telemetry is used.

## Selected-text conversion

The user can explicitly convert the currently selected text in supported native Win32 Edit/RichEdit controls. Default hotkey: `Ctrl+Shift+F9`.

Selected text is read only when this hotkey is invoked. G-switcher infers whether the selection is RU-layout or EN-layout text, maps it through the opposite physical keyboard layout, replaces only the selected range, switches to the target layout, and stores a one-shot volatile Undo record.

The clipboard is not read, written or modified. If the focused control does not provide a supported native selection interface, the action fails open and leaves text unchanged.

## Secure input protection

G-switcher must not build candidates, score text, perform manual conversion, convert selections, or restore text through Undo inside password/PIN/OTP/credential/secure input controls.

Protection includes native password EDIT state and known secure/credential control or process families. When a secure input target is detected, transient G-switcher text state is cleared and the user's original input is passed through unchanged.

This rule overrides per-application mode and sensitivity settings.

## Configurable hotkeys

Version 1.0.1 stores explicit per-user hotkey definitions for five actions. Defaults are:

- selected text: `Ctrl+Shift+F9`;
- current-token manual conversion: `Ctrl+Shift+F12`;
- previous-token manual conversion: `Ctrl+Shift+F10`;
- undo: `Ctrl+Backspace`;
- Pause/Resume: `Ctrl+Shift+F11`.

Settings accepts Ctrl/Shift/Alt combinations with F1–F12, letters, digits, Space or Backspace. The action key event itself is suppressed only when G-switcher successfully recognizes it as a configured action.

Queued manual correction restores only modifier keys that are still physically active when the queued correction executes; already-released hotkey modifiers must not be synthetically re-pressed.

## Manual conversion

Current-token conversion maps the in-progress RU/EN token to the opposite physical-key interpretation without requiring detector confidence. It does not insert a delimiter.

Previous-token conversion operates only on the immediately previous completed token retained in volatile memory. It removes that token and its delimiter, writes the opposite-layout text, then restores the original delimiter. It does not search the document or retain a text history.

Both manual conversion paths use the same focused-control, secure-input and layout-switch safety checks as automatic correction. A successful conversion can be reverted by the configured undo hotkey while focus/caret state remains compatible.

## Per-application modes

Executable basename matching is case-insensitive. Each application effectively has one of three modes:

- `Auto` — automatic detection plus explicit manual and selected-text conversion;
- `Manual only` — candidate tracking and explicit conversion remain available, but automatic replacement is disabled;
- `Disabled` — G-switcher does not build/score candidates and no conversion action modifies text.

Applications not present in either configured list use `Auto`. If a basename appears in both lists, `Disabled` wins.

## Pause / Resume

Pause can be toggled from the tray or the configured hotkey. While paused, G-switcher does not build candidates or perform corrections; original keyboard input passes through unchanged.

Pause clears transient candidate, previous-token, context, Undo and pending-correction/selection state. Pause state is intentionally process-local and resets to active on every new G-switcher start. It is not written to the registry.

## User dictionary

The user dictionary contains only words explicitly entered in Settings. It is never populated automatically from typing.

A dictionary word written correctly in its own layout is protected from automatic correction. If an opposite-layout candidate maps exactly to an explicitly stored word, that target receives maximum detector confidence. Dictionary entries are stored locally per user.

## Case

Preserve lower case, Initial capital and ALL CAPS. Mixed case that resembles identifiers is handled conservatively by code-safe mode.

## Code-safe mode

Automatic correction is suppressed for tokens resembling technical identifiers, including common forms of URLs, email addresses, paths, IP/CIDR values, hostnames/domains, GUID/UUID values, hexadecimal strings/hashes, variable names, command-line switches, and mixed alpha-numeric identifiers.

Code-safe behavior is fail-open: the original text is never swallowed merely because correction was refused. Explicit manual conversion remains a user action except in Disabled mode, Pause or secure input.

## Undo

Immediately after a successful automatic, current-token manual, previous-token manual or selected-text correction, the configured Undo hotkey can restore the original text and source layout when focus remains compatible. Undo state is transient and one-shot.

Selected-text Undo restores exactly the replaced native selection range. Token-based Undo restores the original physical-key token and delimiter if present.

## Settings

The tray Settings window exposes:

- automatic correction on/off;
- sensitivity profile;
- per-user autostart on/off;
- per-application mode management through a process picker;
- explicit user-dictionary words;
- five editable hotkey definitions.

Settings take effect in the running process after Save and do not require elevation. Invalid hotkey syntax blocks Save with a local warning. The UI states that typed context is volatile and secure fields are not processed.

The 1.0.1 native layout reserves enough client height for all sections, provides a genuinely multiline user-dictionary editor, and avoids displaying non-functional vertical scrollbars on the read-only application-mode result lists.

## Privilege model

The application runs as a standard user and does not require elevation for normal use. If Windows integrity rules prevent input injection into an elevated target, G-switcher fails open and avoids partial correction where possible.

## Privacy

Normal operation has no network dependency. Current candidate text, the single previous-token record, at most two context words, pending selected text and Undo state are held only in volatile process memory and are not written to disk.

Persistent configuration is restricted to explicit user choices: booleans, sensitivity, executable basenames, user-dictionary entries, hotkey definitions and autostart state. Diagnostic functionality, if added later, must be content-free by default.
