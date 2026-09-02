use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetWindowTextLengthW, GetWindowTextW, SendMessageW,
};

const EM_GETSEL_VALUE: u32 = 0x00B0;
const EM_SETSEL_VALUE: u32 = 0x00B1;
const EM_REPLACESEL_VALUE: u32 = 0x00C2;
const MAX_CONTROL_TEXT_UNITS: usize = 1_048_576;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}

pub fn read_selected_text(hwnd: HWND) -> Option<SelectedText> {
    unsafe {
        let mut start = 0u32;
        let mut end = 0u32;
        SendMessageW(
            hwnd,
            EM_GETSEL_VALUE,
            &mut start as *mut u32 as usize,
            &mut end as *mut u32 as isize,
        );
        if end <= start {
            return None;
        }

        let text_length = GetWindowTextLengthW(hwnd);
        if text_length <= 0 || text_length as usize > MAX_CONTROL_TEXT_UNITS {
            return None;
        }

        let mut buffer = vec![0u16; text_length as usize + 1];
        let copied = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
        if copied <= 0 {
            return None;
        }
        let copied = copied as usize;
        let start_index = (start as usize).min(copied);
        let end_index = (end as usize).min(copied);
        if end_index <= start_index {
            return None;
        }

        Some(SelectedText {
            start,
            end,
            text: String::from_utf16_lossy(&buffer[start_index..end_index]),
        })
    }
}

pub fn replace_range(hwnd: HWND, start: u32, end: u32, text: &str) -> bool {
    if end < start {
        return false;
    }
    let text = wide(text);
    unsafe {
        SendMessageW(hwnd, EM_SETSEL_VALUE, start as usize, end as isize);
        SendMessageW(hwnd, EM_REPLACESEL_VALUE, 1, text.as_ptr() as isize);
    }
    true
}

pub fn utf16_len(value: &str) -> u32 {
    value.encode_utf16().count().min(u32::MAX as usize) as u32
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
}
