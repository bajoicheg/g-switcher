//! Fresh security observations live exclusively on one windowless MTA.
//! A stalled reader is quarantined; it never performs text mutations.
use super::super::read_worker;
use super::is_word_window;
use std::cell::RefCell;
use std::ffi::c_void;
use std::mem::{size_of, zeroed};
use std::sync::OnceLock;
use std::time::Duration;
use windows::core::Interface;
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::System::Ole::{
    SafeArrayDestroy, SafeArrayGetDim, SafeArrayGetElement, SafeArrayGetLBound, SafeArrayGetUBound,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationCacheRequest, IUIAutomationValuePattern,
    TreeScope_Element, UIA_IsEnabledPropertyId, UIA_IsKeyboardFocusablePropertyId,
    UIA_IsPasswordPropertyId, UIA_NativeWindowHandlePropertyId, UIA_ProcessIdPropertyId,
    UIA_ValueIsReadOnlyPropertyId, UIA_ValuePatternId,
};
use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetAncestor, GetForegroundWindow, GetGUIThreadInfo, GetWindowThreadProcessId,
    SendMessageTimeoutW, GA_ROOT, GUITHREADINFO, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_NULL,
};
static READER: OnceLock<Option<read_worker::BoundedReader<isize, Option<Focus>>>> = OnceLock::new();
thread_local! {
    // Only interface/request configuration is reused. Every probe builds fresh
    // metadata and compares the live runtime identity; no positive-state cache.
    static AUTOMATION: RefCell<Option<(IUIAutomation, IUIAutomationCacheRequest)>> = const { RefCell::new(None) };
}

pub(super) fn focused(hwnd: HWND) -> Option<Focus> {
    READER
        .get_or_init(|| read_worker::BoundedReader::start(probe_on_mta).ok())
        .as_ref()?
        .request(hwnd as isize, Duration::from_millis(750))?
}

fn probe_on_mta(handle: isize) -> Option<Focus> {
    AUTOMATION.with(|slot| {
        if slot.borrow().is_none() {
            unsafe {
                CoInitializeEx(None, COINIT_MULTITHREADED).ok().ok()?;
            }
            let automation: IUIAutomation =
                unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()? };
            let cache = focus_cache_request(&automation)?;
            *slot.borrow_mut() = Some((automation, cache));
        }
        let slot = slot.borrow();
        let (automation, cache) = slot.as_ref()?;
        probe(automation, cache, handle as HWND)
    })
}

#[derive(Clone, PartialEq, Eq)]
pub(super) struct Focus {
    pid: u32,
    pub(super) root: isize,
    runtime_id: Vec<i32>,
    native_hwnd: isize,
}

fn focus_cache_request(automation: &IUIAutomation) -> Option<IUIAutomationCacheRequest> {
    unsafe {
        let request = automation.CreateCacheRequest().ok()?;
        request.SetTreeScope(TreeScope_Element).ok()?;
        for property in [
            UIA_ProcessIdPropertyId,
            UIA_IsPasswordPropertyId,
            UIA_IsEnabledPropertyId,
            UIA_IsKeyboardFocusablePropertyId,
            UIA_NativeWindowHandlePropertyId,
            UIA_ValueIsReadOnlyPropertyId,
        ] {
            request.AddProperty(property).ok()?;
        }
        request.AddPattern(UIA_ValuePatternId).ok()?;
        Some(request)
    }
}

fn probe(
    automation: &IUIAutomation,
    cache: &IUIAutomationCacheRequest,
    hwnd: HWND,
) -> Option<Focus> {
    if !is_word_window(hwnd) {
        return None;
    }
    unsafe {
        let mut pid = 0;
        let thread = GetWindowThreadProcessId(hwnd, &mut pid);
        let foreground = GetForegroundWindow();
        let root = GetAncestor(hwnd, GA_ROOT);
        if thread == 0 || root.is_null() || GetAncestor(foreground, GA_ROOT) != root {
            return None;
        }
        let mut info: GUITHREADINFO = zeroed();
        info.cbSize = size_of::<GUITHREADINFO>() as u32;
        if GetGUIThreadInfo(thread, &mut info) == 0 || info.hwndFocus != hwnd {
            return None;
        }
        let mut result = 0usize;
        if SendMessageTimeoutW(
            hwnd,
            WM_NULL,
            0,
            0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            75,
            &mut result,
        ) == 0
        {
            return None;
        }
        // Build a NEW metadata snapshot on every check. Reuse only the request,
        // never a cached positive result across checks, characters or events.
        let element = automation.GetFocusedElementBuildCache(cache).ok()?;
        if element.CachedProcessId().ok()? as u32 != pid
            || element.CachedIsPassword().ok()?.as_bool()
            || !element.CachedIsEnabled().ok()?.as_bool()
            || !element.CachedIsKeyboardFocusable().ok()?.as_bool()
        {
            return None;
        }
        if let Ok(pattern) = element.GetCachedPattern(UIA_ValuePatternId) {
            let value = pattern.cast::<IUIAutomationValuePattern>().ok()?;
            if value.CachedIsReadOnly().ok()?.as_bool() {
                return None;
            }
        }
        let native_hwnd = element.CachedNativeWindowHandle().ok()?.0 as isize;
        if native_hwnd != 0 && native_hwnd != hwnd as isize && native_hwnd != root as isize {
            return None;
        }
        let array = element.GetRuntimeId().ok()?;
        if array.is_null() {
            return None;
        }
        let runtime_id = (|| {
            if SafeArrayGetDim(array) != 1 {
                return None;
            }
            let lower = SafeArrayGetLBound(array, 1).ok()?;
            let upper = SafeArrayGetUBound(array, 1).ok()?;
            if upper < lower || i64::from(upper) - i64::from(lower) >= 16 {
                return None;
            }
            let mut values = Vec::new();
            for index in lower..=upper {
                let mut value = 0i32;
                SafeArrayGetElement(array, &index, &mut value as *mut i32 as *mut c_void).ok()?;
                values.push(value);
            }
            Some(values)
        })();
        let _ = SafeArrayDestroy(array);
        Some(Focus {
            pid,
            root: root as isize,
            runtime_id: runtime_id?,
            native_hwnd,
        })
    }
}
