#![cfg(windows)]

#[path = "../src/windows_runtime/uia_legacy_v2.rs"]
mod uia_legacy_v2;

#[test]
fn matching_text_with_transient_caret_failure_must_retry() {
    assert!(uia_legacy_v2::should_retry_post_state(
        true,  // document text already reflects the replacement
        false, // UIA caret/selection has not caught up yet
        false, // verification deadline has not expired
    ));
}

#[test]
fn post_state_retry_stops_after_deadline() {
    assert!(!uia_legacy_v2::should_retry_post_state(
        true, false, true,
    ));
}
