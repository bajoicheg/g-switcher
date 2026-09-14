# Verified Text Adapters Specification

## Purpose

Define which focused text targets may be read or mutated, the verification guarantees required around each supported adapter, and the mandatory fail-open behavior for unsupported, stale, or unverifiable controls without clipboard fallback.

## Requirements

### Requirement: Text mutation requires a synchronously verifiable adapter

G-switcher SHALL mutate text only when the currently focused control exposes a supported adapter that can verify the exact pre-state and post-state required by the operation. Adapter unavailability or verification failure MUST leave the original text unchanged.

#### Scenario: Supported adapter verifies replacement

- **WHEN** the focused control exposes a supported adapter, the expected source range matches exactly, and the resulting text can be verified after replacement
- **THEN** G-switcher MAY accept the mutation as successful

#### Scenario: Post-state is unexpected

- **WHEN** the adapter cannot verify the expected resulting text/range after a replacement attempt
- **THEN** G-switcher MUST NOT report the operation as a confirmed success

### Requirement: Plain Win32 Edit uses bounded verified access

For supported plain Win32 `Edit` controls, G-switcher SHALL obtain and verify caret/selection/text state through bounded marshalled control access, SHALL re-check the exact expected source range immediately before replacement, and SHALL verify the resulting control text afterward.

#### Scenario: Separate-process Edit replacement

- **WHEN** a separate-process plain Win32 `Edit` control is responsive and the expected range matches
- **THEN** G-switcher SHALL replace only the verified range and verify the resulting full control text before accepting success

#### Scenario: Edit source range changed

- **WHEN** the Edit control's source range differs from the expected text immediately before mutation
- **THEN** replacement MUST be refused and the current control text MUST remain unchanged by G-switcher

### Requirement: Supported RichEdit operations use verified range state

For supported RichEdit controls, G-switcher SHALL obtain exact selection/document range state through the supported UI Automation text path and SHALL perform only a verified range-local replacement. Selected-text Undo MUST restore exactly the previously replaced verified range when the current context remains compatible.

#### Scenario: RichEdit selected-text replacement

- **WHEN** a supported `RICHEDIT50W` control exposes a verifiable selected range
- **THEN** selected-text conversion SHALL affect only that range and SHALL verify the resulting document/range state

#### Scenario: RichEdit Undo range is stale

- **WHEN** the range saved for selected-text Undo no longer matches the current verified corrected state
- **THEN** Undo MUST fail open rather than restoring through an unverified range

### Requirement: Chromium adapter claims are evidence-bound

G-switcher MAY claim ordinary Edge/Chrome editable-field support only for adapter paths that verify the focused UIA element identity/range, the exact source text, the resulting text, and stable control identity required by the operation. Adapter-level automated success MUST NOT be generalized to arbitrary contenteditable controls, Word PWA, Electron applications, or other applications without their required compatibility evidence.

#### Scenario: Verified ordinary browser field

- **WHEN** an ordinary Edge or Chrome input/textarea is exercised by the reviewed browser adapter test and the adapter verifies source, target, and control identity
- **THEN** that adapter path MAY count as automated evidence for the tested field class

#### Scenario: Untested web/editor control

- **WHEN** a different contenteditable/editor/control class has not completed its required compatibility evidence
- **THEN** G-switcher MUST NOT claim that application/control as supported merely because a browser input adapter test passed

### Requirement: Clipboard fallback is forbidden

G-switcher MUST NOT read, overwrite, or temporarily repurpose the Windows clipboard as a fallback mechanism for selected-text reading, text replacement, current/previous-word conversion, or Undo.

#### Scenario: Verified adapter is unavailable

- **WHEN** the focused control does not expose a supported verified adapter
- **THEN** G-switcher MUST fail open and MUST NOT use Ctrl+C, Ctrl+V, clipboard APIs, or clipboard preservation tricks to complete the operation

#### Scenario: Selected-text conversion succeeds

- **WHEN** selected-text conversion succeeds through a supported adapter
- **THEN** the user's clipboard contents MUST remain unchanged

### Requirement: Adapter selection includes bounded liveness validation

Before entering a supported mutation path, G-switcher SHALL perform the bounded target-liveness checks required by that path. A target already known to be hung, closing, disappeared, or unresponsive MUST be treated as unsupported for that operation.

#### Scenario: Hung target before mutation

- **WHEN** the target fails the bounded liveness preflight
- **THEN** G-switcher MUST refuse the adapter operation before attempting an unverified or indefinite mutation

#### Scenario: Adapter is lost after planning

- **WHEN** adapter availability or identity changes between queueing and execution
- **THEN** G-switcher MUST fail open and MUST NOT fall through to a different unverified mutation path

### Requirement: Unsupported/custom controls preserve user input

Unsupported or custom controls for which G-switcher cannot prove a supported adapter contract MUST receive the user's original input unchanged. Safe no-op behavior is a safety outcome, not evidence that conversion functionality is supported for that control.

#### Scenario: Custom unsupported control

- **WHEN** a focused custom control exposes no supported verified mutation adapter
- **THEN** automatic/manual/selection mutation MUST be refused and original text MUST be preserved
