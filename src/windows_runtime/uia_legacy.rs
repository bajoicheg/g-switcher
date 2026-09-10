use std::cell::RefCell;
use std::ffi::c_void;
use std::thread;
use std::time::{Duration, Instant};

use windows::core::{Interface, BSTR};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::System::Ole::{
    SafeArrayDestroy, SafeArrayGetDim, SafeArrayGetElement, SafeArrayGetLBound, SafeArrayGetUBound,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationLegacyIAccessiblePattern, IUIAutomationTextPattern,
    IUIAutomationTextRange, IUIAutomationValuePattern, TextPatternRangeEndpoint,
    TextPatternRangeEndpoint_End, TextPatternRangeEndpoint_Start, TextUnit_Character,
    UIA_LegacyIAccessiblePatternId, UIA_TextPatternId, UIA_ValuePatternId,
};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetWindowThreadProcessId, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_NULL,
};

const CONTROL_TIMEOUT_MS: u32 = 75;
const MAX_UIA_TEXT_CHARS: usize = 1_048_576;
const MAX_RUNTIME_ID_PARTS: usize = 16;
const POST_MUTATION_VERIFY_TIMEOUT: Duration = Duration::from_millis(300);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacySelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacyCaretSnapshot {
    pub caret: u32,
    pub text_before_caret: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
struct RuntimeId {
    len: u8,
    parts: [i32; MAX_RUNTIME_ID_PARTS],
}

struct LegacyContext {
    runtime_id: RuntimeId,
    text: IUIAutomationTextPattern,
    legacy: IUIAutomationLegacyIAccessiblePattern,
}

thread_local! {
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
}

/// Returns true only when the focused non-password element exposes TextPattern
/// plus LegacyIAccessible on the same RuntimeId. If a ValuePattern is present
/// and explicitly reports read-only, LegacyIAccessible is not allowed to bypass
/// that restriction.
pub fn has_adapter(hwnd: HWND) -> bool {
    let Some(context) = focused_context(hwnd) else {
        return false;
    };
    let Some(document) = (unsafe { context.text.DocumentRange().ok() }) else {
        return false;
    };
    text_of(&document).is_some() && current_selection_range(&context.text).is_some()
}

pub fn read_selected_text(hwnd: HWND) -> Option<LegacySelectedText> {
    let context = focused_context(hwnd)?;
    let document = unsafe { context.text.DocumentRange().ok()? };
    let selection = current_selection_range(&context.text)?;
    let selected = text_of(&selection)?;
    if selected.is_empty() {
        return None;
    }
    let prefix_start = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_Start)?;
    let prefix_end = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_End)?;
    let start = char_count_u32(&prefix_start)?;
    let end = char_count_u32(&prefix_end)?;
    (end > start).then_some(LegacySelectedText {
        start,
        end,
        text: selected,
    })
}

pub fn snapshot_caret(hwnd: HWND) -> Option<LegacyCaretSnapshot> {
    let context = focused_context(hwnd)?;
    snapshot_caret_from_pattern(&context.text)
}

#[cfg(test)]
pub fn read_document_text(hwnd: HWND) -> Option<String> {
    let context = focused_context(hwnd)?;
    let document = unsafe { context.text.DocumentRange().ok()? };
    text_of(&document)
}

