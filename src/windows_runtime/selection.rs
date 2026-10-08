use std::sync::OnceLock;
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetClassNameW, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_GETTEXT, WM_GETTEXTLENGTH,
    WM_NULL,
};

#[path = "read_worker.rs"]
pub(super) mod read_worker;
#[path = "uia_legacy_v2.rs"]
mod uia_legacy;
#[path = "uia_modern.rs"]
mod uia_modern;
#[path = "uia_text.rs"]
mod uia_text;
#[path = "word_native.rs"]
mod word_native;

const EM_GETSEL_VALUE: u32 = 0x00B0;
const EM_SETSEL_VALUE: u32 = 0x00B1;
const EM_REPLACESEL_VALUE: u32 = 0x00C2;
const MAX_CONTROL_TEXT_UNITS: usize = 1_048_576;
const CONTROL_TIMEOUT_MS: u32 = 75;

// This module is also imported by the standalone failure-E2E binary. Bind the
// real runtime explicitly instead of assuming a particular parent module.
struct RuntimePolicy {
    generation: fn() -> u32,
    paused: fn() -> bool,
}
impl RuntimePolicy {
    fn allows_mutation(&self, generation: u32) -> bool {
        (self.generation)() == generation && !(self.paused)()
    }
}
static RUNTIME_POLICY: OnceLock<RuntimePolicy> = OnceLock::new();

pub fn configure_runtime_policy(generation: fn() -> u32, paused: fn() -> bool) {
    // Immutable after startup; every operation keeps its captured generation.
    let _ = RUNTIME_POLICY.set(RuntimePolicy { generation, paused });
}

fn runtime_generation() -> Option<u32> {
    Some((RUNTIME_POLICY.get()?.generation)())
}
fn runtime_allows_mutation(generation: u32) -> bool {
    RUNTIME_POLICY
        .get()
        .is_some_and(|policy| policy.allows_mutation(generation))
}

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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TextAdapter {
    EditMessages,
    RichEditUia,
    ModernUiaValue,
    ModernUiaLegacy,
    WordNative,
}

/// Returns true only for responsive controls with a synchronous, verifiable
/// 2.0.1 text adapter. Plain Edit uses marshalled system messages; RichEdit
/// uses UIA TextPattern plus native range-local replacement. Modern Chromium/
/// WebView2/Electron-style controls use exact TextPattern state and prefer the
/// documented LegacyIAccessible SetValue path when it is exposed; ValuePattern
/// remains the verified fallback for modern controls without LegacyIAccessible.
/// Both paths bind mutations to one RuntimeId and never use clipboard or blind
/// SendInput. A hung, closing, password, disabled, read-only or unverifiable
/// target fails open.
/// Lightweight Word routing for key admission, never mutation authority.
pub fn is_word_target(hwnd: HWND) -> bool {
    word_native::is_word_window(hwnd)
}

pub fn prepare_word_correction_suffix(
    hwnd: HWND,
    expected: &str,
    replacement: &str,
) -> Option<(String, String)> {
    word_native::prepare_correction_suffix(hwnd, expected, replacement)
}

pub fn is_standard_edit(hwnd: HWND) -> bool {
    adapter(hwnd).is_some()
}

/// Plain system Edit controls have a native password/style check and a
/// marshalled cross-process message adapter. Other supported text controls
/// require successful UIA metadata verification before mutation.
pub fn is_plain_edit(hwnd: HWND) -> bool {
    class_name(hwnd).is_some_and(|name| is_plain_edit_class(&name))
}

pub fn read_selected_text(hwnd: HWND) -> Option<SelectedText> {
    if class_name(hwnd).as_deref() == Some("_WwG") {
        let selected = word_native::read_selected_text(hwnd)?;
        return Some(SelectedText {
            start: selected.start,
            end: selected.end,
            text: selected.text,
        });
    }
    match adapter(hwnd)? {
        TextAdapter::WordNative => {
            let selected = word_native::read_selected_text(hwnd)?;
            Some(SelectedText {
                start: selected.start,
                end: selected.end,
                text: selected.text,
            })
        }
        TextAdapter::EditMessages => read_selected_text_messages(hwnd),
        TextAdapter::RichEditUia => {
            let selected = uia_text::read_selected_text(hwnd)?;
            Some(SelectedText {
                start: selected.start,
                end: selected.end,
                text: selected.text,
            })
        }
        TextAdapter::ModernUiaValue => {
            let selected = uia_modern::read_selected_text(hwnd)?;
            Some(SelectedText {
                start: selected.start,
                end: selected.end,
                text: selected.text,
            })
        }
        TextAdapter::ModernUiaLegacy => {
            let selected = uia_legacy::read_selected_text(hwnd)?;
            Some(SelectedText {
                start: selected.start,
                end: selected.end,
                text: selected.text,
            })
        }
    }
}

