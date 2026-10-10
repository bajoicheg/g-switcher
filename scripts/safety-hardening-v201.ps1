$ErrorActionPreference = 'Stop'

$selectionPath = 'src/windows_runtime/selection.rs'
$selection = Get-Content -LiteralPath $selectionPath -Raw

if ($selection -notmatch 'pub fn is_plain_edit\(') {
    $marker = @'
pub fn is_standard_edit(hwnd: HWND) -> bool {
    adapter(hwnd).is_some()
}
'@
    $replacement = @'
pub fn is_standard_edit(hwnd: HWND) -> bool {
    adapter(hwnd).is_some()
}

/// Plain system Edit controls have a native password/style check and a
/// marshalled cross-process message adapter. Other supported text controls
/// require successful UIA metadata verification before mutation.
pub fn is_plain_edit(hwnd: HWND) -> bool {
    class_name(hwnd).is_some_and(|name| is_plain_edit_class(&name))
}
'@
    if (-not $selection.Contains($marker)) {
        throw 'Could not locate is_standard_edit() adapter gate.'
    }
    $selection = $selection.Replace($marker, $replacement)
    Set-Content -LiteralPath $selectionPath -Value $selection -Encoding utf8 -NoNewline
}

$runtimePath = 'src/windows_runtime_v201.rs'
$runtime = Get-Content -LiteralPath $runtimePath -Raw

$oldPolicy = @'
        // UIA is queried only on the runtime worker and only for metadata. The
        // first event in a new context was already passed through while policy
        // was UNKNOWN; after the probe, protected elements remain fail-open.
        match self.uia_password_state(target, event.generation) {
            Some(true) => {
                HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
                self.reset_transient();
                return;
            }
            None if !selection::is_standard_edit(target.hwnd) => {
                HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
                self.reset_transient();
                return;
            }
            _ => {}
        }
'@
$newPolicy = @'
        // Never suppress a hotkey or accumulate an automatic-correction
        // candidate for a control that has no synchronously verifiable text
        // adapter. Unsupported modern controls fail open: original input is
        // left untouched and the application can be placed in Disabled mode.
        if !selection::is_standard_edit(target.hwnd) {
            HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
            self.reset_transient();
            return;
        }

        // UIA is queried only on the runtime worker and only for metadata. A
        // plain Edit remains protected by its native password/style checks if
        // UIA is unavailable. RichEdit requires a successful non-password UIA
        // probe because its verified text adapter is UIA-backed.
        match self.uia_password_state(target, event.generation) {
            Some(true) => {
                HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
                self.reset_transient();
                return;
            }
            None if !selection::is_plain_edit(target.hwnd) => {
                HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
                self.reset_transient();
                return;
            }
            _ => {}
        }
'@
if ($runtime.Contains($oldPolicy)) {
    $runtime = $runtime.Replace($oldPolicy, $newPolicy)
}
if ($runtime -notmatch 'Unsupported modern controls fail open') {
    throw 'Could not install fail-open policy for unsupported controls.'
}

$selectionSecureOld = @'
        if runtime_settings.app_mode(&self.process_name) == AppMode::Disabled
            || secure_input::is_secure_input(target.hwnd, &self.process_name)
        {
            return;
        }

        let Some(selected) = selection::read_selected_text(target.hwnd) else {
'@
$selectionSecureNew = @'
        if runtime_settings.app_mode(&self.process_name) == AppMode::Disabled
            || secure_input::is_secure_input(target.hwnd, &self.process_name)
            || !selection::is_standard_edit(target.hwnd)
        {
            return;
        }
        match self.uia_password_state(target, pending.generation) {
            Some(true) => return,
            None if !selection::is_plain_edit(target.hwnd) => return,
            _ => {}
        }

        let Some(selected) = selection::read_selected_text(target.hwnd) else {
'@
if ($runtime.Contains($selectionSecureOld)) {
    $runtime = $runtime.Replace($selectionSecureOld, $selectionSecureNew)
}
if ($runtime -notmatch 'self\.uia_password_state\(target, pending\.generation\)') {
    throw 'Could not harden selected-text security recheck.'
}

$correctionMarker = @'
        if selection::is_standard_edit(hwnd) {
            if !wait_for_edit_suffix(hwnd, &pending.original_text, pending.generation) {
'@
$correctionGuard = @'
        // Cache the adapter decision once. If it is unavailable now, leave the
        // user's text untouched. Do not fall through to the legacy SendInput
        // mutation path if adapter availability changes during the operation.
        let verified_adapter = selection::is_standard_edit(hwnd);
        if !verified_adapter {
            return;
        }
        if verified_adapter {
            if !wait_for_edit_suffix(hwnd, &pending.original_text, pending.generation) {
'@
if ($runtime.Contains($correctionMarker)) {
    $runtime = $runtime.Replace($correctionMarker, $correctionGuard)
}
if ($runtime -notmatch 'let verified_adapter = selection::is_standard_edit\(hwnd\)') {
    throw 'Could not install pending-correction fail-open adapter guard.'
}

$undoMarker = @'
        if selection::is_standard_edit(target.hwnd) {
            if selection::replace_suffix_at_caret(
'@
$undoGuard = @'
        // Undo is also fail-open. A stale operation may not switch to raw
        // SendInput merely because the verified adapter disappeared.
        let verified_adapter = selection::is_standard_edit(target.hwnd);
        if !verified_adapter {
            let _ = switch_layout(target.hwnd, target.thread_id, undo.target_hkl);
            return false;
        }
        if verified_adapter {
            if selection::replace_suffix_at_caret(
'@
if ($runtime.Contains($undoMarker)) {
    $runtime = $runtime.Replace($undoMarker, $undoGuard)
}
if ($runtime -notmatch 'Undo is also fail-open') {
    throw 'Could not install Undo fail-open adapter guard.'
}

$selectionUndoOld = @'
            if undo.focus != target.hwnd as isize
                || undo.process_id != target.process_id
                || undo.generation != generation
                || current_generation() != generation
                || secure_input::is_secure_input(target.hwnd, &self.process_name)
            {
                return false;
            }
'@
$selectionUndoNew = @'
            if undo.focus != target.hwnd as isize
                || undo.process_id != target.process_id
                || undo.generation != generation
                || current_generation() != generation
                || secure_input::is_secure_input(target.hwnd, &self.process_name)
                || !selection::is_standard_edit(target.hwnd)
            {
                return false;
            }
            match self.uia_password_state(target, generation) {
                Some(true) => return false,
                None if !selection::is_plain_edit(target.hwnd) => return false,
                _ => {}
            }
'@
if ($runtime.Contains($selectionUndoOld)) {
    $runtime = $runtime.Replace($selectionUndoOld, $selectionUndoNew)
}
if ($runtime -notmatch 'None if !selection::is_plain_edit\(target\.hwnd\) => return false') {
    throw 'Could not harden selected-text Undo security recheck.'
}

Set-Content -LiteralPath $runtimePath -Value $runtime -Encoding utf8 -NoNewline
cargo fmt --all
