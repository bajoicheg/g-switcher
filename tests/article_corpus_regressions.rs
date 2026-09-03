use g_switcher::{
    detector::{correction_with_context, DEFAULT_CONFIDENCE_THRESHOLD},
    layout::opposite_layout_text,
    model::Language,
};

const ARTICLE_REGRESSIONS: &[&str] = &[
    "политик",
    "систем",
    "спрос",
    "программ",
    "лиц",
    "дел",
    "правил",
    "команд",
    "виде",
    "работ",
    "инструкции",
    "важны",
    "норм",
];

#[test]
fn restores_article_derived_wrong_layout_words_with_normal_context() {
    let context = vec!["информационная".to_owned(), "безопасность".to_owned()];

    for word in ARTICLE_REGRESSIONS {
        let wrong = opposite_layout_text(word, Language::Russian);
        let detection = correction_with_context(
            &wrong,
            &[],
            DEFAULT_CONFIDENCE_THRESHOLD,
            &context,
        )
        .unwrap_or_else(|| panic!("did not restore {word} from {wrong}"));

        assert_eq!(detection.source, Language::English, "wrong source for {word}");
        assert_eq!(detection.target, Language::Russian, "wrong target for {word}");
        assert_eq!(detection.corrected, *word, "wrong correction for {word}");
    }
}
