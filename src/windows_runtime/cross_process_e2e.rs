use std::io::{BufRead, BufReader};
use std::mem::{size_of, zeroed};
use std::process::{Child, Command, Stdio};
use std::ptr::null_mut;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    GetKeyboardLayout, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP,
    VK_BACK, VK_CONTROL, VK_SHIFT,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetForegroundWindow, GetWindowThreadProcessId, PeekMessageW, PostMessageW,
    SendMessageTimeoutW, TranslateMessage, MSG, PM_REMOVE, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_APP,
    WM_CLOSE, WM_GETTEXTLENGTH, WM_SETTEXT,
};

use super::*;

const WM_TEST_SET_LAYOUT_AND_FOCUS: u32 = WM_APP + 0x51;
const EM_SETSEL_VALUE: u32 = 0x00B1;
const TEST_USER_EXTRA_INFO: usize = 0x4753_4554_4553_5432;
const VK_F9_VALUE: u16 = 0x78;
const VK_F12_VALUE: u16 = 0x7B;
const CONTROL_TIMEOUT_MS: u32 = 250;

struct InjectedInputGuard;

impl InjectedInputGuard {
    fn enable() -> Self {
        TEST_ACCEPT_INJECTED_INPUT.store(true, Ordering::SeqCst);
        Self
    }
}

impl Drop for InjectedInputGuard {
    fn drop(&mut self) {
        TEST_ACCEPT_INJECTED_INPUT.store(false, Ordering::SeqCst);
    }
}

struct CrossProcessHelper {
    child: Child,
    window: HWND,
    edit: HWND,
    rich_edit: HWND,
    password: HWND,
    process_id: u32,
}

impl CrossProcessHelper {
    fn spawn() -> Self {
        let executable = std::env::var("G_SWITCHER_E2E_HELPER")
            .expect("G_SWITCHER_E2E_HELPER must point to the separately built helper executable");
        let mut child = Command::new(executable)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("failed to start cross-process E2E helper");
        let stdout = child.stdout.take().expect("helper stdout was not piped");
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .expect("failed to read helper handle line");
        let fields = line.split_whitespace().collect::<Vec<_>>();
        assert_eq!(
            fields.first().copied(),
            Some("GSE2E"),
            "bad helper banner: {line:?}"
        );
        assert_eq!(fields.len(), 6, "bad helper handle line: {line:?}");
        let parse = |value: &str| value.parse::<usize>().expect("invalid helper handle");
        Self {
            child,
            window: parse(fields[1]) as HWND,
            edit: parse(fields[2]) as HWND,
            rich_edit: parse(fields[3]) as HWND,
            password: parse(fields[4]) as HWND,
            process_id: fields[5].parse().expect("invalid helper pid"),
        }
    }
}

