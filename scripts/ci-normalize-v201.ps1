$ErrorActionPreference = 'Stop'

$path = 'src/windows_runtime_v201.rs'
$text = Get-Content -LiteralPath $path -Raw

$pattern = 'fn invalidates_context\(vk: u16, modifiers: Modifiers\) -> bool \{\s*matches!\('
$replacement = @'
fn invalidates_context(vk: u16, modifiers: Modifiers) -> bool {
    // Modifier key-down events are part of our hotkey chords. Invalidating the
    // generation on Ctrl/Shift/Alt itself would erase the candidate/previous
    // token before the actual hotkey key arrives.
    if is_modifier_vk(vk) {
        return false;
    }
    matches!(
'@

$updated = [regex]::Replace($text, $pattern, $replacement, 1)
if ($updated -eq $text -and $text -notmatch 'if is_modifier_vk\(vk\)') {
    throw 'Could not locate invalidates_context() for the 2.0.1 hotkey fix.'
}

$e2eMarker = @'
#[cfg(test)]
#[path = "windows_runtime/e2e_tests.rs"]
mod e2e_tests;
'@
$crossProcessModule = @'

#[cfg(test)]
#[path = "windows_runtime/cross_process_e2e.rs"]
mod cross_process_e2e;
'@
if ($updated -notmatch 'mod cross_process_e2e;') {
    if (-not $updated.Contains($e2eMarker)) {
        throw 'Could not locate E2E module marker for cross-process gate.'
    }
    $updated = $updated.Replace($e2eMarker, $e2eMarker + $crossProcessModule)
}

if ($updated -ne $text) {
    Set-Content -LiteralPath $path -Value $updated -Encoding utf8 -NoNewline
}

$lockPath = 'Cargo.lock'
$lock = Get-Content -LiteralPath $lockPath -Raw
$lockUpdated = [regex]::Replace(
    $lock,
    '(?ms)(\[\[package\]\]\s*name = "g-switcher"\s*version = ")2\.0\.0("\s*)',
    '${1}2.0.1${2}',
    1
)
if ($lockUpdated -eq $lock -and $lock -notmatch '(?ms)name = "g-switcher"\s*version = "2\.0\.1"') {
    throw 'Could not synchronize g-switcher version in Cargo.lock.'
}
if ($lockUpdated -ne $lock) {
    Set-Content -LiteralPath $lockPath -Value $lockUpdated -Encoding utf8 -NoNewline
}

cargo fmt --all
