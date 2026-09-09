#![cfg(windows)]

use std::fs;
use std::mem::{size_of, zeroed};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::ptr::null_mut;
use std::thread;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{BOOL, HWND, LPARAM};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_CONTROL, VK_TAB,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetForegroundWindow, GetGUIThreadInfo, GetWindowTextLengthW, GetWindowTextW,
    GetWindowThreadProcessId, IsWindowVisible, SetForegroundWindow, ShowWindow, GUITHREADINFO,
    SW_RESTORE,
};

#[path = "../src/windows_runtime/selection.rs"]
mod selection;
#[path = "../src/windows_runtime/uia_secure.rs"]
mod uia_secure;

const VK_A_VALUE: u16 = b'A' as u16;
const TEST_INPUT_EXTRA_INFO: usize = 0x4753_4252_4f57_5345;

#[derive(Clone)]
struct BrowserSpec {
    label: &'static str,
    executable: PathBuf,
}

struct BrowserGuard {
    child: Child,
    profile_dir: PathBuf,
}

impl Drop for BrowserGuard {
    fn drop(&mut self) {
        let pid = self.child.id().to_string();
        let _ = Command::new("taskkill.exe")
            .args(["/PID", &pid, "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        let _ = self.child.wait();
        let _ = fs::remove_dir_all(&self.profile_dir);
    }
}

#[derive(Default)]
struct WindowSearch {
    marker: String,
    hwnd: HWND,
}

#[test]
#[ignore = "real Edge/Chrome UIA adapter release gate"]
fn real_edge_and_chrome_uia_adapter_release_gate() {
    for browser in required_browsers() {
        eprintln!("G-switcher browser UIA E2E: {}", browser.label);
        exercise_browser(&browser);
    }
}

fn required_browsers() -> Vec<BrowserSpec> {
    vec![
        BrowserSpec {
            label: "Microsoft Edge",
            executable: find_browser(
                "msedge.exe",
                &[
                    ("PROGRAMFILES(X86)", "Microsoft\\Edge\\Application\\msedge.exe"),
                    ("PROGRAMFILES", "Microsoft\\Edge\\Application\\msedge.exe"),
                    ("LOCALAPPDATA", "Microsoft\\Edge\\Application\\msedge.exe"),
                ],
            ),
        },
        BrowserSpec {
            label: "Google Chrome",
            executable: find_browser(
                "chrome.exe",
                &[
                    ("PROGRAMFILES", "Google\\Chrome\\Application\\chrome.exe"),
                    ("PROGRAMFILES(X86)", "Google\\Chrome\\Application\\chrome.exe"),
                    ("LOCALAPPDATA", "Google\\Chrome\\Application\\chrome.exe"),
                ],
            ),
        },
    ]
}

fn find_browser(executable_name: &str, candidates: &[(&str, &str)]) -> PathBuf {
    for (environment, suffix) in candidates {
        if let Some(root) = std::env::var_os(environment) {
            let candidate = PathBuf::from(root).join(suffix);
            if candidate.is_file() {
                return candidate;
            }
        }
    }

    if let Ok(output) = Command::new("where.exe").arg(executable_name).output() {
        if output.status.success() {
            if let Some(path) = String::from_utf8_lossy(&output.stdout)
                .lines()
                .map(str::trim)
                .find(|line| !line.is_empty())
            {
                let candidate = PathBuf::from(path);
                if candidate.is_file() {
                    return candidate;
                }
            }
        }
    }

    panic!("required browser executable not found: {executable_name}");
}

fn exercise_browser(browser: &BrowserSpec) {
    let root = std::env::temp_dir().join(format!(
        "g-switcher-browser-uia-{}-{}",
        std::process::id(),
        browser.label.replace(' ', "-")
    ));
    let profile = root.join("profile");
    fs::create_dir_all(&profile).expect("failed to create isolated browser profile");
    let marker = format!("G-switcher UIA E2E - {}", browser.label);
    let html = root.join("browser-uia-e2e.html");
    write_test_page(&html, &marker);
    let url = file_url(&html);

    let child = Command::new(&browser.executable)
        .arg(format!("--user-data-dir={}", profile.display()))
        .args([
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-popup-blocking",
        ])
        .arg(format!("--app={url}"))
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap_or_else(|error| panic!("failed to start {}: {error}", browser.label));
    let _guard = BrowserGuard {
        child,
        profile_dir: root,
    };

    let top = wait_for_window(&marker, Duration::from_secs(20));
    unsafe {
        ShowWindow(top, SW_RESTORE);
        SetForegroundWindow(top);
    }

    let ordinary_hwnd = wait_for_editable_focus(Duration::from_secs(15));
    let mut ordinary_pid = 0u32;
    assert_ne!(
        unsafe { GetWindowThreadProcessId(ordinary_hwnd, &mut ordinary_pid) },
        0,
        "failed to resolve browser focused thread"
    );
    let ordinary_probe = uia_secure::probe_focused(ordinary_pid)
        .unwrap_or_else(|| panic!("{} ordinary UIA security probe failed", browser.label));
    assert!(
        !ordinary_probe.is_password,
        "{} ordinary text field was classified as password",
        browser.label
    );

    wait_for_adapter_text(ordinary_hwnd, "ghbdtn ", Duration::from_secs(10));
    let snapshot = selection::snapshot_caret(ordinary_hwnd)
        .unwrap_or_else(|| panic!("{} caret snapshot unavailable", browser.label));
    assert_eq!(snapshot.caret, 7, "{} initial caret mismatch", browser.label);
    assert_eq!(snapshot.text_before_caret, "ghbdtn ");

    assert!(
        selection::replace_suffix_at_caret(ordinary_hwnd, "ghbdtn ", "привет "),
        "{} automatic-style verified suffix replacement failed",
        browser.label
    );
    wait_for_adapter_text(ordinary_hwnd, "привет ", Duration::from_secs(5));
    assert!(
        selection::replace_suffix_at_caret(ordinary_hwnd, "привет ", "ghbdtn "),
        "{} verified Undo replacement failed",
        browser.label
    );
    wait_for_adapter_text(ordinary_hwnd, "ghbdtn ", Duration::from_secs(5));

    assert!(
        selection::replace_range_if_matches(
            ordinary_hwnd,
            0,
            7,
            "ghbdtn ",
            "ghbdtn rfr ltkf"
        ),
        "{} failed to seed selection scenario through verified UIA mutation",
        browser.label
    );
    wait_for_adapter_text(
        ordinary_hwnd,
        "ghbdtn rfr ltkf",
        Duration::from_secs(5),
    );
    send_ctrl_a();
    let selected = wait_for_selection(ordinary_hwnd, Duration::from_secs(5));
    assert_eq!(selected.text, "ghbdtn rfr ltkf");
    assert!(
        selection::replace_range_if_matches(
            ordinary_hwnd,
            selected.start,
            selected.end,
            &selected.text,
            "привет как дела"
        ),
        "{} selected-text conversion failed",
        browser.label
    );
    wait_for_adapter_text(ordinary_hwnd, "привет как дела", Duration::from_secs(5));
    assert!(
        selection::replace_suffix_at_caret(ordinary_hwnd, "привет как дела", "ghbdtn rfr ltkf"),
        "{} selected-text Undo failed",
        browser.label
    );
    wait_for_adapter_text(
        ordinary_hwnd,
        "ghbdtn rfr ltkf",
        Duration::from_secs(5),
    );

    send_key(VK_TAB);
    let (password_hwnd, password_probe) = wait_for_password_focus(Duration::from_secs(8));
    assert_ne!(
        ordinary_probe.element_id, password_probe.element_id,
        "{} UIA RuntimeId did not distinguish ordinary and password DOM fields",
        browser.label
    );
    assert!(password_probe.is_password);
    assert!(
        !selection::is_standard_edit(password_hwnd),
        "{} password field unexpectedly exposed a writable G-switcher adapter",
        browser.label
    );

    eprintln!(
        "G-switcher browser UIA E2E: {} PASS (verified mutation, selection, Undo, password guard)",
        browser.label
    );
}

fn write_test_page(path: &Path, marker: &str) {
    let document = format!(
        r#"<!doctype html>
<meta charset="utf-8">
<title>{marker}</title>
<style>
body {{ font-family: sans-serif; padding: 40px; }}
input {{ display:block; width:700px; font-size:24px; margin:20px 0; }}
</style>
<label>ordinary<input id="ordinary" type="text" value="ghbdtn " autofocus></label>
<label>password<input id="password" type="password" value=""></label>
<script>
addEventListener('load', () => {{
  const input = document.getElementById('ordinary');
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}});
</script>
"#
    );
    fs::write(path, document).expect("failed to write browser UIA test page");
}

fn file_url(path: &Path) -> String {
    format!("file:///{}", path.to_string_lossy().replace('\\', "/"))
}

fn wait_for_window(marker: &str, timeout: Duration) -> HWND {
    wait_until(timeout, || {
        let hwnd = find_window(marker);
        (!hwnd.is_null()).then_some(hwnd)
    })
    .unwrap_or_else(|| panic!("browser window did not appear: {marker}"))
}

fn find_window(marker: &str) -> HWND {
    let mut state = WindowSearch {
        marker: marker.to_owned(),
        hwnd: null_mut(),
    };
    unsafe {
        EnumWindows(
            Some(enum_window_for_marker),
            &mut state as *mut WindowSearch as LPARAM,
        );
    }
    state.hwnd
}

unsafe extern "system" fn enum_window_for_marker(hwnd: HWND, lparam: LPARAM) -> BOOL {
    if IsWindowVisible(hwnd) == 0 {
        return 1;
    }
    let state = &mut *(lparam as *mut WindowSearch);
    if window_text(hwnd).contains(&state.marker) {
        state.hwnd = hwnd;
        return 0;
    }
    1
}

unsafe fn window_text(hwnd: HWND) -> String {
    let length = GetWindowTextLengthW(hwnd);
    if length <= 0 {
        return String::new();
    }
    let mut buffer = vec![0u16; length as usize + 1];
    let copied = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
    if copied <= 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buffer[..copied as usize])
}

fn focused_hwnd() -> HWND {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            return null_mut();
        }
        let thread_id = GetWindowThreadProcessId(foreground, null_mut());
        if thread_id == 0 {
            return foreground;
        }
        let mut info: GUITHREADINFO = zeroed();
        info.cbSize = size_of::<GUITHREADINFO>() as u32;
        if GetGUIThreadInfo(thread_id, &mut info) != 0 && !info.hwndFocus.is_null() {
            info.hwndFocus
        } else {
            foreground
        }
    }
}

