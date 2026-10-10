//! Proposed shared module at selection parent. Explicit permits, no Drop completion.
#[path = "guard_core.rs"]
mod guard_core;
#[path = "registry_store.rs"]
mod registry_store;
#[path = "win32_identity.rs"]
mod win32_identity;
pub(crate) use guard_core::provider_stage;
use guard_core::{Child, Gate, Operation};
pub(crate) fn deadline_current(deadline: std::time::Instant) -> bool {
    guard_core::deadline_current(deadline)
}
use std::cell::RefCell;
use std::sync::{Arc, Mutex, OnceLock};
use win32_identity::AuthenticatedWord;
static GATE: OnceLock<Arc<Mutex<Gate<registry_store::RegistryStore>>>> = OnceLock::new();
fn gate() -> &'static Arc<Mutex<Gate<registry_store::RegistryStore>>> {
    GATE.get_or_init(|| {
        Arc::new(Mutex::new(Gate::with_store(
            registry_store::RegistryStore {
                namespace: "Software\\GSwitcher\\WordAdmission".to_string(),
            },
        )))
    })
}
#[derive(Clone)]
pub(crate) struct Parent {
    op: Operation,
    host: Arc<AuthenticatedWord>,
    gate: Arc<Mutex<Gate<registry_store::RegistryStore>>>,
}
pub(crate) struct ReaderChild {
    ticket: Child,
    parent: Parent,
}
thread_local! {static CURRENT:RefCell<Option<Parent>>=const{RefCell::new(None)};}
pub(crate) fn begin(hwnd: isize) -> Option<Parent> {
    let host = match AuthenticatedWord::from_window(hwnd as *mut core::ffi::c_void) {
        Some(h) => Arc::new(h),
        None => {
            trace(0, "identity-unavailable");
            return None;
        }
    };
    let op = match gate().lock().ok()?.begin(guard_core::Host {
        pid: host.pid,
        birth: host.birth,
    }) {
        Some(op) => op,
        None => {
            trace(1, "busy-pending-or-quarantined");
            return None;
        }
    };
    Some(Parent {
        op,
        host,
        gate: gate().clone(),
    })
}
impl Parent {
    pub(crate) fn quarantine(&self) {
        trace(2, "provider-outcome-unknown");
        if let Ok(mut g) = self.gate.lock() {
            let _ = g.quarantine(&self.op);
        }
    }
    pub(crate) fn matches(&self, hwnd: isize) -> bool {
        AuthenticatedWord::from_window(hwnd as *mut core::ffi::c_void).is_some_and(|h| {
            h.pid == self.host.pid && h.birth == self.host.birth && self.host.alive()
        })
    }
    pub(crate) fn child(&self) -> Option<ReaderChild> {
        if !self.host.alive() {
            return None;
        }
        Some(ReaderChild {
            ticket: self.gate.lock().ok()?.child(&self.op)?,
            parent: self.clone(),
        })
    }
    pub(crate) fn complete(&self, uncertain: bool) -> bool {
        let completed = self
            .gate
            .lock()
            .ok()
            .is_some_and(|mut g| g.parent_complete(&self.op, uncertain).is_ok());
        if !completed {
            trace(5, "storage-or-completion-unavailable");
        }
        completed
    }
}
impl ReaderChild {
    pub(crate) fn run<R>(&self, call: impl FnOnce() -> R) -> R {
        with_parent(self.parent.clone(), call)
    }
    pub(crate) fn complete(self) -> bool {
        self.parent
            .gate
            .lock()
            .ok()
            .is_some_and(|mut g| g.child_complete(self.ticket).is_ok())
    }
}
pub(crate) fn current() -> Option<Parent> {
    CURRENT.with(|s| s.borrow().clone())
}
pub(crate) fn with_parent<R>(parent: Parent, run: impl FnOnce() -> R) -> R {
    CURRENT.with(|slot| {
        assert!(slot.borrow().is_none(), "nested STA scope");
        *slot.borrow_mut() = Some(parent);
    });
    struct Scope;
    impl Drop for Scope {
        fn drop(&mut self) {
            CURRENT.with(|s| {
                s.borrow_mut().take();
            });
        }
    }
    let _scope = Scope;
    run()
}

