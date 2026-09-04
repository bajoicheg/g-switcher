use g_switcher::{
    detector::{correction_with_context, DEFAULT_CONFIDENCE_THRESHOLD},
    frequency_model,
    layout::opposite_layout_text,
    model::Language,
};

const WIKIPEDIA_FIVE_REGRESSIONS: &[&str] = &[
    "автоматически",
    "автор",
    "англ",
    "блок",
    "боукы",
    "будут",
    "бук",
    "бурундук",
    "быт",
    "верит",
    "вес",
    "взят",
    "видео",
    "включён",
    "вне",
    "вод",
    "встреч",
    "высоки",
    "гвт",
    "герцшпрунгу",
    "глав",
    "гольштейн",
    "групп",
    "дат",
    "доме",
    "доп",
    "дорог",
    "достиг",
    "дума",
    "женщин",
    "жэхэ",
    "задач",
    "игр",
    "идут",
    "имён",
    "интернешнл",
    "интерфакс",
    "интерфейс",
    "квт",
    "кгц",
    "книг",
    "кот",
    "кпк",
    "крк",
    "крупнейшее",
    "крупнейшей",
    "кук",
    "куклу",
    "курируют",
    "лев",
    "луны",
    "люфтваффе",
    "маршрут",
    "маршрутных",
    "маршруту",
    "маршруты",
    "мгц",
    "меня",
    "мест",
    "млн",
    "млрд",
    "москва",
    "москъвь",
    "мпк",
    "мужчин",
    "мыс",
    "над",
    "науку",
    "начал",
    "нефтиду",
    "норма",
    "нос",
    "носит",
    "образован",
    "основ",
    "ост",
    "отв",
    "пар",
    "перу",
    "плохо",
    "показа",
    "пол",
    "получит",
    "пор",
    "пот",
    "прав",
    "приносит",
    "приходит",
    "причин",
    "проблем",
    "просто",
    "проходит",
    "путей",
    "россия",
    "рук",
    "руках",
    "рус",
    "сбор",
    "свобод",
    "сего",
    "сей",
    "сил",
    "сильны",
    "слов",
    "слова",
    "служб",
    "смотре",
    "сост",
    "спб",
    "став",
    "ставит",
    "сторон",
    "стоя",
    "стоят",
    "стран",
    "страниц",
    "строит",
    "структур",
    "структуру",
    "структуры",
    "сферу",
    "тел",
    "теле",
    "термин",
    "термина",
    "трети",
    "трлн",
    "труд",
    "труду",
    "уверен",
    "уверенно",
    "удар",
    "улиц",
    "управ",
    "уход",
    "уча",
    "финал",
    "финляндскую",
    "форм",
    "фрукты",
    "цен",
    "час",
    "чел",
    "чувство",
    "школ",
    "эйнштейн",
    "эйнштейна",
    "якутскую",
    "нефти",
    "наук",
    "сфер",
];

#[test]
fn restores_safe_five_wikipedia_corpus_regressions() {
    let context = vec!["это".to_owned(), "текст".to_owned()];
    for word in WIKIPEDIA_FIVE_REGRESSIONS {
        let wrong = opposite_layout_text(word, Language::Russian);
        let source_score = frequency_model::word_score(Language::English, &wrong);
        let detection =
            correction_with_context(&wrong, &[], DEFAULT_CONFIDENCE_THRESHOLD, &context);
        if source_score >= 15 {
            assert!(
                detection.is_none(),
                "known English source must remain protected for {word} -> {wrong}"
            );
            continue;
        }
        let detection = detection.unwrap_or_else(|| panic!("did not restore {word} from {wrong}"));
        assert_eq!(
            detection.source,
            Language::English,
            "wrong source for {word}"
        );
        assert_eq!(
            detection.target,
            Language::Russian,
            "wrong target for {word}"
        );
        assert_eq!(detection.corrected, *word, "wrong correction for {word}");
        assert_eq!(detection.confidence, 100, "non-deterministic target {word}");
    }
}

#[test]
fn arbitrary_oem_punctuation_remains_unchanged() {
    for token in ["...", ";;;", "[]'", "'''", "```"] {
        assert!(
            correction_with_context(token, &[], DEFAULT_CONFIDENCE_THRESHOLD, &[]).is_none(),
            "unexpected punctuation correction for {token}"
        );
    }
}
