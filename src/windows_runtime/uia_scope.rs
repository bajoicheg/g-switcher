//! Metadata-only scoped lookup for every generic text adapter. No global UIA
//! focus lookup may select an unrelated Word provider after a Chrome precheck.
use windows::Win32::System::Variant::VARIANT;
use windows::Win32::UI::Accessibility::{
    IUIAutomation, IUIAutomationElement, TreeScope_Descendants, UIA_HasKeyboardFocusPropertyId,
};
use windows_sys::Win32::Foundation::HWND;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, GetGUIThreadInfo, GetWindowThreadProcessId, GUITHREADINFO,
};
type Handle = *mut core::ffi::c_void;
#[repr(C)]
struct FileTime {
    low: u32,
    high: u32,
}
#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
    fn CloseHandle(handle: Handle) -> i32;
    fn WaitForSingleObject(handle: Handle, timeout: u32) -> u32;
    fn GetProcessTimes(
        handle: Handle,
        birth: *mut FileTime,
        exit: *mut FileTime,
        kernel: *mut FileTime,
        user: *mut FileTime,
    ) -> i32;
}
pub(crate) struct Target {
    handle: Handle,
    hwnd: HWND,
    pid: u32,
    birth: u64,
}
// Process handles support cross-thread identity queries; no interface crosses.
unsafe impl Send for Target {}
unsafe impl Sync for Target {}
impl Drop for Target {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.handle);
        }
    }
}
impl Target {
    pub(crate) fn capture(hwnd: HWND, pid: u32) -> Option<Self> {
        preflight(hwnd, pid)?;
        let handle = unsafe { OpenProcess(0x0010_1000, 0, pid) };
        if handle.is_null() {
            return None;
        }
        let mut target = Self {
            handle,
            hwnd,
            pid,
            birth: 0,
        };
        target.birth = target.current_birth()?;
        target.valid().then_some(target)
    }
    fn current_birth(&self) -> Option<u64> {
        let mut birth = FileTime { low: 0, high: 0 };
        let mut exit = FileTime { low: 0, high: 0 };
        let mut kernel = FileTime { low: 0, high: 0 };
        let mut user = FileTime { low: 0, high: 0 };
        if unsafe { GetProcessTimes(self.handle, &mut birth, &mut exit, &mut kernel, &mut user) }
            == 0
        {
            return None;
        }
        let birth = (u64::from(birth.high) << 32) | u64::from(birth.low);
        (birth != 0).then_some(birth)
    }
    fn retained_identity_valid(&self) -> bool {
        (unsafe { WaitForSingleObject(self.handle, 0) == 258 })
            && self.current_birth() == Some(self.birth)
    }
    pub(crate) fn valid(&self) -> bool {
        self.retained_identity_valid() && preflight(self.hwnd, self.pid).is_some()
    }
}

