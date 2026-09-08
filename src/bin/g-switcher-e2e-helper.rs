#![cfg_attr(not(windows), allow(dead_code, unused_imports))]

#[cfg(windows)]
use std::io::{self, Write};
#[cfg(windows)]
use std::mem::zeroed;
#[cfg(windows)]
use std::ptr::{null, null_mut};

#[cfg(windows)]
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
#[cfg(windows)]
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
#[cfg(windows)]
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{ActivateKeyboardLayout, SetFocus};
#[cfg(windows)]
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GetMessageW, PostQuitMessage,
    RegisterClassW, SetForegroundWindow, ShowWindow, TranslateMessage, SW_SHOW, WM_APP, WM_CLOSE,
    WM_DESTROY, WNDCLASSW, WS_CAPTION, WS_CHILD, WS_OVERLAPPED, WS_SYSMENU, WS_VISIBLE,
};

#[cfg(windows)]
const WM_TEST_SET_LAYOUT_AND_FOCUS: u32 = WM_APP + 0x51;
#[cfg(windows)]
const WS_BORDER_STYLE: u32 = 0x0080_0000;
#[cfg(windows)]
const ES_MULTILINE_STYLE: u32 = 0x0004;
#[cfg(windows)]
const ES_PASSWORD_STYLE: u32 = 0x0020;
#[cfg(windows)]
const ES_AUTOHSCROLL_STYLE: u32 = 0x0080;
#[cfg(windows)]
const ES_WANTRETURN_STYLE: u32 = 0x1000;

#[cfg(windows)]
fn main() {
    unsafe {
        let module = GetModuleHandleW(null());
        let class_name = wide("GSwitcher.E2E.Helper.Window");
        let window_class = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(window_proc),
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
            "failed to register E2E helper window class"
        );

        let title = wide("G-switcher cross-process E2E helper");
        let window = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
            60,
            60,
            700,
            280,
            null_mut(),
            null_mut(),
            module,
            null(),
        );
        assert!(!window.is_null(), "failed to create helper top-level window");

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
            640,
            110,
            window,
            null_mut(),
            module,
            null(),
        );
        assert!(!edit.is_null(), "failed to create helper EDIT control");

        let password = CreateWindowExW(
            0,
            edit_class.as_ptr(),
            empty.as_ptr(),
            WS_CHILD | WS_VISIBLE | WS_BORDER_STYLE | ES_AUTOHSCROLL_STYLE | ES_PASSWORD_STYLE,
            20,
            160,
            640,
            32,
            window,
            null_mut(),
            module,
            null(),
        );
        assert!(!password.is_null(), "failed to create helper password EDIT");

        ShowWindow(window, SW_SHOW);
        SetForegroundWindow(window);
        SetFocus(edit);

        println!(
            "GSE2E {} {} {} {}",
            window as usize,
            edit as usize,
            password as usize,
            std::process::id()
        );
        io::stdout().flush().expect("failed to flush helper handles");

        let mut message = zeroed();
        while GetMessageW(&mut message, null_mut(), 0, 0) > 0 {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

#[cfg(windows)]
unsafe extern "system" fn window_proc(
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
        WM_CLOSE => {
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

#[cfg(windows)]
fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(not(windows))]
fn main() {}
