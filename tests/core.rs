use g_switcher::{
    code_safe::is_code_safe_token,
    detector::{correction, decide},
    model::{CorrectionRecord, Decision, Language},
    state::CandidateState,
    undo::UndoState,
};

#[test]
fn known_layout_corrections_are_symmetric() {
    assert_eq!(
        correction("ghbdtn"),
        Some((Language::English, Language::Russian, "привет".to_owned()))
    );
    assert_eq!(
        correction("руддщ"),
        Some((Language::Russian, Language::English, "hello".to_owned()))
    );
    assert_eq!(
        correction("rjhj,rf"),
        Some((Language::English, Language::Russian, "коробка".to_owned()))
    );
}

#[test]
fn false_positive_regressions_are_preserved() {
    for word in [
        "беру", "берут", "ещё", "еще", "ёлка", "всё", "моё", "объект", "подъезд",
        "hello", "the", "then",
    ] {
        assert_eq!(decide(word), Decision::Keep, "unexpected correction: {word}");
    }
}

#[test]
fn code_safe_examples_are_never_candidates() {
    for token in [
        "HOST-SRV-01",
        "10.20.30.40",
        "10.20.0.0/16",
        "C:\\Windows\\System32",
        "/usr/local/bin",
        "user@example.test",
        "https://example.test/path",
        "550e8400-e29b-41d4-a716-446655440000",
        "sha256:abcdef0123456789",
        "SomeVariable42",
        "some_variable",
        "--background",
    ] {
        assert!(is_code_safe_token(token));
        assert_eq!(decide(token), Decision::Keep);
    }
}

#[test]
fn backspace_restores_previous_candidate() {
    let mut state = CandidateState::new();
    for ch in "ghbdtn/".chars() {
        state.push(ch);
    }
    state.backspace();
    assert_eq!(state.text(), "ghbdtn");
}

#[test]
fn undo_requires_same_focus_and_is_one_shot() {
    let mut undo = UndoState::default();
    let record = CorrectionRecord::new(
        "ghbdtn".to_owned(),
        "привет".to_owned(),
        Language::English,
        Language::Russian,
    );
    undo.arm(record.clone(), 100);
    assert_eq!(undo.take_if_compatible(100), Some(record));
    assert!(undo.take_if_compatible(100).is_none());
}

#[test]
fn undo_is_invalidated_by_focus_change() {
    let mut undo = UndoState::default();
    undo.arm(
        CorrectionRecord::new(
            "ghbdtn".to_owned(),
            "привет".to_owned(),
            Language::English,
            Language::Russian,
        ),
        100,
    );
    assert!(undo.take_if_compatible(101).is_none());
    assert!(!undo.is_armed());
}
