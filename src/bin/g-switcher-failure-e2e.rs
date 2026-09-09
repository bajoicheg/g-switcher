#![cfg_attr(not(windows), allow(dead_code, unused_imports))]

#[cfg(windows)]
use std::io::{BufRead, BufReader};
#[cfg(windows)]
use std::process::{Child, Command, Stdio};
#[cfg(windows)]
use std::thread;
#[cfg(windows)]
use std::time::{Duration, Instant};

#[cfg(windows)]
use windows_sys::Win32::Foundation::{CloseHandle, HWND, LPARAM, LRESULT, WPARAM};
#[cfg(windows)]
use windows_sys::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};
#[cfg(windows)]
use windows_sys::Win32::UI::WindowsAndMessaging::{
    PostMessageW, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_APP, WM_CLOSE, WM_GETTEXT,
    WM_GETTEXTLENGTH, WM_NULL, WM_SETTEXT,
};

#[cfg(windows)]
#[allow(dead_code)]
#[path = "../windows_runtime/selection.rs"]
mod selection;

#[cfg(windows)]
const WM_TEST_BLOCK_UI: u32 = WM_APP + 0x52;
#[cfg(windows)]
const EM_SETSEL_VALUE: u32 = 0x00B1;
#[cfg(windows)]
const HARNESS_TIMEOUT_MS: u32 = 50;

#[cfg(windows)]
struct CrossProcessHelper {
    child: Child,
    window: HWND,
    edit: HWND,
    process_id: u32,
}

#[cfg(windows)]
impl CrossProcessHelper {
    fn spawn() -> Self {
        let executable = std::env::var("G_SWITCHER_E2E_HELPER")
            .expect("G_SWITCHER_E2E_HELPER must point to g-switcher-e2e-helper.exe");
        let mut child = Command::new(executable)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("failed to start failure-E2E helper");
        let stdout = child.stdout.take().expect("helper stdout was not piped");
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .expect("failed to read helper banner");
        let fields = line.split_whitespace().collect::<Vec<_>>();
        assert_eq!(
            fields.first().copied(),
            Some("GSE2E"),
            "bad banner: {line:?}"
        );
        assert_eq!(fields.len(), 6, "bad helper banner: {line:?}");
        let parse = |value: &str| value.parse::<usize>().expect("invalid helper handle");
        Self {
            child,
            window: parse(fields[1]) as HWND,
            edit: parse(fields[2]) as HWND,
            process_id: fields[5].parse().expect("invalid helper pid"),
        }
    }

