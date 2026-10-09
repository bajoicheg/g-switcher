//! Staged HKCU store: caller must hold the same-user named mutex for each method.
//! No age-based recovery and no overwrite of existing pending records.
use super::guard_core::{Host, Store};
use core::ffi::c_void;
type Key = *mut c_void;
const HKCU: Key = (0x8000_0001u32 as i32 as isize) as Key;
#[link(name = "advapi32")]
extern "system" {
    fn RegCreateKeyExW(
        key: Key,
        path: *const u16,
        reserved: u32,
        class: *mut u16,
        options: u32,
        access: u32,
        security: *const c_void,
        result: *mut Key,
        disposition: *mut u32,
    ) -> i32;
    fn RegQueryValueExW(
        key: Key,
        name: *const u16,
        reserved: *mut u32,
        kind: *mut u32,
        data: *mut u8,
        size: *mut u32,
    ) -> i32;
    fn RegSetValueExW(
        key: Key,
        name: *const u16,
        reserved: u32,
        kind: u32,
        data: *const u8,
        size: u32,
    ) -> i32;
    fn RegFlushKey(key: Key) -> i32;
    fn RegCloseKey(key: Key) -> i32;
}
#[link(name = "kernel32")]
extern "system" {
    fn CreateMutexW(attributes: *const c_void, owner: i32, name: *const u16) -> *mut c_void;
    fn WaitForSingleObject(handle: *mut c_void, millis: u32) -> u32;
    fn ReleaseMutex(handle: *mut c_void) -> i32;
    fn CloseHandle(handle: *mut c_void) -> i32;
}
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}
struct Lock(*mut c_void);
impl Lock {
    fn take(namespace: &str) -> Result<Self, ()> {
        unsafe {
            let encoded: String = namespace.bytes().map(|b| format!("{b:02x}")).collect();
            let name = wide(&format!("Local\\GSwitcher-WordAdmission-v1-{encoded}"));
            let h = CreateMutexW(core::ptr::null(), 0, name.as_ptr());
            if h.is_null() {
                return Err(());
            }
            let status = WaitForSingleObject(h, 0);
            if status != 0 {
                CloseHandle(h);
                return Err(());
            } // abandoned/unknown is not permission
            Ok(Self(h))
        }
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        unsafe {
            ReleaseMutex(self.0);
            CloseHandle(self.0);
        }
    }
}
struct Registry(Key);
impl Registry {
    fn open(namespace: &str) -> Result<Self, ()> {
        unsafe {
            let path = wide(namespace);
            let mut key = core::ptr::null_mut();
            let mut disposition = 0;
            if RegCreateKeyExW(
                HKCU,
                path.as_ptr(),
                0,
                core::ptr::null_mut(),
                0,
                3,
                core::ptr::null(),
                &mut key,
                &mut disposition,
            ) != 0
            {
                return Err(());
            }
            Ok(Self(key))
        }
    }
    fn name(host: Host) -> Vec<u16> {
        wide(&format!("{}-{}", host.pid, host.birth))
    }
    fn read(&self, host: Host) -> Result<Option<Vec<u8>>, ()> {
        unsafe {
            let name = Self::name(host);
            let mut kind = 0;
            let mut size = 0;
            let status = RegQueryValueExW(
                self.0,
                name.as_ptr(),
                core::ptr::null_mut(),
                &mut kind,
                core::ptr::null_mut(),
                &mut size,
            );
            if status == 2 {
                return Ok(None);
            }
            if status != 0 || kind != 3 || size == 0 || size > 512 {
                return Err(());
            }
            let mut bytes = vec![0; size as usize];
            if RegQueryValueExW(
                self.0,
                name.as_ptr(),
                core::ptr::null_mut(),
                &mut kind,
                bytes.as_mut_ptr(),
                &mut size,
            ) != 0
                || kind != 3
                || size as usize != bytes.len()
            {
                return Err(());
            }
            Ok(Some(bytes))
        }
    }
}
impl Drop for Registry {
    fn drop(&mut self) {
        unsafe {
            RegCloseKey(self.0);
        }
    }
}
pub(super) struct RegistryStore {
    pub(super) namespace: String,
}
impl Store for RegistryStore {
    type Hold = ();
    fn reserve(&self, host: Host, marker: &[u8]) -> Result<(), ()> {
        let _lock = Lock::take(&self.namespace)?;
        let key = Registry::open(&self.namespace)?;
        match key.read(host)? {
            Some(bytes) if valid_idle(host, &bytes) => {}
            Some(_) => {
                super::trace(3, "prior-pending-or-uncertain");
                return Err(());
            }
            None => {
                if host.birth <= super::win32_identity::client_birth().ok_or(())? {
                    super::trace(4, "first-enrollment-old-word");
                    return Err(());
                }
            }
        }
        // Enrollment safety must be checked by the retained Win32 identity wrapper.
        let name = Registry::name(host);
        unsafe {
            if RegSetValueExW(
                key.0,
                name.as_ptr(),
                0,
                3,
                marker.as_ptr(),
                marker.len() as u32,
            ) != 0
                || RegFlushKey(key.0) != 0
            {
                return Err(());
            }
        }
        if key.read(host)?.as_deref() != Some(marker) {
            return Err(());
        }
        Ok(())
    }
    fn matches(&self, host: Host, marker: &[u8]) -> bool {
        (|| {
            let _lock = Lock::take(&self.namespace)?;
            let key = Registry::open(&self.namespace)?;
            Ok::<_, ()>(key.read(host)?.as_deref() == Some(marker))
        })()
        .unwrap_or_else(|()| {
            super::trace(5, "storage-or-lock-unavailable");
            false
        })
    }
    fn clear(&self, host: Host, marker: &[u8], _: ()) -> Result<(), ()> {
        let _lock = Lock::take(&self.namespace)?;
        let key = Registry::open(&self.namespace)?;
        if key.read(host)?.as_deref() != Some(marker) {
            return Err(());
        }
        let name = Registry::name(host);
        let idle = idle_from(marker).ok_or(())?;
        unsafe {
            if RegSetValueExW(key.0, name.as_ptr(), 0, 3, idle.as_ptr(), idle.len() as u32) != 0
                || RegFlushKey(key.0) != 0
            {
                return Err(());
            }
        }
        require_exact_idle_readback(&key, host, &idle)
    }
}