pub fn snapshot_caret(hwnd: HWND) -> Option<EditSnapshot> {
    if class_name(hwnd).as_deref() == Some("_WwG") {
        let snapshot = word_native::snapshot_caret(hwnd)?;
        return Some(EditSnapshot {
            caret: snapshot.caret,
            text_before_caret: snapshot.text_before_caret,
        });
    }
    match adapter(hwnd)? {
        TextAdapter::WordNative => {
            let snapshot = word_native::snapshot_caret(hwnd)?;
            Some(EditSnapshot {
                caret: snapshot.caret,
                text_before_caret: snapshot.text_before_caret,
            })
        }
        TextAdapter::EditMessages => snapshot_caret_messages(hwnd),
        TextAdapter::RichEditUia => {
            let snapshot = uia_text::snapshot_caret(hwnd)?;
            Some(EditSnapshot {
                caret: snapshot.caret,
                text_before_caret: snapshot.text_before_caret,
            })
        }
        TextAdapter::ModernUiaValue => {
            let snapshot = uia_modern::snapshot_caret(hwnd)?;
            Some(EditSnapshot {
                caret: snapshot.caret,
                text_before_caret: snapshot.text_before_caret,
            })
        }
        TextAdapter::ModernUiaLegacy => {
            let snapshot = uia_legacy::snapshot_caret(hwnd)?;
            Some(EditSnapshot {
                caret: snapshot.caret,
                text_before_caret: snapshot.text_before_caret,
            })
        }
    }
}

pub fn suffix_matches_at_caret(hwnd: HWND, expected: &str) -> bool {
    let Some(snapshot) = snapshot_caret(hwnd) else {
        return false;
    };
    if word_native::is_word_window(hwnd) {
        snapshot
            .text_before_caret
            .ends_with(&word_native::normalize_newlines(expected))
    } else {
        snapshot.text_before_caret.ends_with(expected)
    }
}

pub fn replace_suffix_at_caret(hwnd: HWND, expected: &str, replacement: &str) -> bool {
    let generation = runtime_generation();
    if class_name(hwnd).as_deref() == Some("_WwG") {
        let Some(generation) = generation else {
            return false;
        };
        return word_native::replace_suffix_if_matches(hwnd, expected, replacement, generation);
    }
    let control_adapter = if class_name(hwnd).as_deref() == Some("_WwG") {
        TextAdapter::WordNative
    } else {
        let Some(adapter) = adapter(hwnd) else {
            return false;
        };
        adapter
    };
    let Some(snapshot) = snapshot_caret(hwnd) else {
        return false;
    };
    let native_expected;
    let native_replacement;
    let (expected, replacement) = if control_adapter == TextAdapter::WordNative {
        native_expected = word_native::normalize_newlines(expected);
        native_replacement = word_native::normalize_newlines(replacement);
        (native_expected.as_str(), native_replacement.as_str())
    } else {
        (expected, replacement)
    };
    if !snapshot.text_before_caret.ends_with(expected) {
        return false;
    }
    let expected_units = match control_adapter {
        TextAdapter::EditMessages | TextAdapter::WordNative => utf16_len(expected),
        TextAdapter::RichEditUia | TextAdapter::ModernUiaValue | TextAdapter::ModernUiaLegacy => {
            expected.chars().count().min(u32::MAX as usize) as u32
        }
    };
    let start = snapshot.caret.saturating_sub(expected_units);
    if control_adapter == TextAdapter::WordNative {
        let Some(generation) = generation else {
            return false;
        };
        return word_native::replace_range_if_matches(
            hwnd,
            start,
            snapshot.caret,
            expected,
            replacement,
            generation,
        );
    }
    replace_range_if_matches(hwnd, start, snapshot.caret, expected, replacement)
}

