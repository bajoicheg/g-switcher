use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    ActivateKeyboardLayout, GetKeyboardLayout, SendInput, SetFocus, INPUT, INPUT_0, INPUT_KEYBOARD,
    KEYBDINPUT, KEYEVENTF_KEYUP, VK_BACK, VK_CONTROL, VK_OEM_2, VK_OEM_3, VK_OEM_COMMA,
    VK_OEM_PERIOD, VK_RETURN, VK_SHIFT, VK_SPACE, VK_TAB,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetForegroundWindow, GetMessageW,
    GetWindowTextLengthW, GetWindowTextW, PeekMessageW, PostMessageW, PostQuitMessage,
    RegisterClassW, SendMessageW, SetForegroundWindow, SetWindowTextW, ShowWindow,
    TranslateMessage, PM_REMOVE, SW_SHOW, WM_APP, WM_CLOSE, WM_DESTROY, WNDCLASSW, WS_CAPTION,
    WS_CHILD, WS_OVERLAPPED, WS_SYSMENU, WS_VISIBLE,
};

use super::*;

const WM_TEST_SET_LAYOUT_AND_FOCUS: u32 = WM_APP + 0x51;
const TEST_USER_EXTRA_INFO: usize = 0x4753_4554_4553_5431;
const WS_BORDER_STYLE: u32 = 0x0080_0000;
const ES_MULTILINE_STYLE: u32 = 0x0004;
const ES_PASSWORD_STYLE: u32 = 0x0020;
const ES_AUTOHSCROLL_STYLE: u32 = 0x0080;
const ES_WANTRETURN_STYLE: u32 = 0x1000;
const EM_SETSEL_VALUE: u32 = 0x00B1;
const VK_F9_VALUE: u16 = 0x78;
const VK_F10_VALUE: u16 = 0x79;
const VK_F11_VALUE: u16 = 0x7A;
const VK_F12_VALUE: u16 = 0x7B;

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

