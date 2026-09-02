use std::mem::size_of;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

use anyhow::{anyhow, Result};
use parking_lot::RwLock;
use windows_sys::Win32::System::Registry::{
    RegCloseKey, RegCreateKeyExW, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW,
    HKEY, HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_DWORD, REG_OPTION_NON_VOLATILE, REG_SZ,
};

const SETTINGS_KEY: &str = "Software\\GSwitcher";
const FIRST_RUN_VALUE: &str = "FirstRunCompleted";
const AUTO_CORRECT_VALUE: &str = "AutoCorrectEnabled";
const DISABLED_APPS_VALUE: &str = "DisabledApps";
const MANUAL_ONLY_APPS_VALUE: &str = "ManualOnlyApps";
const LEGACY_EXCLUDED_APPS_VALUE: &str = "ExcludedApps";
const USER_WORDS_VALUE: &str = "UserDictionary";
const HOTKEY_MANUAL_CURRENT_VALUE: &str = "HotkeyManualCurrent";
const HOTKEY_PREVIOUS_WORD_VALUE: &str = "HotkeyPreviousWord";
const HOTKEY_UNDO_VALUE: &str = "HotkeyUndo";
const HOTKEY_PAUSE_VALUE: &str = "HotkeyPause";
const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const RUN_VALUE: &str = "G-switcher";

const VK_BACK_VALUE: u16 = 0x08;
const VK_SPACE_VALUE: u16 = 0x20;
const VK_F1_VALUE: u16 = 0x70;
const VK_F12_VALUE: u16 = 0x7B;