impl Drop for CrossProcessHelper {
    fn drop(&mut self) {
        unsafe {
            PostMessageW(self.window, WM_CLOSE, 0, 0);
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            if self.child.try_wait().ok().flatten().is_some() {
                break;
            }
            if Instant::now() >= deadline {
                let _ = self.child.kill();
                let _ = self.child.wait();
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
}

#[test]
#[ignore = "mandatory separate-process Win32 E2E release gate"]
fn real_cross_process_edit_e2e_release_gate() {
    let _injected_guard = InjectedInputGuard::enable();
    let original_runtime =
        settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    settings::set_paused(false);

    let helper = CrossProcessHelper::spawn();
    let mut resolved_pid = 0u32;
    let ui_thread_id = unsafe { GetWindowThreadProcessId(helper.edit, &mut resolved_pid) };
    assert_ne!(ui_thread_id, 0, "failed to resolve helper EDIT thread");
    assert_eq!(
        resolved_pid, helper.process_id,
        "helper PID/EDIT PID mismatch"
    );
    let process_name =
        process_name_for_pid(helper.process_id).expect("helper process name missing");

    let engine = ENGINE.get_or_init(|| Mutex::new(Engine::default()));
    *engine.lock() = Engine::default();
    let hook = KeyboardHook::install().expect("failed to install WH_KEYBOARD_LL test hook");

    eprintln!("G-switcher cross-process E2E: automatic correction + undo");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    let ordinary_probe =
        uia_secure::probe_focused(helper.process_id).expect("UIA ordinary Edit probe failed");
    assert!(
        !ordinary_probe.is_password,
        "UIA ordinary field must not be password"
    );
    inject_strokes(&[
        b'G' as u16,
        b'H' as u16,
        b'B' as u16,
        b'D' as u16,
        b'T' as u16,
        b'N' as u16,
        0x20,
    ]);
    await_text(helper.edit, "привет ");
    inject_hotkey(false, VK_BACK);
    await_text(helper.edit, "ghbdtn ");

    eprintln!("G-switcher cross-process E2E: manual current word + undo");
    let mut manual_only = settings::RuntimeSettings::default();
    manual_only.manual_only_apps.push(process_name.clone());
    settings::replace_runtime_settings_for_test(manual_only);
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    let ordinary_probe =
        uia_secure::probe_focused(helper.process_id).expect("UIA ordinary Edit probe failed");
    assert!(
        !ordinary_probe.is_password,
        "UIA ordinary field must not be password"
    );
    inject_strokes(&[
        b'G' as u16,
        b'H' as u16,
        b'B' as u16,
        b'D' as u16,
        b'T' as u16,
        b'N' as u16,
    ]);
    await_text(helper.edit, "ghbdtn");
    inject_hotkey(true, VK_F12_VALUE);
    await_text(helper.edit, "привет");
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
    let russian_hkl = select_layout(Language::Russian).expect("Russian HKL unavailable");
    assert!(switch_layout(helper.edit, ui_thread_id, russian_hkl));
    wait_until(Duration::from_secs(2), || unsafe {
        language_from_hkl(GetKeyboardLayout(ui_thread_id) as isize) == Some(Language::Russian)
    });
    prime_policy();
    inject_hotkey(true, VK_F12_VALUE);
    await_text(helper.edit, "привет");
    inject_hotkey(false, VK_BACK);
    await_text(helper.edit, "ghbdtn");

    eprintln!("G-switcher cross-process E2E: selected text + undo");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    set_text(helper.edit, "ghbdtn rfr ltkf");
    assert!(send_timeout(helper.edit, EM_SETSEL_VALUE, 0, -1).is_some());
    prime_policy();
    inject_hotkey(true, VK_F9_VALUE);
    await_text(helper.edit, "привет как дела");
    inject_hotkey(false, VK_BACK);
    await_text(helper.edit, "ghbdtn rfr ltkf");

    eprintln!("G-switcher cross-process E2E: RichEdit selected text + undo");
    prepare_cross_process_case(
        helper.window,
        helper.rich_edit,
        ui_thread_id,
        Language::English,
    );
    set_text(helper.rich_edit, "ghbdtn rfr ltkf");
    assert!(send_timeout(helper.rich_edit, EM_SETSEL_VALUE, 0, -1).is_some());
    let rich_selected = selection::read_selected_text(helper.rich_edit)
        .expect("RichEdit selection adapter did not read the selected text");
    assert_eq!(rich_selected.text, "ghbdtn rfr ltkf");
    assert!(
        !secure_input::is_secure_input(helper.rich_edit, &process_name),
        "ordinary RichEdit was classified as protected"
    );
    let rich_probe =
        uia_secure::probe_focused(helper.process_id).expect("UIA RichEdit probe failed");
    assert!(
        !rich_probe.is_password,
        "ordinary RichEdit must not be password"
    );
    prime_policy();
    inject_hotkey(true, VK_F9_VALUE);
    await_text(helper.rich_edit, "привет как дела");
    inject_hotkey(false, VK_BACK);
    await_text(helper.rich_edit, "ghbdtn rfr ltkf");

    eprintln!("G-switcher cross-process E2E: code-safe token");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    let ordinary_probe =
        uia_secure::probe_focused(helper.process_id).expect("UIA ordinary Edit probe failed");
    assert!(
        !ordinary_probe.is_password,
        "UIA ordinary field must not be password"
    );
    inject_strokes(&[
        b'U' as u16,
        b'S' as u16,
        b'E' as u16,
        b'R' as u16,
        0xBD,
        b'G' as u16,
        b'H' as u16,
        b'B' as u16,
        b'D' as u16,
        b'T' as u16,
        b'N' as u16,
        0x20,
    ]);
    await_text(helper.edit, "user-ghbdtn ");

    eprintln!("G-switcher cross-process E2E: password field fail-open");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    prepare_cross_process_case(
        helper.window,
        helper.password,
        unsafe { GetWindowThreadProcessId(helper.password, null_mut()) },
        Language::English,
    );
    let password_probe =
        uia_secure::probe_focused(helper.process_id).expect("UIA password Edit probe failed");
    assert!(
        password_probe.is_password,
        "UIA password field was not recognized"
    );
    inject_strokes(&[
        b'G' as u16,
        b'H' as u16,
        b'B' as u16,
        b'D' as u16,
        b'T' as u16,
        b'N' as u16,
        0x20,
    ]);
    wait_until(Duration::from_secs(3), || text_len(helper.password) == 7);
    assert_eq!(
        text_len(helper.password),
        7,
        "password input length changed unexpectedly"
    );
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::English),
        "automatic handling changed layout in password field"
    );
    assert!(send_timeout(helper.password, EM_SETSEL_VALUE, 0, -1).is_some());
    prime_policy();
    inject_hotkey(true, VK_F9_VALUE);
    pump_for(Duration::from_millis(150));
    assert_eq!(
        text_len(helper.password),
        7,
        "selected-text hotkey modified password field"
    );
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::English),
        "selected-text hotkey changed layout in password field"
    );

    eprintln!("G-switcher cross-process E2E: focus race invalidates candidate");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    prepare_cross_process_case(helper.window, helper.edit, ui_thread_id, Language::English);
    let ordinary_probe =
        uia_secure::probe_focused(helper.process_id).expect("UIA ordinary Edit probe failed");
    assert!(
        !ordinary_probe.is_password,
        "UIA ordinary field must not be password"
    );
    inject_strokes(&[
        b'G' as u16,
        b'H' as u16,
        b'B' as u16,
        b'D' as u16,
        b'T' as u16,
        b'N' as u16,
    ]);
    await_text(helper.edit, "ghbdtn");
    set_text(helper.password, "");
    let english_hkl = select_layout(Language::English).expect("English HKL unavailable");
    unsafe {
        assert_ne!(
            PostMessageW(
                helper.window,
                WM_TEST_SET_LAYOUT_AND_FOCUS,
                english_hkl as usize,
                helper.password as isize,
            ),
            0
        );
    }
    wait_until(
        Duration::from_secs(3),
        || unsafe { GetForegroundWindow() } == helper.window,
    );
    prime_policy();
    inject_strokes(&[0x20]);
    pump_for(Duration::from_millis(100));
    assert_eq!(
        read_text(helper.edit),
        "ghbdtn",
        "focus race rewrote old EDIT content"
    );
    assert_eq!(
        text_len(helper.password),
        1,
        "delimiter did not go to new focus target"
    );

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
    drop(helper);
}

