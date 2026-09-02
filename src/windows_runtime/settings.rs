use std::mem::size_of;
use std::ptr::{null, null_mut};

use anyhow::{anyhow, Result};
use windows_sys::Win32::System::Registry::{
    RegCloseKey, RegCreateKeyExW, RegDeleteValueW, RegOpenKeyExW, RegQueryValueExW, RegSetValueExW,
    HKEY, HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_DWORD, REG_OPTION_NON_VOLATILE, REG_SZ,
};

const SETTINGS_KEY: &str = "Software\\GSwitcher";
const FIRST_RUN_VALUE: &str = "FirstRunCompleted";
const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const RUN_VALUE: &str = "G-switcher";

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
