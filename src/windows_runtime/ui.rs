mod settings_dialog;

use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut, without_provenance};
use std::sync::atomic::{AtomicI32, AtomicIsize, Ordering};

use anyhow::{anyhow, Result};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    CreateFontW, DeleteObject, GetStockObject, GetSysColorBrush, SetBkMode, DEFAULT_GUI_FONT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::Sleep;
use windows_sys::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NOTIFYICONDATAW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AdjustWindowRectEx, AppendMenuW, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu,
    DestroyWindow, DispatchMessageW, GetCursorPos, GetDlgItem, GetSystemMetrics, IsWindow,
    LoadCursorW, LoadIconW, LoadImageW, PeekMessageW, PostQuitMessage, RegisterClassW,
    SendMessageW, SetForegroundWindow, ShowWindow, TrackPopupMenu, TranslateMessage, BM_GETCHECK,
    BM_SETCHECK, BS_AUTOCHECKBOX, BS_DEFPUSHBUTTON, IDC_ARROW, MF_SEPARATOR, MF_STRING, MSG,
    PM_REMOVE, SM_CXSCREEN, SM_CYSCREEN, STM_SETICON, SW_SHOW, TPM_RETURNCMD, TPM_RIGHTBUTTON,
    WM_APP, WM_CLOSE, WM_COMMAND, WM_CTLCOLORSTATIC, WM_DESTROY, WM_RBUTTONUP, WM_SETFONT,
    WNDCLASSW, WS_CAPTION, WS_CHILD, WS_OVERLAPPED, WS_SYSMENU, WS_VISIBLE,
};

use super::{paused, settings, toggle_pause};

const FIRST_RUN_CLASS: &str = "GSwitcher.FirstRun";
const TRAY_CLASS: &str = "GSwitcher.Tray";
const TRAY_ID: u32 = 1;
const WM_TRAY: u32 = WM_APP + 7;
const ID_SETTINGS: usize = 1000;
const ID_AUTOSTART: usize = 1001;
const ID_EXIT: usize = 1002;
const ID_PAUSE: usize = 1003;
const ID_CHECKBOX: i32 = 2001;
const ID_OK: i32 = 2002;
const BST_CHECKED_VALUE: u32 = 1;
const COLOR_3DFACE_INDEX: i32 = 15;
const SS_LEFT_STYLE: u32 = 0;
const SS_ICON_STYLE: u32 = 0x0000_0003;
const SS_ETCHEDHORZ_STYLE: u32 = 0x0000_0010;
const IMAGE_ICON_VALUE: u32 = 1;
const LR_SHARED_VALUE: u32 = 0x0000_8000;
const TRANSPARENT_BK_MODE: i32 = 1;

static FIRST_RUN_RESULT: AtomicI32 = AtomicI32::new(-1);
static TITLE_FONT: AtomicIsize = AtomicIsize::new(0);
static EMPHASIS_FONT: AtomicIsize = AtomicIsize::new(0);
static BODY_FONT: AtomicIsize = AtomicIsize::new(0);

pub struct TrayGuard {
    hwnd: HWND,
    data: NOTIFYICONDATAW,
}

impl TrayGuard {
    pub fn install() -> Result<Self> {
        unsafe {
            let module = GetModuleHandleW(null());
            let class = wide(TRAY_CLASS);
            let window_class = WNDCLASSW {
                style: 0,
                lpfnWndProc: Some(tray_proc),
                cbClsExtra: 0,
                cbWndExtra: 0,
                hInstance: module,
                hIcon: load_app_icon(),
                hCursor: LoadCursorW(null_mut(), IDC_ARROW),
                hbrBackground: null_mut(),
                lpszMenuName: null(),
                lpszClassName: class.as_ptr(),
            };
            if RegisterClassW(&window_class) == 0 {
                return Err(anyhow!("RegisterClassW for tray failed"));
            }

            let title = wide("G-switcher");
            let hwnd = CreateWindowExW(
                0,
                class.as_ptr(),
                title.as_ptr(),
                WS_OVERLAPPED,
                0,
                0,
                0,
                0,
                null_mut(),
                null_mut(),
                module,
                null(),
            );
            if hwnd.is_null() {
                return Err(anyhow!("CreateWindowExW for tray failed"));
            }

            let mut data: NOTIFYICONDATAW = zeroed();
            data.cbSize = size_of::<NOTIFYICONDATAW>() as u32;
            data.hWnd = hwnd;
            data.uID = TRAY_ID;
            data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
            data.uCallbackMessage = WM_TRAY;
            data.hIcon = load_app_icon();
            fill_wide_array(&mut data.szTip, "G-switcher");
            if Shell_NotifyIconW(NIM_ADD, &data) == 0 {
                DestroyWindow(hwnd);
                return Err(anyhow!("Shell_NotifyIconW(NIM_ADD) failed"));
            }

            Ok(Self { hwnd, data })
        }
    }
}

