//! Staged Win32-only identity helper; no COM or UIA. Must be tested on Windows.
//! Returned retained handle pins the queried process incarnation. Fields stay private.
use core::ffi::c_void;
type Handle = *mut c_void;
#[repr(C)]
struct FileTime {
    low: u32,
    high: u32,
}
#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
    fn GetCurrentProcess() -> Handle;
    #[cfg(test)]
    fn GetCurrentProcessId() -> u32;
    fn CloseHandle(handle: Handle) -> i32;
    fn GetProcessTimes(
        handle: Handle,
        created: *mut FileTime,
        exited: *mut FileTime,
        kernel: *mut FileTime,
        user: *mut FileTime,
    ) -> i32;
    fn QueryFullProcessImageNameW(
        handle: Handle,
        flags: u32,
        name: *mut u16,
        size: *mut u32,
    ) -> i32;
    fn WaitForSingleObject(handle: Handle, timeout: u32) -> u32;
}
#[link(name = "user32")]
extern "system" {
    fn GetWindowThreadProcessId(hwnd: Handle, pid: *mut u32) -> u32;
}
pub(super) struct AuthenticatedWord {
    handle: Handle,
    pub(super) pid: u32,
    pub(super) birth: u64,
}
impl Drop for AuthenticatedWord {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.handle);
        }
    }
}
impl AuthenticatedWord {
    pub(super) fn from_window(hwnd: Handle) -> Option<Self> {
        unsafe {
            let mut pid = 0;
            if GetWindowThreadProcessId(hwnd, &mut pid) == 0 || pid == 0 {
                return None;
            }
            let handle = OpenProcess(0x0010_1000, 0, pid); // SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
            if handle.is_null() {
                return None;
            }
            let mut owned = Self {
                handle,
                pid,
                birth: 0,
            };
            let mut created = FileTime { low: 0, high: 0 };
            let mut exited = FileTime { low: 0, high: 0 };
            let mut kernel = FileTime { low: 0, high: 0 };
            let mut user = FileTime { low: 0, high: 0 };
            if GetProcessTimes(handle, &mut created, &mut exited, &mut kernel, &mut user) == 0 {
                return None;
            }
            owned.birth = (u64::from(created.high) << 32) | u64::from(created.low);
            let mut name = vec![0u16; 32768];
            let mut size = name.len() as u32;
            if owned.birth == 0
                || QueryFullProcessImageNameW(handle, 0, name.as_mut_ptr(), &mut size) == 0
            {
                return None;
            }
            let image = String::from_utf16(&name[..size as usize]).ok()?;
            if !image
                .rsplit(['\\', '/'])
                .next()?
                .eq_ignore_ascii_case("winword.exe")
            {
                return None;
            }
            // Revalidate the HWND binding after obtaining the process identity.
            let mut current = 0;
            if GetWindowThreadProcessId(hwnd, &mut current) == 0 || current != pid || !owned.alive()
            {
                return None;
            }
            Some(owned)
        }
    }
    pub(super) fn alive(&self) -> bool {
        unsafe { WaitForSingleObject(self.handle, 0) == 0x102 }
    } // WAIT_TIMEOUT only; unknown denies
}

// Retained process HANDLE may be queried across threads; Drop occurs only after last Arc.
unsafe impl Send for AuthenticatedWord {}
unsafe impl Sync for AuthenticatedWord {}

pub(super) fn client_birth() -> Option<u64> {
    unsafe {
        let mut created = FileTime { low: 0, high: 0 };
        let mut exited = FileTime { low: 0, high: 0 };
        let mut kernel = FileTime { low: 0, high: 0 };
        let mut user = FileTime { low: 0, high: 0 };
        if GetProcessTimes(
            GetCurrentProcess(),
            &mut created,
            &mut exited,
            &mut kernel,
            &mut user,
        ) == 0
        {
            return None;
        }
        let birth = (u64::from(created.high) << 32) | u64::from(created.low);
        (birth != 0).then_some(birth)
    }
}

pub(super) fn classify_word(hwnd: Handle) -> Option<bool> {
    unsafe {
        let mut pid = 0;
        if GetWindowThreadProcessId(hwnd, &mut pid) == 0 || pid == 0 {
            return None;
        }
        let handle = OpenProcess(0x0010_1000, 0, pid);
        if handle.is_null() {
            return None;
        }
        let owned = AuthenticatedWord {
            handle,
            pid,
            birth: 0,
        };
        let mut name = vec![0u16; 32768];
        let mut size = name.len() as u32;
        if QueryFullProcessImageNameW(handle, 0, name.as_mut_ptr(), &mut size) == 0 {
            return None;
        }
        let image = String::from_utf16(&name[..size as usize]).ok()?;
        let mut current = 0;
        if GetWindowThreadProcessId(hwnd, &mut current) == 0 || current != pid || !owned.alive() {
            return None;
        }
        Some(
            image
                .rsplit(['\\', '/'])
                .next()?
                .eq_ignore_ascii_case("winword.exe"),
        )
    }
}

#[cfg(test)]
impl AuthenticatedWord {
    pub(super) fn fixture(pid: u32, birth: u64) -> Self {
        let handle = unsafe { OpenProcess(0x0010_1000, 0, GetCurrentProcessId()) };
        assert!(!handle.is_null());
        // Protocol fixture only: live handle is this test process, key identity is fake/disposable. No Word claim.
        Self { handle, pid, birth }
    }
}
