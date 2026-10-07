//! Word NativeOM adapter. COM interfaces never leave the one-operation STA.
//! A synchronous join deliberately has no mutation timeout: returning while a
//! Word call can still write would permit a second correction against unknown
//! state. Any uncertain mutation disables this adapter until process restart.

#[path = "word_native_plan.rs"]
mod plan;

use std::cell::RefCell;
use std::collections::HashMap;
use std::ffi::c_void;
use std::mem::{size_of, zeroed};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use windows::core::{IUnknown, Interface, BSTR, GUID, PCWSTR};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, IDispatch, CLSCTX_INPROC_SERVER,
    COINIT_APARTMENTTHREADED, DISPATCH_FLAGS, DISPATCH_METHOD, DISPATCH_PROPERTYGET,
    DISPATCH_PROPERTYPUT, DISPPARAMS,
};
use windows::Win32::System::Ole::{
    SafeArrayDestroy, SafeArrayGetDim, SafeArrayGetElement, SafeArrayGetLBound, SafeArrayGetUBound,
};
use windows::Win32::System::Variant::VARIANT;
use windows::Win32::UI::Accessibility::{
    AccessibleObjectFromWindow, CUIAutomation, IUIAutomation, IUIAutomationValuePattern,
    UIA_ValuePatternId,
};
use windows_sys::Win32::Foundation::{CloseHandle, HWND};
use windows_sys::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetAncestor, GetClassNameW, GetForegroundWindow, GetGUIThreadInfo,
    GetWindowThreadProcessId, PeekMessageW, SendMessageTimeoutW, TranslateMessage, GA_ROOT,
    GUITHREADINFO, MSG, PM_REMOVE, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_NULL,
};

const OBJID_NATIVEOM: u32 = 0xffff_fff0;
const LOCALE_USER_DEFAULT: u32 = 0x0400;
const DISPID_PROPERTYPUT: i32 = -3;
const VT_DISPATCH: u16 = 9;
static SERIAL: Mutex<()> = Mutex::new(());
static UNCERTAIN_MUTATION: AtomicBool = AtomicBool::new(false);
struct CachedDispatch {
    object: IDispatch,
    ids: HashMap<String, i32>,
}
thread_local! {
    // Retaining the exact dispatch object prevents address reuse while an ID
    // is cached. Clear on this STA before CoUninitialize, including unwinding.
    static DISPATCH_IDS: RefCell<Vec<CachedDispatch>> = const { RefCell::new(Vec::new()) };
}

#[derive(Debug)]
pub struct SelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}
#[derive(Debug)]
pub struct EditSnapshot {
    pub caret: u32,
    pub text_before_caret: String,
}

/// Cheap identity classification only; NativeOM availability is separate.
pub fn is_word_window(hwnd: HWND) -> bool {
    unsafe {
        let mut class = [0u16; 256];
        let length = GetClassNameW(hwnd, class.as_mut_ptr(), class.len() as i32);
        if length <= 0 || String::from_utf16_lossy(&class[..length as usize]) != "_WwG" {
            return false;
        }
        let mut pid = 0;
        if GetWindowThreadProcessId(hwnd, &mut pid) == 0 || pid == 0 {
            return false;
        }
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if process.is_null() {
            return false;
        }
        let mut path = [0u16; 32768];
        let mut size = path.len() as u32;
        let ok = QueryFullProcessImageNameW(process, 0, path.as_mut_ptr(), &mut size);
        CloseHandle(process);
        ok != 0 && plan::is_word_target("_WwG", &String::from_utf16_lossy(&path[..size as usize]))
    }
}

pub fn has_adapter(hwnd: HWND) -> bool {
    run(hwnd, |context| {
        let (_, document_start, document_end, document) = context.content()?;
        let (_, start, end) = context.selection()?;
        if !plan::available_selection(&document, document_start, document_end, start, end) {
            return None;
        }
        context.stable()?;
        Some(true)
    })
    .unwrap_or(false)
}

pub fn normalize_newlines(value: &str) -> String {
    plan::normalize_newlines(value)
}

fn run<R: Send + 'static>(
    hwnd: HWND,
    operation: impl FnOnce(&Context) -> Option<R> + Send + 'static,
) -> Option<R> {
    run_at_generation(hwnd, super::runtime_generation()?, operation)
}

