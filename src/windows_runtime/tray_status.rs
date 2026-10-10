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
    monitor: crate::user_controls::ReasonMonitor,
}
pub(super) use crate::user_controls::StopReason;
impl StopReason {
    pub(super) fn label(self) -> &'static str {
        match self {
            Self::Ready => "",
            Self::Disabled => "Приложение отключено",
            Self::Secure => "Защищённое поле",
            Self::Unsupported => "Поле не поддерживается",
            Self::WordPending => "Ожидание Word",
            Self::WordUnknown => "Word: результат операции неизвестен",
            Self::WordRefused => "Word: исправление не подтверждено",
        }
    }
}

impl Default for StatusState {
    fn default() -> Self {
        Self {
            paused: false,
            mode: AppMode::Auto,
            process_name: String::new(),
            language: None,
            last_operation: None,
            monitor: Default::default(),
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

    state.paused = super::settings::paused();
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

pub(super) fn observe_process(pid: u32) {
    let Some(birth) = super::user_tools::process_birth(pid) else {
        return;
    };
    let mut state = status().lock();
    let before = state.monitor.reason;
    state
        .monitor
        .observe(crate::user_controls::HostKey { pid, birth });
    state.monitor.clear_transient();
    if before != state.monitor.reason {
        let text = tooltip_text(&state);
        drop(state);
        publish(&text);
    }
}

pub(super) fn observe_foreground(app: &super::user_tools::AppIdentity) {
    let value = super::settings::runtime_settings();
    let mut state = status().lock();
    let old_reason = state.monitor.reason;
    let mode = value.app_mode(&app.name);
    let changed = state.process_name != app.name || state.mode != mode;
    state.monitor.observe(app.key());
    if changed || old_reason != state.monitor.reason {
        if state.process_name != app.name {
            state.language = None;
            state.last_operation = None;
        }
        state.process_name = app.name.clone();
        state.mode = mode;
        let text = tooltip_text(&state);
        drop(state);
        publish(&text);
    }
}

pub(super) fn note_reason(pid: u32, reason: StopReason) {
    if let Some(birth) = super::user_tools::process_birth(pid) {
        note_word_reason(pid, birth, reason);
    }
}
pub(super) fn note_word_reason(pid: u32, birth: u64, reason: StopReason) {
    let mut state = status().lock();
    state
        .monitor
        .record(crate::user_controls::HostKey { pid, birth }, reason);
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub(super) fn begin_word(pid: u32, birth: u64, operation: u64) {
    let mut state = status().lock();
    state
        .monitor
        .begin_word(crate::user_controls::HostKey { pid, birth }, operation);
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub(super) fn complete_word(pid: u32, birth: u64, operation: u64, success: bool, uncertain: bool) {
    let mut state = status().lock();
    state.monitor.complete_word(
        crate::user_controls::HostKey { pid, birth },
        operation,
        success,
        uncertain,
    );
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub(super) fn diagnostic_text() -> String {
    let state = status().lock();
    let mode = match state.mode {
        AppMode::Auto => 0,
        AppMode::ManualOnly => 1,
        AppMode::Disabled => 2,
    };
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("schema = \"g-switcher-diagnostics/v1\"\nversion = \"{}\"\nbuild_id = \"{}\"\nobserved_at_unix_ms = {now}\npaused = {}\nmode_code = {mode}\nreason_code = {}\nevent_counts = {:?}\n", crate::PRODUCT_VERSION, env!("GSWITCHER_BROKER_BUILD_ID"), state.paused, state.monitor.reason as u8, state.monitor.events)
}

pub(super) fn reason_label() -> &'static str {
    status().lock().monitor.reason.label()
}

pub(super) fn refresh_policy_view() {
    let value = super::settings::runtime_settings();
    let mut state = status().lock();
    state.mode = value.app_mode(&state.process_name);
    state.paused = super::settings::paused();
    let text = tooltip_text(&state);
    drop(state);
    publish(&text);
}

pub fn set_paused(value: bool) {
    let mut state = status().lock();
    if state.paused == value && !value {
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
    if state.monitor.reason != StopReason::WordUnknown {
        state.monitor.reason = StopReason::Ready;
    }
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
        return super::settings::pause_remaining_minutes().map_or_else(
            || "G-switcher — Пауза".to_owned(),
            |m| format!("G-switcher — Пауза: {m} мин"),
        );
    }

    let mut parts = vec![format!("G-switcher — {}", mode_label(state.mode))];
    // Keep the refusal visible even when the shell truncates its 127-unit tooltip.
    if state.monitor.reason != StopReason::Ready {
        parts.push(state.monitor.reason.label().to_owned());
    }
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
