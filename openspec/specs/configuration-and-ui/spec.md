# Configuration and UI Specification

## Purpose

Define persistent user configuration, first-run behavior, per-application modes, process-picker semantics, sensitivity and dictionary controls, autostart synchronization, Settings usability, and standard-user interaction without changing the runtime safety model.

## Requirements

### Requirement: Settings exposes the supported user configuration

The Settings window SHALL allow the user to configure automatic correction, sensitivity profile, correction sound state and volume, per-user autostart, per-application modes, explicit user-dictionary words, and the five action hotkeys. Valid saved changes SHALL take effect in the running process without requiring elevation or restart unless Windows itself requires otherwise for a specific external state.

#### Scenario: Save valid settings

- **WHEN** the user changes supported settings and chooses Save
- **THEN** G-switcher SHALL persist the explicit per-user choices and apply them to the running process without elevation

#### Scenario: Cancel settings edits

- **WHEN** the user cancels or closes Settings without saving
- **THEN** unsaved edits MUST NOT replace the persisted configuration

### Requirement: Per-application modes are local and deterministic

Executable basenames SHALL be matched case-insensitively. Unlisted applications SHALL use `Auto`; `Manual only` SHALL disable automatic replacement while allowing explicit conversions outside other safety blocks; `Disabled` SHALL prohibit candidate processing and all text conversion. If an executable is present in both configured lists, `Disabled` MUST win.

#### Scenario: Unlisted executable

- **WHEN** the focused process basename is not configured
- **THEN** G-switcher SHALL apply `Auto` mode

#### Scenario: Manual-only application

- **WHEN** a process is configured as `Manual only`
- **THEN** G-switcher SHALL track the state required for explicit supported actions but MUST NOT automatically replace text

#### Scenario: Disabled application

- **WHEN** a process is configured as `Disabled`
- **THEN** G-switcher MUST perform no automatic or explicit text conversion and MUST clear stale candidate, previous-token, context, and Undo state associated with prior processing

#### Scenario: Conflicting application lists

- **WHEN** the same executable basename appears in both `Manual only` and `Disabled`
- **THEN** `Disabled` MUST take precedence

### Requirement: Process picker does not require manual executable typing

Settings SHALL provide a process picker containing currently running process basenames plus already configured application basenames and SHALL let the user assign `Auto`, `Manual only`, or `Disabled` policy from that picker.

#### Scenario: Previously configured process is not currently running

- **WHEN** a configured executable is absent from the current running-process enumeration
- **THEN** the process picker SHALL still expose that configured basename so its policy can be reviewed or changed

#### Scenario: Mode change is saved

- **WHEN** the user selects a process and saves a new application mode
- **THEN** the resulting policy SHALL take effect without requiring restart

### Requirement: User dictionary is explicitly editable

Settings SHALL provide an editable user-dictionary list with one logical entry per line. Duplicate entries MAY be normalized, but ordinary typing MUST NOT add entries automatically.

#### Scenario: Explicit dictionary entry survives restart

- **WHEN** the user adds and saves a valid dictionary word
- **THEN** that word SHALL remain available as per-user configuration after restart

#### Scenario: Duplicate entries

- **WHEN** equivalent duplicate dictionary entries are saved
- **THEN** G-switcher MAY normalize them to one effective entry without changing their protection semantics

### Requirement: Autostart reflects and controls actual per-user Run state

First-run and Settings autostart controls SHALL reflect the actual G-switcher per-user Windows autostart state. Enabling autostart SHALL establish the supported Run entry; disabling or leaving the first-run autostart option unchecked SHALL remove any stale G-switcher Run entry rather than silently preserving it.

#### Scenario: Existing autostart is enabled before first-run UI

- **WHEN** first-run UI opens and the supported G-switcher Run entry already exists
- **THEN** the autostart checkbox SHALL reflect that actual state

#### Scenario: User disables autostart

- **WHEN** the user saves autostart disabled or confirms first-run with the option unchecked
- **THEN** any supported stale G-switcher per-user Run entry MUST be removed

### Requirement: First-run onboarding commits only on explicit completion

The first-run dialog SHALL expose autostart, correction-sound enabled state, and correction volume before normal activation. Closing or cancelling the first-run dialog MUST abort that startup without recording onboarding as completed, so the choices are requested again on the next launch.

#### Scenario: User closes first-run dialog

- **WHEN** the user closes first-run without confirming
- **THEN** G-switcher MUST stop that startup, MUST NOT mark onboarding complete, and MUST show first-run choices again on the next launch

#### Scenario: User completes first-run

- **WHEN** the user confirms valid first-run choices
- **THEN** G-switcher SHALL persist those explicit choices and proceed with normal startup

### Requirement: Settings validates hotkeys before persistence

Settings MUST reject malformed or duplicate action hotkeys and MUST NOT persist a partially invalid mapping.

#### Scenario: Duplicate hotkey detected

- **WHEN** two actions are assigned the same effective combination
- **THEN** Save MUST be blocked with a local warning until the mapping is made unambiguous

### Requirement: Settings layout remains usable on the baseline desktop target

The 2.0.1 Settings client area SHALL be 900x680 and SHALL fit the complete supported controls without clipping on a typical 1366x768 Windows desktop work area with a taskbar. Read-only application-mode lists MUST avoid misleading non-functional scrolling while the editable dictionary SHALL retain normal scrolling.

#### Scenario: Baseline desktop work area

- **WHEN** Settings opens on a typical 1366x768 desktop work area with a taskbar
- **THEN** the complete Settings form SHALL remain usable without controls being clipped by the work area

### Requirement: Product version and branding are derived consistently

First-run and Settings SHALL identify the current package/application version dynamically where version text is shown, and the Settings window SHALL use the G-switcher application icon/branding rather than stale product names.

#### Scenario: 2.0.1 build opens Settings

- **WHEN** the 2.0.1 package displays its Settings build/version label
- **THEN** the visible version SHALL identify `2.0.1`

### Requirement: Startup failures are visible despite GUI subsystem

If G-switcher cannot complete startup, it MUST present an actionable local Windows error indication rather than failing silently solely because the release executable uses the Windows GUI subsystem.

#### Scenario: Startup initialization fails

- **WHEN** a fatal startup error prevents normal operation
- **THEN** G-switcher SHALL show a native/local error message to the user and SHALL NOT pretend that startup succeeded

### Requirement: UI communicates privacy boundaries accurately

Settings SHALL state that detector context is volatile and SHALL describe secure-input protection without implying broader control support than G-switcher can verify.

#### Scenario: User reviews Settings privacy text

- **WHEN** Settings describes detector context and secure fields
- **THEN** the wording SHALL identify volatile context and SHALL scope secure-input protection to protected/verified targets rather than promising universal application support
