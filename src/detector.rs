use std::collections::HashSet;

use once_cell::sync::Lazy;

use crate::{
    code_safe::is_code_safe_token,
    layout::opposite_layout_text,
    model::{Decision, Language},
};

pub const DEFAULT_CONFIDENCE_THRESHOLD: u8 = 72;
pub const MAX_CONTEXT_WORDS: usize = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Detection {
    pub source: Language,
    pub target: Language,
    pub corrected: String,
    pub confidence: u8,
}

static RU_COMMON: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "а",
        "без",
        "беру",
        "берут",
        "был",
        "была",
        "были",
        "быть",
        "в",
        "вам",
        "вас",
        "весь",
        "вот",
        "все",
        "всё",
        "вы",
        "где",
        "да",
        "для",
        "до",
        "его",
        "ее",
        "ещё",
        "еще",
        "если",
        "есть",
        "же",
        "за",
        "здесь",
        "и",
        "из",
        "или",
        "как",
        "кабель",
        "когда",
        "коробка",
        "кто",
        "ли",
        "мне",
        "можно",
        "моё",
        "мой",
        "мы",
        "на",
        "надо",
        "нас",
        "не",
        "него",
        "нее",
        "нет",
        "но",
        "ну",
        "объект",
        "окно",
        "он",
        "она",
        "они",
        "от",
        "под",
        "подъезд",
        "пользователь",
        "потом",
        "проверка",
        "привет",
        "при",
        "про",
        "работа",
        "работает",
        "работаю",
        "раз",
        "с",
        "свобода",
        "свободе",
        "свободно",
        "свободой",
        "свободный",
        "свободу",
        "свободы",
        "себя",
        "сейчас",
        "сервер",
        "система",
        "сказать",
        "так",
        "там",
        "тебя",
        "теперь",
        "то",
        "только",
        "тоже",
        "тут",
        "ты",
        "у",
        "уже",
        "хлеб",
        "хорошо",
        "что",
        "чтобы",
        "это",
        "этого",
        "этот",
        "я",
        "ёлка",
        "безопасность",
        "собака",
    ]
    .into_iter()
    .collect()
});

static EN_COMMON: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "a",
        "about",
        "after",
        "all",
        "also",
        "and",
        "any",
        "api",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "box",
        "but",
        "by",
        "can",
        "check",
        "code",
        "data",
        "do",
        "docker",
        "edr",
        "for",
        "from",
        "good",
        "had",
        "has",
        "have",
        "he",
        "hello",
        "her",
        "here",
        "him",
        "his",
        "how",
        "http",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "json",
        "just",
        "linux",
        "more",
        "my",
        "no",
        "not",
        "now",
        "object",
        "of",
        "on",
        "one",
        "only",
        "or",
        "other",
        "our",
        "out",
        "root",
        "security",
        "server",
        "she",
        "so",
        "soc",
        "sql",
        "system",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "up",
        "user",
        "very",
        "vpn",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "window",
        "windows",
        "with",
        "work",
        "would",
        "you",
        "your",
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
    decide_with_context(token, user_words, confidence_threshold, &[])
}

pub fn decide_with_context(
    token: &str,
    user_words: &[String],
    confidence_threshold: u8,
    previous_tokens: &[String],
) -> Decision {
    let Some(detection) = detect_with_context(token, user_words, previous_tokens) else {
        return Decision::Keep;
    };
    if detection.confidence >= confidence_threshold {
        Decision::CorrectTo(detection.target)
    } else {
        Decision::Keep
    }
}

pub fn detect(token: &str, user_words: &[String]) -> Option<Detection> {
    detect_with_context(token, user_words, &[])
}

