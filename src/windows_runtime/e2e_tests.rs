use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    ActivateKeyboardLayout, GetKeyboardLayout, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD,
    KEYBDINPUT, KEYEVENTF_KEYUP, VK_BACK, VK_CONTROL, VK_OEM_2, VK_OEM_3, VK_OEM_COMMA,
    VK_OEM_PERIOD, VK_RETURN, VK_SHIFT, VK_SPACE, VK_TAB,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetForegroundWindow, GetMessageW,
    GetWindowTextLengthW, GetWindowTextW, PeekMessageW, PostMessageW, PostQuitMessage,
    RegisterClassW, SetFocus, SetForegroundWindow, SetWindowTextW, ShowWindow, TranslateMessage,
    WNDCLASSW, PM_REMOVE, SW_SHOW, WM_APP, WM_CLOSE, WM_DESTROY, WS_CAPTION, WS_CHILD,
    WS_OVERLAPPED, WS_SYSMENU, WS_VISIBLE,
};

use super::*;

const WM_TEST_SET_LAYOUT_AND_FOCUS: u32 = WM_APP + 0x51;
const TEST_USER_EXTRA_INFO: usize = 0x4753_4554_4553_5431;
const WS_BORDER_STYLE: u32 = 0x0080_0000;
const ES_MULTILINE_STYLE: u32 = 0x0004;
const ES_AUTOHSCROLL_STYLE: u32 = 0x0080;
const ES_WANTRETURN_STYLE: u32 = 0x1000;

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
    let (ready_tx, ready_rx) = mpsc::sync_channel(1);

    let ui_thread = thread::spawn(move || run_test_window(ready_tx));
    let (window_value, edit_value) = ready_rx
        .recv_timeout(Duration::from_secs(5))
        .expect("test Win32 window did not start");
    let window = window_value as HWND;
    let edit = edit_value as HWND;
    let ui_thread_id = unsafe { GetWindowThreadProcessId(edit, null_mut()) };
    assert_ne!(ui_thread_id, 0, "failed to resolve test EDIT thread");

    let engine = ENGINE.get_or_init(|| Mutex::new(Engine::default()));
    *engine.lock() = Engine::default();
    let hook = KeyboardHook::install().expect("failed to install WH_KEYBOARD_LL test hook");

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
        "windows ",
    );

    // Regression: Russian physical comma is the letter 'б', not a word boundary.
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

    // A correction can switch the target layout and the next word can switch it back.
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::Russian,
        &keys(&[
            b'H', b'E', b'L', b'L', b'O', VK_SPACE as u8, b'G', b'H', b'B', b'D', b'T', b'N',
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
    inject_strokes(&keys(&[
        b'G', b'H', b'B', b'D', b'T', b'N', VK_OEM_2 as u8,
    ]));
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

    // Undo must survive the Ctrl key-down and restore both text and source layout.
    prepare_case(window, edit, ui_thread_id, Language::English);
    inject_strokes(&keys(&[b'G', b'H', b'B', b'D', b'T', b'N', VK_SPACE as u8]));
    await_text(edit, "привет ");
    inject_raw(&[
        (VK_CONTROL, 0),
        (VK_BACK, 0),
        (VK_BACK, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]);
    await_text(edit, "ghbdtn ");
    assert_eq!(
        language_from_hkl(unsafe { GetKeyboardLayout(ui_thread_id) } as isize),
        Some(Language::English),
        "undo did not restore the source keyboard layout"
    );

    drop(hook);
    unsafe {
        PostMessageW(window, WM_CLOSE, 0, 0);
    }
    ui_thread
        .join()
        .expect("test Win32 UI thread panicked");
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
    *ENGINE
        .get_or_init(|| Mutex::new(Engine::default()))
        .lock() = Engine::default();

    let empty = wide("");
    unsafe {
        assert_ne!(SetWindowTextW(edit, empty.as_ptr()), 0, "failed to clear EDIT text");
    }

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
    let mut raw = Vec::new();
    for stroke in strokes {
        if stroke.shift {
            raw.push((VK_SHIFT, 0));
        }
        raw.push((stroke.vk, 0));
        raw.push((stroke.vk, KEYEVENTF_KEYUP));
        if stroke.shift {
            raw.push((VK_SHIFT, KEYEVENTF_KEYUP));
        }
    }
    inject_raw(&raw);
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
            assert_eq!(sent, expected, "SendInput did not inject the complete user sequence");
            break;
        }
        assert!(Instant::now() < deadline, "SendInput/hook processing timed out");
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
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
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

fn run_test_window(ready_tx: mpsc::SyncSender<(isize, isize)>) {
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
        assert_ne!(RegisterClassW(&window_class), 0, "failed to register E2E window class");

        let title = wide("G-switcher E2E");
        let window = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
            40,
            40,
            660,
            180,
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

        ShowWindow(window, SW_SHOW);
        SetForegroundWindow(window);
        SetFocus(edit);
        ready_tx
            .send((window as isize, edit as isize))
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