impl Drop for TrayGuard {
    fn drop(&mut self) {
        unsafe {
            Shell_NotifyIconW(NIM_DELETE, &self.data);
            if !self.hwnd.is_null() {
                DestroyWindow(self.hwnd);
            }
        }
    }
}

pub fn show_first_run() -> Result<bool> {
    FIRST_RUN_RESULT.store(-1, Ordering::SeqCst);
    unsafe {
        let module = GetModuleHandleW(null());
        let class = wide(FIRST_RUN_CLASS);
        let window_class = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(first_run_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: module,
            hIcon: load_app_icon(),
            hCursor: LoadCursorW(null_mut(), IDC_ARROW),
            hbrBackground: GetSysColorBrush(COLOR_3DFACE_INDEX),
            lpszMenuName: null(),
            lpszClassName: class.as_ptr(),
        };
        if RegisterClassW(&window_class) == 0 {
            return Err(anyhow!("RegisterClassW for first-run window failed"));
        }

        // CreateWindowExW expects the outer window dimensions, while all child controls use
        // client coordinates. Reserve the client area explicitly so title-bar/DPI metrics can
        // never squeeze the bottom row as happened in 0.8.0.
        let client_width = 680;
        let client_height = 550;
        let style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU;
        let mut window_rect = RECT {
            left: 0,
            top: 0,
            right: client_width,
            bottom: client_height,
        };
        if AdjustWindowRectEx(&mut window_rect, style, 0, 0) == 0 {
            return Err(anyhow!("AdjustWindowRectEx for first-run window failed"));
        }
        let width = window_rect.right - window_rect.left;
        let height = window_rect.bottom - window_rect.top;
        let x = (GetSystemMetrics(SM_CXSCREEN) - width) / 2;
        let y = (GetSystemMetrics(SM_CYSCREEN) - height) / 2;
        let title = wide("G-switcher — первый запуск");
        let hwnd = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            style,
            x,
            y,
            width,
            height,
            null_mut(),
            null_mut(),
            module,
            null(),
        );
        if hwnd.is_null() {
            return Err(anyhow!("CreateWindowExW for first-run window failed"));
        }

        ShowWindow(hwnd, SW_SHOW);

        let mut message: MSG = zeroed();
        while IsWindow(hwnd) != 0 {
            while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            Sleep(10);
        }
    }

    Ok(FIRST_RUN_RESULT.load(Ordering::SeqCst) == 1)
}

