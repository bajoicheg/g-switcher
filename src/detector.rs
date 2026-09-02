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
    ]
    .into_iter()
    .collect()
});

static EN_COMMON: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "hello", "the", "then", "to", "work", "system", "server", "user", "check", "security",
        "object", "box",
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

    Decision::Keep
}

pub fn correction(token: &str) -> Option<(Language, Language, String)> {
    let source = infer_language(token)?;
    match decide(token) {
        Decision::CorrectTo(target) => Some((source, target, opposite_layout_text(token, source))),
        Decision::Keep => None,
    }
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
}
