# G-switcher 2.0.1 functional specification

## Product model

G-switcher runs in the current Windows user session and observes keyboard events only to maintain the current candidate token. It may additionally retain exactly one immediately previous completed token for manual previous-word conversion and at most two completed context words for Detector v3. All typed state is volatile-only and is never persisted or transmitted.

The default decision rule is conservative: if evidence is ambiguous, leave the user's text unchanged. Automatic correction is performed only when Detector v3 reaches the confidence threshold selected by the current sensitivity profile.

The 2.0 line starts strictly from 1.0.10 and preserves its fail-open detector rule. Version 2.0.1 keeps the same detector thresholds, pinned generated frequency layer and collision policy as 2.0.0, while hardening cross-process mutation and context validity. The generated layer contains 56,036 normalized RU/EN source forms of four or more letters and 26,990 deterministically restorable targets. Nine generated cross-layout collisions and ambiguous generated three-letter forms remain unchanged by design. Global sensitivity thresholds are not lowered.

## Runtime dispatch and context validity

Low-level keyboard and mouse hooks execute on a dedicated hook thread. Hook callbacks perform only bounded event capture/dispatch work; detector scoring, focused-control inspection, UI Automation and mutation logic run outside the callback. Release CI records callback counts, latency and dropped-event metrics and includes a 100,000-callback stress gate.

Every mutable typing context is associated with a generation identifier. Operations that can change text re-check the current generation plus the relevant focus HWND, process, UI thread, keyboard layout and exact caret/selection state before mutation. Focus changes, cursor/navigation operations, Pause and other context-invalidating events advance or clear transient state. A stale queued correction or stale Undo must fail open and leave the current control unchanged.

## Layout behavior

Supported pair: Russian and English. Other installed layouts are not modified automatically.

A correction targets the actual focused input control, not merely the top-level foreground window. The application requests a concrete target input locale and confirms it before performing a verified replacement.

The user's configured Windows layout shortcut is irrelevant to G-switcher correction.

## Boundaries and editing

Space, Enter and Tab are token boundaries. Supported punctuation may also terminate a token. Ambiguous OEM keys are interpreted contextually because the same physical key may be punctuation in one layout and a letter in the other.

A punctuation-looking OEM key may start or continue a candidate when the prospective physical-key sequence maps to a known prefix in the opposite language. This is required for cases such as English-layout `,kz` → Russian `бля` and `rjhj,jxrf.` → `коробочка.`, where OEM punctuation-looking keys participate in the opposite-layout word.

Where raw `SendInput` is used by a supported path, delivery is loss-aware: if Windows accepts only part of a batch, G-switcher resumes from the first unsent INPUT with bounded retries instead of abandoning the batch after already-delivered events. If the initial `SendInput` call makes zero progress, the operation fails open before any synthetic deletion is delivered.

Backspace updates the current candidate state instead of discarding all prior context. Cursor-moving operations, focus changes and unrelated command shortcuts invalidate transient text state when the runtime cannot prove that it remains applicable.

When a token reaches a boundary without automatic replacement, G-switcher may retain that token plus its delimiter as the single previous-token record. Typing the next visible token, changing process/focus context, entering Disabled mode, entering a secure input control, or pausing clears stale previous-token state.

## Verified text adapters

Version 2.0.1 permits mutation only when the focused control exposes a synchronously verifiable adapter.

Plain Win32 `Edit` controls use marshalled system messages with bounded `SendMessageTimeout` calls. The adapter reads the exact caret/selection state, verifies the expected source text before replacement and verifies the resulting text afterward. A failed or unexpected post-state is not accepted as success.

Supported RichEdit controls use UI Automation TextPattern to obtain exact range state and a range-local documented replacement. UIA-derived character offsets, current selection and full post-state are verified around mutation. The clipboard is not used as a fallback.

Adapter selection includes a bounded liveness preflight. A target whose UI thread is already hung, closing or otherwise unresponsive is treated as unsupported for that operation and left unchanged. If adapter availability is lost between queuing and execution, the operation does not fall through to an unverified raw mutation path.

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

