use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetClassNameW, GetParent, GetWindowLongPtrW, SendMessageW, GWL_STYLE,
};

const ES_PASSWORD_VALUE: isize = 0x0020;
const EM_GETPASSWORDCHAR_VALUE: u32 = 0x00D2;
const MAX_PARENT_DEPTH: usize = 4;

pub fn is_secure_input(hwnd: HWND, process_name: &str) -> bool {
    if is_secure_process(process_name) {
        return true;
    }

    let mut current = hwnd;
    for _ in 0..MAX_PARENT_DEPTH {
        if current.is_null() {
            break;
        }
        if has_password_style(current)
            || has_password_character(current)
            || class_name(current).is_some_and(|name| is_secure_class_name(&name))
        {
            return true;
        }
        current = unsafe { GetParent(current) };
    }
    false
}

fn has_password_style(hwnd: HWND) -> bool {
    unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) & ES_PASSWORD_VALUE != 0 }
}

fn has_password_character(hwnd: HWND) -> bool {
    unsafe { SendMessageW(hwnd, EM_GETPASSWORDCHAR_VALUE, 0, 0) != 0 }
}

fn class_name(hwnd: HWND) -> Option<String> {
    let mut buffer = [0u16; 256];
    let length = unsafe { GetClassNameW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32) };
    if length <= 0 {
        return None;
    }
    Some(String::from_utf16_lossy(&buffer[..length as usize]).to_ascii_lowercase())
}

fn is_secure_process(process_name: &str) -> bool {
    matches!(
        process_name.trim().to_ascii_lowercase().as_str(),
        "credentialuibroker.exe" | "logonui.exe" | "consent.exe"
    )
}

fn is_secure_class_name(class_name: &str) -> bool {
    let normalized = class_name.trim().to_ascii_lowercase();
    normalized.contains("passwordbox")
        || normalized.contains("secureedit")
        || normalized.contains("credential")
        || normalized.contains("pinbox")
        || normalized.contains("otpbox")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_known_secure_class_families() {
        for class in [
            "PasswordBox",
            "Windows.PasswordBox",
            "SecureEdit",
            "CredentialField",
            "PinBox",
            "OtpBox",
        ] {
            assert!(is_secure_class_name(class), "missed {class}");
        }
        assert!(!is_secure_class_name("RichEditD2DPT"));
        assert!(!is_secure_class_name("Edit"));
    }

    #[test]
    fn recognizes_windows_credential_processes_only() {
        assert!(is_secure_process("CredentialUIBroker.exe"));
        assert!(is_secure_process("logonui.exe"));
        assert!(is_secure_process("CONSENT.EXE"));
        assert!(!is_secure_process("notepad.exe"));
    }
}
