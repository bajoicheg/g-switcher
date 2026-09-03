use g_switcher::detector::{detect, detect_with_context};
use g_switcher::layout::opposite_layout_text;
use g_switcher::model::Language;

#[test]
fn security_terms_and_acronyms_correct_both_safely() {
    for expected in [
        "availability",
        "integrity",
        "unauthorized",
        "cissp",
        "nist",
        "gdpr",
    ] {
        let wrong = opposite_layout_text(expected, Language::English);
        let detection = detect(&wrong, &[]).expect("EN corpus term should correct");
        assert_eq!(detection.corrected.to_lowercase(), expected);
        assert_eq!(detection.confidence, 100);
        assert!(detect(expected, &[]).is_none(), "correct EN source changed: {expected}");
    }

    for expected in ["сша", "ссср", "гост", "исо", "ибп"] {
        let wrong = opposite_layout_text(expected, Language::Russian);
        let detection = detect(&wrong, &[]).expect("RU acronym should correct");
        assert_eq!(detection.corrected.to_lowercase(), expected);
        assert_eq!(detection.confidence, 100);
    }
}

#[test]
fn short_function_words_need_two_word_target_context() {
    let ru_context = vec!["защита".to_owned(), "данных".to_owned()];
    let en_context = vec!["data".to_owned(), "security".to_owned()];

    let ru = detect_with_context("b", &[], &ru_context).expect("b should resolve to и");
    assert_eq!(ru.corrected, "и");
    assert!(detect_with_context("b", &[], &[]).is_none());
    assert!(detect_with_context("b", &[], &en_context).is_none());

    let en = detect_with_context("ещ", &[], &en_context).expect("ещ should resolve to to");
    assert_eq!(en.corrected, "to");
    assert!(detect_with_context("ещ", &[], &ru_context).is_none());
}

#[test]
fn shifted_oem_case_round_trips() {
    assert_eq!(
        opposite_layout_text("Безопасность", Language::Russian),
        "<tpjgfcyjcnm"
    );
    assert_eq!(
        opposite_layout_text("<tpjgfcyjcnm", Language::English),
        "Безопасность"
    );
    assert_eq!(
        opposite_layout_text("БЮЁХЪЖЭ,.", Language::Russian),
        "<>~{}:\"?/"
    );
}
