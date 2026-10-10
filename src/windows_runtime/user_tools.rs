//! Explicit local file actions. Never exports typing, documents, paths or raw logs.
use std::io::Read;
use std::mem::{size_of, zeroed};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Result};
use windows_sys::Win32::Foundation::{CloseHandle, FILETIME, HWND};
use windows_sys::Win32::System::Threading::{
    GetProcessTimes, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::Controls::Dialogs::{
    CommDlgExtendedError, GetOpenFileNameW, GetSaveFileNameW, OFN_EXPLORER, OFN_FILEMUSTEXIST,
    OFN_NOCHANGEDIR, OFN_OVERWRITEPROMPT, OFN_PATHMUSTEXIST, OPENFILENAMEW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, GetWindowThreadProcessId, MessageBoxW, IDYES, MB_ICONERROR,
    MB_ICONINFORMATION, MB_OK, MB_YESNO,
};

use super::{settings, tray_status};
use crate::user_controls::SettingsBackup;

const MAX_BACKUP_BYTES: u64 = 1_048_576;

#[derive(Clone)]
pub(super) struct AppIdentity {
    pid: u32,
    birth: u64,
    pub(super) name: String,
}
impl AppIdentity {
    pub(super) fn key(&self) -> crate::user_controls::HostKey {
        crate::user_controls::HostKey {
            pid: self.pid,
            birth: self.birth,
        }
    }
}
pub(super) fn process_birth(pid: u32) -> Option<u64> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return None;
        }
        let mut times = [zeroed::<FILETIME>(); 4];
        let ok = GetProcessTimes(
            handle,
            &mut times[0],
            &mut times[1],
            &mut times[2],
            &mut times[3],
        );
        CloseHandle(handle);
        (ok != 0).then_some(
            (u64::from(times[0].dwHighDateTime) << 32) | u64::from(times[0].dwLowDateTime),
        )
    }
}
pub(super) fn foreground_app() -> Option<AppIdentity> {
    let mut pid = 0;
    unsafe {
        GetWindowThreadProcessId(GetForegroundWindow(), &mut pid);
    }
    if pid == 0 || pid == std::process::id() {
        return None;
    }
    let name = super::process_name_for_pid(pid)?;
    // Explorer owns the notification area. Preserve the explicitly labelled app snapshot.
    if name.eq_ignore_ascii_case("explorer.exe") {
        return None;
    }
    Some(AppIdentity {
        pid,
        birth: process_birth(pid)?,
        name,
    })
}
pub(super) fn set_app_mode(app: &AppIdentity, mode: settings::AppMode) -> Result<()> {
    if app.name.contains(';') || app.name.trim() != app.name {
        return Err(anyhow!("Имя приложения несовместимо с форматом настроек."));
    }
    if process_birth(app.pid) != Some(app.birth)
        || super::process_name_for_pid(app.pid).as_deref() != Some(app.name.as_str())
    {
        return Err(anyhow!(
            "Приложение уже закрыто или изменилось. Откройте меню заново."
        ));
    }
    let mut value = settings::runtime_settings();
    crate::user_controls::apply_app_mode(
        &mut value.disabled_apps,
        &mut value.manual_only_apps,
        &app.name,
        mode,
    );
    settings::save_runtime_settings(value)?;
    super::refresh_user_policy();
    Ok(())
}