The 1.0.10 base retains the earlier deterministic Russian target additions, including `политик`, `систем`, `спрос`, `программ`, `лиц`, `дел`, `правил`, `команд`, `виде`, `работ`, `инструкции`, `важны` and `норм`. Their wrong-layout forms remain locked in integration regression coverage. Representative full runtime cases `cbcntv` → `систем`, `ghjuhfvv` → `программ` and `bycnherwbb` → `инструкции` are also part of the real Win32 hook-to-EDIT release gate.

Short ambiguous words remain context-sensitive where required. The broad common-word layer must not silently convert intentionally ambiguous three-letter tokens merely because a plausible target exists; context-sensitive regression cases remain part of the detector contract.

Unexpected punctuation introduced by opposite-layout mapping is not silently discarded before scoring.

Sensitivity changes the heuristic confidence threshold only:

- `Conservative` — highest threshold and lowest false-positive risk;
- `Normal` — default balance;
- `Aggressive` — lower threshold for more automatic corrections.

The frequency model and common-word lexicons are compiled into the executable. No runtime network lookup, cloud model, remote dictionary or telemetry is used.

## Selected-text conversion

The user can explicitly convert the currently selected text when the focused control exposes a verified text adapter. Default hotkey: `Ctrl+Shift+F9`.

Selected text is read only when this hotkey is invoked. G-switcher verifies the focused control and selected range, infers whether the selection is RU-layout or EN-layout text, maps it through the opposite physical keyboard layout, replaces only that verified range, switches to the target layout, and stores a one-shot volatile Undo record.

The clipboard is not read, written or modified. If the focused control does not provide a supported verified adapter, the action fails open and leaves text unchanged.

## Secure input protection

G-switcher must not build candidates, score text, perform manual conversion, convert selections, or restore text through Undo inside native password controls or recognized Windows credential/secure targets.

Protection includes native password EDIT state and known secure/credential control or process families. For supported UI Automation targets, G-switcher additionally queries focused-element metadata including `IsPassword`; this secure-input decision does not request text-bearing UIA properties or patterns. When a secure input target is detected, transient G-switcher text state is cleared and the user's original input is passed through unchanged.

UIA password verification is fail-open. If the metadata probe cannot safely verify an otherwise non-plain control, mutation is refused rather than guessed. Users can additionally assign `Disabled` mode to an application when they do not want G-switcher processing in that process at all.

This rule overrides per-application mode and sensitivity settings.

## Configurable hotkeys

Version 2.0.1 stores explicit per-user hotkey definitions for five actions. Defaults are:

- selected text: `Ctrl+Shift+F9`;
- current-token manual conversion: `Ctrl+Shift+F12`;
- previous-token manual conversion: `Ctrl+Shift+F10`;
- undo: `Ctrl+Backspace`;
- Pause/Resume: `Ctrl+Shift+F11`.

Settings accepts Ctrl/Shift/Alt combinations with F1–F12, letters, digits, Space or Backspace. The action key event itself is suppressed only when G-switcher successfully recognizes it as a configured action.

All five actions must use distinct combinations. Settings rejects a duplicate pair with a local warning and does not persist a partially ambiguous mapping.

Queued manual correction restores only modifier keys that are still physically active when the queued correction executes; already-released hotkey modifiers must not be synthetically re-pressed.

## Manual conversion

Current-token conversion maps the in-progress RU/EN token to the opposite physical-key interpretation without requiring detector confidence. It does not insert a delimiter.

Previous-token conversion operates only on the immediately previous completed token retained in volatile memory. It removes that token and its delimiter, writes the opposite-layout text, then restores the original delimiter. It does not search the document or retain a text history.

Both manual conversion paths use the same generation, focused-control, verified-adapter, secure-input and layout-switch safety checks as automatic correction. A successful conversion can be reverted by the configured undo hotkey while the verified context remains compatible.

## Per-application modes

Executable basename matching is case-insensitive. Each application effectively has one of three modes:

- `Auto` — automatic detection plus explicit manual and selected-text conversion;
- `Manual only` — candidate tracking and explicit conversion remain available, but automatic replacement is disabled;
- `Disabled` — G-switcher does not build/score candidates and no conversion action modifies text.

Applications not present in either configured list use `Auto`. If a basename appears in both lists, `Disabled` wins.

## Pause / Resume