/// Documented accessibility fallback for Chromium/WebView2/Electron compose
/// surfaces that expose exact TextPattern state but reject or omit ValuePattern
/// mutation. The whole value is changed through LegacyIAccessible::SetValue;
/// exact TextPattern content, RuntimeId and caret are verified afterwards.
/// Rollback is attempted only when the same element still contains the exact
/// planned value. No clipboard access or synthetic typing is used.
pub fn replace_range_if_matches(
    hwnd: HWND,
    start: u32,
    end: u32,
    expected: &str,
    replacement: &str,
) -> bool {
    if end < start {
        return false;
    }

    let Some(context) = focused_context(hwnd) else {
        trace("no legacy context");
        return false;
    };
    let Some(document) = (unsafe { context.text.DocumentRange().ok() }) else {
        trace("no document range");
        return false;
    };
    let Some(before) = text_of(&document) else {
        trace("cannot read pre-mutation document");
        return false;
    };
    let Some(original_selection) = selection_offsets(&context.text, &document) else {
        trace("cannot resolve pre-mutation selection");
        return false;
    };
    let Some(start_index) = byte_index_for_char(&before, start as usize) else {
        return false;
    };
    let Some(end_index) = byte_index_for_char(&before, end as usize) else {
        return false;
    };
    if end_index < start_index || before.get(start_index..end_index) != Some(expected) {
        trace("exact source range mismatch");
        return false;
    }

    let mut planned = String::with_capacity(
        before
            .len()
            .saturating_sub(expected.len())
            .saturating_add(replacement.len()),
    );
    planned.push_str(&before[..start_index]);
    planned.push_str(replacement);
    planned.push_str(&before[end_index..]);

    let Some(target_range) = range_for_char_offsets(&document, start, end) else {
        return false;
    };
    if unsafe { target_range.Select().is_err() }
        || current_selected_text(&context.text).as_deref() != Some(expected)
        || unsafe { context.text.DocumentRange().ok() }
            .and_then(|range| text_of(&range))
            .as_deref()
            != Some(before.as_str())
    {
        let _ = select_offsets(&context.text, original_selection.0, original_selection.1);
        trace("pre-mutation revalidation failed");
        return false;
    }

    let original_id = context.runtime_id;
    let planned_bstr = BSTR::from(planned.as_str());
    let set_result = unsafe { context.legacy.SetValue(&planned_bstr) };
    if let Err(error) = &set_result {
        trace(&format!("LegacyIAccessible SetValue returned {error}"));
    }
    drop(context);

    let replacement_end =
        start.saturating_add(replacement.chars().count().min(u32::MAX as usize) as u32);
    if verify_exact_post_state(hwnd, original_id, &planned, replacement_end) {
        trace("LegacyIAccessible mutation verified");
        return true;
    }

    rollback_if_exact(
        hwnd,
        original_id,
        &planned,
        &before,
        original_selection,
    );
    false
}