// Completion is bound to this operation's exact Idle nonce, not merely a valid record.
fn require_exact_idle_readback(key: &Registry, host: Host, idle: &[u8]) -> Result<(), ()> {
    if key.read(host)?.as_deref() != Some(idle) {
        return Err(());
    }
    Ok(())
}

fn idle_from(marker: &[u8]) -> Option<Vec<u8>> {
    let text = std::str::from_utf8(marker).ok()?;
    text.strip_prefix("word-provider-pending/v1\n")
        .map(|rest| format!("word-provider-idle/v1\n{rest}").into_bytes())
}
fn valid_idle(host: Host, bytes: &[u8]) -> bool {
    let Ok(text) = std::str::from_utf8(bytes) else {
        return false;
    };
    let mut lines = text.lines();
    lines.next() == Some("word-provider-idle/v1")
        && lines.next() == Some(host.pid.to_string().as_str())
        && lines.next() == Some(host.birth.to_string().as_str())
        && lines
            .next()
            .is_some_and(|id| id.len() == 32 && u128::from_str_radix(id, 16).is_ok_and(|v| v != 0))
        && lines.next().is_none()
        && text.ends_with('\n')
}
pub(super) fn may_access(host: Host) -> bool {
    (|| {
        let _lock = Lock::take("Software\\GSwitcher\\WordAdmission")?;
        let key = Registry::open("Software\\GSwitcher\\WordAdmission")?;
        Ok::<_, ()>(match key.read(host)? {
            Some(v) => {
                let allowed = valid_idle(host, &v);
                if !allowed {
                    super::trace(3, "prior-pending-or-uncertain");
                }
                allowed
            }
            None => {
                let allowed = host.birth > super::win32_identity::client_birth().ok_or(())?;
                if !allowed {
                    super::trace(4, "first-enrollment-old-word");
                }
                allowed
            }
        })
    })()
    .unwrap_or(false)
}

