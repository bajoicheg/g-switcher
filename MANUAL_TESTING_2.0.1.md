# G-switcher 2.0.1 — manual compatibility test guide

This guide is for the final pre-release compatibility pass on a normal Windows workstation. Do not use real passwords, PINs, OTPs, API keys, or other secrets during testing.

## Test package

Use the checked CI artifact named `g-switcher-2.0.1-manual-compatibility-kit`. It contains:

- `g-switcher.exe` and its SHA-256 sidecar;
- `manual-compatibility-v201.ps1` — interactive result recorder;
- `verify-compatibility-v201.ps1` — strict release-gate validator;
- `COMPATIBILITY_2.0.1.md` — detailed test cases and result semantics;
- this guide.

The executable under test must come from the same CI run as the scripts and documentation in the kit.

## Before testing

1. Close any older G-switcher instance from the tray.
2. Verify `g-switcher.exe` against `g-switcher.exe.sha256`.
3. Start `g-switcher.exe` normally, without Administrator elevation unless the application being tested is itself elevated.
4. Keep the default 2.0.1 settings unless a test case explicitly asks for Manual-only, Disabled, Pause, or a hotkey action.
5. If Windows marked the downloaded ZIP/files as Internet-originated and your policy is `RemoteSigned`, unblock the trusted test-kit files after inspection. For an already extracted kit:

```powershell
Get-ChildItem -File | Unblock-File
```

Do not change machine-wide execution policy.

6. Open Windows PowerShell in the extracted kit directory and start the recorder. PowerShell 7 (`pwsh`) is not required:

```powershell
powershell.exe -NoProfile -File .\manual-compatibility-v201.ps1
```

The recorder is intentionally kept compatible with Windows PowerShell 5.1 and is exercised by that exact host in CI.

## Required applications

Test the following applications on the same Windows build:

- Notepad
- Microsoft Word
- Microsoft Edge
- Google Chrome
- Telegram Desktop
- Visual Studio Code
- Windows Terminal

The recorder attempts to determine application versions automatically. If it cannot, it asks for the exact version manually. `UNKNOWN`, `N/A`, `NOT INSTALLED`, and similar placeholders cannot pass the release gate.

## What to check in each application

Follow the eight cases in `COMPATIBILITY_2.0.1.md`. The essential checks are:

1. Auto correction: `ghbdtn ` under English layout must become `привет ` without changing adjacent text.
2. Manual current word: in Manual-only mode convert `ghbdtn`; then Undo must restore both exact text and source layout.
3. Selected text: select only `ghbdtn rfr ltkf`, convert it, then Undo; nothing outside the selection may change.
4. Caret race: move the caret with mouse/arrows before the boundary action; stale text must not be modified.
5. Focus race: change field/window while a correction could be pending; neither old nor new target may receive a stale mutation.
6. Sensitive field: when the application exposes a password/PIN/credential field, G-switcher actions must not change its text or layout. Use dummy data only.
7. Pause and application modes: verify Pause/Resume plus Auto, Manual-only, and Disabled behavior.
8. Unsupported control: original input must remain intact and the operation must not be silently swallowed.

## Result values

For `Auto`, `Manual current word`, and `Selected text`, record one of:

- `PASS`
- `FAIL`
- `UNSUPPORTED/FAIL-OPEN`
- `PENDING`

`N/A` is intentionally not accepted for these core text operations.

For `Undo` and `Password/sensitive fields`, `N/A` is additionally permitted when genuinely not applicable.

`UNSUPPORTED/FAIL-OPEN` is a positive safety observation: the feature is unsupported in that control, but the original input was preserved and the action was not destructively swallowed. It must not be used merely because a case was not tested.

## Finish

The recorder writes `compatibility-results-2.0.1.md`. Validate it locally:

```powershell
powershell.exe -NoProfile -File .\verify-compatibility-v201.ps1 -Path .\compatibility-results-2.0.1.md
```

A successful validator run means the matrix contains no publication-blocking values. Keep the generated result file; it is the evidence used to update the canonical `COMPATIBILITY_2.0.1.md` before the PR is taken out of Draft and merged.
