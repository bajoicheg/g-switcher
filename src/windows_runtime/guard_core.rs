//! Staged portable protocol candidate. Windows storage/identity integration is mandatory.
//! Pending marker never expires. Drop deliberately never resolves provider ownership.
use std::collections::HashSet;
#[cfg(any(test, not(windows)))]
use std::fs::File;
#[cfg(test)]
use std::fs::OpenOptions;
#[cfg(not(windows))]
use std::io::Read;
#[cfg(test)]
use std::io::Write;
#[cfg(test)]
use std::path::PathBuf;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct Host {
    pub(super) pid: u32,
    pub(super) birth: u64,
}
#[derive(Clone, Debug)]
pub(super) struct Operation {
    host: Host,
    id: u128,
}
#[derive(Clone, Debug)]
pub(super) struct Child {
    operation: Operation,
    id: u64,
}
struct Active<S: Store> {
    operation: Operation,
    children: HashSet<u64>,
    next_child: u64,
    parent_done: bool,
    uncertain: bool,
    marker: Vec<u8>,
    hold: S::Hold,
}
#[cfg(test)]
pub(super) struct Gate<S: Store = FileStore> {
    store: S,
    active: Option<Active<S>>,
    poisoned: bool,
}
#[cfg(not(test))]
pub(super) struct Gate<S: Store> {
    store: S,
    active: Option<Active<S>>,
    poisoned: bool,
}
pub(super) trait Store {
    type Hold;
    fn reserve(&self, host: Host, marker: &[u8]) -> Result<Self::Hold, ()>;
    fn matches(&self, host: Host, marker: &[u8]) -> bool;
    fn clear(&self, host: Host, marker: &[u8], hold: Self::Hold) -> Result<(), ()>;
}
#[cfg(test)]
pub(super) struct FileStore {
    root: PathBuf,
}
#[cfg(test)]
impl FileStore {
    fn path(&self, host: Host) -> PathBuf {
        self.root
            .join(format!("{}-{}.pending", host.pid, host.birth))
    }
}
#[cfg(test)]
impl Store for FileStore {
    type Hold = File;
    fn reserve(&self, host: Host, marker: &[u8]) -> Result<File, ()> {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.share_mode(1);
        }
        let mut file = options.open(self.path(host)).map_err(|_| ())?;
        file.write_all(marker).map_err(|_| ())?;
        file.sync_all().map_err(|_| ())?;
        if !self.matches(host, marker) {
            return Err(());
        }
        Ok(file)
    }
    fn matches(&self, host: Host, marker: &[u8]) -> bool {
        std::fs::read(self.path(host)).ok().as_deref() == Some(marker)
    }
    fn clear(&self, host: Host, marker: &[u8], hold: File) -> Result<(), ()> {
        if !self.matches(host, marker) {
            return Err(());
        }
        drop(hold);
        std::fs::remove_file(self.path(host)).map_err(|_| ())
    }
}
#[cfg(test)]
impl Gate<FileStore> {
    fn open(root: PathBuf) -> Self {
        Self::with_store(FileStore { root })
    }
}