/// Replaces the requested range only if it still contains `expected` and the
/// selected adapter can verify the exact post-state. Chromium controls that
/// expose LegacyIAccessible use that documented mutation interface directly,
/// avoiding a failed ValuePattern attempt from disturbing the provider's
/// selection state before Undo. There is never a clipboard or blind SendInput
/// fallback.
pub fn replace_range_if_matches(
    hwnd: HWND,
    start: u32,
    end: u32,
    expected: &str,
    replacement: &str,
) -> bool {
    let generation = runtime_generation();
    if end < start {
        return false;
    }
    if class_name(hwnd).as_deref() == Some("_WwG") {
        let Some(generation) = generation else {
            return false;
        };
        return word_native::replace_range_if_matches(
            hwnd,
            start,
            end,
            expected,
            replacement,
            generation,
        );
    }
    match adapter(hwnd) {
        Some(TextAdapter::WordNative) => {
            let Some(generation) = generation else {
                return false;
            };
            word_native::replace_range_if_matches(
                hwnd,
                start,
                end,
                expected,
                replacement,
                generation,
            )
        }
        Some(TextAdapter::EditMessages) => {
            replace_range_if_matches_messages(hwnd, start, end, expected, replacement)
        }
        Some(TextAdapter::RichEditUia) => {
            uia_text::replace_range_if_matches(hwnd, start, end, expected, replacement)
        }
        Some(TextAdapter::ModernUiaValue) => {
            uia_modern::replace_range_if_matches(hwnd, start, end, expected, replacement)
        }
        Some(TextAdapter::ModernUiaLegacy) => {
            uia_legacy::replace_range_if_matches(hwnd, start, end, expected, replacement)
        }
        None => false,
    }
}

#[cfg(test)]
pub fn read_control_text(hwnd: HWND) -> Option<Vec<u16>> {
    match adapter(hwnd)? {
        TextAdapter::WordNative => Some(
            word_native::read_document_text(hwnd)?
                .encode_utf16()
                .collect(),
        ),
        TextAdapter::EditMessages => read_control_text_messages(hwnd),
        TextAdapter::RichEditUia => {
            Some(uia_text::read_document_text(hwnd)?.encode_utf16().collect())
        }
        TextAdapter::ModernUiaValue => Some(
            uia_modern::read_document_text(hwnd)?
                .encode_utf16()
                .collect(),
        ),
        TextAdapter::ModernUiaLegacy => Some(
            uia_legacy::read_document_text(hwnd)?
                .encode_utf16()
                .collect(),
        ),
    }
}

pub fn utf16_len(value: &str) -> u32 {
    value.encode_utf16().count().min(u32::MAX as usize) as u32
}

fn read_selected_text_messages(hwnd: HWND) -> Option<SelectedText> {
    let (start, end) = read_selection_range_messages(hwnd)?;
    if end <= start {
        return None;
    }
    let text = read_control_text_messages(hwnd)?;
    let start_index = start as usize;
    let end_index = end as usize;
    if end_index > text.len() || end_index <= start_index {
        return None;
    }
    Some(SelectedText {
        start,
        end,
        text: String::from_utf16_lossy(&text[start_index..end_index]),
    })
}

fn snapshot_caret_messages(hwnd: HWND) -> Option<EditSnapshot> {
    let (start, end) = read_selection_range_messages(hwnd)?;
    if start != end {
        return None;
    }
    let text = read_control_text_messages(hwnd)?;
    let caret = end as usize;
    if caret > text.len() {
        return None;
    }
    Some(EditSnapshot {
        caret: end,
        text_before_caret: String::from_utf16_lossy(&text[..caret]),
    })
}

fn replace_range_if_matches_messages(
    hwnd: HWND,
    start: u32,
    end: u32,
    expected: &str,
    replacement: &str,
) -> bool {
    let before = match read_control_text_messages(hwnd) {
        Some(value) => value,
        None => return false,
    };
    let start_index = start as usize;
    let end_index = end as usize;
    if end_index > before.len() || start_index > end_index {
        return false;
    }

    let expected_units = expected.encode_utf16().collect::<Vec<_>>();
    if before[start_index..end_index] != expected_units {
        return false;
    }
    let replacement_units = replacement.encode_utf16().collect::<Vec<_>>();
    let mut planned = before.clone();
    planned.splice(start_index..end_index, replacement_units.iter().copied());

    if !replace_range_raw_messages(hwnd, start, end, replacement) {
        return false;
    }
    if read_control_text_messages(hwnd).is_some_and(|after| after == planned) {
        return true;
    }

    let replacement_end =
        start.saturating_add(replacement_units.len().min(u32::MAX as usize) as u32);
    let rollback_end = read_control_text_messages(hwnd)
        .map(|current| (replacement_end as usize).min(current.len()) as u32)
        .unwrap_or(replacement_end);
    let _ = replace_range_raw_messages(hwnd, start, rollback_end, expected);
    false
}