pub(crate) fn classify_word(hwnd: isize) -> Option<bool> {
    win32_identity::classify_word(hwnd as *mut core::ffi::c_void)
}

// Once per process/category: bounded stage-only output, never document/input values.
pub(crate) fn trace(category: u32, reason: &str) {
    use std::io::Write;
    use std::sync::atomic::{AtomicU32, Ordering};
    static REPORTED: AtomicU32 = AtomicU32::new(0);
    let Some(bit) = 1u32.checked_shl(category) else {
        return;
    };
    if REPORTED.fetch_or(bit, Ordering::Relaxed) & bit != 0 {
        return;
    }
    let path = std::env::temp_dir().join("GSwitcher-Word-Runtime.log");
    let oversized = std::fs::metadata(&path).is_ok_and(|m| m.len() > 1_048_576);
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(!oversized)
        .truncate(oversized)
        .open(path)
    {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let _ = writeln!(
            file,
            "{now} pid={} stage=word-admission-refused-{reason}",
            std::process::id()
        );
    }
}

#[cfg(test)]
pub(crate) struct Fixture {
    pub(crate) parent: Parent,
    namespace: String,
    host: guard_core::Host,
}
#[cfg(test)]
impl Fixture {
    pub(crate) fn new() -> Self {
        use std::sync::atomic::{AtomicU32, Ordering};
        static NEXT: AtomicU32 = AtomicU32::new(1);
        let sequence = NEXT.fetch_add(1, Ordering::SeqCst);
        let pid = 0xf000_0000 + sequence;
        let birth = win32_identity::client_birth().unwrap() + 1;
        let namespace = format!(
            "Software\\GSwitcher\\Tests\\WordAdmission-{}-{}-{}",
            std::process::id(),
            sequence,
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let host = guard_core::Host { pid, birth };
        let gate = Arc::new(Mutex::new(Gate::with_store(
            registry_store::RegistryStore {
                namespace: namespace.clone(),
            },
        )));
        let op = gate.lock().unwrap().begin(host).unwrap();
        let parent = Parent {
            op,
            host: Arc::new(AuthenticatedWord::fixture(pid, birth)),
            gate,
        };
        Self {
            parent,
            namespace,
            host,
        }
    }
    pub(crate) fn pending(&self) -> bool {
        registry_store::fixture_pending(&self.namespace, self.host)
    }
    pub(crate) fn idle(&self) -> bool {
        registry_store::fixture_idle(&self.namespace, self.host)
    }
}
#[cfg(test)]
impl Drop for Fixture {
    fn drop(&mut self) {
        registry_store::fixture_cleanup(&self.namespace);
    }
}

pub(crate) fn identity(hwnd: isize) -> Option<(u32, u64)> {
    let host = AuthenticatedWord::from_window(hwnd as *mut core::ffi::c_void)?;
    Some((host.pid, host.birth))
}

fn enrollment_client_birth() -> Option<u64> {
    if super::broker_role() {
        super::broker_client_birth()
    } else {
        win32_identity::client_birth()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_registry_foreign_clear_cannot_replace_pending() {
        use guard_core::Store;
        let fixture = Fixture::new();
        let store = registry_store::RegistryStore {
            namespace: fixture.namespace.clone(),
        };
        assert!(store
            .clear(fixture.host, b"wrong-operation-nonce", ())
            .is_err());
        assert!(fixture.pending());
        assert!(!fixture.idle());
    }
    #[test]
    fn real_registry_idle_survives_gate_restart_and_next_pending_is_exact() {
        let fixture = Fixture::new();
        assert!(fixture.pending());
        assert!(fixture.parent.complete(false));
        assert!(fixture.idle());
        let mut next = Gate::with_store(registry_store::RegistryStore {
            namespace: fixture.namespace.clone(),
        });
        let op = next.begin(fixture.host).unwrap();
        assert!(fixture.pending());
        assert!(!fixture.idle());
        assert!(next.begin(fixture.host).is_none());
        assert!(next.parent_complete(&op, false).is_ok());
        assert!(fixture.idle());
    }
}