fn nonce() -> Option<u128> {
    let mut bytes = [0u8; 16];
    #[cfg(windows)]
    unsafe {
        #[link(name = "bcrypt")]
        extern "system" {
            fn BCryptGenRandom(
                algorithm: *mut core::ffi::c_void,
                bytes: *mut u8,
                length: u32,
                flags: u32,
            ) -> i32;
        }
        if BCryptGenRandom(core::ptr::null_mut(), bytes.as_mut_ptr(), 16, 2) < 0 {
            return None;
        }
    }
    #[cfg(not(windows))]
    File::open("/dev/urandom")
        .ok()?
        .read_exact(&mut bytes)
        .ok()?;
    let value = u128::from_le_bytes(bytes);
    (value != 0).then_some(value)
}
impl<S: Store> Gate<S> {
    pub(super) fn with_store(store: S) -> Self {
        Self {
            store,
            active: None,
            poisoned: false,
        }
    }
    pub(super) fn begin(&mut self, host: Host) -> Option<Operation> {
        // Host must come from retained authenticated Win32 process handle, NOT UIA PID.
        if self.poisoned || self.active.is_some() || host.pid == 0 || host.birth == 0 {
            return None;
        }
        let operation = Operation { host, id: nonce()? };
        let marker = format!(
            "word-provider-pending/v1\n{}\n{}\n{:032x}\n",
            host.pid, host.birth, operation.id
        )
        .into_bytes();
        let hold = match self.store.reserve(host, &marker) {
            Ok(v) => v,
            Err(()) => {
                self.poisoned = true;
                return None;
            }
        };
        self.active = Some(Active {
            operation: operation.clone(),
            children: HashSet::new(),
            next_child: 0,
            parent_done: false,
            uncertain: false,
            marker,
            hold,
        });
        Some(operation)
    }
    fn active_for(&mut self, op: &Operation) -> Result<&mut Active<S>, &'static str> {
        if self.poisoned {
            return Err("gate poisoned");
        }
        let active = self.active.as_mut().ok_or("no active operation")?;
        if active.operation.host != op.host || active.operation.id != op.id {
            return Err("foreign operation");
        }
        Ok(active)
    }
    pub(super) fn child(&mut self, op: &Operation) -> Option<Child> {
        let active = self.active_for(op).ok()?;
        if active.parent_done || active.uncertain {
            return None;
        }
        active.next_child = active.next_child.checked_add(1)?;
        active.children.insert(active.next_child);
        Some(Child {
            operation: op.clone(),
            id: active.next_child,
        })
    }
    pub(super) fn quarantine(&mut self, op: &Operation) -> Result<(), &'static str> {
        self.active_for(op)?.uncertain = true;
        Ok(())
    }
    pub(super) fn parent_complete(
        &mut self,
        op: &Operation,
        uncertain: bool,
    ) -> Result<(), &'static str> {
        let active = self.active_for(op)?;
        if active.parent_done {
            return Err("duplicate parent completion");
        }
        active.parent_done = true;
        active.uncertain |= uncertain;
        self.finish_if_quiescent()
    }
    pub(super) fn child_complete(&mut self, child: Child) -> Result<(), &'static str> {
        let active = self.active_for(&child.operation)?;
        if !active.children.remove(&child.id) {
            return Err("foreign or duplicate child completion");
        }
        self.finish_if_quiescent()
    }
    fn finish_if_quiescent(&mut self) -> Result<(), &'static str> {
        let active = self.active.as_ref().ok_or("no active operation")?;
        if !self.store.matches(active.operation.host, &active.marker) {
            self.poisoned = true;
            return Err("pending marker changed or unavailable");
        }
        if !active.parent_done || !active.children.is_empty() || active.uncertain {
            return Ok(());
        }
        // All actual provider work/teardown and native verification must have completed.
        let active = self.active.take().expect("active above");
        if self
            .store
            .clear(active.operation.host, &active.marker, active.hold)
            .is_err()
        {
            self.poisoned = true;
            return Err("clear failed");
        }
        Ok(())
    }
}
// This is an admission check, never cancellation or proof of provider completion.
pub(crate) fn deadline_current(deadline: std::time::Instant) -> bool {
    std::time::Instant::now() < deadline
}
pub(crate) fn provider_stage<R>(
    authorized: impl FnOnce() -> bool,
    provider: impl FnOnce() -> R,
) -> Option<R> {
    if !authorized() {
        return None;
    }
    Some(provider())
}

#[cfg(test)]
include!("requirements_tests.rs");

#[cfg(test)]
mod authority_tests {
    use super::*;
    #[test]
    fn disconnected_stage_does_not_enter_provider() {
        let calls = std::cell::Cell::new(0);
        assert_eq!(
            provider_stage(
                || true,
                || {
                    calls.set(calls.get() + 1);
                    7
                }
            ),
            Some(7)
        );
        assert_eq!(
            provider_stage(
                || false,
                || {
                    calls.set(calls.get() + 1);
                    8
                }
            ),
            None
        );
        assert_eq!(
            calls.get(),
            1,
            "revoked transport must prevent the NEXT provider stage"
        );
    }
    #[test]
    fn expired_stage_does_not_enter_provider() {
        let expired = std::time::Instant::now() - std::time::Duration::from_secs(1);
        let calls = std::cell::Cell::new(0);
        assert_eq!(
            provider_stage(
                || deadline_current(expired),
                || {
                    calls.set(1);
                    7
                }
            ),
            None
        );
        assert_eq!(calls.get(), 0);
    }
}
