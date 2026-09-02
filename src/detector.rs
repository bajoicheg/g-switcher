use std::collections::HashSet;

use once_cell::sync::Lazy;

use crate::{
    code_safe::is_code_safe_token,
    layout::opposite_layout_text,
    model::{Decision, Language},
};

pub const DEFAULT_CONFIDENCE_THRESHOLD: u8 = 72;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Detection {
    pub source: Language,
    pub target: Language,
    pub corrected: String,
    pub confidence: u8,
}

static RU_COMMON: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "привет",
        "коробка",
        "свобода",
        "свободу",
        "свободы",
        "свободе",
        "свободой",
        "свободный",
        "свободно",
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
    decide_with_user_words(token, &[], DEFAULT_CONFIDENCE_THRESHOLD)
}

pub fn decide_with_user_words(
    token: &str,
    user_words: &[String],
    confidence_threshold: u8,
) -> Decision {
    let Some(detection) = detect(token, user_words) else {
        return Decision::Keep;
    };
    if detection.confidence >= confidence_threshold {
        Decision::CorrectTo(detection.target)
    } else {
        Decision::Keep
    }
}

pub fn detect(token: &str, user_words: &[String]) -> Option<Detection> {
    if is_code_safe_token(token) {
        return None;
    }

    let source = infer_language(token)?;
    let normalized = normalize(token, source);
    if dictionary_contains(source, &normalized, user_words) {
        return None;
    }

    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    let mapped_normalized = normalize(&mapped, target);
    if !candidate_shape_is_valid(&mapped, target) {
        return None;
    }

    let target_exact = dictionary_contains(target, &mapped_normalized, user_words);
    if target_exact {
        return Some(Detection {
            source,
            target,
            corrected: mapped,
            confidence: 100,
        });
    }

    // A physical punctuation key can be a letter in the opposite layout.
    // Keep partial prefixes intact so OEM keys can extend the token first.
    if is_target_word_prefix(&mapped_normalized, target, user_words) {
        return None;
    }

    let source_score = language_score(&normalized, source);
    let target_score = language_score(&mapped_normalized, target);
    let margin = target_score - source_score;
    if target_score < 7 || margin < 3 {
        return None;
    }

    let confidence = confidence_from_scores(target_score, margin);
    Some(Detection {
        source,
        target,
        corrected: mapped,
        confidence,
    })
}

pub fn correction(token: &str) -> Option<(Language, Language, String)> {
    correction_with_user_words(token, &[], DEFAULT_CONFIDENCE_THRESHOLD)
        .map(|detection| (detection.source, detection.target, detection.corrected))
}

pub fn correction_with_user_words(
    token: &str,
    user_words: &[String],
    confidence_threshold: u8,
) -> Option<Detection> {
    let detection = detect(token, user_words)?;
    (detection.confidence >= confidence_threshold).then_some(detection)
}

pub fn opposite_candidate_is_prefix(token: &str) -> bool {
    opposite_candidate_is_prefix_with_user_words(token, &[])
}

pub fn opposite_candidate_is_prefix_with_user_words(token: &str, user_words: &[String]) -> bool {
    let Some(source) = infer_language(token) else {
        return false;
    };
    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    if !candidate_shape_is_valid(&mapped, target) {
        return false;
    }
    let mapped = normalize(&mapped, target);
    is_target_word_prefix(&mapped, target, user_words)
}

fn confidence_from_scores(target_score: i32, margin: i32) -> u8 {
    let raw = 50 + margin * 5 + target_score.max(0) / 2;
    raw.clamp(0, 95) as u8
}

fn is_target_word_prefix(token: &str, language: Language, user_words: &[String]) -> bool {
    source_dictionary(language)
        .iter()
        .any(|word| word.starts_with(token) && word.len() > token.len())
        || user_words.iter().any(|word| {
            let normalized = normalize(word.trim(), language);
            !normalized.is_empty()
                && infer_language(&normalized) == Some(language)
                && normalized.starts_with(token)
                && normalized.len() > token.len()
        })
}

fn dictionary_contains(language: Language, token: &str, user_words: &[String]) -> bool {
    source_dictionary(language).contains(token)
        || user_words.iter().any(|word| {
            let word = word.trim();
            !word.is_empty()
                && infer_language(word) == Some(language)
                && normalize(word, language) == token
        })
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
    const COMMON_TRIGRAMS: &[&str] = &[
        "the", "and", "ing", "ion", "ent", "her", "for", "tha", "nth", "int", "ere", "ter",
        "est", "ers", "ati", "hat", "ate", "all", "eth", "hes", "ver", "his", "oft", "ith",
    ];
    const SUFFIXES: &[&str] = &["ing", "ed", "er", "ly", "tion", "ment", "ness", "able", "ous"];
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
    for triple in token.as_bytes().windows(3) {
        if let Ok(triple) = std::str::from_utf8(triple) {
            if COMMON_TRIGRAMS.contains(&triple) {
                score += 3;
            }
        }
    }
    if SUFFIXES.iter().any(|suffix| token.ends_with(suffix)) {
        score += 3;
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
    const COMMON_TRIGRAMS: &[&str] = &[
        "про", "ост", "ени", "ова", "ние", "ств", "ого", "ать", "это", "тор", "ско", "ной",
        "ова", "ель", "ени", "при", "раз", "как", "под", "без",
    ];
    const SUFFIXES: &[&str] = &[
        "ость", "ение", "ание", "ого", "ему", "ами", "ями", "ый", "ий", "ая", "ое", "ть", "ться",
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
    for triple in chars.windows(3) {
        let triple: String = triple.iter().collect();
        if COMMON_TRIGRAMS.contains(&triple.as_str()) {
            score += 3;
        }
    }
    if SUFFIXES.iter().any(|suffix| token.ends_with(suffix)) {
        score += 3;
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
        assert_eq!(decide("cdj,jle"), Decision::CorrectTo(Language::Russian));
        assert_eq!(decide("цштвщц"), Decision::CorrectTo(Language::English));
    }

    #[test]
    fn exact_dictionary_match_has_maximum_confidence() {
        let detection = detect("ghbdtn", &[]).expect("expected correction");
        assert_eq!(detection.corrected, "привет");
        assert_eq!(detection.confidence, 100);
    }

    #[test]
    fn user_dictionary_protects_source_word() {
        let words = vec!["ghbdtn".to_owned()];
        assert_eq!(
            decide_with_user_words("ghbdtn", &words, DEFAULT_CONFIDENCE_THRESHOLD),
            Decision::Keep
        );
    }

    #[test]
    fn user_dictionary_can_confirm_target_word() {
        let words = vec!["тестслово".to_owned()];
        let wrong = opposite_layout_text("тестслово", Language::Russian);
        let detection = detect(&wrong, &words).expect("custom target should be recognized");
        assert_eq!(detection.corrected, "тестслово");
        assert_eq!(detection.confidence, 100);
    }

    #[test]
    fn corrects_freedom_with_internal_oem_letter() {
        assert_eq!(
            correction("cdj,jle"),
            Some((Language::English, Language::Russian, "свободу".to_owned()))
        );
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