fn run_at_generation<R: Send + 'static>(
    hwnd: HWND,
    generation: u32,
    operation: impl FnOnce(&Context) -> Option<R> + Send + 'static,
) -> Option<R> {
    if UNCERTAIN_MUTATION.load(Ordering::Acquire) || !is_word_window(hwnd) {
        return None;
    }
    let _serial = SERIAL.lock().ok()?;
    if UNCERTAIN_MUTATION.load(Ordering::Acquire) {
        return None;
    }
    let handle = hwnd as isize;
    // The thread owns every interface, VARIANT and BSTR. COM pumps incoming
    // apartment messages during outgoing calls; drain queued messages between
    // calls. There is no persistent STA blocked on a non-pumping receiver.
    std::thread::Builder::new()
        .name("g-switcher-word-sta".into())
        .spawn(move || {
            unsafe {
                CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok().ok()?;
            }
            struct Apartment;
            impl Drop for Apartment {
                fn drop(&mut self) {
                    unsafe {
                        CoUninitialize();
                    }
                }
            }
            let _apartment = Apartment;
            struct DispatchCache;
            impl Drop for DispatchCache {
                fn drop(&mut self) {
                    DISPATCH_IDS.with(|cache| cache.borrow_mut().clear());
                }
            }
            let _cache = DispatchCache;
            pump();
            let context = Context::open(handle as HWND, generation)?;
            let result = operation(&context);
            drop(context);
            pump();
            result
        })
        .ok()?
        .join()
        .ok()?
}

pub fn read_selected_text(hwnd: HWND) -> Option<SelectedText> {
    run(hwnd, |context| {
        let (content, document_start, document_end, text) = context.content()?;
        let (_, start, end) = context.selection()?;
        let (end, text) = plan::selection_text(&text, document_start, document_end, start, end)?;
        let range = duplicate_range(&content, start, end)?;
        if get_text(&range)? != text {
            return None;
        }
        context.stable()?;
        let (_, current_start, current_end) = context.selection()?;
        if current_start != start || (current_end != end && current_end != document_end) {
            return None;
        }
        Some(SelectedText { start, end, text })
    })
}

pub fn snapshot_caret(hwnd: HWND) -> Option<EditSnapshot> {
    run(hwnd, |context| {
        let (content, start, end, text) = context.content()?;
        let (_, caret, selected_end) = context.selection()?;
        if caret != selected_end || caret >= end {
            return None;
        }
        // Use native range endpoints, and prove their mapping to UTF16 before
        // exposing offsets through the existing selection interface.
        let _ = plan::selection_text(&text, start, end, 0, end)?;
        let prefix = duplicate_range(&content, 0, caret)?;
        let text_before_caret = get_text(&prefix)?;
        if text_before_caret.encode_utf16().count() != caret as usize {
            return None;
        }
        context.stable()?;
        let (_, current_start, current_end) = context.selection()?;
        if (current_start, current_end) != (caret, caret) {
            return None;
        }
        Some(EditSnapshot {
            caret,
            text_before_caret,
        })
    })
}

#[cfg(test)]
pub fn read_document_text(hwnd: HWND) -> Option<String> {
    run(hwnd, |context| {
        context.stable()?;
        Some(context.content()?.3)
    })
}

pub fn replace_range_if_matches(
    hwnd: HWND,
    start: u32,
    end: u32,
    expected: &str,
    replacement: &str,
    generation: u32,
) -> bool {
    let expected = plan::normalize_newlines(expected);
    let replacement = plan::normalize_newlines(replacement);
    run_at_generation(hwnd, generation, move |context| {
        context.replace(start, end, &expected, &replacement)
    })
    .unwrap_or(false)
}

#[derive(Clone, PartialEq, Eq)]
struct Focus {
    pid: u32,
    root: isize,
    runtime_id: Vec<i32>,
    native_hwnd: isize,
}

struct Context {
    hwnd: HWND,
    automation: IUIAutomation,
    focus: Focus,
    window: IDispatch,
    document: IDispatch,
    document_identity: IUnknown,
    generation: u32,
}