fn read_selection_range_messages(hwnd: HWND) -> Option<(u32, u32)> {
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

fn read_control_text_messages(hwnd: HWND) -> Option<Vec<u16>> {
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

fn replace_range_raw_messages(hwnd: HWND, start: u32, end: u32, text: &str) -> bool {
    if send_timeout(hwnd, EM_SETSEL_VALUE, start as usize, end as isize).is_none() {
        return false;
    }
    let text = wide(text);
    send_timeout(hwnd, EM_REPLACESEL_VALUE, 1, text.as_ptr() as isize).is_some()
}

fn adapter(hwnd: HWND) -> Option<TextAdapter> {
    send_timeout(hwnd, WM_NULL, 0, 0)?;

    let name = class_name(hwnd)?;
    if name == "_WwG" {
        // Word is exclusively native: failed/uncertain NativeOM never falls
        // through to its known E_NOTIMPL whole-value Legacy writer.
        word_native::has_adapter(hwnd).then_some(TextAdapter::WordNative)
    } else if is_plain_edit_class(&name) {
        Some(TextAdapter::EditMessages)
    } else if is_rich_edit_class(&name) && uia_text::has_rich_text_adapter(hwnd) {
        Some(TextAdapter::RichEditUia)
    } else if uia_legacy::has_adapter(hwnd) {
        Some(TextAdapter::ModernUiaLegacy)
    } else if uia_modern::has_adapter(hwnd) {
        Some(TextAdapter::ModernUiaValue)
    } else {
        None
    }
}

fn class_name(hwnd: HWND) -> Option<String> {
    let mut buffer = [0u16; 256];
    let length = unsafe { GetClassNameW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32) };
    if length <= 0 {
        return None;
    }
    Some(String::from_utf16_lossy(&buffer[..length as usize]))
}

fn is_plain_edit_class(class_name: &str) -> bool {
    class_name.trim().eq_ignore_ascii_case("edit")
}

fn is_rich_edit_class(class_name: &str) -> bool {
    let normalized = class_name.trim().to_ascii_lowercase();
    normalized.starts_with("richedit") || normalized.starts_with("rich edit")
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
    fn runtime_policy_refuses_stale_or_paused_mutations() {
        fn generation() -> u32 {
            7
        }
        fn running() -> bool {
            false
        }
        fn paused() -> bool {
            true
        }
        let running_policy = RuntimePolicy {
            generation,
            paused: running,
        };
        assert!(running_policy.allows_mutation(7));
        assert!(!running_policy.allows_mutation(6));
        let paused_policy = RuntimePolicy { generation, paused };
        assert!(!paused_policy.allows_mutation(7));
    }

    #[test]
    fn utf16_length_matches_windows_selection_units() {
        assert_eq!(utf16_len("hello"), 5);
        assert_eq!(utf16_len("привет"), 6);
        assert_eq!(utf16_len("a😀b"), 4);
    }

    #[test]
    fn suffix_math_is_utf16_based_for_plain_edit() {
        let prefix = "abc😀";
        let suffix = "привет ";
        assert_eq!(utf16_len(prefix), 5);
        assert_eq!(utf16_len(suffix), 7);
    }

    #[test]
    fn native_class_detection_is_limited_but_modern_fallback_is_uia_driven() {
        assert!(is_plain_edit_class("Edit"));
        for class_name in ["RICHEDIT50W", "RichEditD2DPT", "Rich Edit 20W"] {
            assert!(is_rich_edit_class(class_name), "missed {class_name}");
        }
        for class_name in ["Chrome_RenderWidgetHostHWND", "Windows.UI.Core.CoreWindow"] {
            assert!(!is_plain_edit_class(class_name));
            assert!(!is_rich_edit_class(class_name));
        }
    }
}
