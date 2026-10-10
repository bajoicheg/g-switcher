use std::cell::RefCell;
use std::sync::OnceLock;
use std::time::Duration;

use super::selection::read_worker;
type SecurityQuery = (u32, isize, Option<super::selection::uia_scope::Target>);
type SecurityReader = read_worker::BoundedReader<SecurityQuery, Option<UiaSecurityProbe>>;
static READER: OnceLock<Option<SecurityReader>> = OnceLock::new();
use std::ffi::c_void;
use std::mem::{size_of, zeroed};

use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::System::Ole::{
    SafeArrayDestroy, SafeArrayGetDim, SafeArrayGetElement, SafeArrayGetLBound, SafeArrayGetUBound,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationElement, TreeScope_Descendants,
    UIA_HasKeyboardFocusPropertyId,
};
use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, GetGUIThreadInfo, GetWindowThreadProcessId, SendMessageTimeoutW,
    GUITHREADINFO, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_NULL,
};

const UIA_PREFLIGHT_TIMEOUT_MS: u32 = 75;
const MAX_RUNTIME_ID_PARTS: usize = 16;

/// Opaque UI Automation element identity. Runtime IDs are copied only so focus
/// changes inside a single host HWND (for example Chromium DOM fields) can be
/// distinguished without retaining a COM element or any text-bearing property.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct UiaElementId {
    len: u8,
    parts: [i32; MAX_RUNTIME_ID_PARTS],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UiaSecurityProbe {
    pub process_id: u32,
    pub native_hwnd: isize,
    pub element_id: UiaElementId,
    pub is_password: bool,
}

thread_local! {
    // COM/UI Automation objects remain on the windowless MTA reader thread. We never
    // retain an element object, its Name/Value/TextPattern, or user input.
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
}

/// Queries only metadata needed to decide whether the currently focused UIA
/// element is protected. No text-bearing UI Automation property or pattern is
/// requested. The opaque RuntimeId is copied for identity comparison only.
/// Failure is returned as None so the caller can fail open (leave user input
/// unchanged) for unsupported, hung, disappearing, or unidentifiable controls.
#[cfg(test)]
pub fn probe_focused(expected_process_id: u32) -> Option<UiaSecurityProbe> {
    probe_target(
        expected_process_id,
        focused_hwnd_identity(expected_process_id)?,
    )
}
pub fn probe_target(expected_process_id: u32, hwnd: HWND) -> Option<UiaSecurityProbe> {
    if focused_hwnd_identity(expected_process_id)? != hwnd {
        return None;
    }
    let is_word = super::selection::word_admission::classify_word(hwnd as isize)?;
    let identity = if is_word {
        None
    } else {
        Some(super::selection::uia_scope::Target::capture(
            hwnd,
            expected_process_id,
        )?)
    };
    let query = (expected_process_id, hwnd as isize, identity);
    let reader = READER
        .get_or_init(|| read_worker::BoundedReader::start(probe_focused_on_mta).ok())
        .as_ref()?;
    if is_word {
        if !super::selection::broker_role() {
            return None;
        }
        let inherited = super::selection::word_admission::current();
        let parent = match inherited.as_ref() {
            Some(p) => p.clone(),
            None => super::selection::word_admission::begin(hwnd as isize)?,
        };
        let result = reader.request_guarded(query, Duration::from_millis(750), &parent);
        if inherited.is_none() && !parent.complete(false) {
            return None;
        }
        result?
    } else {
        reader.request(query, Duration::from_millis(750))?
    }
}

fn probe_focused_on_mta(
    (expected_process_id, expected_hwnd, identity): SecurityQuery,
) -> Option<UiaSecurityProbe> {
    // Avoid entering a potentially blocking UIA provider when the Win32 focus
    // thread is already unresponsive. This does not read any user text.
    if identity.as_ref().is_some_and(|target| !target.valid()) {
        return None;
    }
    let _responsive_hwnd = responsive_focused_hwnd(expected_process_id, expected_hwnd)?;

    if super::selection::word_admission::classify_word(_responsive_hwnd as isize)? {
        return probe_word_on_mta(expected_process_id, expected_hwnd);
    }

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
        probe_using(
            automation,
            expected_process_id,
            expected_hwnd,
            identity.as_ref(),
        )
    })
}

