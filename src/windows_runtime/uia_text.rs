use std::cell::RefCell;

use windows::core::Interface;
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationLegacyIAccessiblePattern, IUIAutomationTextPattern,
    IUIAutomationTextRange, TextPatternRangeEndpoint_End, TextPatternRangeEndpoint_Start,
    TextUnit_Character, UIA_LegacyIAccessiblePatternId, UIA_TextPatternId,
};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetWindowThreadProcessId, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK,
};

const EM_REPLACESEL_VALUE: u32 = 0x00C2;
const CONTROL_TIMEOUT_MS: u32 = 75;
const MAX_UIA_TEXT_CHARS: usize = 1_048_576;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UiaSelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UiaCaretSnapshot {
    pub caret: u32,
    pub text_before_caret: String,
}

thread_local! {
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
}

pub fn read_selected_text(hwnd: HWND) -> Option<UiaSelectedText> {
    with_focused_text_pattern(hwnd, |pattern| {
        let (selection, document) = selected_and_document(pattern)?;
        let selected = text_of(&selection)?;
        if selected.is_empty() {
            return None;
        }
        let prefix_start = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_Start)?;
        let prefix_end = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_End)?;
        let start = char_count_u32(&prefix_start)?;
        let end = char_count_u32(&prefix_end)?;
        if end <= start {
            return None;
        }
        Some(UiaSelectedText {
            start,
            end,
            text: selected,
        })
    })
}

pub fn snapshot_caret(hwnd: HWND) -> Option<UiaCaretSnapshot> {
    with_focused_text_pattern(hwnd, |pattern| {
        let (selection, document) = selected_and_document(pattern)?;
        if !text_of(&selection)?.is_empty() {
            return None;
        }
        let prefix = prefix_to_endpoint(&document, &selection, TextPatternRangeEndpoint_Start)?;
        Some(UiaCaretSnapshot {
            caret: char_count_u32(&prefix)?,
            text_before_caret: prefix,
        })
    })
}

pub fn read_document_text(hwnd: HWND) -> Option<String> {
    with_focused_text_pattern(hwnd, |pattern| {
        let document = unsafe { pattern.DocumentRange().ok()? };
        text_of(&document)
    })
}

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

    with_focused_text_pattern(hwnd, |pattern| {
        let document = unsafe { pattern.DocumentRange().ok()? };
        let before = text_of(&document)?;
        let start_index = byte_index_for_char(&before, start as usize)?;
        let end_index = byte_index_for_char(&before, end as usize)?;
        if end_index < start_index || before.get(start_index..end_index)? != expected {
            return None;
        }

        let mut planned = String::with_capacity(
            before.len().saturating_sub(expected.len()).saturating_add(replacement.len()),
        );
        planned.push_str(&before[..start_index]);
        planned.push_str(replacement);
        planned.push_str(&before[end_index..]);

        let range = range_for_char_offsets(&document, start, end)?;
        unsafe { range.Select().ok()? };
        let confirmed = current_selected_text(pattern)?;
        if confirmed != expected {
            return None;
        }

        if !replace_current_selection(hwnd, replacement) {
            return None;
        }

        let after = unsafe { pattern.DocumentRange().ok()? };
        let after_text = text_of(&after)?;
        if after_text == planned {
            let caret = current_selection_range(pattern)?;
            if text_of(&caret)?.is_empty() {
                return Some(true);
            }
        }

        // A partial or unexpected mutation is never accepted. Re-select the
        // replacement span through UIA and restore the verified original text.
        let replacement_end = start.saturating_add(replacement.chars().count().min(u32::MAX as usize) as u32);
        if let Some(current_document) = unsafe { pattern.DocumentRange().ok() } {
            if let Some(rollback_range) = range_for_char_offsets(&current_document, start, replacement_end) {
                if unsafe { rollback_range.Select().is_ok() }
                    && current_selected_text(pattern).as_deref() == Some(replacement)
                {
                    let _ = replace_current_selection(hwnd, expected);
                }
            }
        }
        Some(false)
    })
    .unwrap_or(false)
}

/// Returns true when the focused RichEdit-like UIA provider offers both the
/// Text pattern and a writable legacy accessibility value path. This is used
/// only as a capability probe; actual edits preserve formatting by replacing
/// a UIA-selected range with EM_REPLACESEL rather than replacing the document.
pub fn has_rich_text_adapter(hwnd: HWND) -> bool {
    with_focused_element(hwnd, |element| {
        let text = unsafe { element.GetCurrentPattern(UIA_TextPatternId).ok()? };
        let _: IUIAutomationTextPattern = text.cast().ok()?;
        let legacy = unsafe { element.GetCurrentPattern(UIA_LegacyIAccessiblePatternId).ok()? };
        let _: IUIAutomationLegacyIAccessiblePattern = legacy.cast().ok()?;
        Some(true)
    })
    .unwrap_or(false)
}

fn with_focused_text_pattern<T>(
    hwnd: HWND,
    action: impl FnOnce(&IUIAutomationTextPattern) -> Option<T>,
) -> Option<T> {
    with_focused_element(hwnd, |element| {
        let unknown = unsafe { element.GetCurrentPattern(UIA_TextPatternId).ok()? };
        let pattern: IUIAutomationTextPattern = unknown.cast().ok()?;
        action(&pattern)
    })
}

fn with_focused_element<T>(
    hwnd: HWND,
    action: impl FnOnce(&windows::Win32::UI::Accessibility::IUIAutomationElement) -> Option<T>,
) -> Option<T> {
    let mut expected_process_id = 0u32;
    let thread_id = unsafe { GetWindowThreadProcessId(hwnd, &mut expected_process_id) };
    if thread_id == 0 || expected_process_id == 0 {
        return None;
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
        let element = unsafe { automation.GetFocusedElement().ok()? };
        let process_id = unsafe { element.CurrentProcessId().ok()? } as u32;
        let native_hwnd = unsafe { element.CurrentNativeWindowHandle().ok()? }.0 as HWND;
        let is_password = unsafe { element.CurrentIsPassword().ok()? }.as_bool();
        if process_id != expected_process_id || native_hwnd != hwnd || is_password {
            return None;
        }
        action(&element)
    })
}

fn selected_and_document(
    pattern: &IUIAutomationTextPattern,
) -> Option<(IUIAutomationTextRange, IUIAutomationTextRange)> {
    let selection = current_selection_range(pattern)?;
    let document = unsafe { pattern.DocumentRange().ok()? };
    Some((selection, document))
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

fn prefix_to_endpoint(
    document: &IUIAutomationTextRange,
    selection: &IUIAutomationTextRange,
    endpoint: i32,
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

fn replace_current_selection(hwnd: HWND, replacement: &str) -> bool {
    let wide = replacement
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    send_timeout(hwnd, EM_REPLACESEL_VALUE, 1, wide.as_ptr() as isize).is_some()
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