fn backup(value: &settings::RuntimeSettings) -> SettingsBackup {
    SettingsBackup {
        schema: "g-switcher-settings/v1".into(),
        auto_correct: value.auto_correct,
        sensitivity: value.sensitivity.as_text().into(),
        sound_enabled: value.sound_enabled,
        sound_volume: value.sound_volume,
        disabled_apps: value.disabled_apps.clone(),
        manual_only_apps: value.manual_only_apps.clone(),
        user_words: value.user_words.clone(),
        hotkeys: [
            value.selected_text_hotkey,
            value.manual_current_hotkey,
            value.previous_word_hotkey,
            value.undo_hotkey,
            value.pause_hotkey,
        ]
        .iter()
        .map(|h| h.to_text())
        .collect(),
    }
}
fn restore(value: SettingsBackup) -> Result<settings::RuntimeSettings> {
    value.validate().map_err(|e| anyhow!(e))?;
    let hotkeys = value
        .hotkeys
        .iter()
        .map(|h| settings::parse_hotkey(h).ok_or_else(|| anyhow!("Некорректная горячая клавиша")))
        .collect::<Result<Vec<_>>>()?;
    if settings::first_duplicate_hotkey(&hotkeys).is_some() {
        return Err(anyhow!("Горячие клавиши повторяются"));
    }
    Ok(settings::RuntimeSettings {
        auto_correct: value.auto_correct,
        sensitivity: settings::parse_sensitivity(&value.sensitivity)
            .ok_or_else(|| anyhow!("Некорректный профиль"))?,
        sound_enabled: value.sound_enabled,
        sound_volume: value.sound_volume,
        disabled_apps: value.disabled_apps,
        manual_only_apps: value.manual_only_apps,
        user_words: value.user_words,
        selected_text_hotkey: hotkeys[0],
        manual_current_hotkey: hotkeys[1],
        previous_word_hotkey: hotkeys[2],
        undo_hotkey: hotkeys[3],
        pause_hotkey: hotkeys[4],
    })
}

fn file_dialog(hwnd: HWND, save: bool, name: &str, title: &str) -> Result<Option<PathBuf>> {
    let mut path = vec![0u16; 32768];
    let name = wide(name);
    path[..name.len()].copy_from_slice(&name);
    let title = wide(title);
    let filter = wide("TOML (*.toml)\0*.toml\0\0");
    let ext = wide("toml");
    unsafe {
        let mut dialog: OPENFILENAMEW = zeroed();
        dialog.lStructSize = size_of::<OPENFILENAMEW>() as u32;
        dialog.hwndOwner = hwnd;
        dialog.lpstrFile = path.as_mut_ptr();
        dialog.nMaxFile = path.len() as u32;
        dialog.lpstrTitle = title.as_ptr();
        dialog.lpstrFilter = filter.as_ptr();
        dialog.lpstrDefExt = ext.as_ptr();
        dialog.Flags = OFN_EXPLORER
            | OFN_NOCHANGEDIR
            | OFN_PATHMUSTEXIST
            | if save {
                OFN_OVERWRITEPROMPT
            } else {
                OFN_FILEMUSTEXIST
            };
        let ok = if save {
            GetSaveFileNameW(&mut dialog)
        } else {
            GetOpenFileNameW(&mut dialog)
        };
        if ok == 0 {
            let error = CommDlgExtendedError();
            return if error == 0 {
                Ok(None)
            } else {
                Err(anyhow!("Не удалось открыть выбор файла: {error}"))
            };
        }
    }
    use std::os::windows::ffi::OsStringExt;
    let length = path
        .iter()
        .position(|v| *v == 0)
        .ok_or_else(|| anyhow!("Некорректный путь"))?;
    Ok(Some(PathBuf::from(std::ffi::OsString::from_wide(
        &path[..length],
    ))))
}
fn read_backup(path: &Path) -> Result<settings::RuntimeSettings> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(MAX_BACKUP_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_BACKUP_BYTES {
        return Err(anyhow!("Файл настроек превышает 1 МБ"));
    }
    restore(toml::from_str(std::str::from_utf8(&bytes)?)?)
}