// Non-Word requests retain their captured process identity; Word requests also
// revalidate live broker authority before EACH new provider entry.
fn security_stage<R>(hwnd: isize, provider: impl FnOnce() -> R) -> Option<R> {
    if super::selection::word_admission::classify_word(hwnd)? {
        super::selection::word_security_stage(hwnd, provider)
    } else {
        Some(provider())
    }
}
fn probe_word_on_mta(expected_process_id: u32, expected_hwnd: isize) -> Option<UiaSecurityProbe> {
    unsafe {
        CoInitializeEx(None, COINIT_MULTITHREADED).ok().ok()?;
    }
    struct Apartment;
    impl Drop for Apartment {
        fn drop(&mut self) {
            unsafe {
                windows::Win32::System::Com::CoUninitialize();
            }
        }
    }
    let _apartment = Apartment;
    let automation: IUIAutomation = security_stage(expected_hwnd, || unsafe {
        CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()
    })??;
    probe_using(&automation, expected_process_id, expected_hwnd, None)
}
fn probe_using(
    automation: &IUIAutomation,
    expected_process_id: u32,
    expected_hwnd: isize,
    identity: Option<&super::selection::uia_scope::Target>,
) -> Option<UiaSecurityProbe> {
    if identity.is_some_and(|target| !target.valid()) {
        return None;
    }
    let live_hwnd = responsive_focused_hwnd(expected_process_id, expected_hwnd)?;
    if super::selection::word_admission::classify_word(live_hwnd as isize)?
        && !super::selection::word_admission::current()
            .is_some_and(|p| p.matches(live_hwnd as isize))
    {
        return None;
    }
    // Target HWND only: no global focused-element fallback can choose Word
    // after an ordinary Chrome request's precheck. Virtual descendants must
    // prove keyboard focus within this captured process-bound subtree.
    let root = security_stage(expected_hwnd, || unsafe {
        automation
            .ElementFromHandle(windows::Win32::Foundation::HWND(live_hwnd))
            .ok()
    })??;
    if security_stage(expected_hwnd, || unsafe { root.CurrentProcessId().ok() })?? as u32
        != expected_process_id
    {
        return None;
    }
    // A focused native root may also contain a focused virtual field. The
    // password/runtime identity must describe that field, never its host.
    let condition = security_stage(expected_hwnd, || unsafe {
        automation
            .CreatePropertyCondition(
                UIA_HasKeyboardFocusPropertyId,
                &windows::Win32::System::Variant::VARIANT::from(true),
            )
            .ok()
    })??;
    if identity.is_some_and(|target| !target.valid()) {
        return None;
    }
    let focused = security_stage(expected_hwnd, || unsafe {
        root.FindAll(TreeScope_Descendants, &condition).ok()
    })??;
    if identity.is_some_and(|target| !target.valid()) {
        return None;
    }
    let count = security_stage(expected_hwnd, || unsafe { focused.Length().ok() })??;
    if identity.is_some_and(|target| !target.valid()) {
        return None;
    }
    let element = match count {
        1 => security_stage(expected_hwnd, || unsafe { focused.GetElement(0).ok() })??,
        0 if security_stage(expected_hwnd, || unsafe {
            root.CurrentHasKeyboardFocus().ok()
        })??
        .as_bool() =>
        {
            root
        }
        _ => return None,
    };
    let process_id =
        security_stage(expected_hwnd, || unsafe { element.CurrentProcessId().ok() })?? as u32;
    if process_id == 0 || process_id != expected_process_id {
        return None;
    }

    // RuntimeId is opaque metadata specifically intended for comparing UIA
    // element identity. Copy it before any password decision; do not query
    // Name, Value, TextPattern or another text-bearing property here.
    let element_id = runtime_id(&element, expected_hwnd)?;
    let native_hwnd = security_stage(expected_hwnd, || unsafe {
        element.CurrentNativeWindowHandle().ok()
    })??
    .0 as isize;
    let is_password = security_stage(expected_hwnd, || unsafe {
        element.CurrentIsPassword().ok()
    })??
    .as_bool();
    if identity.is_some_and(|target| !target.valid()) {
        return None;
    }
    if focused_hwnd_identity(expected_process_id)? as isize != expected_hwnd
        || !security_stage(expected_hwnd, || unsafe {
            element.CurrentHasKeyboardFocus().ok()
        })??
        .as_bool()
    {
        return None;
    }
    Some(UiaSecurityProbe {
        process_id,
        native_hwnd,
        element_id,
        is_password,
    })
}