fn verify_exact_post_state(
    hwnd: HWND,
    expected_id: RuntimeId,
    planned: &str,
    caret: u32,
) -> bool {
    let deadline = Instant::now() + POST_MUTATION_VERIFY_TIMEOUT;
    loop {
        let Some(context) = focused_context(hwnd) else {
            trace("lost focused legacy context after mutation");
            return false;
        };
        if context.runtime_id != expected_id {
            trace("RuntimeId changed after mutation");
            return false;
        }
        let current = unsafe { context.text.DocumentRange().ok() }.and_then(|range| text_of(&range));
        if current.as_deref() == Some(planned) {
            if select_offsets(&context.text, caret, caret) {
                drop(context);
                if let Some(final_context) = focused_context(hwnd) {
                    if final_context.runtime_id == expected_id
                        && unsafe { final_context.text.DocumentRange().ok() }
                            .and_then(|range| text_of(&range))
                            .as_deref()
                            == Some(planned)
                        && snapshot_caret_from_pattern(&final_context.text)
                            .is_some_and(|snapshot| snapshot.caret == caret)
                    {
                        return true;
                    }
                }
            }
            trace("text changed but final caret verification failed");
            return false;
        }
        if Instant::now() >= deadline {
            trace("timed out waiting for LegacyIAccessible post-state");
            return false;
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn rollback_if_exact(
    hwnd: HWND,
    expected_id: RuntimeId,
    planned: &str,
    original: &str,
    original_selection: (u32, u32),
) {
    let Some(context) = focused_context(hwnd) else {
        return;
    };
    if context.runtime_id != expected_id
        || unsafe { context.text.DocumentRange().ok() }
            .and_then(|range| text_of(&range))
            .as_deref()
            != Some(planned)
    {
        return;
    }

    let original_bstr = BSTR::from(original);
    if unsafe { context.legacy.SetValue(&original_bstr).is_err() } {
        trace("LegacyIAccessible rollback SetValue failed");
        return;
    }
    drop(context);

    let deadline = Instant::now() + POST_MUTATION_VERIFY_TIMEOUT;
    loop {
        let Some(restored) = focused_context(hwnd) else {
            return;
        };
        if restored.runtime_id != expected_id {
            return;
        }
        if unsafe { restored.text.DocumentRange().ok() }
            .and_then(|range| text_of(&range))
            .as_deref()
            == Some(original)
        {
            let _ = select_offsets(&restored.text, original_selection.0, original_selection.1);
            trace("LegacyIAccessible rollback verified");
            return;
        }
        if Instant::now() >= deadline {
            trace("LegacyIAccessible rollback verification timed out");
            return;
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn focused_context(hwnd: HWND) -> Option<LegacyContext> {
    let mut expected_process_id = 0u32;
    let thread_id = unsafe { GetWindowThreadProcessId(hwnd, &mut expected_process_id) };
    if thread_id == 0 || expected_process_id == 0 {
        return None;
    }
    send_timeout(hwnd, WM_NULL, 0, 0)?;

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
        if process_id != expected_process_id
            || unsafe { element.CurrentIsPassword().ok()? }.as_bool()
            || !unsafe { element.CurrentIsEnabled().ok()? }.as_bool()
            || !unsafe { element.CurrentIsKeyboardFocusable().ok()? }.as_bool()
        {
            return None;
        }

        let native_hwnd = unsafe { element.CurrentNativeWindowHandle().ok()? }.0 as HWND;
        if !native_hwnd.is_null() && native_hwnd != hwnd {
            let mut native_process_id = 0u32;
            if unsafe { GetWindowThreadProcessId(native_hwnd, &mut native_process_id) } == 0
                || native_process_id != expected_process_id
            {
                return None;
            }
        }

        // If the element also exposes ValuePattern, an explicit read-only state
        // wins. LegacyIAccessible must never be used to bypass that declaration.
        if let Ok(value_unknown) = unsafe { element.GetCurrentPattern(UIA_ValuePatternId) } {
            let value: IUIAutomationValuePattern = value_unknown.cast().ok()?;
            if unsafe { value.CurrentIsReadOnly().ok()? }.as_bool() {
                return None;
            }
        }

        let runtime_id = runtime_id(&element)?;
        let text_unknown = unsafe { element.GetCurrentPattern(UIA_TextPatternId).ok()? };
        let text: IUIAutomationTextPattern = text_unknown.cast().ok()?;
        let legacy_unknown = unsafe {
            element
                .GetCurrentPattern(UIA_LegacyIAccessiblePatternId)
                .ok()?
        };
        let legacy: IUIAutomationLegacyIAccessiblePattern = legacy_unknown.cast().ok()?;
        Some(LegacyContext {
            runtime_id,
            text,
            legacy,
        })
    })
}

fn runtime_id(
    element: &windows::Win32::UI::Accessibility::IUIAutomationElement,
) -> Option<RuntimeId> {
    let array = unsafe { element.GetRuntimeId().ok()? };
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

        let mut id = RuntimeId::default();
        id.len = count as u8;
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
    let _ = unsafe { SafeArrayDestroy(array) };
    result
}

fn current_selection_range(pattern: &IUIAutomationTextPattern) -> Option<IUIAutomationTextRange> {
    let ranges = unsafe { pattern.GetSelection().ok()? };
    let length = unsafe { ranges.Length().ok()? };
    if length != 1 {
        return None;
    }
    unsafe { ranges.GetElement(0).ok() }
}

fn current_selected_text(pattern: &IUIAutomationTextPattern) -> Option<String> {
    text_of(&current_selection_range(pattern)?)
}

fn selection_offsets(
    pattern: &IUIAutomationTextPattern,
    document: &IUIAutomationTextRange,
) -> Option<(u32, u32)> {
    let selection = current_selection_range(pattern)?;
    let prefix_start = prefix_to_endpoint(document, &selection, TextPatternRangeEndpoint_Start)?;
    let prefix_end = prefix_to_endpoint(document, &selection, TextPatternRangeEndpoint_End)?;
    Some((char_count_u32(&prefix_start)?, char_count_u32(&prefix_end)?))
}

fn snapshot_caret_from_pattern(pattern: &IUIAutomationTextPattern) -> Option<LegacyCaretSnapshot> {
    let selection = current_selection_range(pattern)?;
    if !text_of(&selection)?.is_empty() {
        return None;
    }
    let document = unsafe { pattern.DocumentRange().ok()? };
    let prefix = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_Start)?;
    Some(LegacyCaretSnapshot {
        caret: char_count_u32(&prefix)?,
        text_before_caret: prefix,
    })
}

fn select_offsets(pattern: &IUIAutomationTextPattern, start: u32, end: u32) -> bool {
    let Some(document) = (unsafe { pattern.DocumentRange().ok() }) else {
        return false;
    };
    let Some(range) = range_for_char_offsets(&document, start, end) else {
        return false;
    };
    unsafe { range.Select().is_ok() }
}

fn prefix_to_endpoint(
    document: &IUIAutomationTextRange,
    selection: &IUIAutomationTextRange,
    endpoint: TextPatternRangeEndpoint,
) -> Option<String> {
    let prefix = unsafe { document.Clone().ok()? };
    unsafe {
        prefix
            .MoveEndpointByRange(TextPatternRangeEndpoint_End, selection, endpoint)
            .ok()?;
    }
    text_of(&prefix)
}

fn range_for_char_offsets(
    document: &IUIAutomationTextRange,
    start: u32,
    end: u32,
) -> Option<IUIAutomationTextRange> {
    if end < start || start > i32::MAX as u32 || end > i32::MAX as u32 {
        return None;
    }
    let range = unsafe { document.Clone().ok()? };
    let moved_start = unsafe {
        range
            .MoveEndpointByUnit(
                TextPatternRangeEndpoint_Start,
                TextUnit_Character,
                start as i32,
            )
            .ok()?
    };
    if moved_start != start as i32 {
        return None;
    }

    let anchor = unsafe { range.Clone().ok()? };
    unsafe {
        range
            .MoveEndpointByRange(
                TextPatternRangeEndpoint_End,
                &anchor,
                TextPatternRangeEndpoint_Start,
            )
            .ok()?;
    }
    let count = end - start;
    let moved_end = unsafe {
        range
            .MoveEndpointByUnit(
                TextPatternRangeEndpoint_End,
                TextUnit_Character,
                count as i32,
            )
            .ok()?
    };
    if moved_end != count as i32 {
        return None;
    }
    Some(range)
}

fn text_of(range: &IUIAutomationTextRange) -> Option<String> {
    let text = unsafe { range.GetText(-1).ok()? }.to_string();
    (text.chars().count() <= MAX_UIA_TEXT_CHARS).then_some(text)
}

fn char_count_u32(value: &str) -> Option<u32> {
    u32::try_from(value.chars().count()).ok()
}

fn byte_index_for_char(value: &str, char_index: usize) -> Option<usize> {
    if char_index == value.chars().count() {
        return Some(value.len());
    }
    value.char_indices().nth(char_index).map(|(index, _)| index)
}

fn send_timeout(hwnd: HWND, message: u32, wparam: WPARAM, lparam: LPARAM) -> Option<LRESULT> {
    let mut result = 0usize;
    let ok = unsafe {
        SendMessageTimeoutW(
            hwnd,
            message,
            wparam,
            lparam,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            CONTROL_TIMEOUT_MS,
            &mut result,
        )
    };
    (ok != 0).then_some(result as LRESULT)
}

#[cfg(test)]
fn trace(message: &str) {
    eprintln!("G-switcher LegacyIAccessible adapter: {message}");
}

#[cfg(not(test))]
fn trace(_message: &str) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_index_tracks_unicode_character_offsets() {
        let value = "a😀б";
        assert_eq!(byte_index_for_char(value, 0), Some(0));
        assert_eq!(byte_index_for_char(value, 1), Some(1));
        assert_eq!(byte_index_for_char(value, 2), Some(5));
        assert_eq!(byte_index_for_char(value, 3), Some(value.len()));
        assert_eq!(byte_index_for_char(value, 4), None);
    }
}