pub(super) fn preflight(hwnd: HWND, pid: u32) -> Option<()> {
    if hwnd.is_null() || pid == 0 || super::word_admission::classify_word(hwnd as isize)? {
        return None;
    }
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            return None;
        }
        let thread = GetWindowThreadProcessId(foreground, std::ptr::null_mut());
        if thread == 0 {
            return None;
        }
        let mut info: GUITHREADINFO = std::mem::zeroed();
        info.cbSize = std::mem::size_of::<GUITHREADINFO>() as u32;
        if GetGUIThreadInfo(thread, &mut info) == 0 || info.hwndFocus != hwnd {
            return None;
        }
        let mut actual = 0;
        if GetWindowThreadProcessId(hwnd, &mut actual) == 0 || actual != pid {
            return None;
        }
    }
    Some(())
}
pub(super) fn focused_element(
    automation: &IUIAutomation,
    hwnd: HWND,
    pid: u32,
    identity: &Target,
) -> Option<IUIAutomationElement> {
    if !identity.valid() {
        return None;
    }
    let root = unsafe {
        automation
            .ElementFromHandle(windows::Win32::Foundation::HWND(hwnd))
            .ok()?
    };
    if unsafe { root.CurrentProcessId().ok()? } as u32 != pid {
        return None;
    }
    // Chromium can expose native-root focus together with a virtual field's
    // focus. Prefer the unique focused descendant; ambiguity/errors refuse.
    let condition = unsafe {
        automation
            .CreatePropertyCondition(UIA_HasKeyboardFocusPropertyId, &VARIANT::from(true))
            .ok()?
    };
    if !identity.valid() {
        return None;
    }
    let focused = unsafe { root.FindAll(TreeScope_Descendants, &condition).ok()? };
    if !identity.valid() {
        return None;
    }
    let count = unsafe { focused.Length().ok()? };
    if !identity.valid() {
        return None;
    }
    let element = match count {
        1 => unsafe { focused.GetElement(0).ok()? },
        0 if unsafe { root.CurrentHasKeyboardFocus().ok()? }.as_bool() => root,
        _ => return None,
    };
    if unsafe { element.CurrentProcessId().ok()? } as u32 != pid
        || unsafe { element.CurrentIsPassword().ok()? }.as_bool()
        || !unsafe { element.CurrentHasKeyboardFocus().ok()? }.as_bool()
    {
        return None;
    }
    if !identity.valid() {
        return None;
    }
    Some(element)
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::SetFocus;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DestroyWindow, SetForegroundWindow, WS_OVERLAPPEDWINDOW, WS_VISIBLE,
    };
    struct Window(HWND);
    impl Drop for Window {
        fn drop(&mut self) {
            unsafe {
                DestroyWindow(self.0);
            }
        }
    }
    fn edit() -> Window {
        let class = "EDIT".encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        let title = [0u16];
        let hwnd = unsafe {
            CreateWindowExW(
                0,
                class.as_ptr(),
                title.as_ptr(),
                WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                10,
                10,
                300,
                100,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null(),
            )
        };
        assert!(!hwnd.is_null());
        Window(hwnd)
    }
    struct Process(std::process::Child);
    impl Drop for Process {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    #[test]
    #[ignore = "explicit no-provider subprocess identity fixture"]
    fn fixture_process_holder() {
        if std::env::var("GSWITCHER_FIXTURE_ROLE").as_deref() != Ok("target-identity") {
            return;
        }
        use std::io::Read;
        let mut byte = [0u8; 1];
        let _ = std::io::stdin().read(&mut byte);
    }
    #[test]
    fn actual_retained_process_exit_and_foreign_birth_revoke_identity() {
        let path =
            module_path!().split_once("::").unwrap().1.to_string() + "::fixture_process_holder";
        let mut child = Process(
            std::process::Command::new(std::env::current_exe().unwrap())
                .args(["--exact", &path, "--ignored", "--nocapture"])
                .env("GSWITCHER_FIXTURE_ROLE", "target-identity")
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::null())
                .spawn()
                .unwrap(),
        );
        let pid = child.0.id();
        let handle = unsafe { OpenProcess(0x0010_1000, 0, pid) };
        assert!(!handle.is_null());
        // Exercise actual kernel identity predicate without a Word/provider authority.
        let mut identity = Target {
            handle,
            hwnd: std::ptr::null_mut(),
            pid,
            birth: 0,
        };
        identity.birth = identity.current_birth().unwrap();
        assert!(identity.retained_identity_valid());
        let actual = identity.birth;
        identity.birth = actual + 1;
        assert!(!identity.retained_identity_valid());
        identity.birth = actual;
        child.0.kill().unwrap();
        child.0.wait().unwrap();
        assert!(
            !identity.retained_identity_valid(),
            "retained old process handle must stay revoked even if PID is later reused"
        );
    }
    #[test]
    fn actual_same_process_focus_change_refuses_captured_other_hwnd() {
        let first = edit();
        let second = edit();
        assert_ne!(first.0, second.0);
        let pid = std::process::id();
        unsafe {
            SetForegroundWindow(second.0);
            SetFocus(second.0);
        }
        let retained =
            Target::capture(second.0, pid).expect("capture actual live process identity");
        assert!(retained.valid());
        assert!(
            preflight(second.0, pid).is_some(),
            "fixture must actually focus the second same-process Edit"
        );
        assert!(
            preflight(first.0, pid).is_none(),
            "same PID is insufficient for captured-HWND security authority"
        );
        unsafe {
            SetForegroundWindow(first.0);
            SetFocus(first.0);
        }
        assert!(
            !retained.valid(),
            "retained live PID alone cannot authorize changed HWND focus"
        );
        assert!(preflight(first.0, pid).is_some());
        assert!(preflight(second.0, pid).is_none());
    }
}