fn runtime_id(element: &IUIAutomationElement, expected_hwnd: isize) -> Option<UiaElementId> {
    let array = security_stage(expected_hwnd, || unsafe { element.GetRuntimeId().ok() })??;
    if array.is_null() {
        return None;
    }

    let result = (|| {
        if unsafe { SafeArrayGetDim(array) } != 1 {
            return None;
        }
        let lower = unsafe { SafeArrayGetLBound(array, 1).ok()? };
        let upper = unsafe { SafeArrayGetUBound(array, 1).ok()? };
        if upper < lower {
            return None;
        }
        let count = usize::try_from(i64::from(upper) - i64::from(lower) + 1).ok()?;
        if count == 0 || count > MAX_RUNTIME_ID_PARTS {
            return None;
        }

        let mut id = UiaElementId {
            len: count as u8,
            ..Default::default()
        };
        for (slot, index) in (lower..=upper).enumerate() {
            let mut value = 0i32;
            unsafe {
                SafeArrayGetElement(
                    array,
                    &index as *const i32,
                    &mut value as *mut i32 as *mut c_void,
                )
                .ok()?;
            }
            id.parts[slot] = value;
        }
        Some(id)
    })();

    // GetRuntimeId transfers ownership of the SAFEARRAY to the caller.
    let _ = unsafe { SafeArrayDestroy(array) };
    result
}

fn focused_hwnd_identity(expected_process_id: u32) -> Option<HWND> {
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

        Some(focused)
    }
}
fn responsive_focused_hwnd(expected_process_id: u32, expected_hwnd: isize) -> Option<HWND> {
    let focused = focused_hwnd_identity(expected_process_id)?;
    if focused as isize != expected_hwnd {
        return None;
    }
    if super::selection::word_admission::classify_word(focused as isize)?
        && !super::selection::word_admission::current().is_some_and(|p| p.matches(focused as isize))
    {
        return None;
    }
    let mut result = 0usize;
    let ok = security_stage(expected_hwnd, || unsafe {
        SendMessageTimeoutW(
            focused,
            WM_NULL,
            0,
            0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            UIA_PREFLIGHT_TIMEOUT_MS,
            &mut result,
        )
    })?;
    if ok == 0 && super::selection::word_admission::classify_word(focused as isize)? {
        if let Some(p) = super::selection::word_admission::current() {
            p.quarantine();
        }
    }
    (ok != 0).then_some(focused)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn security_probe_contains_identity_but_no_text_payload() {
        let mut element_id = UiaElementId {
            len: 2,
            ..Default::default()
        };
        element_id.parts[0] = 42;
        element_id.parts[1] = 7;
        let probe = UiaSecurityProbe {
            process_id: 123,
            native_hwnd: 456,
            element_id,
            is_password: true,
        };
        assert_eq!(probe.process_id, 123);
        assert_eq!(probe.native_hwnd, 456);
        assert_eq!(probe.element_id, element_id);
        assert!(probe.is_password);
    }
}
