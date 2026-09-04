// Permanent regressions from the ten-article Wikipedia corpus audit.
use g_switcher::{
    detector::{correction_with_context, DEFAULT_CONFIDENCE_THRESHOLD},
    layout::opposite_layout_text,
    model::Language,
};

const SAFE_CORRECTIONS: &[&str] = &[
    "автомат",
    "блоки",
    "ведут",
    "вещающих",
    "внутрь",
    "встреча",
    "выделен",
    "выучку",
    "герц",
    "герцшпрунга",
    "говорит",
    "голов",
    "гонтарук",
    "длин",
    "доступны",
    "европа",
    "здоров",
    "инструкцию",
    "интерференции",
    "кома",
    "крузенштерна",
    "куйбышеве",
    "культуру",
    "курляндскую",
    "кючук",
    "математика",
    "образ",
    "образов",
    "пешей",
    "почт",
    "продолжит",
    "прото",
    "реально",
    "росс",
    "русскую",
    "свободны",
    "семь",
    "скупку",
    "солнечная",
    "союз",
    "структурную",
    "тепе",
    "трук",
    "увеличив",
    "устройств",
    "уходит",
    "учеб",
    "физика",
    "чешку",
    "якуты",
];

const INTENTIONAL_KEEP: &[&str] = &[
    "внук", "гор", "дан", "дум", "зап", "кут", "луны", "мвт", "мкм", "мкс", "нев", "ран", "рын",
    "сем", "сер", "ста", "ток", "тян", "эне",
];

#[test]
fn restores_safe_ten_wikipedia_corpus_regressions() {
    let context = vec!["это".to_owned(), "текст".to_owned()];
    for word in SAFE_CORRECTIONS {
        let wrong = opposite_layout_text(word, Language::Russian);
        let detection =
            correction_with_context(&wrong, &[], DEFAULT_CONFIDENCE_THRESHOLD, &context)
                .unwrap_or_else(|| panic!("did not restore {word} from {wrong}"));
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
fn ambiguous_short_and_english_collision_cases_stay_fail_open() {
    let context = vec!["это".to_owned(), "текст".to_owned()];
    for word in INTENTIONAL_KEEP {
        let wrong = opposite_layout_text(word, Language::Russian);
        assert!(
            correction_with_context(&wrong, &[], DEFAULT_CONFIDENCE_THRESHOLD, &context).is_none(),
            "ambiguous source unexpectedly corrected: {wrong} -> {word}"
        );
    }
}

#[test]
fn explicit_english_collisions_remain_english() {
    for token in ["keys", "dyer", "ren", "ytd", "cnf", "lev"] {
        assert!(
            correction_with_context(token, &[], DEFAULT_CONFIDENCE_THRESHOLD, &[]).is_none(),
            "known/ambiguous English token unexpectedly corrected: {token}"
        );
    }
}