pub(super) fn export_settings(hwnd: HWND) -> Result<()> {
    let Some(path) = file_dialog(
        hwnd,
        true,
        "GSwitcher-Settings.toml",
        "Сохранить настройки и словарь",
    )?
    else {
        return Ok(());
    };
    let value = backup(&settings::runtime_settings());
    value.validate().map_err(|e| anyhow!(e))?;
    std::fs::write(&path, toml::to_string_pretty(&value)?)?;
    info(hwnd, "Настройки и словарь сохранены.");
    Ok(())
}
pub(super) fn import_settings(hwnd: HWND) -> Result<()> {
    let Some(path) = file_dialog(hwnd, false, "", "Выбрать настройки G-switcher")?
    else {
        return Ok(());
    };
    let value = read_backup(&path)?;
    let message = format!("Заменить текущие настройки?\r\nПриложений: {}. Слов в словаре: {}.\r\nАвтозапуск и пауза сохранятся.", value.disabled_apps.len() + value.manual_only_apps.len(), value.user_words.len());
    if unsafe {
        MessageBoxW(
            hwnd,
            wide(&message).as_ptr(),
            wide("Импорт настроек").as_ptr(),
            MB_YESNO | MB_ICONINFORMATION,
        )
    } != IDYES
    {
        return Ok(());
    }
    let previous = settings::runtime_settings();
    if let Err(error) = settings::save_runtime_settings(value) {
        let rollback = settings::save_runtime_settings(previous);
        return Err(anyhow!(
            "Импорт не завершён: {error}. Восстановление прежних настроек: {}",
            if rollback.is_ok() {
                "выполнено"
            } else {
                "не удалось"
            }
        ));
    }
    super::refresh_user_policy();
    info(hwnd, "Настройки применены.");
    Ok(())
}
pub(super) fn export_diagnostics(hwnd: HWND) -> Result<()> {
    let Some(path) = file_dialog(
        hwnd,
        true,
        "GSwitcher-Diagnostics.toml",
        "Сохранить техническую диагностику",
    )?
    else {
        return Ok(());
    };
    let settings = settings::runtime_settings();
    std::fs::write(&path, diagnostics_text(&settings))?;
    info(
        hwnd,
        "Диагностика сохранена без введённого текста и содержимого документов.",
    );
    Ok(())
}
fn diagnostics_text(settings: &settings::RuntimeSettings) -> String {
    format!("{}auto_correct = {}\nsensitivity = \"{}\"\nsound_enabled = {}\nsound_volume = {}\ndisabled_app_count = {}\nmanual_app_count = {}\ndictionary_word_count = {}\n", tray_status::diagnostic_text(), settings.auto_correct, settings.sensitivity.as_text(), settings.sound_enabled, settings.sound_volume, settings.disabled_apps.len(), settings.manual_only_apps.len(), settings.user_words.len())
}
pub(super) fn report_error(hwnd: HWND, result: Result<()>) {
    if let Err(error) = result {
        unsafe {
            MessageBoxW(
                hwnd,
                wide(&format!("{error}")).as_ptr(),
                wide("G-switcher").as_ptr(),
                MB_OK | MB_ICONERROR,
            );
        }
    }
}
fn info(hwnd: HWND, message: &str) {
    unsafe {
        MessageBoxW(
            hwnd,
            wide(message).as_ptr(),
            wide("G-switcher").as_ptr(),
            MB_OK | MB_ICONINFORMATION,
        );
    }
}
fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_settings_roundtrip_includes_all_hotkeys_and_dictionary() {
        let value = settings::RuntimeSettings {
            user_words: vec!["Градиент".into()],
            manual_only_apps: vec!["winword.exe".into()],
            ..Default::default()
        };
        assert_eq!(restore(backup(&value)).unwrap(), value);
    }
    #[test]
    fn import_rejects_semantically_duplicate_or_invalid_hotkeys() {
        let mut value = backup(&settings::RuntimeSettings::default());
        value.hotkeys[1] = "shift+ctrl+f9".into();
        assert!(restore(value).is_err());
        let mut value = backup(&settings::RuntimeSettings::default());
        value.hotkeys[0] = "garbage".into();
        assert!(restore(value).is_err());
    }
    #[test]
    fn diagnostics_exclude_dictionary_and_application_names() {
        let value = settings::RuntimeSettings {
            user_words: vec!["private-sentinel-word".into()],
            disabled_apps: vec!["private-sentinel-app.exe".into()],
            ..Default::default()
        };
        let text = diagnostics_text(&value);
        let parsed: toml::Value = toml::from_str(&text).unwrap();
        assert_eq!(parsed["dictionary_word_count"].as_integer(), Some(1));
        assert_eq!(parsed["disabled_app_count"].as_integer(), Some(1));
        assert!(!text.contains("private-sentinel"));
        assert!(parsed.get("user_words").is_none());
        assert!(parsed.get("disabled_apps").is_none());
        assert!(parsed.get("input").is_none());
    }
    #[test]
    fn replaced_process_snapshot_is_refused_before_settings_writes() {
        let pid = std::process::id();
        let app = AppIdentity {
            pid,
            birth: process_birth(pid).unwrap().wrapping_add(1),
            name: super::super::process_name_for_pid(pid).unwrap(),
        };
        assert!(set_app_mode(&app, settings::AppMode::Disabled).is_err());
    }
}
