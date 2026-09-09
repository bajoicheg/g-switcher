use std::cell::RefCell;
use std::mem::{size_of, zeroed};

use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::UI::Accessibility::{CUIAutomation, IUIAutomation};
use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, GetGUIThreadInfo, GetWindowThreadProcessId, SendMessageTimeoutW,
    GUITHREADINFO, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_NULL,
};

const UIA_PREFLIGHT_TIMEOUT_MS: u32 = 75;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UiaSecurityProbe {
    pub process_id: u32,
    pub native_hwnd: isize,
    pub is_password: bool,
}

thread_local! {
    // COM/UI Automation objects remain on the runtime worker thread. We never
    // retain an element object, its Name/Value/TextPattern, or user input.
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
}

/// Queries only metadata needed to decide whether the currently focused UIA
/// element is protected. No text-bearing UI Automation property or pattern is
/// requested. Failure is returned as None so the caller can fail open (leave
/// user input unchanged) for unsupported, hung, or disappearing controls.
pub fn probe_focused(expected_process_id: u32) -> Option<UiaSecurityProbe> {
    // Avoid entering a potentially blocking UIA provider when the Win32 focus
    // thread is already unresponsive. This does not read any user text.
    let _responsive_hwnd = responsive_focused_hwnd(expected_process_id)?;

    AUTOMATION.with(|slot| {
        if slot.borrow().is_none() {
            unsafe {
                CoInitializeEx(None, COINIT_MULTITHREADED).ok().ok()?;
                let automation: IUIAutomation =
                    CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()?;
                *slot.borrow_mut() = Some(automation);
            }
        }

        let automation = slot.borrow();
        let automation = automation.as_ref()?;
        let element = unsafe { automation.GetFocusedElement().ok()? };
        let process_id = unsafe { element.CurrentProcessId().ok()? } as u32;
        if process_id == 0 || process_id != expected_process_id {
            return None;
        }

        let native_hwnd = unsafe { element.CurrentNativeWindowHandle().ok()? }.0 as isize;
        let is_password = unsafe { element.CurrentIsPassword().ok()? }.as_bool();
        Some(UiaSecurityProbe {
            process_id,
            native_hwnd,
            is_password,
        })
    })
}

fn responsive_focused_hwnd(expected_process_id: u32) -> Option<HWND> {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            return None;
        }

        let mut foreground_process_id = 0u32;
        let foreground_thread =
            GetWindowThreadProcessId(foreground, &mut foreground_process_id as *mut u32);
        if foreground_thread == 0 || foreground_process_id != expected_process_id {
            return None;
        }

        let mut info: GUITHREADINFO = zeroed();
        info.cbSize = size_of::<GUITHREADINFO>() as u32;
        let focused =
            if GetGUIThreadInfo(foreground_thread, &mut info) != 0 && !info.hwndFocus.is_null() {
                info.hwndFocus
            } else {
                foreground
            };

        let mut focused_process_id = 0u32;
        if GetWindowThreadProcessId(focused, &mut focused_process_id as *mut u32) == 0
            || focused_process_id != expected_process_id
        {
            return None;
        }

        let mut result = 0usize;
        let ok = SendMessageTimeoutW(
            focused,
            WM_NULL,
            0,
            0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            UIA_PREFLIGHT_TIMEOUT_MS,
            &mut result,
        );
        (ok != 0).then_some(focused)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn security_probe_contains_no_text_payload() {
        let probe = UiaSecurityProbe {
            process_id: 123,
            native_hwnd: 456,
            is_password: true,
        };
        assert_eq!(probe.process_id, 123);
        assert_eq!(probe.native_hwnd, 456);
        assert!(probe.is_password);
    }
}