fn prepare_cross_process_case(window: HWND, edit: HWND, ui_thread_id: u32, language: Language) {
    *ENGINE.get_or_init(|| Mutex::new(Engine::default())).lock() = Engine::default();
    set_text(edit, "");
    let hkl = select_layout(language).expect("required RU/EN keyboard layout is unavailable");
    unsafe {
        assert_ne!(
            PostMessageW(
                window,
                WM_TEST_SET_LAYOUT_AND_FOCUS,
                hkl as usize,
                edit as isize,
            ),
            0,
            "failed to request helper source layout/focus"
        );
    }
    wait_until(Duration::from_secs(3), || {
        pump_runtime();
        unsafe {
            GetKeyboardLayout(ui_thread_id) as isize == hkl
                && GetForegroundWindow() == window
                && focused_hwnd_fast() == edit
        }
    });
    assert_eq!(unsafe { GetKeyboardLayout(ui_thread_id) } as isize, hkl);
    assert_eq!(unsafe { GetForegroundWindow() }, window);
    assert_eq!(
        focused_hwnd_fast(),
        edit,
        "helper child focus was not established"
    );
    prime_policy();
}

fn prime_policy() {
    inject_raw(&[(VK_SHIFT, 0), (VK_SHIFT, KEYEVENTF_KEYUP)]);
    pump_for(Duration::from_millis(30));
}

