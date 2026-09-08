$ErrorActionPreference = 'Stop'

$runtimePath = 'src/windows_runtime_v201.rs'
$runtime = Get-Content -LiteralPath $runtimePath -Raw

if ($runtime -notmatch 'mod uia_secure;') {
    $marker = @'
#[path = "windows_runtime/secure_input.rs"]
mod secure_input;
'@
    $replacement = @'
#[path = "windows_runtime/secure_input.rs"]
mod secure_input;
#[path = "windows_runtime/uia_secure.rs"]
mod uia_secure;
'@
    if (-not $runtime.Contains($marker)) {
        throw 'Could not locate secure_input module marker.'
    }
    $runtime = $runtime.Replace($marker, $replacement)
}

if ($runtime -notmatch 'struct UiaSecurityCache') {
    $engineMarker = @'
#[derive(Default)]
struct Engine {
'@
    $cacheBlock = @'
#[derive(Debug, Clone, Copy, Default)]
struct UiaSecurityCache {
    generation: u32,
    process_id: u32,
    focus: isize,
    native_hwnd: isize,
    checked: bool,
    is_password: Option<bool>,
}

#[derive(Default)]
struct Engine {
'@
    if (-not $runtime.Contains($engineMarker)) {
        throw 'Could not locate Engine marker for UIA cache.'
    }
    $runtime = $runtime.Replace($engineMarker, $cacheBlock)
}

if ($runtime -notmatch 'uia_cache: UiaSecurityCache') {
    $engineTail = @'
    process_id: u32,
    process_name: String,
    generation: u32,
}
'@
    $engineTailReplacement = @'
    process_id: u32,
    process_name: String,
    generation: u32,
    uia_cache: UiaSecurityCache,
}
'@
    if (-not $runtime.Contains($engineTail)) {
        throw 'Could not locate Engine tail for UIA cache.'
    }
    $runtime = $runtime.Replace($engineTail, $engineTailReplacement)
}