#[cfg(test)]
pub(super) fn fixture_pending(namespace: &str, host: Host) -> bool {
    Registry::open(namespace)
        .ok()
        .and_then(|k| k.read(host).ok())
        .flatten()
        .is_some_and(|v| v.starts_with(b"word-provider-pending/v1\n"))
}
#[cfg(test)]
pub(super) fn fixture_idle(namespace: &str, host: Host) -> bool {
    Registry::open(namespace)
        .ok()
        .and_then(|k| k.read(host).ok())
        .flatten()
        .is_some_and(|v| valid_idle(host, &v))
}
#[cfg(test)]
pub(super) fn fixture_cleanup(namespace: &str) {
    assert!(namespace.starts_with("Software\\GSwitcher\\Tests\\WordAdmission-"));
    #[link(name = "advapi32")]
    extern "system" {
        fn RegDeleteTreeW(key: Key, path: *const u16) -> i32;
    }
    assert_eq!(unsafe { RegDeleteTreeW(HKCU, wide(namespace).as_ptr()) }, 0);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn completion_readback_rejects_foreign_idle_and_absent_value() {
        // Real disposable registry values exercise the production completion predicate.
        let fixture = super::super::Fixture::new();
        let key = Registry::open(&fixture.namespace).unwrap();
        let host = fixture.host;
        let pending = key.read(host).unwrap().unwrap();
        let expected = idle_from(&pending).unwrap();
        let foreign = format!(
            "word-provider-idle/v1\n{}\n{}\n{:032x}\n",
            host.pid,
            host.birth,
            if expected.ends_with(b"00000000000000000000000000000001\n") {
                2
            } else {
                1
            }
        )
        .into_bytes();
        assert!(valid_idle(host, &foreign));
        assert_ne!(foreign, expected);
        let name = Registry::name(host);
        unsafe {
            assert_eq!(
                RegSetValueExW(
                    key.0,
                    name.as_ptr(),
                    0,
                    3,
                    foreign.as_ptr(),
                    foreign.len() as u32
                ),
                0
            );
            assert_eq!(RegFlushKey(key.0), 0);
        }
        assert!(require_exact_idle_readback(&key, host, &expected).is_err());
        #[link(name = "advapi32")]
        extern "system" {
            fn RegDeleteValueW(key: Key, name: *const u16) -> i32;
        }
        unsafe {
            assert_eq!(RegDeleteValueW(key.0, name.as_ptr()), 0);
            assert_eq!(RegFlushKey(key.0), 0);
        }
        assert!(require_exact_idle_readback(&key, host, &expected).is_err());
        unsafe {
            assert_eq!(
                RegSetValueExW(
                    key.0,
                    name.as_ptr(),
                    0,
                    3,
                    expected.as_ptr(),
                    expected.len() as u32
                ),
                0
            );
            assert_eq!(RegFlushKey(key.0), 0);
        }
        assert!(require_exact_idle_readback(&key, host, &expected).is_ok());
        drop(key); // Close disposable-key handle before Fixture removes its subtree.
    }
    #[test]
    fn verified_idle_identity_and_format_are_required() {
        let host = Host { pid: 1, birth: 2 };
        let marker = b"word-provider-pending/v1\n1\n2\n00000000000000000000000000000001\n";
        let idle = idle_from(marker).unwrap();
        assert!(valid_idle(host, &idle));
        assert!(!valid_idle(Host { pid: 1, birth: 3 }, &idle));
        assert!(!valid_idle(host, marker));
        assert!(!valid_idle(host, b"word-provider-idle/v1\n1\n2\n0\n"));
    }
}