Pause can be toggled from the tray or the configured hotkey. While paused, G-switcher does not build candidates or perform corrections; original keyboard input passes through unchanged.

Pause clears transient candidate, previous-token, context, Undo and pending-correction/selection state and invalidates the current generation. Pause state is intentionally process-local and resets to active on every new G-switcher start. It is not written to the registry.

## User dictionary

The user dictionary contains only words explicitly entered in Settings. It is never populated automatically from typing.

A dictionary word written correctly in its own layout is protected from automatic correction. If an opposite-layout candidate maps exactly to an explicitly stored word, that target receives maximum detector confidence. Dictionary entries are stored locally per user.

## Case

Preserve lower case, Initial capital and ALL CAPS. Mixed case that resembles identifiers is handled conservatively by code-safe mode.

## Code-safe mode

Automatic correction is suppressed for tokens resembling technical identifiers, including common forms of URLs, email addresses, absolute paths, IP/CIDR values, GUID/UUID values, hexadecimal strings/hashes, variable names, command-line switches, and mixed alpha-numeric identifiers. Version 2.0.1 keeps digits and common technical separators inside the runtime candidate long enough for Code-safe classification, preventing such sequences from being split into misleading word fragments.

Code-safe behavior is fail-open: the original text is never swallowed merely because correction was refused. Explicit manual conversion remains a user action except in Disabled mode, Pause or secure input.

## Undo

Immediately after a successful automatic, current-token manual, previous-token manual or selected-text correction, the configured Undo hotkey can restore the original text and source layout only when the saved generation and verified focus/process/range context remain compatible. Undo state is transient and one-shot.

Selected-text Undo restores exactly the replaced verified range. Token-based Undo restores the original token and delimiter if present. If the original adapter or exact expected corrected text cannot be verified, Undo fails open rather than switching to an unverified mutation path.

## Correction sound

After a confirmed successful automatic, current-word, previous-word or selected-text conversion, G-switcher may play one short correction signal. Refused or failed conversions, Pause, secure input and Undo do not produce the signal.

The signal is enabled by default at 20% and can be disabled or adjusted from 0% to 100% in 5% steps on first launch and in Settings. Volume changes the PCM sample amplitude rather than the Windows master volume. The waveform is generated and cached in process memory; no external audio asset, recorded content, network access or text-derived sound is used.

## Settings

The tray Settings window exposes:

- automatic correction on/off;
- sensitivity profile;
- correction sound on/off and volume;
- per-user autostart on/off;
- per-application mode management through a process picker;
- explicit user-dictionary words;
- five editable hotkey definitions.

Settings take effect in the running process after Save and do not require elevation. Invalid or duplicate hotkeys block Save with a local warning. The UI states that typed context is volatile and identifies protection as applying to secure fields.

The 2.0.1 native layout uses a 900×680 client area and centers inside the Windows work area so the complete form remains usable on a typical 1366×768 desktop with a taskbar. It provides a multiline user-dictionary editor, avoids non-functional vertical scrollbars on the read-only application-mode result lists, and identifies the Settings build dynamically from the package version.

The first-run dialog exposes autostart, correction-sound state and correction volume before activation. Closing it cancels startup without writing first-run completion, so onboarding is presented again next launch.

## Privilege model

The application runs as a standard user and does not require elevation for normal use. If Windows integrity rules prevent verified access or mutation of an elevated target, G-switcher fails open.

## Failure-path requirements

A hung target UI thread must not make G-switcher wait indefinitely or guess at mutation state. Verified adapter calls use bounded Win32 message timeouts and perform a liveness preflight before entering supported UIA text paths.

If a target process closes or disappears during a pending operation, the operation must fail open without modifying any newly focused control. After such a failure, G-switcher must continue processing a fresh responsive target normally.

These requirements are exercised by a dedicated separate-process release-gate harness in addition to the normal same-process and cross-process E2E tests.

## Privacy

Normal operation has no network dependency. Current candidate text, the single previous-token record, at most two context words, pending selected text and Undo state are held only in volatile process memory and are not written to disk.

Persistent configuration is restricted to explicit user choices: automatic-correction and sound booleans, sound volume, sensitivity, executable basenames, user-dictionary entries, hotkey definitions and autostart state. Diagnostic functionality, if added later, must be content-free by default.
