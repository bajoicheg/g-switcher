use std::ptr::{null, null_mut};
use std::sync::atomic::Ordering;

use anyhow::{anyhow, Result};
use windows_sys::Win32::Foundation::{
    GetLastError, ERROR_CLASS_ALREADY_EXISTS, HWND, LPARAM, LRESULT, WPARAM,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, RegisterClassW, HWND_MESSAGE, WNDCLASSW,
};

use super::{
    decode_hook_event, ENGINE, RUNTIME_WINDOW, WM_RUNTIME_CORRECTION, WM_RUNTIME_INVALIDATE,
    WM_RUNTIME_KEY_EVENT, WM_RUNTIME_SELECTION,
};

const CLASS_NAME: &str = concat!("GSwitcher.RuntimeDispatch.", env!("CARGO_PKG_VERSION"));

pub struct RuntimeDispatchWindow {
    hwnd: HWND,
}

impl RuntimeDispatchWindow {
    pub fn install() -> Result<Self> {
        unsafe {
            let module = GetModuleHandleW(null());
            let class = wide(CLASS_NAME);
            let window_class = WNDCLASSW {
                style: 0,
                lpfnWndProc: Some(runtime_proc),
                cbClsExtra: 0,
                cbWndExtra: 0,
                hInstance: module,
                hIcon: null_mut(),
                hCursor: null_mut(),
                hbrBackground: null_mut(),
                lpszMenuName: null(),
                lpszClassName: class.as_ptr(),
            };
            if RegisterClassW(&window_class) == 0 && GetLastError() != ERROR_CLASS_ALREADY_EXISTS {
                return Err(anyhow!("RegisterClassW for runtime dispatch failed"));
            }

            let title = wide("");
            let hwnd = CreateWindowExW(
                0,
                class.as_ptr(),
                title.as_ptr(),
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                null_mut(),
                module,
                null(),
            );
            if hwnd.is_null() {
                return Err(anyhow!("CreateWindowExW for runtime dispatch failed"));
            }

            RUNTIME_WINDOW.store(hwnd as isize, Ordering::SeqCst);
            Ok(Self { hwnd })
        }
    }
}

impl Drop for RuntimeDispatchWindow {
    fn drop(&mut self) {
        RUNTIME_WINDOW
            .compare_exchange(self.hwnd as isize, 0, Ordering::SeqCst, Ordering::SeqCst)
            .ok();
        unsafe {
            if !self.hwnd.is_null() {
                DestroyWindow(self.hwnd);
            }
        }
    }
}

unsafe extern "system" fn runtime_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    let Some(engine) = ENGINE.get() else {
        return DefWindowProcW(hwnd, message, wparam, lparam);
    };

    match message {
        WM_RUNTIME_KEY_EVENT => {
            engine
                .lock()
                .on_key_event(decode_hook_event(wparam, lparam));
            0
        }
        WM_RUNTIME_CORRECTION => {
            engine.lock().execute_pending_correction();
            0
        }
        WM_RUNTIME_SELECTION => {
            engine.lock().execute_pending_selection();
            0
        }
        WM_RUNTIME_INVALIDATE => {
            engine.lock().reset_transient();
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}
