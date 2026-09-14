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
    CUIAutomation, IUIAutomation, IUIAutomationTextPattern, IUIAutomationTextRange,
    IUIAutomationValuePattern, TextPatternRangeEndpoint, TextPatternRangeEndpoint_End,
    TextPatternRangeEndpoint_Start, TextUnit_Character, UIA_TextPatternId, UIA_ValuePatternId,
};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetWindowThreadProcessId, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_NULL,
};

const CONTROL_TIMEOUT_MS: u32 = 75;
const MAX_UIA_TEXT_CHARS: usize = 1_048_576;
const MAX_RUNTIME_ID_PARTS: usize = 16;
const POST_MUTATION_VERIFY_TIMEOUT: Duration = Duration::from_millis(250);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModernSelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModernCaretSnapshot {
    pub caret: u32,
    pub text_before_caret: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
struct RuntimeId {
    len: u8,
    parts: [i32; MAX_RUNTIME_ID_PARTS],
}

struct ModernContext {
    runtime_id: RuntimeId,
    text: IUIAutomationTextPattern,
    value: IUIAutomationValuePattern,
}

thread_local! {
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
}

pub fn has_adapter(hwnd: HWND) -> bool {
    let Some(context) = focused_context(hwnd) else {
        return false;
    };
    if unsafe { context.value.CurrentIsReadOnly().ok() }.is_none_or(|value| value.as_bool()) {
        return false;
    }
    let Some(value) = value_of(&context.value) else {
        return false;
    };
    let Some(document) = (unsafe { context.text.DocumentRange().ok() }) else {
        return false;
    };
    text_of(&document).is_some_and(|text| text == value)
        && current_selection_range(&context.text).is_some()
}

pub fn read_selected_text(hwnd: HWND) -> Option<ModernSelectedText> {
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
    (end > start).then_some(ModernSelectedText {
        start,
        end,
        text: selected,
    })
}

pub fn snapshot_caret(hwnd: HWND) -> Option<ModernCaretSnapshot> {
    let context = focused_context(hwnd)?;
    snapshot_caret_from_pattern(&context.text)
}

#[cfg(test)]
pub fn read_document_text(hwnd: HWND) -> Option<String> {
    let context = focused_context(hwnd)?;
    let document = unsafe { context.text.DocumentRange().ok()? };
    text_of(&document)
}

/// Verified whole-value mutation for modern controls such as Chromium/WebView2
/// and Electron text fields. The precondition is checked against TextPattern
/// and ValuePattern. After SetValue, the focused element and both patterns are
/// reacquired because Chromium may invalidate provider objects/ranges when the
/// DOM value changes. RuntimeId must remain identical across the operation.
/// No clipboard or blind SendInput fallback is used.
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
        return false;
    };
    if unsafe { context.value.CurrentIsReadOnly().ok() }.is_none_or(|value| value.as_bool()) {
        return false;
    }

    let Some(document) = (unsafe { context.text.DocumentRange().ok() }) else {
        return false;
    };
    let Some(before_text) = text_of(&document) else {
        return false;
    };
    let Some(before_value) = value_of(&context.value) else {
        return false;
    };
    if before_text != before_value {
        return false;
    }

    let Some(original_selection) = selection_offsets(&context.text, &document) else {
        return false;
    };
    let Some(start_index) = byte_index_for_char(&before_text, start as usize) else {
        return false;
    };
    let Some(end_index) = byte_index_for_char(&before_text, end as usize) else {
        return false;
    };
    if end_index < start_index || before_text.get(start_index..end_index) != Some(expected) {
        return false;
    }

    let mut planned = String::with_capacity(
        before_text
            .len()
            .saturating_sub(expected.len())
            .saturating_add(replacement.len()),
    );
    planned.push_str(&before_text[..start_index]);
    planned.push_str(replacement);
    planned.push_str(&before_text[end_index..]);

    let Some(target_range) = range_for_char_offsets(&document, start, end) else {
        return false;
    };
    if unsafe { target_range.Select().is_err() }
        || current_selected_text(&context.text).as_deref() != Some(expected)
        || value_of(&context.value).as_deref() != Some(before_value.as_str())
    {
        let _ = select_offsets(&context.text, original_selection.0, original_selection.1);
        return false;
    }

    let original_id = context.runtime_id;
    let planned_bstr = BSTR::from(planned.as_str());
    let set_result = unsafe { context.value.SetValue(&planned_bstr) };
    drop(context);

    let replacement_end =
        start.saturating_add(replacement.chars().count().min(u32::MAX as usize) as u32);

    // A provider may refresh its UIA objects asynchronously after SetValue.
    // Reacquire rather than trusting pre-mutation COM objects/ranges.
    let deadline = Instant::now() + POST_MUTATION_VERIFY_TIMEOUT;
    loop {
        let Some(after) = focused_context(hwnd) else {
            return false;
        };
        if after.runtime_id != original_id {
            // Same host HWND can contain multiple DOM fields. A RuntimeId change
            // is a focus race: never mutate or roll back the newly focused field.
            return false;
        }

        let current_value = value_of(&after.value);
        let current_text =
            unsafe { after.text.DocumentRange().ok() }.and_then(|range| text_of(&range));
        if current_value.as_deref() == Some(planned.as_str())
            && current_text.as_deref() == Some(planned.as_str())
        {
            if select_offsets(&after.text, replacement_end, replacement_end) {
                // Reacquire one more time so the final acceptance is based on a
                // fresh provider snapshot after the selection operation too.
                drop(after);
                if let Some(final_context) = focused_context(hwnd) {
                    if final_context.runtime_id == original_id
                        && value_of(&final_context.value).as_deref() == Some(planned.as_str())
                        && unsafe { final_context.text.DocumentRange().ok() }
                            .and_then(|range| text_of(&range))
                            .as_deref()
                            == Some(planned.as_str())
                        && snapshot_caret_from_pattern(&final_context.text)
                            .is_some_and(|snapshot| snapshot.caret == replacement_end)
                    {
                        return true;
                    }
                }
            }
            break;
        }

        if Instant::now() >= deadline {
            break;
        }
        thread::sleep(Duration::from_millis(5));
    }

    // If SetValue reported an error or postconditions could not be established,
    // restore only when the exact planned value is still present on the same
    // UIA element. Never overwrite an unexpected/user-edited value.
    let _ = set_result;
    rollback_if_exact(
        hwnd,
        original_id,
        &planned,
        &before_value,
        original_selection,
    );
    false
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
    if context.runtime_id != expected_id || value_of(&context.value).as_deref() != Some(planned) {
        return;
    }
    let original_bstr = BSTR::from(original);
    if unsafe { context.value.SetValue(&original_bstr).is_err() } {
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
        if value_of(&restored.value).as_deref() == Some(original)
            && unsafe { restored.text.DocumentRange().ok() }
                .and_then(|range| text_of(&range))
                .as_deref()
                == Some(original)
        {
            let _ = select_offsets(&restored.text, original_selection.0, original_selection.1);
            return;
        }
        if Instant::now() >= deadline {
            return;
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn focused_context(hwnd: HWND) -> Option<ModernContext> {
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

        let runtime_id = runtime_id(&element)?;
        let text_unknown = unsafe { element.GetCurrentPattern(UIA_TextPatternId).ok()? };
        let text: IUIAutomationTextPattern = text_unknown.cast().ok()?;
        let value_unknown = unsafe { element.GetCurrentPattern(UIA_ValuePatternId).ok()? };
        let value: IUIAutomationValuePattern = value_unknown.cast().ok()?;
        Some(ModernContext {
            runtime_id,
            text,
            value,
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

        let mut id = RuntimeId {
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

fn snapshot_caret_from_pattern(pattern: &IUIAutomationTextPattern) -> Option<ModernCaretSnapshot> {
    let selection = current_selection_range(pattern)?;
    if !text_of(&selection)?.is_empty() {
        return None;
    }
    let document = unsafe { pattern.DocumentRange().ok()? };
    let prefix = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_Start)?;
    Some(ModernCaretSnapshot {
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

fn value_of(pattern: &IUIAutomationValuePattern) -> Option<String> {
    let value = unsafe { pattern.CurrentValue().ok()? }.to_string();
    (value.chars().count() <= MAX_UIA_TEXT_CHARS).then_some(value)
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
