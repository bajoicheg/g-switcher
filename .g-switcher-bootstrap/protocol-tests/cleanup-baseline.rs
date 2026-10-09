//! Explicit model of the reviewed revocation bug, not an original COM binary.
struct CallGate;
impl CallGate {
    fn provider() -> Self { Self }
    fn undo_completion() -> Self { Self }
    fn allows(self, live: impl FnOnce() -> bool) -> bool { live() }
}
fn finish_once(active: &mut bool, cleanup: impl FnOnce() -> Option<()>) -> Option<()> {
    if !*active { return Some(()); }
    *active = false;
    if !CallGate::undo_completion().allows(|| false) { return None; }
    cleanup()
}
include!("../product/src/windows_runtime/word_call_gate_requirements.rs");
