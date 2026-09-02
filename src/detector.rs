use std::collections::HashSet;

use once_cell::sync::Lazy;

use crate::{
    code_safe::is_code_safe_token,
    layout::opposite_layout_text,
    model::{Decision, Language},
};

static RU_COMMON: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "привет",
        "коробка",
        "беру",
        "берут",
        "ещё",
        "еще",
        "ёлка",
        "всё",
        "моё",
        "объект",
        "подъезд",
        "хлеб",
        "кабель",
        "собака",
        "безопасность",
        "работа",
        "работаю",
        "работает",
        "проверка",
        "система",
        "сервер",
        "пользователь",
        "окно",
    ]
    .into_iter()
    .collect()
});

static EN_COMMON: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "hello", "the", "then", "to", "work", "system", "server", "user", "check", "security",
        "object", "box", "window", "windows",
    ]
    .into_iter()
    .collect()
});

pub fn infer_language(token: &str) -> Option<Language> {
    let mut ru = false;
    let mut en = false;
    for ch in token.chars() {
        if is_ru_letter(ch) {
            ru = true;
        } else if ch.is_ascii_alphabetic() {
            en = true;
        }
    }
    match (ru, en) {
        (true, false) => Some(Language::Russian),
        (false, true) => Some(Language::English),
        _ => None,
    }
}

pub fn decide(token: &str) -> Decision {
    if is_code_safe_token(token) {
        return Decision::Keep;
    }

    let Some(source) = infer_language(token) else {
        return Decision::Keep;
    };
    let normalized = normalize(token, source);
    if source_dictionary(source).contains(normalized.as_str()) {
        return Decision::Keep;
    }

    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    let mapped_normalized = normalize(&mapped, target);

    if !candidate_shape_is_valid(&mapped, target) {
        return Decision::Keep;
    }

    if source_dictionary(target).contains(mapped_normalized.as_str()) {
        return Decision::CorrectTo(target);
    }

    // A physical punctuation key can be a letter in the opposite layout.
    // Do not let statistical scoring convert a partial prefix before that
    // key has a chance to extend the candidate (for example rjhj,rf -> коробка).
    if is_target_word_prefix(&mapped_normalized, target) {
        return Decision::Keep;
    }

    if language_score(&mapped_normalized, target) >= 8
        && language_score(&mapped_normalized, target) >= language_score(&normalized, source) + 5
    {
        return Decision::CorrectTo(target);
    }

    Decision::Keep
}

pub fn correction(token: &str) -> Option<(Language, Language, String)> {
    let source = infer_language(token)?;
    match decide(token) {
        Decision::CorrectTo(target) => Some((source, target, opposite_layout_text(token, source))),
        Decision::Keep => None,
    }
}

pub fn opposite_candidate_is_prefix(token: &str) -> bool {
    let Some(source) = infer_language(token) else {
        return false;
    };
    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    if !candidate_shape_is_valid(&mapped, target) {
        return false;
    }
    let mapped = normalize(&mapped, target);
    is_target_word_prefix(&mapped, target)
}

fn is_target_word_prefix(token: &str, language: Language) -> bool {
    source_dictionary(language)
        .iter()
        .any(|word| word.starts_with(token) && word.len() > token.len())
}

fn source_dictionary(language: Language) -> &'static HashSet<&'static str> {
    match language {
        Language::Russian => &RU_COMMON,
        Language::English => &EN_COMMON,
    }
}

fn opposite(language: Language) -> Language {
    match language {
        Language::Russian => Language::English,
        Language::English => Language::Russian,
    }
}

fn normalize(token: &str, language: Language) -> String {
    let lower = token.to_lowercase();
    match language {
        Language::Russian => lower.replace('ё', "е"),
        Language::English => lower,
    }
}

fn candidate_shape_is_valid(candidate: &str, language: Language) -> bool {
    candidate.chars().all(|ch| match language {
        Language::Russian => is_ru_letter(ch),
        Language::English => ch.is_ascii_alphabetic(),
    })
}

fn language_score(token: &str, language: Language) -> i32 {
    if token.chars().count() < 3 {
        return 0;
    }
    match language {
        Language::English => score_english(token),
        Language::Russian => score_russian(token),
    }
}

