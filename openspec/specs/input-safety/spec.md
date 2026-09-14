# Input Safety Specification

## Purpose

Define the safety boundaries that prevent stale, slow, partial, or unverifiable input operations from corrupting user text, including hook-thread isolation, generation-bound state, exact context revalidation, bounded failure behavior, and fail-open recovery.

## Requirements

### Requirement: Low-level hooks perform bounded dispatch only

Low-level keyboard and mouse hooks SHALL execute on a dedicated hook thread. Hook callbacks MUST limit their work to bounded event capture and dispatch; detector scoring, UI Automation, focused-control inspection, and text mutation MUST execute outside the low-level callback.

#### Scenario: Normal keyboard event

- **WHEN** a keyboard event reaches the low-level hook
- **THEN** the callback SHALL capture and dispatch only the bounded information required by the runtime and SHALL return without running detector or mutation logic inline

#### Scenario: Stress sequence

- **WHEN** the mandatory stress gate delivers at least 100,000 hook callbacks
- **THEN** runtime dispatch MUST drop zero events and the hook MUST continue receiving subsequent events after the stress sequence

### Requirement: Mutable text state is generation-bound

Every pending correction, selected-text operation, and Undo record that may mutate text MUST be associated with a context generation. Events that make previously captured state uncertain MUST advance or invalidate that generation before another mutation can use the stale state.

#### Scenario: Focus changes after correction was queued

- **WHEN** a correction is queued and focus changes before execution
- **THEN** the old generation MUST be rejected and the queued correction MUST NOT modify either the newly focused control or the stale control

#### Scenario: Pause is entered with work pending

- **WHEN** Pause is activated while a correction, selection operation, or Undo is pending
- **THEN** the active generation and pending mutation state MUST be invalidated before any such operation can execute

### Requirement: Mutation context is revalidated immediately before use

Before changing text, a mutation-capable operation MUST re-check the relevant current generation, focused HWND/control, process, UI thread, keyboard layout, and exact caret, selection, or replacement-range state required by that operation. A mismatch MUST fail open.

#### Scenario: Caret moved before token correction

- **WHEN** the user moves the caret after the candidate was captured but before correction executes
- **THEN** the correction MUST fail open and MUST NOT alter text at the new caret position

#### Scenario: Selection changed before selected-text conversion

- **WHEN** the selection or verified range differs from the range captured for selected-text conversion
- **THEN** the operation MUST fail open and leave the current text unchanged

#### Scenario: Process or UI thread changed

- **WHEN** the current focused target no longer belongs to the validated process/UI-thread context
- **THEN** the operation MUST fail open rather than transferring mutation intent to the new context

### Requirement: Loss of a verified path never falls through to an unverified path

If the adapter, target, or verification conditions that justified a pending mutation are lost between queueing and execution, G-switcher MUST fail open. It MUST NOT switch to an unverified raw mutation mechanism merely to complete the action.

#### Scenario: Adapter disappears after queueing

- **WHEN** a verified adapter was available during planning but is no longer valid when execution begins
- **THEN** G-switcher MUST leave the text unchanged and MUST NOT attempt an unverified fallback

### Requirement: Partial synthetic input delivery is loss-aware

Where a supported path uses `SendInput`, partial delivery SHALL resume from the exact first unsent INPUT with bounded retries. If the initial call makes zero progress, the operation MUST fail open before any destructive synthetic deletion has been delivered.

#### Scenario: Partial delivery

- **WHEN** Windows accepts only the first part of a synthetic input batch
- **THEN** G-switcher SHALL resume from the exact unsent tail rather than replaying accepted INPUT records or abandoning already-started destructive work

#### Scenario: Zero initial delivery

- **WHEN** the initial `SendInput` call accepts zero INPUT records
- **THEN** G-switcher MUST stop the operation with the original user text intact

### Requirement: Hung or disappearing targets fail within a bounded time

A text target that is hung, closing, disappeared, or otherwise unresponsive MUST be treated as unsupported for the pending operation. Liveness and mutation calls SHALL use bounded behavior so G-switcher does not wait indefinitely or guess about mutation state.

#### Scenario: Hung target UI thread

- **WHEN** a target UI thread fails the bounded liveness check or becomes unresponsive during a verified mutation attempt
- **THEN** the operation MUST return failure within the configured gate bound and the target text MUST remain unchanged after recovery

#### Scenario: Target process closes

- **WHEN** the target process disappears while a verified mutation attempt is pending
- **THEN** the operation MUST fail within the configured gate bound and MUST NOT modify another or newly focused control

### Requirement: Failure does not poison later input processing

After a hung-target, closing-target, stale-context, or other fail-open outcome, G-switcher MUST remain able to process a fresh responsive supported target normally. Failure handling MUST NOT leave global mutation or adapter state corrupted.

#### Scenario: Fresh target after failure

- **WHEN** a prior target failed because it hung or disappeared and the user then focuses a fresh supported Edit control
- **THEN** a normal verified correction/replacement SHALL still be possible in the fresh target

### Requirement: Hook latency remains within the release gate

The release-gate stress test SHALL require at least 99% of low-level hook callbacks to complete at or below 10 ms, zero dropped callback events, and continued hook operation after at least 100,000 delivered callbacks.

#### Scenario: Stress gate meets latency contract

- **WHEN** the release stress harness completes its 100,000-callback sequence
- **THEN** zero callbacks SHALL be reported dropped, at least 99% SHALL be at or below 10 ms, and a subsequent probe event SHALL still be observed
