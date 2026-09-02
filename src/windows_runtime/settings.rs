use std::mem::size_of;
use std::ptr::{null, null_mut};
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
const EXCLUDED_APPS_VALUE: &str = "ExcludedApps";
const USER_WORDS_VALUE: &str = "UserDictionary";
const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const RUN_VALUE: &str = "G-switcher";

static RUNTIME_SETTINGS: OnceLock<RwLock<RuntimeSettings>> = OnceLock::new();

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeSettings {
    pub auto_correct: bool,
    pub excluded_apps: Vec<String>,
    pub user_words: Vec<String>,
}

impl Default for RuntimeSettings {
    fn default() -> Self {
        Self {
            auto_correct: true,
            excluded_apps: Vec::new(),
            user_words: Vec::new(),
        }
    }
}

impl RuntimeSettings {
    pub fn is_process_excluded(&self, process_name: &str) -> bool {
        let process_name = process_name.trim().to_ascii_lowercase();
        self.excluded_apps
            .iter()
            .any(|entry| entry.eq_ignore_ascii_case(&process_name))
    }

    pub fn excluded_apps_text(&self) -> String {
        self.excluded_apps.join("\r\n")
    }

    pub fn user_words_text(&self) -> String {
        self.user_words.join("\r\n")
    }
}

pub fn runtime_settings() -> RuntimeSettings {
    runtime_settings_lock().read().clone()
}

pub fn save_runtime_settings(value: RuntimeSettings) -> Result<()> {
    let value = normalize_runtime_settings(value);
    write_dword(SETTINGS_KEY, AUTO_CORRECT_VALUE, u32::from(value.auto_correct))?;
    write_string(
        SETTINGS_KEY,
        EXCLUDED_APPS_VALUE,
        &value.excluded_apps.join("\n"),
    )?;
    write_string(SETTINGS_KEY, USER_WORDS_VALUE, &value.user_words.join("\n"))?;
    *runtime_settings_lock().write() = value;
    Ok(())
}

pub fn settings_from_text(auto_correct: bool, excluded_apps: &str, user_words: &str) -> RuntimeSettings {
    normalize_runtime_settings(RuntimeSettings {
        auto_correct,
        excluded_apps: parse_entries(excluded_apps, true),
        user_words: parse_entries(user_words, false),
    })
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
    normalize_runtime_settings(RuntimeSettings {
        auto_correct: read_dword(SETTINGS_KEY, AUTO_CORRECT_VALUE).unwrap_or(1) != 0,
        excluded_apps: read_string(SETTINGS_KEY, EXCLUDED_APPS_VALUE)
            .map(|value| parse_entries(&value, true))
            .unwrap_or_default(),
        user_words: read_string(SETTINGS_KEY, USER_WORDS_VALUE)
            .map(|value| parse_entries(&value, false))
            .unwrap_or_default(),
    })
}

fn normalize_runtime_settings(mut value: RuntimeSettings) -> RuntimeSettings {
    value.excluded_apps = normalize_entries(value.excluded_apps, true);
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
    fn parses_and_normalizes_exclusions() {
        let settings = settings_from_text(true, "Code.EXE\r\npowershell.exe; code.exe", "");
        assert_eq!(settings.excluded_apps, ["code.exe", "powershell.exe"]);
        assert!(settings.is_process_excluded("CODE.EXE"));
    }

    #[test]
    fn parses_user_dictionary_without_recording_history() {
        let settings = settings_from_text(true, "", "Градиент\nGradient\nГрадиент");
        assert_eq!(settings.user_words, ["Градиент", "Gradient"]);
    }
}
