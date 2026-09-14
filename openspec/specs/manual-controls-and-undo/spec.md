# Manual Controls and Undo Specification

## Purpose

Define explicit user conversion controls, configurable hotkeys, previous-token retention, selected-text conversion, Pause/Resume, and one-shot Undo so manual actions remain predictable while sharing the same safety and secure-input boundaries as automatic correction.

## Requirements

### Requirement: Five user actions have configurable distinct hotkeys

G-switcher SHALL provide configurable hotkeys for selected-text conversion, current-word conversion, previous-word conversion, Undo, and Pause/Resume. The 2.0.1 defaults SHALL be `Ctrl+Shift+F9`, `Ctrl+Shift+F12`, `Ctrl+Shift+F10`, `Ctrl+Backspace`, and `Ctrl+Shift+F11` respectively. Saved action combinations MUST be distinct.

#### Scenario: Default bindings

- **WHEN** a new configuration is created
- **THEN** the five actions SHALL use the documented 2.0.1 default combinations

#### Scenario: Duplicate binding

- **WHEN** the user attempts to assign a combination already assigned to another action
- **THEN** Settings MUST reject the save and MUST NOT persist a partially ambiguous hotkey mapping

#### Scenario: Reassigned binding

- **WHEN** the user saves a valid supported replacement combination
- **THEN** the new binding SHALL take effect without application restart

### Requirement: Hotkey matching requires the configured modifier set

A configured action SHALL trigger only when its expected modifier/key combination is recognized according to the configured matching rules; an arbitrary modifier prefix/superset MUST NOT be accepted as the same binding. Queued manual correction MUST NOT synthetically re-press Ctrl, Shift, or Alt after the user has already released those modifiers.

#### Scenario: Modifiers released before queued mutation

- **WHEN** a manual hotkey is recognized but one or more modifiers are released before the queued conversion executes
- **THEN** G-switcher MUST restore only modifiers that remain physically active and MUST NOT reintroduce stale modifier state

### Requirement: Current-word manual conversion bypasses detector confidence but not safety

In `Auto` or `Manual only` mode, the configured current-word action SHALL map the in-progress RU/EN token through the opposite physical keyboard layout without requiring automatic detector confidence and without inserting a delimiter. It MUST still obey generation, focused-control, verified-adapter, layout, secure-input, Pause, and Disabled-mode safety checks.

#### Scenario: Explicit ambiguous current word

- **WHEN** an in-progress `ghbdtn` token is in a supported non-secure control and the user invokes current-word conversion
- **THEN** G-switcher SHALL convert it to `привет` without adding a delimiter even if the automatic detector would have refused the token

#### Scenario: Current-word action in Disabled mode

- **WHEN** the focused application's mode is `Disabled`
- **THEN** current-word conversion MUST leave the text unchanged

### Requirement: Previous-word conversion is bounded to one retained token

G-switcher MAY retain exactly one immediately previous completed token plus its delimiter in volatile memory for the previous-word action. The action SHALL replace only that retained token through the opposite layout and restore the original delimiter. Typing the next visible token, relevant focus/process changes, Disabled mode, secure-input entry, or Pause MUST invalidate the record.

#### Scenario: Previous word is converted

- **WHEN** `ghbdtn ` was completed without automatic correction and remains the valid immediately previous token
- **THEN** the previous-word action SHALL produce `привет ` and preserve the delimiter

#### Scenario: Next visible token has started

- **WHEN** the user begins another visible token after the previous-token record was captured
- **THEN** the prior record MUST be invalidated and the previous-word action MUST NOT search backward through document history

### Requirement: Selected-text conversion is explicit and range-local

Selected text SHALL be read only after the configured selected-text action is invoked and only when the focused control exposes a supported verified adapter. G-switcher SHALL infer the RU/EN source interpretation, replace only the exact verified selected range, select/confirm the target layout, and create one-shot volatile Undo state. The clipboard MUST remain unchanged.

#### Scenario: English-layout selection converts to Russian

- **WHEN** the user selects `ghbdtn rfr ltkf` in a supported non-secure control and invokes selected-text conversion
- **THEN** only the selected range SHALL become `привет как дела` and the target input layout SHALL become Russian

#### Scenario: No selection

- **WHEN** no verifiable non-empty selection exists
- **THEN** selected-text conversion MUST perform no destructive modification

#### Scenario: Unsupported selected-text target

- **WHEN** the focused control cannot provide a verified selected range
- **THEN** the action MUST fail open and leave text and clipboard unchanged

### Requirement: Undo is one-shot and context-bound

Immediately after a confirmed automatic, current-word, previous-word, or selected-text conversion, Undo MAY restore the original text and source layout exactly once only while the saved generation, focus/process/control, adapter, and expected corrected text/range remain compatible. A mismatch MUST fail open.

#### Scenario: Immediate current-word Undo

- **WHEN** the user invokes Undo immediately after a successful current-word conversion and the verified context is unchanged
- **THEN** G-switcher SHALL restore the original token and source layout and consume that Undo record

#### Scenario: Selected-text Undo

- **WHEN** the user invokes Undo after successful selected-text conversion and the exact corrected range is still verified
- **THEN** G-switcher SHALL restore exactly the original selected range and source layout

#### Scenario: Stale Undo

- **WHEN** typing, focus, caret, selection, process, or other context changes make the saved Undo context uncertain
- **THEN** Undo MUST fail open and MUST NOT mutate the current target

### Requirement: Pause disables all processing and clears transient state

Pause SHALL be togglable from the tray and configured hotkey. While paused, G-switcher MUST NOT build candidates or perform automatic/manual/selected-text/Undo conversions. Entering Pause MUST clear candidate, previous-token, context, Undo, pending correction/selection state and invalidate the active generation. Pause state SHALL be process-local and MUST reset to active on application restart.

#### Scenario: Pause during ordinary typing

- **WHEN** G-switcher is paused and the user types `ghbdtn `
- **THEN** the input MUST remain unchanged and no explicit conversion action may mutate it

#### Scenario: Resume after stale pre-pause context

- **WHEN** G-switcher resumes after Pause
- **THEN** no candidate, previous-token, context, Undo, or pending mutation captured before Pause may be resurrected

#### Scenario: Application restarts after being paused

- **WHEN** G-switcher starts a new process after a prior process was paused
- **THEN** it SHALL start active rather than persisting Pause state

### Requirement: Explicit actions share secure-input and mutation safety boundaries

Manual conversion, selected-text conversion, and Undo MUST obey the same generation, focused-control, verified-adapter, layout, integrity, and secure-input rules as automatic correction.

#### Scenario: Explicit action in protected password control

- **WHEN** any conversion or Undo hotkey is invoked while a protected password/credential target is focused
- **THEN** G-switcher MUST perform no text mutation and MUST leave the target layout unchanged
