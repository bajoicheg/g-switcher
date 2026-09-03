$ErrorActionPreference = 'Stop'

function Replace-Required([string]$Path, [string]$Old, [string]$New) {
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $text.Contains($Old)) { throw "Expected text not found in $Path" }
    $text = $text.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $text -Encoding UTF8 -NoNewline
}

foreach ($path in @('Cargo.toml', 'src/lib.rs', 'build.rs', 'scripts/release-check.ps1')) {
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $text = $text.Replace('1.0.2', '1.0.3')
    Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline
}

Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'GSwitcher.Settings.1.0.2' 'GSwitcher.Settings.1.0.3'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'Настройки G-switcher 1.0.2' 'Настройки G-switcher 1.0.3'

$readme = Get-Content -LiteralPath 'README.md' -Raw -Encoding UTF8
$readme = $readme.Replace('Version 1.0.2 is a focused UI hardening release. It fixes text clipping and overlapping labels observed on real Windows while preserving the Detector v3, expanded RU/EN lexicons and runtime behavior from 1.0.1.', 'Version 1.0.3 is a runtime reliability patch. It prevents destructive truncation when Windows accepts only part of a SendInput correction batch, and locks `rjhj,jxrf.` → `коробочка.` as a detector and real Win32 regression.')
$readme = $readme.Replace('## 1.0.2 behavior', '## 1.0.3 behavior')
$readme = $readme.Replace('- OEM-key candidate tracking supports words whose opposite-layout form begins with punctuation-looking keys, including `,kz` → `бля`, while retaining `rjhj,rf` → `коробка` and `cdj,jle` → `свободу` behavior.', '- OEM-key candidate tracking supports words whose opposite-layout form begins with punctuation-looking keys, including `,kz` → `бля`, `rjhj,rf` → `коробка`, `rjhj,jxrf.` → `коробочка.` and `cdj,jle` → `свободу`.')
$readme = $readme.Replace('- Standard-user operation with fail-open input behavior.', '- Partial `SendInput` delivery resumes from the first unsent INPUT instead of abandoning a correction after already-delivered Backspace events; zero initial progress still fails open without modifying text.`r`n- Standard-user operation with fail-open input behavior.')
$readme = $readme.Replace('G-switcher 1.0.2 version metadata', 'G-switcher 1.0.3 version metadata')
Set-Content -LiteralPath 'README.md' -Value $readme -Encoding UTF8 -NoNewline

$spec = Get-Content -LiteralPath 'docs/FUNCTIONAL_SPEC.md' -Raw -Encoding UTF8
$spec = $spec.Replace('G-switcher 1.0.2 functional specification', 'G-switcher 1.0.3 functional specification')
$spec = $spec.Replace('Version 1.0.2 stores explicit per-user hotkey definitions', 'Version 1.0.3 stores explicit per-user hotkey definitions')
$spec = $spec.Replace('This is required for cases such as English-layout `,kz` → Russian `бля`, where the first physical key normally produces a comma in English but `б` in Russian.', 'This is required for cases such as English-layout `,kz` → Russian `бля` and `rjhj,jxrf.` → `коробочка.`, where OEM punctuation-looking keys participate in the opposite-layout word.')
$spec = $spec.Replace('Backspace updates the current candidate state instead of discarding all prior context.', 'Correction injection is loss-aware: if Windows accepts only part of a `SendInput` batch, G-switcher resumes from the first unsent INPUT with bounded retries instead of abandoning the batch after already-delivered Backspace events. If the initial `SendInput` call makes zero progress, the correction fails open before any synthetic deletion is delivered.`r`n`r`nBackspace updates the current candidate state instead of discarding all prior context.')
Set-Content -LiteralPath 'docs/FUNCTIONAL_SPEC.md' -Value $spec -Encoding UTF8 -NoNewline

$accept = Get-Content -LiteralPath 'docs/ACCEPTANCE_TESTS.md' -Raw -Encoding UTF8
$accept = $accept.Replace('# G-switcher 1.0.0 acceptance tests', '# G-switcher 1.0.3 acceptance tests')
$accept = $accept.Replace('- `rjhj,rf ` → `коробка `', '- `rjhj,rf ` → `коробка `
- `rjhj,jxrf.` → `коробочка.`')
$accept = $accept.Replace('- immediate Undo restores original text and source layout', '- immediate Undo restores original text and source layout
- simulated partial `SendInput` delivery resumes from the exact unsent INPUT tail; zero initial delivery fails without destructive progress')
Set-Content -LiteralPath 'docs/ACCEPTANCE_TESTS.md' -Value $accept -Encoding UTF8 -NoNewline

$security = Get-Content -LiteralPath 'docs/SECURITY_MODEL.md' -Raw -Encoding UTF8
$security = $security.Replace('# G-switcher 1.0.0 security model', '# G-switcher 1.0.3 security model')
$security = $security.Replace('- Input injection failures are fail-open for the user''s original keystroke where Windows permits safe recovery.', '- Input injection failures are fail-open for the user''s original keystroke where Windows permits safe recovery. Partial `SendInput` batches are continued from the exact unsent INPUT with bounded retries so already-delivered Backspace events are not silently abandoned.')
$security = $security.Replace('- The `v1.0.0` publication workflow', '- The `v1.0.3` publication workflow')
Set-Content -LiteralPath 'docs/SECURITY_MODEL.md' -Value $security -Encoding UTF8 -NoNewline

$changelog = Get-Content -LiteralPath 'CHANGELOG.md' -Raw -Encoding UTF8
$entry = @'
## 1.0.3 — 2026-09-03

- Fixes destructive truncation when Windows accepts only part of a correction `SendInput` batch: delivery now resumes from the first unsent INPUT with bounded retry instead of abandoning already-started Backspace/retype sequences.
- Keeps zero-progress injection fail-open: if the first `SendInput` call inserts nothing, the original text is left untouched.
- Adds `коробочка` to deterministic local target recognition and locks `rjhj,jxrf.` → `коробочка.` in detector and real Win32 E2E coverage.
- Adds pure regression tests for partial/zero-progress input delivery.
- Updates package/Windows metadata, release checks, CI artifact naming and gated release automation to 1.0.3.

## 1.0.2 — 2026-09-03

- Hardens the Settings layout against clipping by increasing the client area and reserving dedicated multi-line regions for sensitivity and Pause help.
- Shortens long Russian UI labels and moves footer controls down to keep spacing stable on real Windows.
- Adds more bottom room to the first-run window while preserving 1.0.1 detector/runtime behavior.
- Updates package/Windows metadata, release checks, CI artifact naming and gated release automation to 1.0.2.

'@
if (-not $changelog.StartsWith("# Changelog`n`n")) { throw 'Unexpected CHANGELOG header' }
$changelog = "# Changelog`n`n" + $entry + $changelog.Substring("# Changelog`n`n".Length)
Set-Content -LiteralPath 'CHANGELOG.md' -Value $changelog -Encoding UTF8 -NoNewline
