# Correction Feedback Specification

## Purpose

Define the local correction sound contract so audible feedback occurs only for confirmed successful conversions, remains user-configurable, does not expose text content, and never changes system-wide audio settings.

## Requirements

### Requirement: Sound is emitted only after confirmed successful conversion

When correction sound is enabled and effective volume is above 0%, G-switcher SHALL play exactly one short local signal after a confirmed successful automatic correction, current-word conversion, previous-word conversion, or selected-text conversion. It MUST NOT play the correction signal for refused, failed, or unverified operations.

#### Scenario: Confirmed automatic correction

- **WHEN** an automatic correction completes successfully and is verified
- **THEN** G-switcher SHALL play one correction signal if sound is enabled and volume is above 0%

#### Scenario: Confirmed manual conversion

- **WHEN** a current-word, previous-word, or selected-text conversion completes successfully and is verified
- **THEN** G-switcher SHALL play one correction signal if sound is enabled and volume is above 0%

#### Scenario: Refused conversion

- **WHEN** a conversion is refused because confidence, safety, adapter, context, or verification requirements are not met
- **THEN** G-switcher MUST remain silent for that attempted conversion

### Requirement: Undo, Pause, and secure-input actions are silent

The correction signal MUST NOT be emitted for Undo, entering or leaving Pause, secure-input exclusion, or an action that produces no confirmed text conversion.

#### Scenario: Undo succeeds

- **WHEN** the user successfully restores original text through Undo
- **THEN** G-switcher MUST NOT play the correction signal

#### Scenario: Secure field blocks an action

- **WHEN** a conversion hotkey is invoked in protected secure input and the action is blocked
- **THEN** G-switcher MUST remain silent

#### Scenario: Pause is toggled

- **WHEN** the user pauses or resumes G-switcher
- **THEN** correction feedback MUST NOT be emitted merely for the mode change

### Requirement: Default correction sound is enabled at 20%

A new configuration SHALL default correction sound to enabled with a volume setting of 20%. First-run and Settings SHALL both expose the enabled state and the user-adjustable volume.

#### Scenario: New configuration

- **WHEN** G-switcher creates a new configuration with no prior sound settings
- **THEN** correction sound SHALL be enabled and the configured volume SHALL be 20%

### Requirement: Volume range is 0-100% in 5% steps

The exposed correction volume SHALL range from 0% through 100% in 5% steps. Values above 100% MUST be clamped to the maximum effective amplitude. An effective volume of 0% MUST result in no playback even if the sound-enabled setting is true.

#### Scenario: User selects 0%

- **WHEN** correction sound is enabled but the saved effective volume is 0%
- **THEN** successful corrections MUST produce no audible playback

#### Scenario: User selects a normal step

- **WHEN** the user selects 35% in the supported UI
- **THEN** G-switcher SHALL use 35% as the correction waveform amplitude setting

#### Scenario: Out-of-range value reaches runtime

- **WHEN** an input value above 100% is encountered
- **THEN** effective playback amplitude MUST be clamped to the 100% maximum rather than overflowing or increasing system master volume

### Requirement: Correction audio is generated locally in memory

The correction signal SHALL be a short PCM waveform generated/cached in process memory. Runtime playback MUST NOT require an external audio asset, network request, cloud service, or recorded user content, and MUST NOT write a generated audio file as part of normal playback.

#### Scenario: Offline playback

- **WHEN** a successful correction occurs while the computer has no network connectivity
- **THEN** the configured correction signal SHALL remain available without any network access

#### Scenario: User text differs

- **WHEN** different words or selected text are corrected successfully
- **THEN** the audio bytes MUST remain independent of the typed or selected text content

### Requirement: Volume affects only generated waveform amplitude

Changing G-switcher's correction volume SHALL affect the generated PCM sample amplitude only. G-switcher MUST NOT change the Windows master volume or another application's audio level.

#### Scenario: Correction volume changes

- **WHEN** the user changes G-switcher correction volume from 20% to 60%
- **THEN** the generated signal peak amplitude SHALL increase accordingly while the Windows master volume remains unchanged

### Requirement: Generated waveform is bounded and valid

The generated sound data SHALL use a valid RIFF/WAVE representation compatible with the chosen local playback path and SHALL have a bounded short duration appropriate for unobtrusive correction feedback.

#### Scenario: Waveform is generated

- **WHEN** G-switcher prepares the in-memory correction signal
- **THEN** the resulting data SHALL contain a valid RIFF/WAVE header and a bounded payload rather than unbounded or text-derived audio data