impl Context {
    fn open(hwnd: HWND, generation: u32) -> Option<Self> {
        let automation: IUIAutomation =
            unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()? };
        let focus = focused(&automation, hwnd)?;
        let window = native_window(hwnd)?;
        if get_i32(&window, "Hwnd")? as isize != focus.root {
            return None;
        }
        let selection = get_dispatch(&window, "Selection")?;
        let document = get_dispatch(&get_dispatch(&selection, "Range")?, "Document")?;
        let document_identity = document.cast::<IUnknown>().ok()?;
        let context = Self {
            hwnd,
            automation,
            focus,
            window,
            document,
            document_identity,
            generation,
        };
        context.stable()?;
        Some(context)
    }

    fn stable(&self) -> Option<()> {
        self.bound()?;
        let window = native_window(self.hwnd)?;
        if get_i32(&window, "Hwnd")? as isize != self.focus.root {
            return None;
        }
        // Initial scope refuses structural containers anywhere in the document.
        // This also refuses a range inside a field/control whose local Count
        // can be zero, without relying on ambiguous provider boundary queries.
        for collection in ["Fields", "Tables", "ContentControls", "Revisions"] {
            if get_i32(&get_dispatch(&self.document, collection)?, "Count")? != 0 {
                return None;
            }
        }
        if focused(&self.automation, self.hwnd)? != self.focus {
            return None;
        }
        Some(())
    }

    fn bound(&self) -> Option<(IDispatch, u32, u32)> {
        if super::runtime_generation() != Some(self.generation) {
            return None;
        }
        if focused(&self.automation, self.hwnd)? != self.focus {
            return None;
        }
        let selection = self.selection()?;
        if get_bool(&self.document, "ReadOnly")?
            || get_i32(&self.document, "ProtectionType")? != -1
            || get_bool(&self.document, "TrackRevisions")?
            || ![1, 2].contains(&get_i32(&selection.0, "Type")?)
        {
            return None;
        }
        if focused(&self.automation, self.hwnd)? != self.focus {
            return None;
        }
        if super::runtime_generation() != Some(self.generation) {
            return None;
        }
        Some(selection)
    }

    fn content(&self) -> Option<(IDispatch, u32, u32, String)> {
        let content = get_dispatch(&self.document, "Content")?;
        if get_i32(&content, "StoryType")? != 1 {
            return None;
        }
        let start = u32::try_from(get_i32(&content, "Start")?).ok()?;
        let end = u32::try_from(get_i32(&content, "End")?).ok()?;
        if end as usize > plan::MAX_DOCUMENT_UNITS {
            return None;
        }
        let text = get_text(&content)?;
        if start != 0 || text.encode_utf16().count() != end as usize {
            return None;
        }
        Some((content, start, end, text))
    }

    fn selection(&self) -> Option<(IDispatch, u32, u32)> {
        let selection = get_dispatch(&self.window, "Selection")?;
        let range = get_dispatch(&selection, "Range")?;
        if get_i32(&range, "StoryType")? != 1
            || get_dispatch(&range, "Document")?
                .cast::<IUnknown>()
                .ok()?
                .as_raw()
                != self.document_identity.as_raw()
        {
            return None;
        }
        let start = u32::try_from(get_i32(&range, "Start")?).ok()?;
        let end = u32::try_from(get_i32(&range, "End")?).ok()?;
        Some((selection, start, end))
    }

    fn replace(&self, start: u32, end: u32, expected: &str, replacement: &str) -> Option<bool> {
        self.mutation_allowed()?;
        self.stable()?;
        let (content, document_start, document_end, before) = self.content()?;
        let plan = plan::Plan::new(
            &before,
            document_start,
            document_end,
            start,
            end,
            expected,
            replacement,
        )?;
        let (start, end) = (plan.start, plan.end);
        let (_, selected_start, selected_end) = self.selection()?;
        if !plan::selection_matches(selected_start, selected_end, start, end, document_end) {
            return None;
        }
        let range = duplicate_range(&content, start, end)?;
        if get_text(&range)? != expected {
            return None;
        }
        let application = get_dispatch(&self.window, "Application")?;
        let undo = get_dispatch(&application, "UndoRecord")?;
        if get_bool(&undo, "IsRecordingCustomRecord")? {
            return None;
        }
        self.stable()?;
        if self.content()?.3 != before
            || self.selection()?.1 != selected_start
            || self.selection()?.2 != selected_end
        {
            return None;
        }
        self.mutation_allowed()?;

        // Set the latch before submitting a COM operation with side effects.
        // A failed HRESULT or panic cannot prove that Word made no change.
        UNCERTAIN_MUTATION.store(true, Ordering::Release);
        call(
            &undo,
            "StartCustomRecord",
            vec![VARIANT::from("G-switcher correction")],
        )?;
        let mut record = UndoRecord {
            dispatch: undo,
            active: true,
        };
        let result = (|| {
            let one = duplicate_range(&content, start, start.checked_add(1)?)?;
            for (offset, character) in plan.replacement.iter().enumerate() {
                self.mutation_allowed()?;
                let (_, current_start, current_end) = self.bound()?;
                if get_text(&range)? != plan.range_progress(offset) {
                    return None;
                }
                if (current_start, current_end) != (selected_start, selected_end) {
                    return None;
                }
                let position = start.checked_add(offset as u32)?;
                set_range(&one, position, position.checked_add(1)?)?;
                let previous = plan.original[offset].to_string();
                if get_text(&one)? != previous {
                    return None;
                }
                if previous == character.to_string() {
                    continue;
                }
                if focused(&self.automation, self.hwnd)? != self.focus {
                    return None;
                }
                self.mutation_allowed()?;
                // Independent one-character range; never writes Font, global
                // flags, Selection.Text, a full document, or the clipboard.
                put(&one, "Text", VARIANT::from(character.to_string().as_str()))?;
                if get_text(&one)? != character.to_string() {
                    return None;
                }
            }
            self.stable()?;
            if self.content()?.3 != plan.after || get_text(&range)? != replacement {
                return None;
            }
            let (selection, current_start, current_end) = self.selection()?;
            if (current_start, current_end) != (selected_start, selected_end) {
                return None;
            }
            self.mutation_allowed()?;
            call(
                &selection,
                "SetRange",
                vec![VARIANT::from(end as i32), VARIANT::from(end as i32)],
            )?;
            self.stable()?;
            let (_, caret_start, caret_end) = self.selection()?;
            if (caret_start, caret_end) != (end, end) || self.content()?.3 != plan.after {
                return None;
            }
            Some(())
        })();
        // End only our successfully started record, including partial failure.
        // Never blindly Undo an unknown outcome or retry another writer.
        let ended = record.end().is_some();
        if result.is_none() || !ended {
            return None;
        }
        self.mutation_allowed()?;
        self.stable()?;
        if self.content()?.3 != plan.after
            || self.selection()?.1 != end
            || self.selection()?.2 != end
        {
            return None;
        }
        UNCERTAIN_MUTATION.store(false, Ordering::Release);
        Some(true)
    }

    fn mutation_allowed(&self) -> Option<()> {
        if !super::runtime_allows_mutation(self.generation) {
            return None;
        }
        Some(())
    }
}

