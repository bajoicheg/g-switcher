//! Admission for new calls and the single retained Undo completion obligation.
//! A completion gate is private native control flow, never client/IPC authority.
#[derive(Clone, Copy)]
pub(super) struct CallGate {
    completion: bool,
}
impl CallGate {
    pub(super) fn provider() -> Self {
        Self { completion: false }
    }
    pub(super) fn undo_completion() -> Self {
        Self { completion: true }
    }
    pub(super) fn allows(self, live: impl FnOnce() -> bool) -> bool {
        self.completion || live()
    }
}
pub(super) fn finish_once(active: &mut bool, cleanup: impl FnOnce() -> Option<()>) -> Option<()> {
    if !*active {
        return Some(());
    }
    // Consume before provider entry. Failure/panic/hang never admits a retry.
    *active = false;
    cleanup()
}
#[cfg(test)]
include!("word_call_gate_requirements.rs");