#[test]
#[ignore = "real Win32 keyboard hook / SendInput end-to-end release gate"]
fn real_windows_hook_to_edit_e2e() {
    let _injected_guard = InjectedInputGuard::enable();
    let original_runtime =
        settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    settings::set_paused(false);
    let (ready_tx, ready_rx) = mpsc::sync_channel(1);

    let ui_thread = thread::spawn(move || run_test_window(ready_tx));
    let (window_value, edit_value, password_value) = ready_rx
        .recv_timeout(Duration::from_secs(5))
        .expect("test Win32 window did not start");
    let window = window_value as HWND;
    let edit = edit_value as HWND;
    let password_edit = password_value as HWND;
    let ui_thread_id = unsafe { GetWindowThreadProcessId(edit, null_mut()) };
    assert_ne!(ui_thread_id, 0, "failed to resolve test EDIT thread");

    let engine = ENGINE.get_or_init(|| Mutex::new(Engine::default()));
    *engine.lock() = Engine::default();
    let hook = KeyboardHook::install().expect("failed to install WH_KEYBOARD_LL test hook");

    let russian_hkl = select_layout(Language::Russian).expect("Russian HKL is unavailable");
    for ch in ['б', 'ю', ',', '.'] {
        let encoded = unsafe { VkKeyScanExW(ch as u16, russian_hkl as *mut core::ffi::c_void) };
        eprintln!(
            "G-switcher E2E RU keymap: char={ch:?} hkl=0x{russian_hkl:x} encoded=0x{:04x} vk=0x{:02x} shift=0x{:02x}",
            encoded as u16,
            (encoded as u16) & 0xff,
            ((encoded as u16) >> 8) & 0xff
        );
    }

    prepare_case(window, edit, ui_thread_id, Language::Russian);
    let mut direct_target_inputs = Vec::new();
    assert!(append_text_for_layout(
        &mut direct_target_inputs,
        "бю,.",
        russian_hkl
    ));
    assert!(send_inputs_in_layout(&direct_target_inputs, russian_hkl));
    await_text(edit, "бю,.");

    prepare_case(window, edit, ui_thread_id, Language::English);
    assert!(
        switch_layout(edit, ui_thread_id, russian_hkl),
        "production layout switch EN -> RU failed"
    );
    let mut switched_target_inputs = Vec::new();
    assert!(append_text_for_layout(
        &mut switched_target_inputs,
        "бю,.",
        russian_hkl
    ));
    assert!(send_inputs_in_layout(&switched_target_inputs, russian_hkl));
    await_text(edit, "бю,.");

    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_SPACE as u8]),
        "привет ",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(b'R'),
            key(b'J'),
            key(b'H'),
            key(b'J'),
            key(VK_OEM_COMMA as u8),
            key(b'R'),
            key(b'F'),
            key(VK_SPACE as u8),
        ],
        "коробка ",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(b'C'),
            key(b'D'),
            key(b'J'),
            key(VK_OEM_COMMA as u8),
            key(b'J'),
            key(b'L'),
            key(b'E'),
            key(VK_SPACE as u8),
        ],
        "свободу ",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &keys(&[b'H', b'E', b'L', b'L', b'O', VK_SPACE as u8]),
        "hello ",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &keys(&[b'W', b'I', b'N', b'D', b'O', b'W', VK_SPACE as u8]),
        "window ",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &keys(&[b'W', b'I', b'N', b'D', b'O', b'W', b'S', VK_SPACE as u8]),
        "windows ",
    );

    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &[
            key(VK_OEM_COMMA as u8),
            key(b'T'),
            key(b'H'),
            key(b'E'),
            key(VK_SPACE as u8),
        ],
        "беру ",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &[
            key(b'T'),
            key(b'O'),
            key(VK_OEM_3 as u8),
            key(VK_SPACE as u8),
        ],
        "ещё ",
    );

    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &keys(&[
            b'H',
            b'E',
            b'L',
            b'L',
            b'O',
            VK_SPACE as u8,
            b'G',
            b'H',
            b'B',
            b'D',
            b'T',
            b'N',
            VK_SPACE as u8,
        ]),
        "hello привет ",
    );

    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_OEM_COMMA as u8]),
        "привет,",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_OEM_PERIOD as u8]),
        "привет.",
    );

    prepare_case(window, edit, ui_thread_id, Language::English);
    inject_strokes(&keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_OEM_2 as u8]));
    await_text(edit, "привет/");
    inject_strokes(&[key(VK_BACK as u8), key(VK_SPACE as u8)]);
    await_text(edit, "привет ");

    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_TAB as u8]),
        "привет\t",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_RETURN as u8]),
        "привет\r\n",
    );

    eprintln!("G-switcher E2E checkpoint: automatic undo");
    prepare_case(window, edit, ui_thread_id, Language::English);
    inject_strokes(&keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_SPACE as u8]));
    await_text(edit, "привет ");
    inject_undo_hotkey();
    await_text(edit, "ghbdtn ");
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::English),
        "undo did not restore the source keyboard layout"
    );

    eprintln!("G-switcher E2E checkpoint: pause");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    settings::set_paused(false);
    prepare_case(window, edit, ui_thread_id, Language::English);
    inject_ctrl_shift_hotkey(VK_F11_VALUE);
    assert!(settings::paused(), "pause hotkey did not pause runtime");
    inject_strokes(&keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_SPACE as u8]));
    await_text(edit, "ghbdtn ");
    inject_ctrl_shift_hotkey(VK_F11_VALUE);
    assert!(!settings::paused(), "pause hotkey did not resume runtime");
    await_text(edit, "ghbdtn ");

    eprintln!("G-switcher E2E checkpoint: manual-only");
    let process_name = process_name_for_pid(std::process::id()).expect("test process name missing");
    let mut manual_only = settings::RuntimeSettings::default();
    manual_only.manual_only_apps.push(process_name.clone());
    settings::replace_runtime_settings_for_test(manual_only);
    assert_eq!(
        settings::runtime_settings().app_mode(&process_name),
        AppMode::ManualOnly
    );
    prepare_case(window, edit, ui_thread_id, Language::English);
    inject_strokes(&keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_SPACE as u8]));
    eprintln!(
        "G-switcher E2E manual-only resolved process: {:?}",
        ENGINE
            .get()
            .map(|engine| engine.lock().process_name.clone())
    );
    await_text(edit, "ghbdtn ");
    inject_ctrl_shift_hotkey(VK_F10_VALUE);
    await_text(edit, "привет ");
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::Russian),
        "previous-word conversion did not switch to Russian"
    );
    inject_undo_hotkey();
    await_text(edit, "ghbdtn ");
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::English),
        "undo after previous-word conversion did not restore English"
    );

    eprintln!("G-switcher E2E checkpoint: disabled mode");
    let mut disabled = settings::RuntimeSettings::default();
    disabled.disabled_apps.push(process_name);
    settings::replace_runtime_settings_for_test(disabled);
    prepare_case(window, edit, ui_thread_id, Language::English);
    inject_strokes(&keys(b"GHBDTN"));
    await_text(edit, "ghbdtn");
    inject_ctrl_shift_hotkey(VK_F12_VALUE);
    await_text(edit, "ghbdtn");
    inject_strokes(&[key(VK_SPACE as u8)]);
    await_text(edit, "ghbdtn ");

    eprintln!("G-switcher E2E checkpoint: selected text 1.0");
    settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    prepare_case(window, edit, ui_thread_id, Language::English);
    set_text(edit, "ghbdtn rfr ltkf");
    unsafe {
        SendMessageW(edit, EM_SETSEL_VALUE, 0, -1);
    }
    inject_ctrl_shift_hotkey(VK_F9_VALUE);
    await_text(edit, "привет как дела");
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::Russian),
        "selected-text conversion did not switch to Russian"
    );
    inject_undo_hotkey();
    await_text(edit, "ghbdtn rfr ltkf");
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::English),
        "selected-text undo did not restore English"
    );

    eprintln!("G-switcher E2E checkpoint: password protection 1.0");
    prepare_case(window, password_edit, ui_thread_id, Language::English);
    inject_strokes(&keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_SPACE as u8]));
    await_text(password_edit, "ghbdtn ");
    unsafe {
        SendMessageW(password_edit, EM_SETSEL_VALUE, 0, -1);
    }
    inject_ctrl_shift_hotkey(VK_F9_VALUE);
    await_text(password_edit, "ghbdtn ");
    inject_ctrl_shift_hotkey(VK_F12_VALUE);
    await_text(password_edit, "ghbdtn ");

    settings::replace_runtime_settings_for_test(original_runtime);
    settings::set_paused(false);
    drop(hook);
    unsafe {
        PostMessageW(window, WM_CLOSE, 0, 0);
    }
    ui_thread.join().expect("test Win32 UI thread panicked");
}