struct UndoRecord {
    dispatch: IDispatch,
    active: bool,
}
impl UndoRecord {
    fn end(&mut self) -> Option<()> {
        if !self.active {
            return Some(());
        }
        // Mark the attempt before provider I/O. On failure Drop must not repeat
        // a possibly completed effect; the global latch stays set.
        self.active = false;
        call(&self.dispatch, "EndCustomRecord", vec![]).map(|_| ())
    }
}
impl Drop for UndoRecord {
    fn drop(&mut self) {
        if self.active {
            let _ = self.end();
        }
    }
}

fn duplicate_range(content: &IDispatch, start: u32, end: u32) -> Option<IDispatch> {
    let range = get_dispatch(content, "Duplicate")?;
    set_range(&range, start, end)?;
    Some(range)
}
fn set_range(range: &IDispatch, start: u32, end: u32) -> Option<()> {
    call(
        range,
        "SetRange",
        vec![VARIANT::from(start as i32), VARIANT::from(end as i32)],
    )?;
    if get_i32(range, "Start")? != start as i32
        || get_i32(range, "End")? != end as i32
        || get_i32(range, "StoryType")? != 1
    {
        return None;
    }
    Some(())
}

fn native_window(hwnd: HWND) -> Option<IDispatch> {
    let mut raw = std::ptr::null_mut();
    unsafe {
        AccessibleObjectFromWindow(
            windows::Win32::Foundation::HWND(hwnd),
            OBJID_NATIVEOM,
            &IDispatch::IID,
            &mut raw,
        )
        .ok()?;
        if raw.is_null() {
            return None;
        }
        Some(IDispatch::from_raw(raw))
    }
}