unsafe extern "system" fn first_run_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        windows_sys::Win32::UI::WindowsAndMessaging::WM_CREATE => {
            create_first_run_controls(hwnd);
            0
        }
        WM_COMMAND => {
            let command = (wparam & 0xffff) as i32;
            if command == ID_OK {
                let checkbox = GetDlgItem(hwnd, ID_CHECKBOX);
                let checked = SendMessageW(checkbox, BM_GETCHECK, 0, 0) as u32 == BST_CHECKED_VALUE;
                FIRST_RUN_RESULT.store(i32::from(checked), Ordering::SeqCst);
                DestroyWindow(hwnd);
                return 0;
            }
            DefWindowProcW(hwnd, message, wparam, lparam)
        }
        WM_CTLCOLORSTATIC => {
            SetBkMode(wparam as *mut core::ffi::c_void, TRANSPARENT_BK_MODE);
            GetSysColorBrush(COLOR_3DFACE_INDEX) as LRESULT
        }
        WM_CLOSE => {
            FIRST_RUN_RESULT.store(0, Ordering::SeqCst);
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            cleanup_first_run_fonts();
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

unsafe fn create_first_run_controls(hwnd: HWND) {
    let module = GetModuleHandleW(null());
    let static_class = wide("STATIC");
    let button_class = wide("BUTTON");
    let empty = wide("");

    let icon_control = CreateWindowExW(
        0,
        static_class.as_ptr(),
        empty.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_ICON_STYLE,
        36,
        30,
        116,
        116,
        hwnd,
        null_mut(),
        module,
        null(),
    );
    SendMessageW(
        icon_control,
        STM_SETICON,
        load_app_icon_sized(112, 112) as usize,
        0,
    );

    let title_text = wide("G-switcher");
    let title = CreateWindowExW(
        0,
        static_class.as_ptr(),
        title_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        176,
        34,
        448,
        40,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let description_text = wide(
        "Исправляет слова, набранные в неверной русской или английской раскладке.\r\nРаботает полностью локально — без сети, облака и телеметрии.",
    );
    let description = CreateWindowExW(
        0,
        static_class.as_ptr(),
        description_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        176,
        82,
        448,
        58,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let privacy_text = wide("Набираемый текст не сохраняется на диск.");
    let privacy = CreateWindowExW(
        0,
        static_class.as_ptr(),
        privacy_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        176,
        146,
        448,
        24,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let separator = CreateWindowExW(
        0,
        static_class.as_ptr(),
        empty.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_ETCHEDHORZ_STYLE,
        36,
        184,
        608,
        2,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let examples_header_text = wide("Примеры");
    let examples_header = CreateWindowExW(
        0,
        static_class.as_ptr(),
        examples_header_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        36,
        207,
        160,
        24,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let examples_text = wide("ghbdtn  →  привет            руддщ  →  hello");
    let examples = CreateWindowExW(
        0,
        static_class.as_ptr(),
        examples_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        36,
        237,
        608,
        26,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let undo_header_text = wide("Быстрая отмена");
    let undo_header = CreateWindowExW(
        0,
        static_class.as_ptr(),
        undo_header_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        36,
        282,
        260,
        24,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let undo_text =
        wide("Ctrl+Backspace сразу после замены вернёт исходное слово и прежнюю раскладку.");
    let undo = CreateWindowExW(
        0,
        static_class.as_ptr(),
        undo_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        36,
        312,
        608,
        42,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let settings_hint_text =
        wide("Горячие клавиши и режимы приложений: значок G-switcher в трее → «Настройки».");
    let settings_hint = CreateWindowExW(
        0,
        static_class.as_ptr(),
        settings_hint_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        36,
        358,
        608,
        46,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let footer_separator = CreateWindowExW(
        0,
        static_class.as_ptr(),
        empty.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_ETCHEDHORZ_STYLE,
        36,
        422,
        608,
        2,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let checkbox_text = wide("Запускать G-switcher при входе в Windows");
    let checkbox = CreateWindowExW(
        0,
        button_class.as_ptr(),
        checkbox_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX as u32,
        36,
        442,
        390,
        28,
        hwnd,
        ID_CHECKBOX as usize as *mut core::ffi::c_void,
        module,
        null(),
    );
    SendMessageW(checkbox, BM_SETCHECK, BST_CHECKED_VALUE as usize, 0);

    let footer_text = wide("G-switcher © V. Vasilev 2026");
    let footer = CreateWindowExW(
        0,
        static_class.as_ptr(),
        footer_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        36,
        516,
        300,
        20,
        hwnd,
        null_mut(),
        module,
        null(),
    );

    let ok_text = wide("OK");
    let ok = CreateWindowExW(
        0,
        button_class.as_ptr(),
        ok_text.as_ptr(),
        WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON as u32,
        532,
        437,
        112,
        36,
        hwnd,
        ID_OK as usize as *mut core::ffi::c_void,
        module,
        null(),
    );

    let default_font = GetStockObject(DEFAULT_GUI_FONT);
    let body_font = create_ui_font(-16, 400);
    let emphasis_font = create_ui_font(-17, 600);
    let title_font = create_ui_font(-28, 600);

    store_font(&BODY_FONT, body_font);
    store_font(&EMPHASIS_FONT, emphasis_font);
    store_font(&TITLE_FONT, title_font);

    let body_font = if body_font.is_null() {
        default_font
    } else {
        body_font
    };
    let emphasis_font = if emphasis_font.is_null() {
        body_font
    } else {
        emphasis_font
    };
    let title_font = if title_font.is_null() {
        emphasis_font
    } else {
        title_font
    };

    SendMessageW(title, WM_SETFONT, title_font as usize, 1);
    for control in [examples_header, undo_header] {
        SendMessageW(control, WM_SETFONT, emphasis_font as usize, 1);
    }
    for control in [
        description,
        privacy,
        examples,
        undo,
        settings_hint,
        checkbox,
        footer,
        ok,
        separator,
        footer_separator,
    ] {
        SendMessageW(control, WM_SETFONT, body_font as usize, 1);
    }
}

unsafe fn create_ui_font(height: i32, weight: i32) -> *mut core::ffi::c_void {
    let face = wide("Segoe UI");
    CreateFontW(
        height,
        0,
        0,
        0,
        weight,
        0,
        0,
        0,
        1,
        0,
        0,
        5,
        0,
        face.as_ptr(),
    )
}

fn store_font(slot: &AtomicIsize, font: *mut core::ffi::c_void) {
    if !font.is_null() {
        slot.store(font as isize, Ordering::SeqCst);
    }
}

unsafe fn cleanup_first_run_fonts() {
    for slot in [&TITLE_FONT, &EMPHASIS_FONT, &BODY_FONT] {
        let font = slot.swap(0, Ordering::SeqCst);
        if font != 0 {
            DeleteObject(font as *mut core::ffi::c_void);
        }
    }
}

unsafe extern "system" fn tray_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        WM_TRAY => {
            if lparam as u32 == WM_RBUTTONUP {
                show_tray_menu(hwnd);
            }
            0
        }
        WM_COMMAND => {
            match wparam & 0xffff {
                ID_PAUSE => {
                    toggle_pause();
                }
                ID_SETTINGS => {
                    let _ = settings_dialog::show();
                }
                ID_AUTOSTART => {
                    let enabled = settings::autostart_enabled();
                    let _ = settings::set_autostart(!enabled);
                }
                ID_EXIT => PostQuitMessage(0),
                _ => {}
            }
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

unsafe fn show_tray_menu(hwnd: HWND) {
    let menu = CreatePopupMenu();
    if menu.is_null() {
        return;
    }

    let pause_label = wide(if paused() {
        "Возобновить G-switcher"
    } else {
        "Приостановить G-switcher"
    });
    let settings_label = wide("Настройки…");
    let autostart_label = if settings::autostart_enabled() {
        "Убрать из автозапуска"
    } else {
        "Добавить в автозапуск"
    };
    let autostart_label = wide(autostart_label);
    let exit_label = wide("Выход");
    AppendMenuW(menu, MF_STRING, ID_PAUSE, pause_label.as_ptr());
    AppendMenuW(menu, MF_STRING, ID_SETTINGS, settings_label.as_ptr());
    AppendMenuW(menu, MF_SEPARATOR, 0, null());
    AppendMenuW(menu, MF_STRING, ID_AUTOSTART, autostart_label.as_ptr());
    AppendMenuW(menu, MF_SEPARATOR, 0, null());
    AppendMenuW(menu, MF_STRING, ID_EXIT, exit_label.as_ptr());

    let mut point = POINT { x: 0, y: 0 };
    GetCursorPos(&mut point);
    SetForegroundWindow(hwnd);
    let command = TrackPopupMenu(
        menu,
        TPM_RIGHTBUTTON | TPM_RETURNCMD,
        point.x,
        point.y,
        0,
        hwnd,
        null(),
    );
    DestroyMenu(menu);

    if command != 0 {
        SendMessageW(hwnd, WM_COMMAND, command as usize, 0);
    }
}

unsafe fn load_app_icon_sized(width: i32, height: i32) -> *mut core::ffi::c_void {
    let module = GetModuleHandleW(null());
    let icon = LoadImageW(
        module,
        without_provenance::<u16>(1),
        IMAGE_ICON_VALUE,
        width,
        height,
        LR_SHARED_VALUE,
    );
    if icon.is_null() {
        load_app_icon()
    } else {
        icon
    }
}

unsafe fn load_app_icon() -> *mut core::ffi::c_void {
    let module = GetModuleHandleW(null());
    let icon = LoadIconW(module, without_provenance::<u16>(1));
    if icon.is_null() {
        LoadIconW(
            null_mut(),
            windows_sys::Win32::UI::WindowsAndMessaging::IDI_APPLICATION,
        )
    } else {
        icon
    }
}

fn fill_wide_array<const N: usize>(target: &mut [u16; N], value: &str) {
    let encoded: Vec<u16> = value.encode_utf16().collect();
    let length = encoded.len().min(N.saturating_sub(1));
    target[..length].copy_from_slice(&encoded[..length]);
    target[length] = 0;
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}