fn score_english(token: &str) -> i32 {
    const COMMON: &[&str] = &[
        "th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es", "or", "te", "of",
        "ed", "is", "it", "al", "ar", "st", "to", "nt", "ng", "se", "ha", "as", "ou", "io", "le",
        "ve", "co", "me", "de", "hi", "ri", "ro", "ic", "ne", "ea", "ra", "ce", "li", "ch", "ll",
        "be", "ma", "si", "om", "ur",
    ];
    const RARE: &[&str] = &["qj", "qz", "jx", "zq", "xq", "wj", "jq", "vh", "hg"];

    let mut score = 0;
    let vowels = token
        .chars()
        .filter(|ch| matches!(ch, 'a' | 'e' | 'i' | 'o' | 'u' | 'y'))
        .count();
    if vowels > 0 {
        score += 3;
    } else {
        score -= 6;
    }
    for pair in token.as_bytes().windows(2) {
        if let Ok(pair) = std::str::from_utf8(pair) {
            if COMMON.contains(&pair) {
                score += 2;
            }
            if RARE.contains(&pair) {
                score -= 3;
            }
        }
    }
    score
}

fn score_russian(token: &str) -> i32 {
    const COMMON: &[&str] = &[
        "ст", "но", "то", "на", "ен", "ов", "ни", "ра", "во", "ко", "ро", "по", "пр", "ер", "ос",
        "ал", "го", "ли", "от", "ре", "та", "ть", "ан", "ор", "ка", "ло", "ва", "ит", "те", "ет",
        "ел", "ри", "не", "де", "ам", "ла", "ве", "ие", "ис", "ол", "ле", "ся", "ин", "тр", "ом",
        "ма", "ме", "до", "че", "об", "бо",
    ];
    const RARE: &[&str] = &["жы", "шы", "чя", "щя", "йй", "ъъ", "ьы"];

    let mut score = 0;
    let vowels = token
        .chars()
        .filter(|ch| {
            matches!(
                ch,
                'а' | 'е' | 'ё' | 'и' | 'о' | 'у' | 'ы' | 'э' | 'ю' | 'я'
            )
        })
        .count();
    if vowels > 0 {
        score += 3;
    } else {
        score -= 6;
    }

    let chars: Vec<char> = token.chars().collect();
    for pair in chars.windows(2) {
        let pair: String = pair.iter().collect();
        if COMMON.contains(&pair.as_str()) {
            score += 2;
        }
        if RARE.contains(&pair.as_str()) {
            score -= 3;
        }
    }
    score
}

fn is_ru_letter(ch: char) -> bool {
    matches!(ch, 'а'..='я' | 'А'..='Я' | 'ё' | 'Ё')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn corrects_known_wrong_layout_words() {
        assert_eq!(decide("ghbdtn"), Decision::CorrectTo(Language::Russian));
        assert_eq!(decide("руддщ"), Decision::CorrectTo(Language::English));
        assert_eq!(decide("rjhj,rf"), Decision::CorrectTo(Language::Russian));
        assert_eq!(decide("цштвщц"), Decision::CorrectTo(Language::English));
    }

    #[test]
    fn protects_known_false_positive_cases() {
        for word in [
            "беру",
            "берут",
            "ещё",
            "еще",
            "ёлка",
            "всё",
            "моё",
            "объект",
            "подъезд",
            "hello",
            "the",
            "then",
        ] {
            assert_eq!(decide(word), Decision::Keep, "changed {word}");
        }
    }

    #[test]
    fn punctuation_in_opposite_candidate_is_not_silently_dropped() {
        assert_eq!(decide("беру"), Decision::Keep);
    }

    #[test]
    fn known_opposite_prefix_is_not_corrected_early() {
        assert_eq!(decide("rjhj"), Decision::Keep);
        assert!(opposite_candidate_is_prefix("rjhj"));
    }

    #[test]
    fn recognizes_ambiguous_oem_prefix() {
        assert!(opposite_candidate_is_prefix("rjhj"));
        assert!(!opposite_candidate_is_prefix("hello"));
    }
}