fn invoke(
    object: &IDispatch,
    name: &str,
    flags: DISPATCH_FLAGS,
    mut args: Vec<VARIANT>,
) -> Option<VARIANT> {
    pump();
    let id = DISPATCH_IDS.with(|cache| {
        let mut cache = cache.borrow_mut();
        let index = match cache
            .iter()
            .position(|dispatch| dispatch.object.as_raw() == object.as_raw())
        {
            Some(index) => index,
            None => {
                cache.push(CachedDispatch {
                    object: object.clone(),
                    ids: HashMap::new(),
                });
                cache.len() - 1
            }
        };
        if let Some(id) = cache[index].ids.get(name) {
            return Some(*id);
        }
        let wide: Vec<u16> = name.encode_utf16().chain(std::iter::once(0)).collect();
        let name_pointer = PCWSTR(wide.as_ptr());
        let mut id = 0i32;
        unsafe {
            object
                .GetIDsOfNames(
                    &GUID::zeroed(),
                    &name_pointer,
                    1,
                    LOCALE_USER_DEFAULT,
                    &mut id,
                )
                .ok()?;
        }
        cache[index].ids.insert(name.to_owned(), id);
        Some(id)
    })?;
    let mut named = DISPID_PROPERTYPUT;
    args.reverse(); // COM DISPPARAMS arguments are in reverse order.
    let parameters = DISPPARAMS {
        rgvarg: args.as_mut_ptr(),
        cArgs: args.len() as u32,
        rgdispidNamedArgs: if flags == DISPATCH_PROPERTYPUT {
            &mut named
        } else {
            std::ptr::null_mut()
        },
        cNamedArgs: u32::from(flags == DISPATCH_PROPERTYPUT),
    };
    let mut result = VARIANT::default();
    unsafe {
        // No EXCEPINFO allocation or diagnostic text is retained/logged.
        object
            .Invoke(
                id,
                &GUID::zeroed(),
                LOCALE_USER_DEFAULT,
                flags,
                &parameters,
                Some(&mut result),
                None,
                None,
            )
            .ok()?;
    }
    Some(result)
}
fn get(object: &IDispatch, name: &str) -> Option<VARIANT> {
    invoke(object, name, DISPATCH_PROPERTYGET, vec![])
}
fn call(object: &IDispatch, name: &str, args: Vec<VARIANT>) -> Option<VARIANT> {
    invoke(object, name, DISPATCH_METHOD, args)
}
fn put(object: &IDispatch, name: &str, value: VARIANT) -> Option<()> {
    invoke(object, name, DISPATCH_PROPERTYPUT, vec![value]).map(|_| ())
}
fn get_i32(object: &IDispatch, name: &str) -> Option<i32> {
    let value = get(object, name)?;
    if value.vt().0 != 3 {
        return None;
    }
    i32::try_from(&value).ok()
}
fn get_bool(object: &IDispatch, name: &str) -> Option<bool> {
    let value = get(object, name)?;
    if value.vt().0 != 11 {
        return None;
    }
    bool::try_from(&value).ok()
}
fn get_text(object: &IDispatch) -> Option<String> {
    let value = get(object, "Text")?;
    if value.vt().0 != 8 {
        return None;
    }
    let text = BSTR::try_from(&value).ok()?;
    if text.len() > plan::MAX_DOCUMENT_UNITS {
        return None;
    }
    String::from_utf16(&text).ok()
}
fn get_dispatch(object: &IDispatch, name: &str) -> Option<IDispatch> {
    let variant = get(object, name)?;
    unsafe {
        if variant.vt().0 != VT_DISPATCH {
            return None;
        }
        variant
            .Anonymous
            .Anonymous
            .Anonymous
            .pdispVal
            .as_ref()
            .cloned()
    }
}

fn focused(automation: &IUIAutomation, hwnd: HWND) -> Option<Focus> {
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
        let element = automation.GetFocusedElement().ok()?;
        if element.CurrentProcessId().ok()? as u32 != pid
            || element.CurrentIsPassword().ok()?.as_bool()
            || !element.CurrentIsEnabled().ok()?.as_bool()
            || !element.CurrentIsKeyboardFocusable().ok()?.as_bool()
        {
            return None;
        }
        if let Ok(pattern) = element.GetCurrentPattern(UIA_ValuePatternId) {
            let value = pattern.cast::<IUIAutomationValuePattern>().ok()?;
            if value.CurrentIsReadOnly().ok()?.as_bool() {
                return None;
            }
        }
        let native_hwnd = element.CurrentNativeWindowHandle().ok()?.0 as isize;
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

fn pump() {
    unsafe {
        let mut message: MSG = zeroed();
        while PeekMessageW(&mut message, std::ptr::null_mut(), 0, 0, PM_REMOVE) != 0 {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}
