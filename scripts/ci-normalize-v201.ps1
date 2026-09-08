$ErrorActionPreference = 'Stop'

$path = 'src/windows_runtime_v201.rs'
$text = Get-Content -LiteralPath $path -Raw
$updated = $text.Replace(
    'const SINGLE_INSTANCE_NAME: &str = "Local\\GSwitcher.SingleInstance.v2.0.1";',
    'const SINGLE_INSTANCE_NAME: &str = "Local\\GSwitcher.SingleInstance.v0.8";'
)

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
$updated = [regex]::Replace($updated, $pattern, $replacement, 1)
if ($updated -notmatch 'if is_modifier_vk\(vk\)') {
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

$oldSelectionReplace = 'if !selection::replace_range(target.hwnd, selected.start, selected.end, &corrected) {'
$newSelectionReplace = @'
if !selection::replace_range_if_matches(
            target.hwnd,
            selected.start,
            selected.end,
            &selected.text,
            &corrected,
        ) {
'@
if ($updated.Contains($oldSelectionReplace)) {
    $updated = $updated.Replace($oldSelectionReplace, $newSelectionReplace.TrimEnd("`r", "`n"))
}
if ($updated -notmatch 'selection::replace_range_if_matches') {
    throw 'Could not wire verified selected-text replacement.'
}

$queuePattern = '(?s)(fn queue_correction_parts\(.*?\) -> bool \{\r?\n)(\s*let Some\(target_hkl\))'
$queueInsert = @'
$1        // 2.0.1 fails open for controls without a synchronously verifiable
        // Edit/RichEdit message adapter. UI Automation support is added as a
        // separate adapter; raw SendInput mutation is not allowed to guess.
        if !selection::is_standard_edit(source.hwnd) {
            return false;
        }

$2
'@
if ($updated -notmatch 'raw SendInput mutation is not allowed to guess') {
    $updated = [regex]::Replace($updated, $queuePattern, $queueInsert, 1)
}
if ($updated -notmatch 'if !selection::is_standard_edit\(source\.hwnd\)') {
    throw 'Could not install fail-open mutation gate.'
}

if ($updated -ne $text) {
    Set-Content -LiteralPath $path -Value $updated -Encoding utf8 -NoNewline
}

$selectionPath = 'src/windows_runtime/selection.rs'
$selection = Get-Content -LiteralPath $selectionPath -Raw
$obsoleteWrapper = '(?s)/// Generic verified replacement used only when the current range itself is the\r?\n/// source of truth\..*?\r?\npub fn replace_range\(.*?\r?\n\}\r?\n\r?\n(?=pub fn read_selection_range)'
$selectionUpdated = [regex]::Replace($selection, $obsoleteWrapper, '', 1)
if ($selectionUpdated -ne $selection) {
    Set-Content -LiteralPath $selectionPath -Value $selectionUpdated -Encoding utf8 -NoNewline
}

$crossPath = 'src/windows_runtime/cross_process_e2e.rs'
$cross = Get-Content -LiteralPath $crossPath -Raw
$crossUpdated = $cross.Replace('await_text(helper.edit, "user_ghbdtn ");', 'await_text(helper.edit, "user-ghbdtn ");')
if ($crossUpdated -ne $cross) {
    Set-Content -LiteralPath $crossPath -Value $crossUpdated -Encoding utf8 -NoNewline
}

$e2ePath = 'src/windows_runtime/e2e_tests.rs'
$e2e = Get-Content -LiteralPath $e2ePath -Raw
$selectedMarker = @'
    unsafe {
        SendMessageW(edit, EM_SETSEL_VALUE, 0, -1);
    }
    inject_ctrl_shift_hotkey(VK_F9_VALUE);
'@
$selectedPrimed = @'
    unsafe {
        SendMessageW(edit, EM_SETSEL_VALUE, 0, -1);
    }
    // The preceding disabled-mode case deliberately leaves the hook policy
    // denied. A harmless modifier event forces the worker to re-evaluate the
    // now-restored application mode before testing the suppressing hotkey.
    inject_strokes(&[key(VK_SHIFT as u8)]);
    inject_ctrl_shift_hotkey(VK_F9_VALUE);
'@
if ($e2e.Contains($selectedMarker)) {
    $e2e = $e2e.Replace($selectedMarker, $selectedPrimed)
    Set-Content -LiteralPath $e2ePath -Value $e2e -Encoding utf8 -NoNewline
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