    fn wait_for_exit(&mut self, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        loop {
            if self.child.try_wait().ok().flatten().is_some() {
                return true;
            }
            if Instant::now() >= deadline {
                return false;
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
}

#[cfg(windows)]
impl Drop for CrossProcessHelper {
    fn drop(&mut self) {
        unsafe {
            PostMessageW(self.window, WM_CLOSE, 0, 0);
        }
        if !self.wait_for_exit(Duration::from_secs(2)) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

#[cfg(windows)]
fn main() {
    eprintln!("G-switcher failure E2E: hung target must fail open");
    let mut hung = CrossProcessHelper::spawn();
    set_text(hung.edit, "ghbdtn");
    select_all(hung.edit);
    block_ui(hung.window, 900);
    assert_unresponsive(hung.window);

    let started = Instant::now();
    let changed = selection::replace_range_if_matches(hung.edit, 0, 6, "ghbdtn", "привет");
    let elapsed = started.elapsed();
    assert!(!changed, "hung target unexpectedly accepted a mutation");
    assert!(
        elapsed < Duration::from_millis(350),
        "hung-target mutation did not fail within the bounded timeout: {elapsed:?}"
    );

    wait_until(Duration::from_secs(2), || {
        harness_send(hung.window, WM_NULL, 0, 0).is_some()
    });
    assert_eq!(
        read_text(hung.edit),
        "ghbdtn",
        "hung-target failure changed text after the target recovered"
    );
    drop(hung);

    eprintln!("G-switcher failure E2E: target exit during operation must fail open");
    let mut doomed = CrossProcessHelper::spawn();
    set_text(doomed.edit, "ghbdtn");
    select_all(doomed.edit);
    block_ui(doomed.window, 5_000);
    assert_unresponsive(doomed.window);

    let doomed_pid = doomed.process_id;
    let killer = thread::spawn(move || {
        thread::sleep(Duration::from_millis(25));
        terminate_process(doomed_pid);
    });
    let started = Instant::now();
    let changed = selection::replace_range_if_matches(doomed.edit, 0, 6, "ghbdtn", "привет");
    let elapsed = started.elapsed();
    killer.join().expect("terminator thread panicked");
    assert!(!changed, "closing target unexpectedly accepted a mutation");
    assert!(
        elapsed < Duration::from_millis(350),
        "target-exit mutation did not fail within the bounded timeout: {elapsed:?}"
    );
    assert!(
        doomed.wait_for_exit(Duration::from_secs(2)),
        "terminated helper process did not exit"
    );
    drop(doomed);

    eprintln!("G-switcher failure E2E: adapter remains healthy after failures");
    let fresh = CrossProcessHelper::spawn();
    set_text(fresh.edit, "ghbdtn");
    select_all(fresh.edit);
    assert!(
        selection::replace_range_if_matches(fresh.edit, 0, 6, "ghbdtn", "привет"),
        "fresh target could not be mutated after hung/closed-target failures"
    );
    assert_eq!(read_text(fresh.edit), "привет");
    drop(fresh);

    eprintln!("G-switcher failure E2E: PASS");
}

#[cfg(windows)]
fn block_ui(window: HWND, duration_ms: u32) {
    let posted = unsafe { PostMessageW(window, WM_TEST_BLOCK_UI, duration_ms as usize, 0) };
    assert_ne!(posted, 0, "failed to post controlled UI-thread hang");
    // WM_TEST_BLOCK_UI is a posted message. Give the helper enough time to
    // enter its test-only sleep before probing liveness.
    thread::sleep(Duration::from_millis(100));
}

#[cfg(windows)]
fn assert_unresponsive(window: HWND) {
    assert!(
        harness_send(window, WM_NULL, 0, 0).is_none(),
        "helper UI thread did not enter the controlled hung state"
    );
}

#[cfg(windows)]
fn terminate_process(process_id: u32) {
    unsafe {
        let process = OpenProcess(PROCESS_TERMINATE, 0, process_id);
        assert!(!process.is_null(), "OpenProcess(PROCESS_TERMINATE) failed");
        let terminated = TerminateProcess(process, 0xE201);
        CloseHandle(process);
        assert_ne!(terminated, 0, "TerminateProcess failed");
    }
}

#[cfg(windows)]
fn set_text(hwnd: HWND, value: &str) {
    let wide = wide(value);
    assert!(
        harness_send(hwnd, WM_SETTEXT, 0, wide.as_ptr() as isize).is_some(),
        "WM_SETTEXT failed"
    );
}

#[cfg(windows)]
fn select_all(hwnd: HWND) {
    assert!(
        harness_send(hwnd, EM_SETSEL_VALUE, 0, -1).is_some(),
        "EM_SETSEL failed"
    );
}

#[cfg(windows)]
fn read_text(hwnd: HWND) -> String {
    let length = harness_send(hwnd, WM_GETTEXTLENGTH, 0, 0).expect("WM_GETTEXTLENGTH failed");
    assert!(length >= 0, "negative text length");
    let mut buffer = vec![0u16; length as usize + 1];
    let copied = harness_send(hwnd, WM_GETTEXT, buffer.len(), buffer.as_mut_ptr() as isize)
        .expect("WM_GETTEXT failed");
    assert!(copied >= 0, "negative WM_GETTEXT result");
    buffer.truncate((copied as usize).min(buffer.len()));
    String::from_utf16_lossy(&buffer)
}

#[cfg(windows)]
fn harness_send(hwnd: HWND, message: u32, wparam: WPARAM, lparam: LPARAM) -> Option<LRESULT> {
    let mut result = 0usize;
    let ok = unsafe {
        SendMessageTimeoutW(
            hwnd,
            message,
            wparam,
            lparam,
            SMTO_ABORTIFHUNG | SMTO_BLOCK,
            HARNESS_TIMEOUT_MS,
            &mut result,
        )
    };
    (ok != 0).then_some(result as LRESULT)
}

#[cfg(windows)]
fn wait_until(timeout: Duration, mut predicate: impl FnMut() -> bool) {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if predicate() {
            return;
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert!(predicate(), "condition did not become true before timeout");
}

#[cfg(windows)]
fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(not(windows))]
fn main() {}
