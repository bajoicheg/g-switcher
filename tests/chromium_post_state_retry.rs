#![cfg(windows)]

#[allow(dead_code)]
#[path = "../src/windows_runtime/selection.rs"]
mod selection;

#[test]
fn matching_text_with_transient_caret_failure_must_retry() {
    assert!(selection::uia_legacy::should_retry_post_state(
        true,  // document text already reflects the replacement
        false, // UIA caret/selection has not caught up yet
        false, // verification deadline has not expired
    ));
}

#[test]
fn post_state_retry_stops_after_deadline() {
    assert!(!selection::uia_legacy::should_retry_post_state(
        true, false, true,
    ));
}
