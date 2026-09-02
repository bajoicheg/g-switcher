use std::mem::{size_of, zeroed};
use std::ptr::null;
use std::sync::OnceLock;

use parking_lot::Mutex;
use windows_sys::Win32::UI::Shell::{Shell_NotifyIconW, NIF_TIP, NIM_MODIFY, NOTIFYICONDATAW};
use windows_sys::Win32::UI::WindowsAndMessaging::FindWindowW;

use crate::model::Language;

use super::settings::AppMode;

const TRAY_CLASS: &str = "GSwitcher.Tray";
const TRAY_ID: u32 = 1;

#[derive(Debug, Clone)]
struct StatusState {
    paused: bool,
    mode: AppMode,
    process_name: String,
    language: Option<Language>,
    last_operation: Option<String>,
}

impl Default for StatusState {
    fn default() -> Self {
        Self {
            paused: false,
            mode: AppMode::Auto,
            process_name: String::new(),
            language: None,
            last_operation: None,
        }
    }
}

static STATUS: OnceLock<Mutex<StatusState>> = OnceLock::new();

pub fn update_context(mode: AppMode, process_name: &str, language: Language) {
    let mut state = status().lock();
    let process_changed = !state.process_name.eq_ignore_ascii_case(process_name);
    let changed =
        state.paused || state.mode != mode || process_changed || state.language != Some(language);
    if !changed {
        return;
    }

    state.paused = false;
    state.mode = mode;
    state.process_name = process_name.to_owned();
    state.language = Some(language);
    if process_changed {
        state.last_operation = None;
    }
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub fn set_paused(value: bool) {
    let mut state = status().lock();
    if state.paused == value {
        return;
    }
    state.paused = value;
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub fn note_correction(target: Language) {
    let mut state = status().lock();
    state.language = Some(target);
    state.last_operation = Some(format!("исправлено → {}", language_label(target)));
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub fn note_undo(language: Language) {
    let mut state = status().lock();
    state.language = Some(language);
    state.last_operation = Some(format!("отмена → {}", language_label(language)));
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

fn status() -> &'static Mutex<StatusState> {
    STATUS.get_or_init(|| Mutex::new(StatusState::default()))
}

fn tooltip_text(state: &StatusState) -> String {
    if state.paused {
        return "G-switcher — Пауза".to_owned();
    }

    let mut parts = vec![format!("G-switcher — {}", mode_label(state.mode))];
    if !state.process_name.is_empty() {
        parts.push(state.process_name.clone());
    }
    if let Some(language) = state.language {
        parts.push(language_label(language).to_owned());
    }
    if let Some(operation) = &state.last_operation {
        parts.push(operation.clone());
    }
    parts.join(" · ")
}

fn mode_label(mode: AppMode) -> &'static str {
    match mode {
        AppMode::Auto => "Auto",
        AppMode::ManualOnly => "Manual",
        AppMode::Disabled => "Disabled",
    }
}

fn language_label(language: Language) -> &'static str {
    match language {
        Language::Russian => "RU",
        Language::English => "EN",
    }
}

fn publish(text: &str) {
    unsafe {
        let class = wide(TRAY_CLASS);
        let hwnd = FindWindowW(class.as_ptr(), null());
        if hwnd.is_null() {
            return;
        }

        let mut data: NOTIFYICONDATAW = zeroed();
        data.cbSize = size_of::<NOTIFYICONDATAW>() as u32;
        data.hWnd = hwnd;
        data.uID = TRAY_ID;
        data.uFlags = NIF_TIP;
        fill_wide_array(&mut data.szTip, text);
        Shell_NotifyIconW(NIM_MODIFY, &data);
    }
}

fn fill_wide_array<const N: usize>(target: &mut [u16; N], value: &str) {
    let encoded: Vec<u16> = value.encode_utf16().collect();
    let length = encoded.len().min(N.saturating_sub(1));
    target[..length].copy_from_slice(&encoded[..length]);
    target[length] = 0;
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}