fn run_case(
    window: HWND,
    edit: HWND,
    ui_thread_id: u32,
    source_language: Language,
    strokes: &[Stroke],
    expected: &str,
) {
    prepare_case(window, edit, ui_thread_id, source_language);
    inject_strokes(strokes);
    await_text(edit, expected);
}

fn prepare_case(window: HWND, edit: HWND, ui_thread_id: u32, language: Language) {
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
            "failed to request source layout"
        );
    }

    wait_until(Duration::from_secs(3), || {
        pump_hook_thread();
        let current = unsafe { GetKeyboardLayout(ui_thread_id) } as isize;
        let foreground = unsafe { GetForegroundWindow() };
        current == hkl && foreground == window
    });

    assert_eq!(
        unsafe { GetKeyboardLayout(ui_thread_id) } as isize,
        hkl,
        "test source layout did not activate"
    );
    assert_eq!(
        unsafe { GetForegroundWindow() },
        window,
        "test window is not the foreground input target"
    );
}

fn inject_strokes(strokes: &[Stroke]) {
    for stroke in strokes {
        let mut raw = Vec::with_capacity(4);
        if stroke.shift {
            raw.push((VK_SHIFT, 0));
        }
        raw.push((stroke.vk, 0));
        raw.push((stroke.vk, KEYEVENTF_KEYUP));
        if stroke.shift {
            raw.push((VK_SHIFT, KEYEVENTF_KEYUP));
        }
        inject_raw(&raw);
        pump_hook_thread();
        thread::sleep(Duration::from_millis(2));
    }
}

fn inject_ctrl_shift_hotkey(vk: u16) {
    inject_raw(&[
        (VK_CONTROL, 0),
        (VK_SHIFT, 0),
        (vk, 0),
        (vk, KEYEVENTF_KEYUP),
        (VK_SHIFT, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]);
}

fn inject_undo_hotkey() {
    inject_raw(&[
        (VK_CONTROL, 0),
        (VK_BACK, 0),
        (VK_BACK, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]);
}

fn inject_raw(events: &[(u16, u32)]) {
    let events = events.to_vec();
    let (done_tx, done_rx) = mpsc::sync_channel(1);
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(20));
        let inputs: Vec<INPUT> = events
            .into_iter()
            .map(|(vk, flags)| test_key_input(vk, flags))
            .collect();
        let sent = unsafe {
            SendInput(
                inputs.len() as u32,
                inputs.as_ptr(),
                size_of::<INPUT>() as i32,
            )
        };
        let _ = done_tx.send((sent, inputs.len() as u32));
    });

    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        pump_hook_thread();
        if let Ok((sent, expected)) = done_rx.try_recv() {
            assert_eq!(
                sent, expected,
                "SendInput did not inject the complete user sequence"
            );
            break;
        }
        assert!(
            Instant::now() < deadline,
            "SendInput/hook processing timed out"
        );
        thread::sleep(Duration::from_millis(2));
    }
}

