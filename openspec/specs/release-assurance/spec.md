# Release Assurance Specification

## Purpose

Define the evidence required to promote a G-switcher release, preserving automated Windows safety gates, locked/reproducible build checks, artifact integrity, malware-scan evidence, and the independent manual real-application compatibility gate.

## Requirements

### Requirement: Release builds use the reviewed locked dependency graph

Release CI SHALL build from the reviewed source revision using the committed Rust dependency lockfile and locked dependency resolution. Normalization or hardening checks that run before build MUST leave the checked-out source revision unchanged.

#### Scenario: Release CI resolves Rust dependencies

- **WHEN** the release candidate is built in CI
- **THEN** Cargo dependency resolution MUST use the committed lockfile with locked resolution rather than silently updating dependency versions

#### Scenario: Pre-build normalization is checked

- **WHEN** CI executes normalization or hardening verification
- **THEN** the checked-out candidate tree MUST remain unchanged before compilation and packaging

### Requirement: Static quality gates are mandatory

Release CI MUST run the repository's required formatting, unit/integration tests, regression suites, and Clippy with warnings denied before accepting the release build as an automated candidate.

#### Scenario: Clippy warning is introduced

- **WHEN** Clippy reports a warning under the release configuration
- **THEN** the automated release gate MUST fail rather than accepting a warning-bearing candidate

#### Scenario: Regression test fails

- **WHEN** any required unit/integration/corpus regression fails
- **THEN** the candidate MUST NOT be considered automated-gate complete

### Requirement: Windows end-to-end mutation paths are release-gated

The automated Windows release gate SHALL exercise the real path from keyboard/input dispatch through context validation and verified replacement in supported Win32 controls. It SHALL include same-process coverage and separate-process Edit/RichEdit/password coverage for the behaviors claimed by the release.

#### Scenario: Separate-process Edit gate

- **WHEN** the mandatory separate-process Edit E2E runs
- **THEN** it SHALL cover the applicable automatic correction, manual conversion, selected-text, Undo, context/focus safety, and verified replacement behavior required by the current release

#### Scenario: Password fixture gate

- **WHEN** the separate-process password fixture is exercised
- **THEN** automated evidence SHALL confirm that protected input remains unchanged and that the secure-input decision includes native and UIA `IsPassword` protection as applicable

### Requirement: Hook stress and failure-path gates are mandatory

Release CI SHALL include the reviewed 100,000-callback stress sequence and the dedicated hung/closing-target failure-path E2E. Stress MUST demonstrate zero dropped events, the required callback-latency distribution, and continued operation afterward. Failure paths MUST leave target text unchanged within bounded time and MUST demonstrate recovery with a fresh responsive target.

#### Scenario: Hook stress gate

- **WHEN** at least 100,000 low-level callback events are delivered by the mandatory stress harness
- **THEN** zero events MUST be dropped, at least 99% of callbacks MUST complete at or below 10 ms, and the hook MUST still receive a subsequent probe event

#### Scenario: Hung target gate

- **WHEN** the failure harness blocks a target UI thread during a verified mutation attempt
- **THEN** the operation MUST fail within the bounded gate timeout and the original target text MUST remain unchanged after recovery

#### Scenario: Closing target gate

- **WHEN** the failure harness terminates the target process while a verified mutation is pending
- **THEN** the operation MUST fail within the bounded gate timeout, MUST NOT mutate a newly focused control, and a fresh supported target MUST remain usable afterward

### Requirement: Browser adapter evidence remains scoped to the tested control classes

Automated Edge/Chrome adapter tests MAY establish evidence for the specific ordinary input/textarea or other explicitly exercised browser field classes. Such tests MUST NOT be interpreted as full compatibility evidence for arbitrary contenteditable controls, Word PWA, Electron applications, desktop Office, Telegram, Visual Studio Code, or Windows Terminal.

#### Scenario: Browser adapter test passes

- **WHEN** the real Edge/Chrome adapter test passes for an ordinary tested input class
- **THEN** CI MAY record that adapter/class evidence but MUST NOT generalize the result to untested application/control classes

### Requirement: Release binary and package are checked for expected identity

The built production executable SHALL be checked for the Windows GUI subsystem, the intended G-switcher version/branding metadata, and the absence of forbidden stale product residue defined by the release checks. Packaged release contents MUST correspond to the reviewed candidate revision.

#### Scenario: Version metadata is stale

- **WHEN** the built executable or package metadata does not identify the intended release version
- **THEN** the release gate MUST fail

#### Scenario: Wrong subsystem is built

- **WHEN** the production executable is not built as the expected Windows GUI subsystem binary
- **THEN** the release gate MUST fail

### Requirement: Artifact integrity and provenance are recorded

CI SHALL record SHA-256 integrity information for the standalone executable and packaged Windows artifact and SHALL preserve enough build provenance to tie those artifacts to the reviewed source revision and workflow run.

#### Scenario: Candidate artifact is packaged

- **WHEN** CI creates the release-candidate executable and ZIP/package
- **THEN** SHA-256 evidence SHALL be produced and the artifact provenance SHALL identify the exact source revision used for the build

