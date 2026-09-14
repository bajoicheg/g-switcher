# Detector and Context Specification

## Purpose

Define Detector v3's conservative decision contract, lexical evidence, generated frequency data boundaries, sensitivity profiles, volatile context, user-dictionary effects, collision handling, and Code-safe protection against false-positive automatic corrections.

## Requirements

### Requirement: Automatic detection is conservative and fail-open

Detector v3 SHALL perform automatic correction only when the opposite-layout interpretation reaches the confidence threshold for the active sensitivity profile or is a deterministic recognized target. Ambiguous evidence MUST leave the source token unchanged.

#### Scenario: Ambiguous token

- **WHEN** both the typed token and its opposite-layout interpretation remain plausible and no deterministic target rule resolves the ambiguity
- **THEN** Detector v3 MUST preserve the typed token unchanged

#### Scenario: Deterministic recognized target

- **WHEN** the opposite-layout form is an exact recognized target and no higher-precedence source protection applies
- **THEN** Detector v3 SHALL treat the target as maximum-confidence evidence for correction

### Requirement: Exact source protection outranks weaker target evidence

An exact valid source-language system or user-dictionary match MUST protect the typed token from automatic rewriting. Context, n-grams, morphology, and generated frequency evidence MUST NOT override exact source protection.

#### Scenario: Exact valid source word

- **WHEN** a typed token exactly matches a protected source-language word
- **THEN** automatic correction MUST leave it unchanged even if its opposite-layout form is plausible

#### Scenario: Context favors the opposite language

- **WHEN** the previous volatile context words favor a target-language interpretation but the current token is an exact protected source word
- **THEN** the exact source protection MUST win and the token MUST remain unchanged

### Requirement: Detector evidence combines local lexical and shape signals

Detector v3 SHALL combine exact source protection, exact opposite-layout target recognition, explicit user-dictionary evidence, baked-in RU/EN frequency priors, common n-gram plausibility, morphology/word-shape signals, punctuation penalties, token length, case pattern, Code-safe classification, and at most two volatile completed context words. Runtime detection MUST NOT require a network lookup, cloud model, remote dictionary, or telemetry.

#### Scenario: Common-language target outweighs keyboard noise

- **WHEN** the source sequence is not protected and its opposite-layout form is strongly supported by local frequency and language-shape evidence
- **THEN** Detector v3 SHALL score the target more strongly than keyboard-layout noise without contacting any external service

#### Scenario: N-grams alone are insufficient to defeat source protection

- **WHEN** common target-language n-grams favor conversion but the source token has exact source protection
- **THEN** the token MUST remain unchanged

### Requirement: Generated frequency layer is pinned and conservative

The 2.0.1 baseline SHALL use the pinned OpenSubtitles2018-derived generated layer containing 56,036 normalized RU/EN source forms of four or more letters and 26,990 deterministically restorable target forms. Generated three-letter forms and generated prefixes shorter than four letters SHALL remain excluded from deterministic promotion. Generated-vs-generated cross-layout collisions MUST fail open.

#### Scenario: Generated four-plus-letter target

- **WHEN** a four-or-more-letter opposite-layout form is in the pinned deterministic generated target set and no higher-precedence source protection applies
- **THEN** Detector v3 MAY use that evidence as deterministic target recognition under the 2.0.1 rules

#### Scenario: Ambiguous generated three-letter form

- **WHEN** only an excluded generated three-letter target would justify automatic correction
- **THEN** Detector v3 MUST NOT promote it solely from the generated layer

#### Scenario: Generated cross-layout collision

- **WHEN** both generated interpretations collide without a higher-precedence curated/source decision
- **THEN** Detector v3 MUST fail open and preserve the typed token

### Requirement: Sensitivity changes heuristic threshold only

G-switcher SHALL expose `Conservative`, `Normal`, and `Aggressive` sensitivity profiles. `Normal` SHALL be the default. The Conservative threshold MUST be strictly higher than Normal, and Normal MUST be strictly higher than Aggressive. Sensitivity MUST NOT disable exact source protection, Code-safe protection, or secure-input protection.

