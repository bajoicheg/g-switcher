$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$runtimePath = 'src/windows_runtime_v201.rs'
$runtime = Get-Content -LiteralPath $runtimePath -Raw

$manualOld = @'
        let target = opposite_language(source.language);
        let corrected = opposite_layout_text(&self.candidate, source.language);
        self.previous = None;
        self.selection_undo = None;
        self.queue_correction_parts(
            source,
            target,
'@
$manualNew = @'
        // The default manual hotkeys use Ctrl+Shift. On Windows installations
        // where Ctrl+Shift is also configured as an input-language shortcut,
        // the OS may change the focused thread HKL before F12/F10 reaches us.
        // The candidate itself still records the alphabet that was typed, so
        // derive the manual source language from that text instead of trusting
        // the potentially hotkey-shifted current HKL.
        let source_language = infer_language(&self.candidate).unwrap_or(source.language);
        let source_hkl = if source_language == source.language {
            source.hkl
        } else {
            let Some(hkl) = select_layout(source_language) else {
                return false;
            };
            hkl
        };
        let source = FocusTarget {
            hkl: source_hkl,
            language: source_language,
            ..source
        };
        let target = opposite_language(source_language);
        let corrected = opposite_layout_text(&self.candidate, source_language);
        self.previous = None;
        self.selection_undo = None;
        self.queue_correction_parts(
            source,
            target,
'@
if (-not $runtime.Contains($manualOld)) {
    throw 'Could not locate try_manual_convert source-language block.'
}
$runtime = $runtime.Replace($manualOld, $manualNew)

$executeOld = @'
        let hwnd = pending.focus as HWND;
        let Some(now) = focused_target() else {
            return;
        };
        if now.hwnd as isize != pending.focus
            || now.process_id != pending.process_id
            || now.thread_id != pending.thread_id
            || now.hkl != pending.source_hkl
        {
            return;
        }
'@
$executeNew = @'
        let hwnd = pending.focus as HWND;
        let Some(now) = focused_target() else {
            return;
        };
        // Explicit manual actions carry their held modifiers. Allow only those
        // actions to tolerate HKL drift caused by the hotkey chord itself. Focus,
        // process, UI thread, generation and exact source suffix are still
        // revalidated before mutation, so unrelated/stale operations remain
        // fail-open.
        let manual_layout_drift = pending.held_modifiers.ctrl
            || pending.held_modifiers.shift
            || pending.held_modifiers.alt;
        let pre_operation_hkl = now.hkl;
        if now.hwnd as isize != pending.focus
            || now.process_id != pending.process_id
            || now.thread_id != pending.thread_id
            || (!manual_layout_drift && now.hkl != pending.source_hkl)
        {
            return;
        }
'@
if (-not $runtime.Contains($executeOld)) {
    throw 'Could not locate pending-correction layout validation block.'
}
$runtime = $runtime.Replace($executeOld, $executeNew)

$restoreOld = @'
                let _ = switch_layout(hwnd, pending.thread_id, pending.source_hkl);
                return;
'@
$restoreNew = @'
                let _ = switch_layout(hwnd, pending.thread_id, pre_operation_hkl);
                return;
'@
# There are multiple failure returns in execute_pending_correction. Restrict the
# replacement to the function body, then splice it back into the source.
$start = $runtime.IndexOf('    fn execute_pending_correction(&mut self) {')
$end = $runtime.IndexOf('    fn try_undo(', $start)
if ($start -lt 0 -or $end -lt 0) {
    throw 'Could not isolate execute_pending_correction.'
}
$before = $runtime.Substring(0, $start)
$body = $runtime.Substring($start, $end - $start)
$after = $runtime.Substring($end)
$body = $body.Replace($restoreOld, $restoreNew)
$runtime = $before + $body + $after

Set-Content -LiteralPath $runtimePath -Value $runtime -Encoding utf8 -NoNewline

$crossPath = 'src/windows_runtime/cross_process_e2e.rs'
$cross = Get-Content -LiteralPath $crossPath -Raw
$marker = @'
    inject_hotkey(false, VK_BACK);
    await_text(helper.edit, "ghbdtn");

    eprintln!("G-switcher cross-process E2E: selected text + undo");
'@
$replacement = @'
    inject_hotkey(false, VK_BACK);
    await_text(helper.edit, "ghbdtn");

    eprintln!("G-switcher cross-process E2E: manual current word survives HKL drift");
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    inject_strokes(&[
        b'G' as u16,
        b'H' as u16,
        b'B' as u16,
        b'D' as u16,
        b'T' as u16,
        b'N' as u16,
    ]);
    await_text(helper.edit, "ghbdtn");
    // Simulate Windows Ctrl+Shift language-switch behavior occurring before
    // the final manual-hotkey keydown. The typed candidate was English and
    // must still convert to Russian rather than silently doing nothing.
    request_layout(helper.edit, Language::Russian);
    wait_until(Duration::from_secs(2), || unsafe {
        language_from_hkl(GetKeyboardLayout(ui_thread_id) as isize) == Some(Language::Russian)
    });
    prime_policy();
    inject_hotkey(true, VK_F12_VALUE);
    await_text(helper.edit, "привет");
    inject_hotkey(false, VK_BACK);
    await_text(helper.edit, "ghbdtn");

    eprintln!("G-switcher cross-process E2E: selected text + undo");
'@
if (-not $cross.Contains($marker)) {
    throw 'Could not locate cross-process manual current-word checkpoint.'
}
$cross = $cross.Replace($marker, $replacement)
Set-Content -LiteralPath $crossPath -Value $cross -Encoding utf8 -NoNewline

cargo fmt --all