fn await_text(edit: HWND, expected: &str) {
    wait_until(Duration::from_secs(3), || {
        pump_hook_thread();
        read_text(edit) == expected
    });
    assert_eq!(read_text(edit), expected);
}

fn wait_until(timeout: Duration, mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if condition() {
            return;
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn pump_hook_thread() {
    unsafe {
        let mut message = zeroed();
        while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
            if handle_runtime_message(&message) {
                continue;
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

fn set_text(edit: HWND, value: &str) {
    let value = wide(value);
    unsafe {
        assert_ne!(
            SetWindowTextW(edit, value.as_ptr()),
            0,
            "failed to set EDIT text"
        );
    }
}

fn read_text(edit: HWND) -> String {
    unsafe {
        let length = GetWindowTextLengthW(edit);
        let mut buffer = vec![0u16; length as usize + 1];
        let copied = GetWindowTextW(edit, buffer.as_mut_ptr(), buffer.len() as i32);
        String::from_utf16_lossy(&buffer[..copied as usize])
    }
}

fn test_key_input(vk: u16, flags: u32) -> INPUT {
    INPUT {
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
    }
}

fn key(vk: u8) -> Stroke {
    Stroke {
        vk: vk as u16,
        shift: false,
    }
}

fn keys(values: &[u8]) -> Vec<Stroke> {
    values.iter().copied().map(key).collect()
}

fn run_test_window(ready_tx: mpsc::SyncSender<(isize, isize, isize)>) {
    unsafe {
        let module = GetModuleHandleW(null());
        let class_name = wide("GSwitcher.E2E.Window");
        let window_class = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(test_window_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: module,
            hIcon: null_mut(),
            hCursor: null_mut(),
            hbrBackground: null_mut(),
            lpszMenuName: null(),
            lpszClassName: class_name.as_ptr(),
        };
        assert_ne!(
            RegisterClassW(&window_class),
            0,
            "failed to register E2E window class"
        );

        let title = wide("G-switcher E2E");
        let window = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
            40,
            40,
            660,
            250,
            null_mut(),
            null_mut(),
            module,
            null(),
        );
        assert!(!window.is_null(), "failed to create E2E top-level window");

        let edit_class = wide("EDIT");
        let empty = wide("");
        let edit = CreateWindowExW(
            0,
            edit_class.as_ptr(),
            empty.as_ptr(),
            WS_CHILD
                | WS_VISIBLE
                | WS_BORDER_STYLE
                | ES_MULTILINE_STYLE
                | ES_AUTOHSCROLL_STYLE
                | ES_WANTRETURN_STYLE,
            20,
            20,
            600,
            100,
            window,
            null_mut(),
            module,
            null(),
        );
        assert!(!edit.is_null(), "failed to create E2E EDIT control");

        let password_edit = CreateWindowExW(
            0,
            edit_class.as_ptr(),
            empty.as_ptr(),
            WS_CHILD | WS_VISIBLE | WS_BORDER_STYLE | ES_AUTOHSCROLL_STYLE | ES_PASSWORD_STYLE,
            20,
            145,
            600,
            30,
            window,
            null_mut(),
            module,
            null(),
        );
        assert!(
            !password_edit.is_null(),
            "failed to create E2E password EDIT control"
        );

        ShowWindow(window, SW_SHOW);
        SetForegroundWindow(window);
        SetFocus(edit);
        ready_tx
            .send((window as isize, edit as isize, password_edit as isize))
            .expect("failed to publish E2E window handles");

        let mut message = zeroed();
        while GetMessageW(&mut message, null_mut(), 0, 0) > 0 {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

unsafe extern "system" fn test_window_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        WM_TEST_SET_LAYOUT_AND_FOCUS => {
            ActivateKeyboardLayout(wparam as *mut core::ffi::c_void, 0);
            SetForegroundWindow(hwnd);
            SetFocus(lparam as HWND);
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}