#### Scenario: Packaged executable differs from reviewed build output

- **WHEN** integrity comparison detects that packaged or duplicated candidate executables differ unexpectedly
- **THEN** the candidate MUST NOT be promoted

### Requirement: Malware-scan evidence is part of the candidate record

The release workflow SHALL include the configured Windows Defender or equivalent repository-approved malware scan of the candidate release executables and SHALL retain the result as candidate evidence. A clean scan is evidence for that exact artifact only and MUST NOT be represented as a universal SmartScreen/EDR reputation guarantee.

#### Scenario: Defender flags the candidate

- **WHEN** the configured malware scan detects a threat in a release executable
- **THEN** promotion MUST be blocked pending investigation and a new reviewed candidate

#### Scenario: Defender reports no threats

- **WHEN** the scan reports no threats for the candidate executable
- **THEN** that result MAY be recorded as evidence for the scanned artifact but MUST NOT be described as guaranteeing absence of SmartScreen or third-party EDR warnings on other systems

### Requirement: Green CI alone is not sufficient for public promotion

A fully green automated CI run is necessary but NOT sufficient to authorize public promotion while required manual compatibility evidence remains incomplete. `COMPATIBILITY_2.0.1.md` or the corresponding release-specific successor SHALL remain an independent release gate for the applications and scenarios claimed by that release.

#### Scenario: Automated CI is green but manual rows are pending

- **WHEN** all automated jobs pass but one or more required manual compatibility rows remain `PENDING` or otherwise incomplete
- **THEN** the release MUST remain unpromoted/draft

#### Scenario: Automated CI is green and an application failed manually

- **WHEN** required manual testing records a behavior that corrupts text, changes the wrong target/layout, touches protected input, or otherwise violates a requirement
- **THEN** public promotion MUST be blocked regardless of automated CI status

### Requirement: Manual result semantics distinguish safety from compatibility

Manual compatibility evidence SHALL distinguish `PASS`, `UNSUPPORTED/FAIL-OPEN`, `PENDING`, `FAIL`, and genuinely applicable `N/A` outcomes according to the release matrix. `UNSUPPORTED/FAIL-OPEN` SHALL mean that original input was preserved without destructive behavior, but it MUST NOT by itself be counted as functional support.

#### Scenario: Unsupported custom control safely no-ops

- **WHEN** a control is explicitly outside the supported claim and G-switcher safely preserves the input without mutation
- **THEN** the result MAY be recorded as `UNSUPPORTED/FAIL-OPEN` but MUST NOT be represented as `PASS`

#### Scenario: Required supported application safely no-ops

- **WHEN** a mainstream application/control is part of the intended support claim and its required conversion operations merely no-op safely
- **THEN** that outcome MUST remain a release blocker rather than being upgraded to functional `PASS`

### Requirement: Edge and Chrome ordinary editable fields require functional PASS for 2.0.1 promotion

For the G-switcher 2.0.1 public compatibility claim, ordinary editable fields in Microsoft Edge and Google Chrome MUST pass the required Auto, Manual current-word, Selected-text, and Undo scenarios. Safe no-op `UNSUPPORTED/FAIL-OPEN` in those ordinary fields is not sufficient for promotion. Protected password/sensitive fields are expected to remain unchanged.

#### Scenario: Edge ordinary field is fail-open only

- **WHEN** Edge ordinary editable fields preserve input but do not perform the required Auto/Manual/Selected/Undo operations
- **THEN** the Edge compatibility row MUST remain a 2.0.1 release blocker

#### Scenario: Chrome protected field remains unchanged

- **WHEN** Chrome password/sensitive-field testing confirms no text mutation and no layout change
- **THEN** that protected-field behavior SHALL count as the expected security PASS for that scenario, independently of ordinary-field functionality

### Requirement: Manual evidence identifies the actual tested environment

Required application compatibility rows SHALL record the actual tested application version and Windows build. Placeholder values such as `UNKNOWN`, `NOT INSTALLED`, or an unrelated application's version MUST NOT satisfy the release gate.

#### Scenario: Desktop Word row lacks an actual desktop Word test

- **WHEN** only Word PWA/browser behavior has been observed but the release requires Microsoft Word desktop compatibility evidence
- **THEN** the desktop Word row MUST remain incomplete and the PWA observation MUST NOT be substituted for it

### Requirement: Existing security and release gates cannot be implicitly weakened by spec tooling

OpenSpec validation, change verification, or archival SHALL be additive process controls. They MUST NOT replace required Rust tests, Windows E2E, stress/failure-path tests, provenance, malware scanning, binary/package checks, or manual compatibility evidence.

#### Scenario: OpenSpec strict validation passes

- **WHEN** all OpenSpec artifacts validate successfully but a required Windows or manual gate is incomplete or failing
- **THEN** the release MUST remain blocked

#### Scenario: Release gates are proposed for removal

- **WHEN** a future change would remove or weaken an existing mandatory release/security gate
- **THEN** that change MUST explicitly modify this capability through an approved proposal/spec delta rather than being introduced silently through CI refactoring