pub fn detect_with_context(
    token: &str,
    user_words: &[String],
    previous_tokens: &[String],
) -> Option<Detection> {
    if is_code_safe_token(token) || token.chars().count() < 3 {
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

    if dictionary_contains(target, &mapped_normalized, user_words) {
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
    let context_bonus = context_bonus(target, &mapped_normalized, previous_tokens);
    let effective_target = target_score + context_bonus;
    let effective_margin = target_score - source_score + context_bonus;

    if effective_target < 8 || effective_margin < 4 {
        return None;
    }

    // Three-letter words are intrinsically ambiguous. Let them pass only when the
    // surrounding two-word context supplies a strong signal.
    if token.chars().count() == 3 && target_score < 8 && context_bonus < 10 {
        return None;
    }

    let confidence = confidence_from_scores(effective_target, effective_margin);
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
    correction_with_context(token, user_words, confidence_threshold, &[])
}

pub fn correction_with_context(
    token: &str,
    user_words: &[String],
    confidence_threshold: u8,
    previous_tokens: &[String],
) -> Option<Detection> {
    let detection = detect_with_context(token, user_words, previous_tokens)?;
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
    let raw = 46 + margin * 4 + target_score.max(0) / 2;
    raw.clamp(0, 95) as u8
}

fn context_bonus(target: Language, candidate: &str, previous_tokens: &[String]) -> i32 {
    let recent: Vec<&String> = previous_tokens.iter().rev().take(MAX_CONTEXT_WORDS).collect();
    let mut bonus = 0;

    for (index, token) in recent.iter().enumerate() {
        match infer_language(token) {
            Some(language) if language == target => bonus += if index == 0 { 7 } else { 4 },
            Some(_) => bonus -= if index == 0 { 3 } else { 2 },
            None => {}
        }
    }

    if let Some(last) = recent.first() {
        if infer_language(last) == Some(target) {
            let last = normalize(last, target);
            if common_phrase_pair(target, &last, candidate) {
                bonus += 6;
            }
        }
    }

    bonus.clamp(-6, 18)
}

fn common_phrase_pair(language: Language, previous: &str, current: &str) -> bool {
    const RU_PAIRS: &[(&str, &str)] = &[
        ("в", "мир"),
        ("в", "системе"),
        ("как", "дела"),
        ("добрый", "день"),
        ("на", "работу"),
        ("это", "важно"),
    ];
    const EN_PAIRS: &[(&str, &str)] = &[
        ("good", "morning"),
        ("hello", "world"),
        ("in", "the"),
        ("thank", "you"),
        ("the", "system"),
        ("to", "the"),
    ];

    match language {
        Language::Russian => RU_PAIRS,
        Language::English => EN_PAIRS,
    }
    .contains(&(previous, current))
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
        "be", "ma", "si", "om", "ur", "ca", "el", "la", "ns", "di", "fo", "ho", "pe", "ec", "pr",
    ];
    const COMMON_TRIGRAMS: &[&str] = &[
        "the", "and", "ing", "ion", "ent", "her", "for", "tha", "nth", "int", "ere", "ter", "est",
        "ers", "ati", "hat", "ate", "all", "eth", "hes", "ver", "his", "oft", "ith", "not", "you",
        "our", "rea", "com", "pro", "con", "sta",
    ];
    const COMMON_FOUR: &[&str] = &[
        "tion", "ther", "that", "with", "ment", "ions", "this", "here", "ould", "ight", "have", "from",
    ];
    const SUFFIXES: &[&str] = &[
        "ing", "ed", "er", "ly", "tion", "ment", "ness", "able", "ous", "ive", "ize", "ise",
    ];
    const RARE: &[&str] = &[
        "qj", "qz", "jx", "zq", "xq", "wj", "jq", "vh", "hg", "zx", "xj", "vv", "wwq",
    ];

    let mut score = 0;
    let chars: Vec<char> = token.chars().collect();
    let vowels = chars
        .iter()
        .filter(|ch| matches!(ch, 'a' | 'e' | 'i' | 'o' | 'u' | 'y'))
        .count();
    if vowels == 0 {
        score -= 8;
    } else {
        let ratio = vowels * 100 / chars.len();
        score += if (20..=70).contains(&ratio) { 4 } else { 1 };
    }

    for pair in token.as_bytes().windows(2) {
        if let Ok(pair) = std::str::from_utf8(pair) {
            if COMMON.contains(&pair) {
                score += 2;
            }
            if RARE.contains(&pair) {
                score -= 4;
            }
        }
    }
    for triple in token.as_bytes().windows(3) {
        if let Ok(triple) = std::str::from_utf8(triple) {
            if COMMON_TRIGRAMS.contains(&triple) {
                score += 4;
            }
            if RARE.contains(&triple) {
                score -= 5;
            }
        }
    }
    for four in token.as_bytes().windows(4) {
        if let Ok(four) = std::str::from_utf8(four) {
            if COMMON_FOUR.contains(&four) {
                score += 5;
            }
        }
    }
    if SUFFIXES.iter().any(|suffix| token.ends_with(suffix)) {
        score += 4;
    }
    score -= consonant_run_penalty(&chars, Language::English);
    score -= repeated_letter_penalty(&chars);
    score
}

fn score_russian(token: &str) -> i32 {
    const COMMON: &[&str] = &[
        "ст", "но", "то", "на", "ен", "ов", "ни", "ра", "во", "ко", "ро", "по", "пр", "ер", "ос",
        "ал", "го", "ли", "от", "ре", "та", "ть", "ан", "ор", "ка", "ло", "ва", "ит", "те", "ет",
        "ел", "ри", "не", "де", "ам", "ла", "ве", "ие", "ис", "ол", "ле", "ся", "ин", "тр", "ом",
        "ма", "ме", "до", "че", "об", "бо", "ми", "ир", "си", "ем", "ты", "бы", "за", "ск", "од",
    ];
    const COMMON_TRIGRAMS: &[&str] = &[
        "про", "ост", "ени", "ова", "ние", "ств", "ого", "ать", "это", "тор", "ско", "ной", "ова",
        "ель", "ени", "при", "раз", "как", "под", "без", "ист", "раб", "сер", "пол", "ние", "ова",
    ];
    const COMMON_FOUR: &[&str] = &[
        "ение", "ость", "ного", "овой", "ство", "тель", "ного", "ться", "ской", "работ", "сист",
    ];
    const SUFFIXES: &[&str] = &[
        "ость", "ение", "ание", "ого", "ему", "ами", "ями", "ый", "ий", "ая", "ое", "ть", "ться",
        "ный", "ная", "ные", "ов", "ев",
    ];
    const RARE: &[&str] = &[
        "жы", "шы", "чя", "щя", "йй", "ъъ", "ьы", "ыы", "эы", "йь", "ъь",
    ];

    let mut score = 0;
    let chars: Vec<char> = token.chars().collect();
    let vowels = chars
        .iter()
        .filter(|ch| {
            matches!(
                ch,
                'а' | 'е' | 'ё' | 'и' | 'о' | 'у' | 'ы' | 'э' | 'ю' | 'я'
            )
        })
        .count();
    if vowels == 0 {
        score -= 8;
    } else {
        let ratio = vowels * 100 / chars.len();
        score += if (20..=70).contains(&ratio) { 4 } else { 1 };
    }

    for pair in chars.windows(2) {
        let pair: String = pair.iter().collect();
        if COMMON.contains(&pair.as_str()) {
            score += 2;
        }
        if RARE.contains(&pair.as_str()) {
            score -= 4;
        }
    }
    for triple in chars.windows(3) {
        let triple: String = triple.iter().collect();
        if COMMON_TRIGRAMS.contains(&triple.as_str()) {
            score += 4;
        }
    }
    for four in chars.windows(4) {
        let four: String = four.iter().collect();
        if COMMON_FOUR.contains(&four.as_str()) {
            score += 5;
        }
    }
    if SUFFIXES.iter().any(|suffix| token.ends_with(suffix)) {
        score += 4;
    }
    score -= consonant_run_penalty(&chars, Language::Russian);
    score -= repeated_letter_penalty(&chars);
    score
}

fn consonant_run_penalty(chars: &[char], language: Language) -> i32 {
    let mut longest = 0usize;
    let mut current = 0usize;
    for ch in chars {
        let vowel = match language {
            Language::Russian => matches!(
                ch,
                'а' | 'е' | 'ё' | 'и' | 'о' | 'у' | 'ы' | 'э' | 'ю' | 'я'
            ),
            Language::English => matches!(ch, 'a' | 'e' | 'i' | 'o' | 'u' | 'y'),
        };
        if vowel {
            current = 0;
        } else {
            current += 1;
            longest = longest.max(current);
        }
    }
    match longest {
        0..=3 => 0,
        4 => 2,
        5 => 5,
        _ => 8,
    }
}

fn repeated_letter_penalty(chars: &[char]) -> i32 {
    if chars
        .windows(3)
        .any(|window| window[0] == window[1] && window[1] == window[2])
    {
        5
    } else {
        0
    }
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
            "беру", "берут", "ещё", "еще", "ёлка", "всё", "моё", "объект", "подъезд",
            "hello", "the", "then", "json", "http", "docker", "linux", "vpn", "edr", "soc",
        ] {
            assert_eq!(decide(word), Decision::Keep, "changed {word}");
        }
    }

    #[test]
    fn russian_context_can_resolve_short_ambiguous_word() {
        let context = vec!["это".to_owned(), "в".to_owned()];
        assert_eq!(decide("vbh"), Decision::Keep);
        assert_eq!(
            decide_with_context("vbh", &[], DEFAULT_CONFIDENCE_THRESHOLD, &context),
            Decision::CorrectTo(Language::Russian)
        );
    }

    #[test]
    fn opposite_language_context_does_not_force_a_correction() {
        let context = vec!["this".to_owned(), "is".to_owned()];
        assert_eq!(
            decide_with_context("vbh", &[], DEFAULT_CONFIDENCE_THRESHOLD, &context),
            Decision::Keep
        );
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