static RUNTIME_SETTINGS: OnceLock<RwLock<RuntimeSettings>> = OnceLock::new();
static PAUSED: AtomicBool = AtomicBool::new(false);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppMode {
    Auto,
    ManualOnly,
    Disabled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Hotkey {
    pub ctrl: bool,
    pub shift: bool,
    pub alt: bool,
    pub vk: u16,
}

impl Hotkey {
    pub const fn new(ctrl: bool, shift: bool, alt: bool, vk: u16) -> Self {
        Self {
            ctrl,
            shift,
            alt,
            vk,
        }
    }

    pub fn matches(self, vk: u16, ctrl: bool, shift: bool, alt: bool) -> bool {
        self.vk == vk && self.ctrl == ctrl && self.shift == shift && self.alt == alt
    }

    pub fn to_text(self) -> String {
        let mut parts = Vec::new();
        if self.ctrl {
            parts.push("Ctrl".to_owned());
        }
        if self.shift {
            parts.push("Shift".to_owned());
        }
        if self.alt {
            parts.push("Alt".to_owned());
        }
        parts.push(key_name(self.vk));
        parts.join("+")
    }
}

pub const DEFAULT_MANUAL_CURRENT_HOTKEY: Hotkey = Hotkey::new(true, true, false, 0x7B); // F12
pub const DEFAULT_PREVIOUS_WORD_HOTKEY: Hotkey = Hotkey::new(true, true, false, 0x79); // F10
pub const DEFAULT_UNDO_HOTKEY: Hotkey = Hotkey::new(true, false, false, VK_BACK_VALUE);
pub const DEFAULT_PAUSE_HOTKEY: Hotkey = Hotkey::new(true, true, false, 0x7A); // F11

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeSettings {
    pub auto_correct: bool,
    pub disabled_apps: Vec<String>,
    pub manual_only_apps: Vec<String>,
    pub user_words: Vec<String>,
    pub manual_current_hotkey: Hotkey,
    pub previous_word_hotkey: Hotkey,
    pub undo_hotkey: Hotkey,
    pub pause_hotkey: Hotkey,
}

impl Default for RuntimeSettings {
    fn default() -> Self {
        Self {
            auto_correct: true,
            disabled_apps: Vec::new(),
            manual_only_apps: Vec::new(),
            user_words: Vec::new(),
            manual_current_hotkey: DEFAULT_MANUAL_CURRENT_HOTKEY,
            previous_word_hotkey: DEFAULT_PREVIOUS_WORD_HOTKEY,
            undo_hotkey: DEFAULT_UNDO_HOTKEY,
            pause_hotkey: DEFAULT_PAUSE_HOTKEY,
        }
    }
}

impl RuntimeSettings {
    pub fn app_mode(&self, process_name: &str) -> AppMode {
        let process_name = process_name.trim().to_ascii_lowercase();
        if self
            .disabled_apps
            .iter()
            .any(|entry| entry.eq_ignore_ascii_case(&process_name))
        {
            AppMode::Disabled
        } else if self
            .manual_only_apps
            .iter()
            .any(|entry| entry.eq_ignore_ascii_case(&process_name))
        {
            AppMode::ManualOnly
        } else {
            AppMode::Auto
        }
    }

    pub fn disabled_apps_text(&self) -> String {
        self.disabled_apps.join("\r\n")
    }

    pub fn manual_only_apps_text(&self) -> String {
        self.manual_only_apps.join("\r\n")
    }

    pub fn user_words_text(&self) -> String {
        self.user_words.join("\r\n")
    }
}

pub fn runtime_settings() -> RuntimeSettings {
    runtime_settings_lock().read().clone()
}

#[cfg(test)]
pub fn replace_runtime_settings_for_test(value: RuntimeSettings) -> RuntimeSettings {
    let mut guard = runtime_settings_lock().write();
    std::mem::replace(&mut *guard, normalize_runtime_settings(value))
}

pub fn paused() -> bool {
    PAUSED.load(Ordering::SeqCst)
}

pub fn set_paused(value: bool) {
    PAUSED.store(value, Ordering::SeqCst);
}

pub fn toggle_paused() -> bool {
    let next = !paused();
    set_paused(next);
    next
}

pub fn save_runtime_settings(value: RuntimeSettings) -> Result<()> {
    let value = normalize_runtime_settings(value);
    write_dword(
        SETTINGS_KEY,
        AUTO_CORRECT_VALUE,
        u32::from(value.auto_correct),
    )?;
    write_string(
        SETTINGS_KEY,
        DISABLED_APPS_VALUE,
        &value.disabled_apps.join("\n"),
    )?;
    // Keep the 0.7 value synchronized for downgrade compatibility.
    write_string(
        SETTINGS_KEY,
        LEGACY_EXCLUDED_APPS_VALUE,
        &value.disabled_apps.join("\n"),
    )?;
    write_string(
        SETTINGS_KEY,
        MANUAL_ONLY_APPS_VALUE,
        &value.manual_only_apps.join("\n"),
    )?;
    write_string(SETTINGS_KEY, USER_WORDS_VALUE, &value.user_words.join("\n"))?;
    write_string(
        SETTINGS_KEY,
        HOTKEY_MANUAL_CURRENT_VALUE,
        &value.manual_current_hotkey.to_text(),
    )?;
    write_string(
        SETTINGS_KEY,
        HOTKEY_PREVIOUS_WORD_VALUE,
        &value.previous_word_hotkey.to_text(),
    )?;
    write_string(
        SETTINGS_KEY,
        HOTKEY_UNDO_VALUE,
        &value.undo_hotkey.to_text(),
    )?;
    write_string(
        SETTINGS_KEY,
        HOTKEY_PAUSE_VALUE,
        &value.pause_hotkey.to_text(),
    )?;
    *runtime_settings_lock().write() = value;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn settings_from_text(
    auto_correct: bool,
    disabled_apps: &str,
    manual_only_apps: &str,
    user_words: &str,
    manual_current_hotkey: &str,
    previous_word_hotkey: &str,
    undo_hotkey: &str,
    pause_hotkey: &str,
) -> RuntimeSettings {
    normalize_runtime_settings(RuntimeSettings {
        auto_correct,
        disabled_apps: parse_entries(disabled_apps, true),
        manual_only_apps: parse_entries(manual_only_apps, true),
        user_words: parse_entries(user_words, false),
        manual_current_hotkey: parse_hotkey(manual_current_hotkey)
            .unwrap_or(DEFAULT_MANUAL_CURRENT_HOTKEY),
        previous_word_hotkey: parse_hotkey(previous_word_hotkey)
            .unwrap_or(DEFAULT_PREVIOUS_WORD_HOTKEY),
        undo_hotkey: parse_hotkey(undo_hotkey).unwrap_or(DEFAULT_UNDO_HOTKEY),
        pause_hotkey: parse_hotkey(pause_hotkey).unwrap_or(DEFAULT_PAUSE_HOTKEY),
    })
}

pub fn parse_hotkey(value: &str) -> Option<Hotkey> {
    let mut ctrl = false;
    let mut shift = false;
    let mut alt = false;
    let mut key = None;

    for raw in value.split('+') {
        let token = raw.trim();
        if token.is_empty() {
            continue;
        }
        match token.to_ascii_uppercase().as_str() {
            "CTRL" | "CONTROL" => ctrl = true,
            "SHIFT" => shift = true,
            "ALT" => alt = true,
            other => {
                if key.is_some() {
                    return None;
                }
                key = parse_key(other);
                key?;
            }
        }
    }

    let vk = key?;
    if !ctrl && !shift && !alt {
        return None;
    }
    Some(Hotkey::new(ctrl, shift, alt, vk))
}

pub fn first_run_completed() -> bool {
    read_dword(SETTINGS_KEY, FIRST_RUN_VALUE) == Some(1)
}

pub fn mark_first_run_completed() -> Result<()> {
    write_dword(SETTINGS_KEY, FIRST_RUN_VALUE, 1)
}

pub fn autostart_enabled() -> bool {
    value_exists(RUN_KEY, RUN_VALUE)
}

pub fn set_autostart(enabled: bool) -> Result<()> {
    if enabled {
        let executable = std::env::current_exe()?;
        let command = format!("\"{}\"", executable.display());
        write_string(RUN_KEY, RUN_VALUE, &command)
    } else {
        delete_value(RUN_KEY, RUN_VALUE)
    }
}

fn runtime_settings_lock() -> &'static RwLock<RuntimeSettings> {
    RUNTIME_SETTINGS.get_or_init(|| RwLock::new(load_runtime_settings()))
}

fn load_runtime_settings() -> RuntimeSettings {
    let disabled_apps = read_string(SETTINGS_KEY, DISABLED_APPS_VALUE)
        .or_else(|| read_string(SETTINGS_KEY, LEGACY_EXCLUDED_APPS_VALUE))
        .map(|value| parse_entries(&value, true))
        .unwrap_or_default();

    normalize_runtime_settings(RuntimeSettings {
        auto_correct: read_dword(SETTINGS_KEY, AUTO_CORRECT_VALUE).unwrap_or(1) != 0,
        disabled_apps,
        manual_only_apps: read_string(SETTINGS_KEY, MANUAL_ONLY_APPS_VALUE)
            .map(|value| parse_entries(&value, true))
            .unwrap_or_default(),
        user_words: read_string(SETTINGS_KEY, USER_WORDS_VALUE)
            .map(|value| parse_entries(&value, false))
            .unwrap_or_default(),
        manual_current_hotkey: read_hotkey(
            HOTKEY_MANUAL_CURRENT_VALUE,
            DEFAULT_MANUAL_CURRENT_HOTKEY,
        ),
        previous_word_hotkey: read_hotkey(HOTKEY_PREVIOUS_WORD_VALUE, DEFAULT_PREVIOUS_WORD_HOTKEY),
        undo_hotkey: read_hotkey(HOTKEY_UNDO_VALUE, DEFAULT_UNDO_HOTKEY),
        pause_hotkey: read_hotkey(HOTKEY_PAUSE_VALUE, DEFAULT_PAUSE_HOTKEY),
    })
}

fn read_hotkey(name: &str, default: Hotkey) -> Hotkey {
    read_string(SETTINGS_KEY, name)
        .and_then(|value| parse_hotkey(&value))
        .unwrap_or(default)
}

fn normalize_runtime_settings(mut value: RuntimeSettings) -> RuntimeSettings {
    value.disabled_apps = normalize_entries(value.disabled_apps, true);
    value.manual_only_apps = normalize_entries(value.manual_only_apps, true);
    value.manual_only_apps.retain(|entry| {
        !value
            .disabled_apps
            .iter()
            .any(|disabled| disabled.eq_ignore_ascii_case(entry))
    });
    value.user_words = normalize_entries(value.user_words, false);
    value
}

fn normalize_entries(entries: Vec<String>, process_names: bool) -> Vec<String> {
    let mut normalized = Vec::new();
    for entry in entries {
        let trimmed = entry.trim();
        if trimmed.is_empty() {
            continue;
        }
        let item = if process_names {
            trimmed.to_ascii_lowercase()
        } else {
            trimmed.to_owned()
        };
        if !normalized
            .iter()
            .any(|existing: &String| existing.eq_ignore_ascii_case(&item))
        {
            normalized.push(item);
        }
    }
    normalized
}

fn parse_entries(value: &str, process_names: bool) -> Vec<String> {
    let entries = value
        .split(['\r', '\n', ';'])
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(ToOwned::to_owned)
        .collect();
    normalize_entries(entries, process_names)
}

fn parse_key(value: &str) -> Option<u16> {
    if value == "BACKSPACE" || value == "BACK" {
        return Some(VK_BACK_VALUE);
    }
    if value == "SPACE" {
        return Some(VK_SPACE_VALUE);
    }
    if let Some(number) = value.strip_prefix('F') {
        let number: u16 = number.parse().ok()?;
        if (1..=12).contains(&number) {
            return Some(VK_F1_VALUE + number - 1);
        }
    }
    let bytes = value.as_bytes();
    if bytes.len() == 1 && (bytes[0].is_ascii_uppercase() || bytes[0].is_ascii_digit()) {
        return Some(bytes[0] as u16);
    }
    None
}

fn key_name(vk: u16) -> String {
    if vk == VK_BACK_VALUE {
        return "Backspace".to_owned();
    }
    if vk == VK_SPACE_VALUE {
        return "Space".to_owned();
    }
    if (VK_F1_VALUE..=VK_F12_VALUE).contains(&vk) {
        return format!("F{}", vk - VK_F1_VALUE + 1);
    }
    if (b'A' as u16..=b'Z' as u16).contains(&vk) || (b'0' as u16..=b'9' as u16).contains(&vk) {
        return char::from_u32(vk as u32).unwrap_or('?').to_string();
    }
    format!("VK{vk:02X}")
}

fn read_dword(path: &str, name: &str) -> Option<u32> {
    unsafe {
        let mut key: HKEY = null_mut();
        let path = wide(path);
        if RegOpenKeyExW(HKEY_CURRENT_USER, path.as_ptr(), 0, KEY_READ, &mut key) != 0 {
            return None;
        }

        let name = wide(name);
        let mut value_type = 0u32;
        let mut value = 0u32;
        let mut size = size_of::<u32>() as u32;
        let status = RegQueryValueExW(
            key,
            name.as_ptr(),
            null_mut(),
            &mut value_type,
            &mut value as *mut u32 as *mut u8,
            &mut size,
        );
        RegCloseKey(key);
        if status == 0 && value_type == REG_DWORD && size == size_of::<u32>() as u32 {
            Some(value)
        } else {
            None
        }
    }
}

fn read_string(path: &str, name: &str) -> Option<String> {
    unsafe {
        let mut key: HKEY = null_mut();
        let path = wide(path);
        if RegOpenKeyExW(HKEY_CURRENT_USER, path.as_ptr(), 0, KEY_READ, &mut key) != 0 {
            return None;
        }

        let name = wide(name);
        let mut value_type = 0u32;
        let mut size = 0u32;
        let first = RegQueryValueExW(
            key,
            name.as_ptr(),
            null_mut(),
            &mut value_type,
            null_mut(),
            &mut size,
        );
        if first != 0 || value_type != REG_SZ || size < 2 {
            RegCloseKey(key);
            return None;
        }

        let mut buffer = vec![0u16; (size as usize).div_ceil(size_of::<u16>())];
        let second = RegQueryValueExW(
            key,
            name.as_ptr(),
            null_mut(),
            &mut value_type,
            buffer.as_mut_ptr() as *mut u8,
            &mut size,
        );
        RegCloseKey(key);
        if second != 0 || value_type != REG_SZ {
            return None;
        }
        if buffer.last().copied() == Some(0) {
            buffer.pop();
        }
        Some(String::from_utf16_lossy(&buffer))
    }
}

fn value_exists(path: &str, name: &str) -> bool {
    unsafe {
        let mut key: HKEY = null_mut();
        let path = wide(path);
        if RegOpenKeyExW(HKEY_CURRENT_USER, path.as_ptr(), 0, KEY_READ, &mut key) != 0 {
            return false;
        }
        let name = wide(name);
        let status = RegQueryValueExW(
            key,
            name.as_ptr(),
            null_mut(),
            null_mut(),
            null_mut(),
            null_mut(),
        );
        RegCloseKey(key);
        status == 0
    }
}

fn write_dword(path: &str, name: &str, value: u32) -> Result<()> {
    let bytes = value.to_ne_bytes();
    write_value(path, name, REG_DWORD, &bytes)
}

fn write_string(path: &str, name: &str, value: &str) -> Result<()> {
    let value = wide(value);
    let bytes = unsafe {
        std::slice::from_raw_parts(value.as_ptr() as *const u8, value.len() * size_of::<u16>())
    };
    write_value(path, name, REG_SZ, bytes)
}

fn write_value(path: &str, name: &str, value_type: u32, bytes: &[u8]) -> Result<()> {
    unsafe {
        let mut key: HKEY = null_mut();
        let path = wide(path);
        let mut disposition = 0u32;
        let status = RegCreateKeyExW(
            HKEY_CURRENT_USER,
            path.as_ptr(),
            0,
            null_mut(),
            REG_OPTION_NON_VOLATILE,
            KEY_SET_VALUE,
            null(),
            &mut key,
            &mut disposition,
        );
        if status != 0 {
            return Err(anyhow!("RegCreateKeyExW failed with {status}"));
        }

        let name = wide(name);
        let status = RegSetValueExW(
            key,
            name.as_ptr(),
            0,
            value_type,
            bytes.as_ptr(),
            bytes.len() as u32,
        );
        RegCloseKey(key);
        if status != 0 {
            return Err(anyhow!("RegSetValueExW failed with {status}"));
        }
        Ok(())
    }
}

fn delete_value(path: &str, name: &str) -> Result<()> {
    unsafe {
        let mut key: HKEY = null_mut();
        let path = wide(path);
        let status = RegOpenKeyExW(HKEY_CURRENT_USER, path.as_ptr(), 0, KEY_SET_VALUE, &mut key);
        if status != 0 {
            return Ok(());
        }
        let name = wide(name);
        let _ = RegDeleteValueW(key, name.as_ptr());
        RegCloseKey(key);
        Ok(())
    }
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_normalizes_application_modes() {
        let settings = settings_from_text(
            true,
            "Code.EXE\r\npowershell.exe; code.exe",
            "terminal.exe\nCODE.EXE",
            "",
            "Ctrl+Shift+F12",
            "Ctrl+Shift+F10",
            "Ctrl+Backspace",
            "Ctrl+Shift+F11",
        );
        assert_eq!(settings.disabled_apps, ["code.exe", "powershell.exe"]);
        assert_eq!(settings.manual_only_apps, ["terminal.exe"]);
        assert_eq!(settings.app_mode("CODE.EXE"), AppMode::Disabled);
        assert_eq!(settings.app_mode("terminal.EXE"), AppMode::ManualOnly);
        assert_eq!(settings.app_mode("notepad.exe"), AppMode::Auto);
    }

    #[test]
    fn parses_user_dictionary_without_recording_history() {
        let settings = settings_from_text(
            true,
            "",
            "",
            "Пример\nExample\nПример",
            "Ctrl+Shift+F12",
            "Ctrl+Shift+F10",
            "Ctrl+Backspace",
            "Ctrl+Shift+F11",
        );
        assert_eq!(settings.user_words, ["Пример", "Example"]);
    }

    #[test]
    fn parses_and_formats_supported_hotkeys() {
        assert_eq!(
            parse_hotkey("ctrl + shift + f12"),
            Some(DEFAULT_MANUAL_CURRENT_HOTKEY)
        );
        assert_eq!(parse_hotkey("Ctrl+Backspace"), Some(DEFAULT_UNDO_HOTKEY));
        assert_eq!(parse_hotkey("Alt+Q").unwrap().to_text(), "Alt+Q");
        assert_eq!(parse_hotkey("F12"), None);
        assert_eq!(parse_hotkey("Ctrl+NoSuchKey"), None);
    }

    #[test]
    fn pause_is_ephemeral_process_state() {
        set_paused(false);
        assert!(!paused());
        assert!(toggle_paused());
        assert!(paused());
        set_paused(false);
    }
}
