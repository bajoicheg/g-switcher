use g_switcher::model::{CorrectionRecord, Language};

#[test]
fn correction_record_preserves_direction() {
    let record = CorrectionRecord::new(
        "ghbdtn".to_owned(),
        "привет".to_owned(),
        Language::English,
        Language::Russian,
    );
    assert_eq!(record.source, Language::English);
    assert_eq!(record.target, Language::Russian);
}