#### Scenario: New configuration

- **WHEN** a new or upgraded configuration has no explicit sensitivity value
- **THEN** G-switcher SHALL use `Normal`

#### Scenario: Sensitivity is changed

- **WHEN** the user saves a different sensitivity profile
- **THEN** the new heuristic threshold SHALL take effect without requiring application restart

#### Scenario: Aggressive profile in secure input

- **WHEN** the active profile is `Aggressive` and the focused target is protected secure input
- **THEN** secure-input exclusion MUST still prevent processing and mutation

### Requirement: Context is bounded, volatile, and non-authoritative

Detector context SHALL contain at most two immediately previous completed words in process memory only. Relevant focus/process/control changes, Pause, secure-input entry, Undo, and other context-invalidating events MUST clear it. Context MAY influence heuristic scoring but MUST NOT by itself force a correction or override exact source protection.

#### Scenario: Two-word bound

- **WHEN** more than two words have been completed in one valid context
- **THEN** Detector v3 MUST retain no more than the two immediately previous context words for scoring

#### Scenario: Focus changes

- **WHEN** focus/process context changes
- **THEN** retained detector context MUST be cleared before evaluating text in the new context

#### Scenario: Context alone favors conversion

- **WHEN** opposite-language context is the only meaningful evidence for conversion
- **THEN** the current token MUST remain unchanged unless the normal confidence rules independently accept the correction

### Requirement: User dictionary is explicit only

The user dictionary SHALL contain only words explicitly entered by the user. Normal typing MUST NOT automatically learn or persist new dictionary entries. An exact source dictionary match MUST protect the source, while an exact opposite-layout mapping to an explicit dictionary word SHALL receive maximum target confidence subject to higher-priority safety rules.

#### Scenario: Correct dictionary source word

- **WHEN** a typed token exactly matches an explicit user-dictionary word in its own layout
- **THEN** automatic correction MUST preserve it

#### Scenario: Wrong-layout form maps to dictionary target

- **WHEN** an opposite-layout candidate maps exactly to an explicit user-dictionary word and no safety rule blocks mutation
- **THEN** that target SHALL receive maximum confidence

#### Scenario: Ordinary typing

- **WHEN** the user types a word not already present in the explicit dictionary
- **THEN** G-switcher MUST NOT persist that word into the dictionary automatically

### Requirement: Code-safe tokens are protected from automatic correction

Automatic correction MUST be suppressed for tokens that resemble technical identifiers, including common URL, email, absolute path, IP/CIDR, GUID/UUID, hexadecimal/hash, variable-name, command-line-switch, or mixed alphanumeric forms. Digits and common technical separators SHALL remain available to the classifier long enough to avoid misleading fragment scoring. Refusal MUST preserve the original token.

#### Scenario: Technical token

- **WHEN** the current candidate is classified as Code-safe
- **THEN** Detector v3 MUST NOT perform confidence-based automatic correction and MUST preserve the token unchanged

#### Scenario: Explicit manual action on non-secure Code-safe text

- **WHEN** the user explicitly requests manual conversion of a Code-safe token in a supported non-secure target and application mode permits manual actions
- **THEN** Code-safe automatic protection MUST NOT by itself prohibit that explicit manual action

### Requirement: Regression targets and protected collisions remain stable

The 2.0.1 baseline SHALL retain deterministic correction coverage for the reviewed corpus additions without lowering global confidence thresholds, and SHALL retain documented valid-source/short collision protections as fail-open cases.

#### Scenario: Reviewed Russian target regression

- **WHEN** a reviewed wrong-layout regression such as `cbcntv`, `ghjuhfvv`, or `bycnherwbb` is evaluated under the accepted 2.0.1 conditions
- **THEN** it SHALL restore respectively to `систем`, `программ`, or `инструкции`

#### Scenario: Protected valid English collision

- **WHEN** a documented valid English source/collision token such as `dyer`, `ytd`, or `cnf` is typed correctly
- **THEN** Detector v3 MUST preserve it unchanged