fn wait_for_editable_focus(timeout: Duration) -> HWND {
    wait_until(timeout, || {
        let hwnd = focused_hwnd();
        if hwnd.is_null() || !selection::is_standard_edit(hwnd) {
            return None;
        }
        (adapter_text(hwnd).as_deref() == Some("ghbdtn ")).then_some(hwnd)
    })
    .expect("browser ordinary editable field did not expose TextPattern + writable ValuePattern")
}

fn wait_for_password_focus(timeout: Duration) -> (HWND, uia_secure::UiaSecurityProbe) {
    wait_until(timeout, || {
        let hwnd = focused_hwnd();
        if hwnd.is_null() {
            return None;
        }
        let mut process_id = 0u32;
        if unsafe { GetWindowThreadProcessId(hwnd, &mut process_id) } == 0 || process_id == 0 {
            return None;
        }
        let probe = uia_secure::probe_focused(process_id)?;
        probe.is_password.then_some((hwnd, probe))
    })
    .expect("browser password field did not expose UIA IsPassword=true")
}

fn adapter_text(hwnd: HWND) -> Option<String> {
    selection::read_control_text(hwnd).map(|wide| String::from_utf16_lossy(&wide))
}

fn wait_for_adapter_text(hwnd: HWND, expected: &str, timeout: Duration) {
    let actual = wait_until(timeout, || {
        let value = adapter_text(hwnd)?;
        (value == expected).then_some(value)
    });
    assert_eq!(actual.as_deref(), Some(expected));
}