if ($runtime -notmatch 'fn uia_password_state\(') {
    $implMarker = @'
impl Engine {
    fn on_key_event(&mut self, event: HookEvent) {
'@
    $implReplacement = @'
impl Engine {
    fn uia_password_state(&mut self, target: FocusTarget, generation: u32) -> Option<bool> {
        let cache_matches = self.uia_cache.checked
            && self.uia_cache.generation == generation
            && self.uia_cache.process_id == target.process_id
            && self.uia_cache.focus == target.hwnd as isize
            && (self.uia_cache.native_hwnd == 0
                || self.uia_cache.native_hwnd == target.hwnd as isize);
        if cache_matches {
            return self.uia_cache.is_password;
        }

        let probe = uia_secure::probe_focused(target.process_id);
        self.uia_cache = UiaSecurityCache {
            generation,
            process_id: target.process_id,
            focus: target.hwnd as isize,
            native_hwnd: probe.map(|value| value.native_hwnd).unwrap_or_default(),
            checked: true,
            is_password: probe.map(|value| value.is_password),
        };
        self.uia_cache.is_password
    }

    fn on_key_event(&mut self, event: HookEvent) {
'@
    if (-not $runtime.Contains($implMarker)) {
        throw 'Could not locate Engine implementation marker for UIA state.'
    }
    $runtime = $runtime.Replace($implMarker, $implReplacement)
}

if ($runtime -notmatch 'self\.uia_cache\.native_hwnd == 0') {
    $cacheMatchOld = @'
        let cache_matches = self.uia_cache.checked
            && self.uia_cache.generation == generation
            && self.uia_cache.process_id == target.process_id
            && self.uia_cache.focus == target.hwnd as isize;
'@
    $cacheMatchNew = @'
        let cache_matches = self.uia_cache.checked
            && self.uia_cache.generation == generation
            && self.uia_cache.process_id == target.process_id
            && self.uia_cache.focus == target.hwnd as isize
            && (self.uia_cache.native_hwnd == 0
                || self.uia_cache.native_hwnd == target.hwnd as isize);
'@
    if (-not $runtime.Contains($cacheMatchOld)) {
        throw 'Could not locate UIA cache match block.'
    }
    $runtime = $runtime.Replace($cacheMatchOld, $cacheMatchNew)
}

if ($runtime -notmatch 'uia_password_state\(target, event\.generation\)') {
    $nativeSecure = @'
        if secure_input::is_secure_input(target.hwnd, &self.process_name) {
            HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
            self.reset_transient();
            return;
        }
        HOOK_FOCUS.store(target.hwnd as isize, Ordering::SeqCst);
        HOOK_POLICY.store(POLICY_READY, Ordering::SeqCst);
'@
    $uiaSecure = @'
        if secure_input::is_secure_input(target.hwnd, &self.process_name) {
            HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
            self.reset_transient();
            return;
        }

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
        HOOK_FOCUS.store(target.hwnd as isize, Ordering::SeqCst);
        HOOK_POLICY.store(POLICY_READY, Ordering::SeqCst);
'@
    if (-not $runtime.Contains($nativeSecure)) {
        throw 'Could not locate native secure-input block for UIA integration.'
    }
    $runtime = $runtime.Replace($nativeSecure, $uiaSecure)
}

$requiredRuntimeMarkers = @(
    'mod runtime_dispatch;',
    'mod uia_secure;',
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
Set-Content -LiteralPath $runtimePath -Value $runtime -Encoding utf8 -NoNewline

$crossPath = 'src/windows_runtime/cross_process_e2e.rs'
$cross = Get-Content -LiteralPath $crossPath -Raw
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

if ($cross -notmatch 'UIA ordinary field must not be password') {
    $ordinaryMarker = @'
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    inject_strokes(&[
'@
    $ordinaryProbe = @'
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    let ordinary_probe = uia_secure::probe_focused(helper.process_id)
        .expect("UIA ordinary Edit probe failed");
    assert!(!ordinary_probe.is_password, "UIA ordinary field must not be password");
    inject_strokes(&[
'@
    if (-not $cross.Contains($ordinaryMarker)) {
        throw 'Could not locate ordinary cross-process E2E marker for UIA probe.'
    }
    $cross = $cross.Replace($ordinaryMarker, $ordinaryProbe)
}

if ($cross -notmatch 'UIA password field was not recognized') {
    $passwordMarker = @'
    prepare_cross_process_case(
        helper.window,
        helper.password,
        unsafe { GetWindowThreadProcessId(helper.password, null_mut()) },
        Language::English,
    );
    inject_strokes(&[
'@
    $passwordProbe = @'
    prepare_cross_process_case(
        helper.window,
        helper.password,
        unsafe { GetWindowThreadProcessId(helper.password, null_mut()) },
        Language::English,
    );
    let password_probe = uia_secure::probe_focused(helper.process_id)
        .expect("UIA password Edit probe failed");
    assert!(password_probe.is_password, "UIA password field was not recognized");
    inject_strokes(&[
'@
    if (-not $cross.Contains($passwordMarker)) {
        throw 'Could not locate password cross-process E2E marker for UIA probe.'
    }
    $cross = $cross.Replace($passwordMarker, $passwordProbe)
}

if ($cross -notmatch 'focused_hwnd_fast\(\) == edit') {
    $waitOld = @'
            GetKeyboardLayout(ui_thread_id) as isize == hkl && GetForegroundWindow() == window
'@
    $waitNew = @'
            GetKeyboardLayout(ui_thread_id) as isize == hkl
                && GetForegroundWindow() == window
                && focused_hwnd_fast() == edit
'@
    if (-not $cross.Contains($waitOld)) {
        throw 'Could not locate cross-process focus wait condition.'
    }
    $cross = $cross.Replace($waitOld, $waitNew)
    $foregroundAssert = '    assert_eq!(unsafe { GetForegroundWindow() }, window);'
    $focusAssert = @'
    assert_eq!(unsafe { GetForegroundWindow() }, window);
    assert_eq!(focused_hwnd_fast(), edit, "helper child focus was not established");
'@
    $cross = $cross.Replace($foregroundAssert, $focusAssert.TrimEnd("`r", "`n"))
}

if ($cross -notmatch 'RichEdit selection adapter did not read') {
    $richSelectionMarker = @'
    set_text(helper.rich_edit, "ghbdtn rfr ltkf");
    assert!(send_timeout(helper.rich_edit, EM_SETSEL_VALUE, 0, -1).is_some());
    prime_policy();
'@
    $richSelectionProbe = @'
    set_text(helper.rich_edit, "ghbdtn rfr ltkf");
    assert!(send_timeout(helper.rich_edit, EM_SETSEL_VALUE, 0, -1).is_some());
    let rich_selected = selection::read_selected_text(helper.rich_edit)
        .expect("RichEdit selection adapter did not read the selected text");
    assert_eq!(rich_selected.text, "ghbdtn rfr ltkf");
    assert!(
        !secure_input::is_secure_input(helper.rich_edit, &process_name),
        "ordinary RichEdit was classified as protected"
    );
    let rich_probe = uia_secure::probe_focused(helper.process_id)
        .expect("UIA RichEdit probe failed");
    assert!(!rich_probe.is_password, "ordinary RichEdit must not be password");
    prime_policy();
'@
    if (-not $cross.Contains($richSelectionMarker)) {
        throw 'Could not locate RichEdit selection probe marker.'
    }
    $cross = $cross.Replace($richSelectionMarker, $richSelectionProbe)
}
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
    inject_strokes(&[key(VK_SHIFT as u8)]);
    inject_ctrl_shift_hotkey(VK_F9_VALUE);
'@
    if (-not $e2e.Contains($selectedMarker)) {
        throw 'Could not locate same-process selected-text E2E marker.'
    }
    $e2e = $e2e.Replace($selectedMarker, $selectedPrimed)
    Set-Content -LiteralPath $e2ePath -Value $e2e -Encoding utf8 -NoNewline
}

cargo generate-lockfile
cargo fmt --all
