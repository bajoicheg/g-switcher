use std::cell::RefCell;

use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::UI::Accessibility::{CUIAutomation, IUIAutomation};

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
/// user input unchanged) for unsupported controls.
pub fn probe_focused(expected_process_id: u32) -> Option<UiaSecurityProbe> {
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
