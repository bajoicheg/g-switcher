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

if ($runtime -notmatch 'static CALLBACK_OVER_10MS: AtomicU64') {
    $metricMarker = @'
static CALLBACK_COUNT: AtomicU64 = AtomicU64::new(0);
static CALLBACK_MAX_NS: AtomicU64 = AtomicU64::new(0);
static DROPPED_EVENTS: AtomicU64 = AtomicU64::new(0);
'@
    $metricReplacement = @'
static CALLBACK_COUNT: AtomicU64 = AtomicU64::new(0);
static CALLBACK_MAX_NS: AtomicU64 = AtomicU64::new(0);
static CALLBACK_OVER_10MS: AtomicU64 = AtomicU64::new(0);
static DROPPED_EVENTS: AtomicU64 = AtomicU64::new(0);
'@
    if (-not $runtime.Contains($metricMarker)) {
        throw 'Could not locate callback metric statics.'
    }
    $runtime = $runtime.Replace($metricMarker, $metricReplacement)
}

if ($runtime -notmatch 'CALLBACK_OVER_10MS\.fetch_add') {
    $recordMarker = @'
fn record_callback_time(elapsed_ns: u64) {
    CALLBACK_COUNT.fetch_add(1, Ordering::Relaxed);
    let mut current = CALLBACK_MAX_NS.load(Ordering::Relaxed);
'@
    $recordReplacement = @'
fn record_callback_time(elapsed_ns: u64) {
    CALLBACK_COUNT.fetch_add(1, Ordering::Relaxed);
    if elapsed_ns > 10_000_000 {
        CALLBACK_OVER_10MS.fetch_add(1, Ordering::Relaxed);
    }
    let mut current = CALLBACK_MAX_NS.load(Ordering::Relaxed);
'@
    if (-not $runtime.Contains($recordMarker)) {
        throw 'Could not locate callback timing recorder.'
    }
    $runtime = $runtime.Replace($recordMarker, $recordReplacement)
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
    'static CALLBACK_OVER_10MS: AtomicU64',
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

if ($cross -notmatch '100k callback stress gate') {
    $cleanupMarker = @'
    settings::replace_runtime_settings_for_test(original_runtime);
    settings::set_paused(false);
    drop(hook);
'@
    $stressBlock = @'
    eprintln!("G-switcher cross-process E2E: 100k callback stress gate");
    settings::set_paused(true);
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    let callback_before = CALLBACK_COUNT.load(Ordering::Relaxed);
    let slow_before = CALLBACK_OVER_10MS.load(Ordering::Relaxed);
    let dropped_before = DROPPED_EVENTS.load(Ordering::Relaxed);
    inject_stress_callbacks(100_000);
    pump_for(Duration::from_millis(250));
    let callback_delta = CALLBACK_COUNT
        .load(Ordering::Relaxed)
        .saturating_sub(callback_before);
    let slow_delta = CALLBACK_OVER_10MS
        .load(Ordering::Relaxed)
        .saturating_sub(slow_before);
    let dropped_delta = DROPPED_EVENTS
        .load(Ordering::Relaxed)
        .saturating_sub(dropped_before);
    let max_ns = CALLBACK_MAX_NS.load(Ordering::Relaxed);
    eprintln!(
        "G-switcher callback stress: callbacks={callback_delta} over_10ms={slow_delta} dropped={dropped_delta} max_ns={max_ns}"
    );
    assert!(
        callback_delta >= 100_000,
        "hook did not observe all 100k stress events: {callback_delta}"
    );
    assert!(
        slow_delta.saturating_mul(100) <= callback_delta,
        "callback p99 exceeded 10 ms: {slow_delta}/{callback_delta} callbacks were slower"
    );
    assert_eq!(dropped_delta, 0, "runtime dispatch dropped stress events");

    let alive_before = CALLBACK_COUNT.load(Ordering::Relaxed);
    inject_stress_callbacks(2);
    pump_for(Duration::from_millis(30));
    assert!(
        CALLBACK_COUNT.load(Ordering::Relaxed) >= alive_before + 2,
        "keyboard hook stopped receiving events after stress"
    );

    settings::replace_runtime_settings_for_test(original_runtime);
    settings::set_paused(false);
    drop(hook);
'@
    if (-not $cross.Contains($cleanupMarker)) {
        throw 'Could not locate cross-process cleanup marker for stress gate.'
    }
    $cross = $cross.Replace($cleanupMarker, $stressBlock)
}

if ($cross -notmatch 'fn inject_stress_callbacks\(') {
    $pumpMarker = @'
fn pump_for(duration: Duration) {
'@
    $stressHelper = @'
fn inject_stress_callbacks(total_events: usize) {
    const VK_F24_VALUE: u16 = 0x87;
    const CHUNK_EVENTS: usize = 512;
    assert_eq!(total_events % 2, 0, "stress event count must be even");

    let key_down = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: VK_F24_VALUE,
                wScan: 0,
                dwFlags: 0,
                time: 0,
                dwExtraInfo: TEST_USER_EXTRA_INFO,
            },
        },
    };
    let key_up = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: VK_F24_VALUE,
                wScan: 0,
                dwFlags: KEYEVENTF_KEYUP,
                time: 0,
                dwExtraInfo: TEST_USER_EXTRA_INFO,
            },
        },
    };

    let mut remaining = total_events;
    while remaining > 0 {
        let count = remaining.min(CHUNK_EVENTS);
        let mut batch = Vec::with_capacity(count);
        for index in 0..count {
            batch.push(if index % 2 == 0 { key_down } else { key_up });
        }
        let sent = unsafe {
            SendInput(
                batch.len() as u32,
                batch.as_ptr(),
                size_of::<INPUT>() as i32,
            )
        } as usize;
        assert_eq!(sent, batch.len(), "SendInput truncated the callback stress batch");
        remaining -= count;
        pump_for(Duration::from_millis(1));
    }
}

fn pump_for(duration: Duration) {
'@
    if (-not $cross.Contains($pumpMarker)) {
        throw 'Could not locate pump_for helper for stress injection.'
    }
    $cross = $cross.Replace($pumpMarker, $stressHelper)
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
