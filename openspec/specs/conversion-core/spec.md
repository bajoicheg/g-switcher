# Conversion Core Specification

## Purpose

Define the user-visible Russian/English physical-keyboard-layout conversion contract, including token boundaries, punctuation preservation, case preservation, target layout handling, and conservative behavior when a safe correction cannot be established.

## Requirements

### Requirement: Supported layout pair

G-switcher SHALL automatically convert only between the Russian and English keyboard layouts. Text entered under any other active layout MUST remain unchanged by automatic conversion.

#### Scenario: English-layout text maps to Russian

- **WHEN** the user types `ghbdtn ` under the English layout in a supported verified text target
- **THEN** G-switcher SHALL produce `привет ` and select/confirm the Russian target layout for the focused input context

#### Scenario: Russian-layout text maps to English

- **WHEN** the user types `руддщ ` under the Russian layout in a supported verified text target
- **THEN** G-switcher SHALL produce `hello ` and select/confirm the English target layout for the focused input context

#### Scenario: Unsupported active layout

- **WHEN** the active input layout is neither Russian nor English
- **THEN** automatic conversion MUST leave the user's text unchanged

### Requirement: Physical-key mapping preserves intended token content

G-switcher SHALL interpret a candidate through the physical RU/EN key mapping rather than by transliteration. Space, Enter, Tab, and supported punctuation boundaries SHALL preserve their delimiter semantics after a successful correction.

#### Scenario: Space-delimited word

- **WHEN** `rjhj,rf ` is completed under the wrong layout
- **THEN** G-switcher SHALL produce `коробка `, preserving the trailing space

#### Scenario: Embedded OEM key belongs to the opposite-layout word

- **WHEN** `cdj,jle ` is completed under the English layout
- **THEN** G-switcher SHALL produce `свободу ` and MUST treat the physical comma key inside the candidate as Russian `б`, not as an early token boundary

#### Scenario: Punctuation terminates the corrected word

- **WHEN** the user completes `rjhj,jxrf.` under the wrong layout
- **THEN** G-switcher SHALL produce `коробочка.` with the final period preserved exactly once

#### Scenario: Punctuation-looking OEM key can start an opposite-layout candidate

- **WHEN** the user types `,kz` in a context where the physical-key sequence is recognized as an opposite-layout target
- **THEN** G-switcher SHALL be able to produce `бля` rather than discarding the leading OEM key as punctuation

### Requirement: Delimiters and punctuation are never lost on refusal

If automatic conversion is refused or cannot be completed safely, G-switcher MUST preserve the original typed token and its delimiter or punctuation without swallowing, duplicating, or reordering characters.

#### Scenario: Failed correction at punctuation

- **WHEN** a candidate reaches punctuation but the correction is refused
- **THEN** the original candidate and punctuation MUST remain in the focused control unchanged

#### Scenario: Failed correction at whitespace boundary

- **WHEN** a candidate reaches Space, Enter, or Tab but no safe correction is accepted
- **THEN** the original candidate and the user's boundary input MUST be preserved

### Requirement: Case pattern is preserved

For supported conversions, G-switcher SHALL preserve lowercase, Initial-capital, and ALL-CAPS patterns when mapping the token to the opposite layout. Mixed-case technical-looking forms SHALL remain subject to conservative Code-safe protection rather than forced normalization.

#### Scenario: Lowercase conversion

- **WHEN** a lowercase wrong-layout token is corrected
- **THEN** the corrected token SHALL remain lowercase

#### Scenario: Initial-capital conversion

- **WHEN** a wrong-layout token has an initial capital and otherwise lowercase letters
- **THEN** the corrected token SHALL preserve that Initial-capital pattern

#### Scenario: All-caps conversion

- **WHEN** a wrong-layout token is all caps
- **THEN** the corrected token SHALL be all caps

### Requirement: Correction applies only to the verified focused input context

A successful conversion SHALL target the actual focused input control and the exact candidate range that was validated for the operation. G-switcher MUST NOT use a top-level foreground window alone as sufficient proof of the mutation target.

#### Scenario: Focused child control receives correction

- **WHEN** a top-level application window contains multiple controls and one supported input control has focus
- **THEN** the correction SHALL affect only the verified focused input control and exact candidate range

#### Scenario: Target context cannot be verified

- **WHEN** the focused control or exact replacement range cannot be verified at execution time
- **THEN** conversion MUST fail open and leave the user's text unchanged

### Requirement: Target layout is selected deliberately

After a confirmed successful conversion, G-switcher SHALL request the concrete target RU/EN input locale for the focused context and confirm the resulting layout state as required by the supported mutation path. It MUST NOT depend on the user's configured Windows layout-toggle shortcut.

#### Scenario: User has a custom Windows layout shortcut

- **WHEN** the user has configured any Windows shortcut for switching layouts
- **THEN** G-switcher SHALL still perform correction by selecting the intended target layout directly rather than replaying that shortcut

#### Scenario: Target layout cannot be established safely

- **WHEN** the required target layout cannot be established or verified for the current focused context
- **THEN** G-switcher MUST fail open rather than committing an unverified correction