fn wait_for_selection(hwnd: HWND, timeout: Duration) -> selection::SelectedText {
    wait_until(timeout, || selection::read_selected_text(hwnd))
        .expect("browser selection was not exposed through UIA TextPattern")
}

fn send_ctrl_a() {
    send_inputs(&[
        key_input(VK_CONTROL, 0),
        key_input(VK_A_VALUE, 0),
        key_input(VK_A_VALUE, KEYEVENTF_KEYUP),
        key_input(VK_CONTROL, KEYEVENTF_KEYUP),
    ]);
}

fn send_key(vk: u16) {
    send_inputs(&[key_input(vk, 0), key_input(vk, KEYEVENTF_KEYUP)]);
}

fn key_input(vk: u16, flags: u32) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: TEST_INPUT_EXTRA_INFO,
            },
        },
    }
}

fn send_inputs(inputs: &[INPUT]) {
    let sent = unsafe {
        SendInput(
            inputs.len() as u32,
            inputs.as_ptr(),
            size_of::<INPUT>() as i32,
        )
    };
    assert_eq!(sent as usize, inputs.len(), "SendInput did not deliver browser test chord");
    thread::sleep(Duration::from_millis(80));
}

fn wait_until<T>(timeout: Duration, mut probe: impl FnMut() -> Option<T>) -> Option<T> {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(value) = probe() {
            return Some(value);
        }
        if Instant::now() >= deadline {
            return None;
        }
        thread::sleep(Duration::from_millis(25));
    }
}
