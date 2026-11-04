#[cfg(test)]
mod cleanup_tests {
    use super::*;
    #[test]
    fn undo_cleanup_attempts_once_after_authority_revocation() {
        let mut active = true;
        let calls = std::cell::Cell::new(0);
        assert_eq!(
            finish_once(&mut active, || {
                assert!(CallGate::undo_completion().allows(|| false));
                calls.set(calls.get() + 1);
                Some(())
            }),
            Some(())
        );
        assert_eq!(
            finish_once(&mut active, || panic!("duplicate cleanup")),
            Some(())
        );
        assert_eq!(
            calls.get(),
            1,
            "retained started record must be completed once after revocation"
        );
    }
    #[test]
    fn failed_undo_cleanup_is_not_repeated() {
        let mut active = true;
        let calls = std::cell::Cell::new(0);
        assert_eq!(
            finish_once(&mut active, || {
                calls.set(1);
                None
            }),
            None
        );
        assert_eq!(
            finish_once(&mut active, || panic!("unknown cleanup cannot retry")),
            Some(())
        );
        assert_eq!(calls.get(), 1);
    }
    #[test]
    fn undo_completion_never_authorizes_a_new_provider_stage() {
        assert!(CallGate::undo_completion().allows(|| false));
        assert!(!CallGate::provider().allows(|| false));
        assert!(CallGate::provider().allows(|| true));
    }
}
