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
if ($updated -ne $text) {
    Set-Content -LiteralPath $path -Value $updated -Encoding utf8 -NoNewline
}

cargo fmt --all
