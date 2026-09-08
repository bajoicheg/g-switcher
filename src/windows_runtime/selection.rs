use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetClassNameW, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_GETTEXT, WM_GETTEXTLENGTH,
};

const EM_GETSEL_VALUE: u32 = 0x00B0;
const EM_SETSEL_VALUE: u32 = 0x00B1;
const EM_REPLACESEL_VALUE: u32 = 0x00C2;
const MAX_CONTROL_TEXT_UNITS: usize = 1_048_576;
const CONTROL_TIMEOUT_MS: u32 = 75;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EditSnapshot {
    pub caret: u32,
    pub text_before_caret: String,
}

/// Returns true only for controls where the classic system Edit messages are a
/// documented supported path. The name is kept for compatibility with the
/// 2.0.0 runtime while 2.0.1 also accepts the RichEdit family.
pub fn is_standard_edit(hwnd: HWND) -> bool {
    class_name(hwnd).is_some_and(|name| is_message_text_class(&name))
}

pub fn read_selected_text(hwnd: HWND) -> Option<SelectedText> {
    if !is_standard_edit(hwnd) {
        return None;
    }
    let (start, end) = read_selection_range(hwnd)?;
    if end <= start {
        return None;
    }
    let text = read_control_text(hwnd)?;
    let start_index = (start as usize).min(text.len());
    let end_index = (end as usize).min(text.len());
    if end_index <= start_index {
        return None;
    }

    Some(SelectedText {
        start,
        end,
        text: String::from_utf16_lossy(&text[start_index..end_index]),
    })
}

pub fn snapshot_caret(hwnd: HWND) -> Option<EditSnapshot> {
    if !is_standard_edit(hwnd) {
        return None;
    }
    let (start, end) = read_selection_range(hwnd)?;
    if start != end {
        return None;
    }
    let text = read_control_text(hwnd)?;
    let caret = (end as usize).min(text.len());
    Some(EditSnapshot {
        caret: end,
        text_before_caret: String::from_utf16_lossy(&text[..caret]),
    })
}

pub fn suffix_matches_at_caret(hwnd: HWND, expected: &str) -> bool {
    let Some(snapshot) = snapshot_caret(hwnd) else {
        return false;
    };
    snapshot.text_before_caret.ends_with(expected)
}

pub fn replace_suffix_at_caret(hwnd: HWND, expected: &str, replacement: &str) -> bool {
    let Some(snapshot) = snapshot_caret(hwnd) else {
        return false;
    };
    if !snapshot.text_before_caret.ends_with(expected) {
        return false;
    }
    let expected_units = utf16_len(expected);
    let start = snapshot.caret.saturating_sub(expected_units);
    if !replace_range(hwnd, start, snapshot.caret, replacement) {
        return false;
    }

    let Some(after) = snapshot_caret(hwnd) else {
        return false;
    };
    after.text_before_caret.ends_with(replacement)
}

pub fn replace_range(hwnd: HWND, start: u32, end: u32, text: &str) -> bool {
    if end < start || !is_standard_edit(hwnd) {
        return false;
    }
    if send_timeout(hwnd, EM_SETSEL_VALUE, start as usize, end as isize).is_none() {
        return false;
    }

    let text = wide(text);
    if send_timeout(hwnd, EM_REPLACESEL_VALUE, 1, text.as_ptr() as isize).is_none() {
        return false;
    }
    true
}

pub fn read_selection_range(hwnd: HWND) -> Option<(u32, u32)> {
    if !is_standard_edit(hwnd) {
        return None;
    }
    let mut start = 0u32;
    let mut end = 0u32;
    send_timeout(
        hwnd,
        EM_GETSEL_VALUE,
        &mut start as *mut u32 as usize,
        &mut end as *mut u32 as isize,
    )?;
    Some((start, end))
}

pub fn read_control_text(hwnd: HWND) -> Option<Vec<u16>> {
    if !is_standard_edit(hwnd) {
        return None;
    }
    let length = send_timeout(hwnd, WM_GETTEXTLENGTH, 0, 0)?;
    if length < 0 || length as usize > MAX_CONTROL_TEXT_UNITS {
        return None;
    }
    let capacity = length as usize + 1;
    let mut buffer = vec![0u16; capacity];
    let copied = send_timeout(hwnd, WM_GETTEXT, capacity, buffer.as_mut_ptr() as isize)?;
    if copied < 0 {
        return None;
    }
    let copied = (copied as usize).min(buffer.len().saturating_sub(1));
    buffer.truncate(copied);
    Some(buffer)
}

pub fn utf16_len(value: &str) -> u32 {
    value.encode_utf16().count().min(u32::MAX as usize) as u32
}

fn class_name(hwnd: HWND) -> Option<String> {
    let mut buffer = [0u16; 256];
    let length = unsafe { GetClassNameW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32) };
    if length <= 0 {
        return None;
    }
    Some(String::from_utf16_lossy(&buffer[..length as usize]))
}

fn is_message_text_class(class_name: &str) -> bool {
    let normalized = class_name.trim().to_ascii_lowercase();
    normalized == "edit"
        || normalized.starts_with("richedit")
        || normalized.starts_with("rich edit")
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

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utf16_length_matches_windows_selection_units() {
        assert_eq!(utf16_len("hello"), 5);
        assert_eq!(utf16_len("привет"), 6);
        assert_eq!(utf16_len("a😀b"), 4);
    }

    #[test]
    fn suffix_math_is_utf16_based() {
        let prefix = "abc😀";
        let suffix = "привет ";
        assert_eq!(utf16_len(prefix), 5);
        assert_eq!(utf16_len(suffix), 7);
    }

    #[test]
    fn message_adapter_is_limited_to_edit_and_richedit_families() {
        for class_name in ["Edit", "RICHEDIT50W", "RichEditD2DPT", "Rich Edit 20W"] {
            assert!(is_message_text_class(class_name), "missed {class_name}");
        }
        for class_name in ["Chrome_RenderWidgetHostHWND", "Windows.UI.Core.CoreWindow"] {
            assert!(
                !is_message_text_class(class_name),
                "unsafe class {class_name}"
            );
        }
    }
}
