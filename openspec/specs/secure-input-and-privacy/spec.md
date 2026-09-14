# Secure Input and Privacy Specification

## Purpose

Define G-switcher's secure-input exclusion, minimum text-access boundary, volatile-state rules, persistence boundary, local-only runtime, and standard-user privacy model so text handling cannot silently expand through future changes.

## Requirements

### Requirement: Native password and recognized credential targets are excluded

G-switcher MUST NOT build candidates, score text, perform automatic correction, perform current-word or previous-word manual conversion, convert selected text, or restore text through Undo while the focused target is a native password control or a recognized Windows credential/secure target. Original user input MUST pass through unchanged.

#### Scenario: Native password Edit

- **WHEN** the focused `EDIT` control is in native password state and the user types `ghbdtn `
- **THEN** the field MUST remain exactly `ghbdtn ` and G-switcher MUST NOT change the field's input layout

#### Scenario: Manual action in secure input

- **WHEN** the user invokes any configured conversion or Undo action while a protected secure field is focused
- **THEN** G-switcher MUST perform no text mutation and MUST leave the field's layout unchanged

### Requirement: Secure-input protection overrides user modes and sensitivity

Secure-input exclusion MUST apply in `Auto` and `Manual only` modes and under all sensitivity profiles. No application-mode or detector setting MAY weaken this protection.

#### Scenario: Aggressive sensitivity in Manual only

- **WHEN** the application is `Manual only`, sensitivity is `Aggressive`, and a protected password control is focused
- **THEN** automatic and explicit text conversion actions MUST still be blocked

### Requirement: UI Automation secure-state probing is metadata-only

For supported non-plain controls, the secure-input decision MAY use focused-element metadata including UI Automation `IsPassword`. The secure-input decision MUST NOT request text-bearing UIA properties or TextPattern content merely to determine whether the target is secure.

#### Scenario: UIA password element

- **WHEN** the focused UIA element reports `IsPassword = true`
- **THEN** G-switcher MUST classify the target as secure without reading its text content for the security decision

#### Scenario: Secure state cannot be verified

- **WHEN** a non-plain target's secure state cannot be safely verified
- **THEN** mutation MUST fail open rather than assuming that the target is safe

### Requirement: Entering secure input clears transient text state

When G-switcher detects entry into protected secure input, it MUST clear transient candidate, context, previous-token, pending selection/correction, and Undo state that could otherwise cross the trust boundary.

#### Scenario: Secure field focused after ordinary typing

- **WHEN** the user moves focus from a normal field with active transient state into a protected password field
- **THEN** all transient text/correction state that could apply to the prior context MUST be cleared before processing further input

### Requirement: Typed and selected content is volatile only

Normal runtime candidate text, the single previous-token record, up to two detector context words, pending selected text, pending correction content, and Undo text MUST exist only in volatile process memory for the time required by their function. G-switcher MUST NOT persist or transmit this content.

#### Scenario: Normal automatic detection

- **WHEN** the user types ordinary text for automatic detection
- **THEN** candidate/context content MAY be held in RAM within the documented bounds but MUST NOT be written to disk, registry, logs, telemetry, or a remote service

#### Scenario: Explicit selected-text conversion

- **WHEN** the user invokes selected-text conversion on a supported control
- **THEN** G-switcher MAY read the verified selection only for validation, replacement, and one-shot Undo, and MUST NOT persist or transmit the selected content

### Requirement: Persistent data is limited to explicit configuration

Persisted per-user state SHALL be limited to explicit user choices needed for product configuration: automatic-correction state, sensitivity profile, correction-sound state and volume, `Disabled`/`Manual only` executable basenames, explicit user-dictionary entries, hotkey definitions, onboarding/settings state required for the product, and autostart state. Normal typing MUST NOT expand the persistent dataset.

#### Scenario: User enters a dictionary word

- **WHEN** the user explicitly saves a word in the user dictionary
- **THEN** that configuration MAY persist for the current user

#### Scenario: User merely types a new word

- **WHEN** the user types a word during normal operation without explicitly adding it to configuration
- **THEN** G-switcher MUST NOT persist that word or learn it into the user dictionary

### Requirement: Runtime operation is local-only

Normal G-switcher runtime MUST NOT require or initiate network access, a cloud service, an online account, a remote model, a remote dictionary, or telemetry. Detection data required at runtime SHALL be local to the installed binary/configuration.

#### Scenario: Network is unavailable

- **WHEN** the Windows computer has no network connectivity
- **THEN** normal G-switcher correction, configuration, and local protection behavior SHALL remain available without network-dependent degradation

#### Scenario: Future feature wants remote inference

- **WHEN** a proposed change would send typed/selected text or detector context to a network service
- **THEN** that behavior is outside this baseline and MUST NOT be introduced without an explicit approved specification change to the privacy/runtime contract

### Requirement: Process enumeration remains local and non-historical

Settings MAY enumerate currently running process basenames and already configured application basenames to support the per-application mode picker. The enumerated running-process list MUST NOT be transmitted or retained as a usage history.

#### Scenario: Process picker opens

- **WHEN** the user opens the Settings process picker
- **THEN** G-switcher MAY enumerate local running-process basenames for immediate selection but MUST NOT upload them or persist a separate execution history

### Requirement: Normal operation uses standard-user privilege

G-switcher SHALL operate as a standard user for normal use and MUST NOT require elevation merely to obtain broader access to text targets. If Windows integrity boundaries prevent verified access or mutation, G-switcher MUST fail open.

#### Scenario: Elevated target is inaccessible

- **WHEN** the standard-user G-switcher process cannot safely inspect or mutate an elevated target because of Windows integrity rules
- **THEN** the operation MUST be refused rather than requesting elevation or guessing at the target state

### Requirement: Diagnostic behavior is content-free by default

Any diagnostic functionality added to the product MUST be content-free by default and MUST NOT persist typed or selected user text unless a future explicitly approved privacy specification changes this rule.

#### Scenario: Diagnostic event records a failed correction

- **WHEN** diagnostic information is produced for a failed correction
- **THEN** default diagnostics MUST identify the event without recording the user's candidate, selection, password, or contextual word content