fn inject_strokes(keys: &[u16]) {
    for &vk in keys {
        inject_raw(&[(vk, 0), (vk, KEYEVENTF_KEYUP)]);
        pump_for(Duration::from_millis(3));
    }
}

fn inject_hotkey(with_shift: bool, vk: u16) {
    let mut raw = vec![(VK_CONTROL, 0)];
    if with_shift {
        raw.push((VK_SHIFT, 0));
    }
    raw.push((vk, 0));
    raw.push((vk, KEYEVENTF_KEYUP));
    if with_shift {
        raw.push((VK_SHIFT, KEYEVENTF_KEYUP));
    }
    raw.push((VK_CONTROL, KEYEVENTF_KEYUP));
    inject_raw(&raw);
    pump_for(Duration::from_millis(30));
}

fn inject_raw(events: &[(u16, u32)]) {
    let inputs = events
        .iter()
        .map(|&(vk, flags)| INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: vk,
                    wScan: 0,
                    dwFlags: flags,
                    time: 0,
                    dwExtraInfo: TEST_USER_EXTRA_INFO,
                },
            },
        })
        .collect::<Vec<_>>();
    let expected = inputs.len() as u32;
    let (done_tx, done_rx) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let sent = unsafe { SendInput(expected, inputs.as_ptr(), size_of::<INPUT>() as i32) };
        let _ = done_tx.send(sent);
    });
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        pump_runtime();
        if let Ok(sent) = done_rx.try_recv() {
            assert_eq!(
                sent, expected,
                "SendInput did not deliver the complete sequence"
            );
            break;
        }
        assert!(Instant::now() < deadline, "SendInput timed out");
        thread::sleep(Duration::from_millis(1));
    }
}

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
        assert_eq!(
            sent,
            batch.len(),
            "SendInput truncated the callback stress batch"
        );
        remaining -= count;
        pump_for(Duration::from_millis(1));
    }
}

fn pump_for(duration: Duration) {
    let deadline = Instant::now() + duration;
    while Instant::now() < deadline {
        pump_runtime();
        thread::sleep(Duration::from_millis(1));
    }
}

fn pump_runtime() {
    unsafe {
        let mut message: MSG = zeroed();
        while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
            if handle_runtime_message(&message) {
                continue;
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

fn wait_until(timeout: Duration, mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if condition() {
            return;
        }
        pump_runtime();
        thread::sleep(Duration::from_millis(5));
    }
}

fn await_text(edit: HWND, expected: &str) {
    wait_until(Duration::from_secs(3), || read_text(edit) == expected);
    assert_eq!(read_text(edit), expected);
}

fn read_text(edit: HWND) -> String {
    let text = selection::read_control_text(edit).expect("failed to read cross-process EDIT text");
    String::from_utf16_lossy(&text)
}

fn set_text(edit: HWND, value: &str) {
    let text = value
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    assert!(
        send_timeout(edit, WM_SETTEXT, 0, text.as_ptr() as isize).is_some(),
        "cross-process WM_SETTEXT failed"
    );
}

fn text_len(edit: HWND) -> usize {
    send_timeout(edit, WM_GETTEXTLENGTH, 0, 0).expect("cross-process WM_GETTEXTLENGTH failed")
        as usize
}

fn send_timeout(hwnd: HWND, message: u32, wparam: WPARAM, lparam: LPARAM) -> Option<LRESULT> {
    let mut result = 0usize;
    let ok = unsafe {
        SendMessageTimeoutW(
            hwnd,
            message,
            wparam,
            lparam,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            CONTROL_TIMEOUT_MS,
            &mut result,
        )
    };
    (ok != 0).then_some(result as LRESULT)
}
