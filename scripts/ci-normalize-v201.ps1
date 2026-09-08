$ErrorActionPreference = 'Stop'

$runtimePath = 'src/windows_runtime_v201.rs'
$runtime = Get-Content -LiteralPath $runtimePath -Raw

$requiredRuntimeMarkers = @(
    'mod runtime_dispatch;',
    'static RUNTIME_WINDOW: AtomicIsize',
    'RUNTIME_WINDOW.load(Ordering::SeqCst)',
    'if is_modifier_vk(vk)',
    'selection::replace_range_if_matches',
    'if !selection::is_standard_edit(source.hwnd)',
    'mod cross_process_e2e;',
    'const SINGLE_INSTANCE_NAME: &str = "Local\\GSwitcher.SingleInstance.v0.8";'
)
foreach ($marker in $requiredRuntimeMarkers) {
    if (-not $runtime.Contains($marker)) {
        throw "Required hardened runtime marker is missing: $marker"
    }
}

$crossPath = 'src/windows_runtime/cross_process_e2e.rs'
$cross = Get-Content -LiteralPath $crossPath -Raw
# Repair any residue from earlier bring-up transforms and keep this step idempotent.
$cross = [regex]::Replace(
    $cross,
    '(?m)^(\s*rich_edit: HWND,\r?\n)(?:\s*rich_edit: HWND,\r?\n)+',
    '$1'
)
if ($cross -notmatch 'assert_eq!\(fields\.len\(\), 6') {
    throw 'Cross-process helper parser is not using the six-field Edit/RichEdit/password banner.'
}
if ($cross -notmatch 'rich_edit: parse\(fields\[3\]\) as HWND') {
    throw 'Cross-process RichEdit handle is not parsed.'
}
if ($cross -notmatch 'RichEdit selected text \+ undo') {
    throw 'Cross-process RichEdit selected-text/Undo gate is missing.'
}
$cross = $cross.Replace('await_text(helper.edit, "user_ghbdtn ");', 'await_text(helper.edit, "user-ghbdtn ");')
Set-Content -LiteralPath $crossPath -Value $cross -Encoding utf8 -NoNewline

$e2ePath = 'src/windows_runtime/e2e_tests.rs'
$e2e = Get-Content -LiteralPath $e2ePath -Raw
if ($e2e -notmatch '(?s)SendMessageW\(edit, EM_SETSEL_VALUE, 0, -1\);.*?inject_strokes\(&\[key\(VK_SHIFT as u8\)\]\);.*?inject_ctrl_shift_hotkey\(VK_F9_VALUE\);') {
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
    // Force the worker to re-evaluate policy after the preceding disabled-mode case.
    inject_strokes(&[key(VK_SHIFT as u8)]);
    inject_ctrl_shift_hotkey(VK_F9_VALUE);
'@
    if (-not $e2e.Contains($selectedMarker)) {
        throw 'Could not locate same-process selected-text E2E marker.'
    }
    $e2e = $e2e.Replace($selectedMarker, $selectedPrimed)
    Set-Content -LiteralPath $e2ePath -Value $e2e -Encoding utf8 -NoNewline
}

# Cargo.toml may gain Windows-only bindings during the 2.0.1 hardening work.
# Generate the lockfile before any --locked gate and commit the deterministic result.
cargo generate-lockfile
cargo fmt --all
