use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut, without_provenance};
use std::sync::atomic::{AtomicI32, Ordering};

use anyhow::{anyhow, Result};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{GetStockObject, DEFAULT_GUI_FONT};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::Sleep;
use windows_sys::Win32::UI::Shell::{
    Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NOTIFYICONDATAW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu, DestroyWindow,
    DispatchMessageW, GetCursorPos, GetDlgItem, GetSystemMetrics, IsWindow, LoadCursorW, LoadIconW,
    PeekMessageW, PostQuitMessage, RegisterClassW, SendMessageW, SetForegroundWindow, ShowWindow,
    TrackPopupMenu, TranslateMessage, BM_GETCHECK, BM_SETCHECK, BS_AUTOCHECKBOX, BS_DEFPUSHBUTTON,
    IDC_ARROW, MF_SEPARATOR, MF_STRING, MSG, PM_REMOVE, SM_CXSCREEN, SM_CYSCREEN, STM_SETICON,
    SW_SHOW, TPM_RETURNCMD, TPM_RIGHTBUTTON, WM_APP, WM_CLOSE, WM_COMMAND, WM_RBUTTONUP,
    WM_SETFONT, WNDCLASSW, WS_CAPTION, WS_CHILD, WS_OVERLAPPED, WS_SYSMENU, WS_VISIBLE,
};

use super::settings;

const FIRST_RUN_CLASS: &str = "GSwitcher.FirstRun";
const TRAY_CLASS: &str = "GSwitcher.Tray";
const TRAY_ID: u32 = 1;
const WM_TRAY: u32 = WM_APP + 7;
const ID_AUTOSTART: usize = 1001;
const ID_EXIT: usize = 1002;
const ID_CHECKBOX: i32 = 2001;
const ID_OK: i32 = 2002;
const BST_CHECKED_VALUE: u32 = 1;
const COLOR_WINDOW_INDEX: usize = 5;
const SS_LEFT_STYLE: u32 = 0;
const SS_ICON_STYLE: u32 = 0x0000_0003;

static FIRST_RUN_RESULT: AtomicI32 = AtomicI32::new(-1);

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
            hbrBackground: (COLOR_WINDOW_INDEX + 1) as *mut core::ffi::c_void,
            lpszMenuName: null(),
            lpszClassName: class.as_ptr(),
        };
        if RegisterClassW(&window_class) == 0 {
            return Err(anyhow!("RegisterClassW for first-run window failed"));
        }

        let width = 480;
        let height = 245;
        let x = (GetSystemMetrics(SM_CXSCREEN) - width) / 2;
        let y = (GetSystemMetrics(SM_CYSCREEN) - height) / 2;
        let title = wide("G-switcher — первый запуск");
        let hwnd = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU,
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
        WM_CLOSE => {
            FIRST_RUN_RESULT.store(0, Ordering::SeqCst);
            DestroyWindow(hwnd);
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
        25,
        25,
        72,
        72,
        hwnd,
        null_mut(),
        module,
        null(),
    );
    SendMessageW(icon_control, STM_SETICON, load_app_icon() as usize, 0);

    let text = wide(
        "G-switcher автоматически исправляет текст, набранный в неверной русской/английской раскладке.\r\nРаботает локально, без сети и телеметрии.",
    );
    let description = CreateWindowExW(
        0,
        static_class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE | SS_LEFT_STYLE,
        115,
        25,
        330,
        70,
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
        115,
        105,
        320,
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
        25,
        175,
        260,
        25,
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
        350,
        165,
        95,
        32,
        hwnd,
        ID_OK as usize as *mut core::ffi::c_void,
        module,
        null(),
    );

    let font = GetStockObject(DEFAULT_GUI_FONT);
    for control in [description, checkbox, footer, ok] {
        SendMessageW(control, WM_SETFONT, font as usize, 1);
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

    let autostart_label = if settings::autostart_enabled() {
        "Убрать из автозапуска"
    } else {
        "Добавить в автозапуск"
    };
    let autostart_label = wide(autostart_label);
    let exit_label = wide("Выход");
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
