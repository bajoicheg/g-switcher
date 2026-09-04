use crate::{
    code_safe::is_code_safe_token,
    frequency_model,
    layout::opposite_layout_text,
    model::{Decision, Language},
};

pub const CONSERVATIVE_CONFIDENCE_THRESHOLD: u8 = 84;
pub const NORMAL_CONFIDENCE_THRESHOLD: u8 = 72;
pub const AGGRESSIVE_CONFIDENCE_THRESHOLD: u8 = 62;
pub const DEFAULT_CONFIDENCE_THRESHOLD: u8 = NORMAL_CONFIDENCE_THRESHOLD;
pub const MAX_CONTEXT_WORDS: usize = 2;

const RU_EXACT: &str = "а без безопасность беру берут был была были быть в вам вас весь вот все всё вы где да для до его ее ещё еще если есть же за здесь и из или как кабель когда коробка кто ли мне можно моё мой мы на надо нас не него нее нет но ну объект окно он она они от под подъезд пользователь потом проверка привет при про работа работает работаю раз с свобода свободе свободно свободой свободный свободу свободы себя сейчас сервер система сказать собака так там тебя теперь то только тоже тут ты у уже хлеб хорошо что чтобы это этого этот я ёлка";
const EN_EXACT: &str = "a about after all also and any api are as at be because been before box but by can check code data do docker edr for from good had has have he hello her here him his how http i if in into is it its json just linux more my no not now object of on one only or other our out root security server she so soc sql system than that the their them then there these they this to up user very vpn was we were what when which who will window windows with work would you your";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Detection {
    pub source: Language,
    pub target: Language,
    pub corrected: String,
    pub confidence: u8,
}

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

    let source = match infer_language(token) {
        Some(source) => source,
        None => punctuation_only_known_target_source(token, user_words)?,
    };
    let normalized = normalize(token, source);
    let source_frequency = frequency_model::word_score(source, &normalized);
    if dictionary_contains(source, &normalized, user_words) || source_frequency >= 15 {
        return None;
    }

    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    let mapped_normalized = normalize(&mapped, target);
    if !candidate_shape_is_valid(&mapped, target) {
        return None;
    }

    let target_frequency = frequency_model::word_score(target, &mapped_normalized);
    if dictionary_contains(target, &mapped_normalized, user_words) || target_frequency >= 15 {
        return Some(Detection {
            source,
            target,
            corrected: mapped,
            confidence: 100,
        });
    }

    // OEM punctuation can map to a letter in the opposite layout. Keep a known
    // target prefix intact until the remaining physical keys arrive.
    if is_target_word_prefix(&mapped_normalized, target, user_words) {
        return None;
    }

    let source_score =
        language_score(&normalized, source) + frequency_model::lexical_score(source, &normalized);
    let target_score = language_score(&mapped_normalized, target)
        + frequency_model::lexical_score(target, &mapped_normalized);
    let context_bonus = context_bonus(target, &mapped_normalized, previous_tokens, user_words);
    let effective_target = target_score + context_bonus;
    let effective_margin = target_score - source_score + context_bonus;

    if effective_target < 10 || effective_margin < 5 {
        return None;
    }

    // Unknown short words are especially ambiguous. Exact target matches have
    // already returned above; all other 3-letter candidates need context or a
    // frequency prior.
    if token.chars().count() == 3 && context_bonus < 10 && target_frequency == 0 {
        return None;
    }

    Some(Detection {
        source,
        target,
        corrected: mapped,
        confidence: confidence_from_scores(
            effective_target,
            effective_margin,
            target_frequency,
            source_frequency,
        ),
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
    opposite_candidate_is_prefix_for_language(token, source, user_words)
}

pub fn opposite_candidate_is_prefix_for_language(
    token: &str,
    source: Language,
    user_words: &[String],
) -> bool {
    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    if !candidate_shape_is_valid(&mapped, target) {
        return false;
    }
    is_target_word_prefix(&normalize(&mapped, target), target, user_words)
}

fn punctuation_only_known_target_source(token: &str, user_words: &[String]) -> Option<Language> {
    if token.chars().count() < 3
        || token
            .chars()
            .any(|ch| ch.is_ascii_alphanumeric() || is_ru_letter(ch) || ch.is_whitespace())
    {
        return None;
    }

    // A few Russian words can be typed entirely on OEM keys in the English
    // layout (for example, жэхэ -> ;'['). Only admit this otherwise
    // language-less shape when it maps to an already-known Russian target.
    // This keeps arbitrary punctuation fail-open.
    let source = Language::English;
    let target = Language::Russian;
    let mapped = opposite_layout_text(token, source);
    if !candidate_shape_is_valid(&mapped, target) {
        return None;
    }
    let normalized = normalize(&mapped, target);
    let known_target = dictionary_contains(target, &normalized, user_words)
        || frequency_model::word_score(target, &normalized) >= 15;
    known_target.then_some(source)
}

fn confidence_from_scores(
    target_score: i32,
    margin: i32,
    target_frequency: i32,
    source_frequency: i32,
) -> u8 {
    let frequency_margin = target_frequency - source_frequency;
    let raw = 43 + margin * 3 + target_score.max(0) / 2 + frequency_margin.max(0) / 2;
    raw.clamp(0, 96) as u8
}

fn context_bonus(
    target: Language,
    candidate: &str,
    previous_tokens: &[String],
    user_words: &[String],
) -> i32 {
    let recent: Vec<&String> = previous_tokens
        .iter()
        .rev()
        .take(MAX_CONTEXT_WORDS)
        .collect();
    let mut bonus = 0;
    for (index, token) in recent.iter().enumerate() {
        match trusted_context_language(token, user_words) {
            Some(language) if language == target => bonus += if index == 0 { 7 } else { 4 },
            Some(_) => bonus -= if index == 0 { 3 } else { 2 },
            None => {}
        }
    }
    if let Some(last) = recent.first() {
        if trusted_context_language(last, user_words) == Some(target) {
            let last = normalize(last, target);
            bonus += frequency_model::transition_score(target, &last, candidate);
        }
    }
    bonus.clamp(-6, 20)
}

fn trusted_context_language(token: &str, user_words: &[String]) -> Option<Language> {
    let language = infer_language(token)?;
    let normalized = normalize(token, language);
    let known = dictionary_contains(language, &normalized, user_words)
        || frequency_model::word_score(language, &normalized) >= 15;
    known.then_some(language)
}

fn is_target_word_prefix(token: &str, language: Language, user_words: &[String]) -> bool {
    frequency_model::has_word_prefix(language, token)
        || exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
        || user_words.iter().any(|word| {
            let normalized = normalize(word.trim(), language);
            !normalized.is_empty()
                && infer_language(&normalized) == Some(language)
                && normalized.starts_with(token)
                && normalized.len() > token.len()
        })
}

fn dictionary_contains(language: Language, token: &str, user_words: &[String]) -> bool {
    exact_words(language).any(|word| word == token)
        || user_words.iter().any(|word| {
            let word = word.trim();
            !word.is_empty()
                && infer_language(word) == Some(language)
                && normalize(word, language) == token
        })
}

fn exact_words(language: Language) -> impl Iterator<Item = &'static str> {
    match language {
        Language::Russian => RU_EXACT,
        Language::English => EN_EXACT,
    }
    .split_whitespace()
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
    let chars: Vec<char> = token.chars().collect();
    let vowel_count = chars.iter().filter(|ch| is_vowel(**ch, language)).count();
    let mut score = if vowel_count == 0 {
        -8
    } else {
        let ratio = vowel_count * 100 / chars.len();
        if (20..=70).contains(&ratio) {
            4
        } else {
            1
        }
    };

    if has_common_suffix(token, language) {
        score += 4;
    }
    score -= consonant_run_penalty(&chars, language);
    score -= repeated_letter_penalty(&chars);
    score
}

fn has_common_suffix(token: &str, language: Language) -> bool {
    const EN_SUFFIXES: &[&str] = &[
        "ing", "ed", "er", "ly", "tion", "ment", "ness", "able", "ous", "ive", "ize", "ise",
    ];
    const RU_SUFFIXES: &[&str] = &[
        "ость", "ение", "ание", "ого", "ему", "ами", "ями", "ый", "ий", "ая", "ое", "ть", "ться",
        "ный", "ная", "ные", "ов", "ев",
    ];
    match language {
        Language::English => EN_SUFFIXES,
        Language::Russian => RU_SUFFIXES,
    }
    .iter()
    .any(|suffix| token.ends_with(suffix))
}

fn consonant_run_penalty(chars: &[char], language: Language) -> i32 {
    let mut longest = 0usize;
    let mut current = 0usize;
    for ch in chars {
        if is_vowel(*ch, language) {
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

fn is_vowel(ch: char, language: Language) -> bool {
    match language {
        Language::Russian => matches!(
            ch,
            'а' | 'е' | 'ё' | 'и' | 'о' | 'у' | 'ы' | 'э' | 'ю' | 'я'
        ),
        Language::English => matches!(ch, 'a' | 'e' | 'i' | 'o' | 'u' | 'y'),
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
        assert_eq!(
            correction("rjhj,jxrf"),
            Some((Language::English, Language::Russian, "коробочка".to_owned()))
        );
        assert_eq!(decide("cdj,jle"), Decision::CorrectTo(Language::Russian));
        assert_eq!(decide("цштвщц"), Decision::CorrectTo(Language::English));
    }

    #[test]
    fn mixed_language_context_does_not_flip_plausible_source_tokens() {
        let french = vec!["les".to_owned(), "notres".to_owned()];
        assert!(
            correction_with_context("князь", &[], DEFAULT_CONFIDENCE_THRESHOLD, &french).is_none()
        );
        let russian = vec!["сказала".to_owned(), "она".to_owned()];
        assert!(
            correction_with_context("que", &[], DEFAULT_CONFIDENCE_THRESHOLD, &russian).is_none()
        );
    }

    #[test]
    fn unknown_foreign_context_does_not_suppress_known_wrong_layout_russian() {
        let french = vec!["chere".to_owned(), "annette".to_owned()];
        let detection =
            correction_with_context("crfpfk", &[], DEFAULT_CONFIDENCE_THRESHOLD, &french)
                .expect("сказал should correct after foreign context");
        assert_eq!(detection.corrected, "сказал");
    }

    #[test]
    fn symmetric_source_collisions_stay_fail_open() {
        for token in ["руку", "внук", "ста", "here", "dyer", "cnf"] {
            assert!(
                correction(token).is_none(),
                "collision token must stay source: {token}"
            );
        }
    }

    #[test]
    fn common_foreign_latin_source_words_are_protected() {
        for token in [
            "que", "sire", "une", "des", "monsieur", "comme", "ils", "mot", "quelle", "votre",
            "adieu", "dans", "die", "merci", "pas", "sans", "sur",
        ] {
            assert!(
                correction(token).is_none(),
                "Latin-layout source must stay source: {token}"
            );
        }
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
            "json",
            "http",
            "docker",
            "linux",
            "vpn",
            "edr",
            "soc",
            "security",
            "system",
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
    fn sensitivity_thresholds_are_strictly_ordered() {
        const {
            assert!(CONSERVATIVE_CONFIDENCE_THRESHOLD > NORMAL_CONFIDENCE_THRESHOLD);
            assert!(NORMAL_CONFIDENCE_THRESHOLD > AGGRESSIVE_CONFIDENCE_THRESHOLD);
        }
    }

    #[test]
    fn expanded_builtin_lexicon_protects_real_words() {
        for word in [
            "truth",
            "information",
            "company",
            "fuck",
            "shit",
            "пизда",
            "бля",
            "блять",
            "хуй",
            "ебать",
            "сука",
            "правда",
            "сегодня",
        ] {
            assert_eq!(decide(word), Decision::Keep, "changed valid word {word}");
        }
    }

    #[test]
    fn expanded_builtin_lexicon_corrects_wrong_layout_forms() {
        for (word, language) in [
            ("truth", Language::English),
            ("fuck", Language::English),
            ("пизда", Language::Russian),
            ("бля", Language::Russian),
            ("хуй", Language::Russian),
            ("ебать", Language::Russian),
        ] {
            let wrong = opposite_layout_text(word, language);
            assert_eq!(
                decide(&wrong),
                Decision::CorrectTo(language),
                "did not restore {word} from {wrong}"
            );
        }
    }
    #[test]
    fn frequency_model_protects_frequent_source_words() {
        for word in ["system", "security", "работа", "система"] {
            assert_eq!(decide(word), Decision::Keep, "changed frequent word {word}");
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

    #[test]
    fn infer_language_accepts_multiword_selected_text() {
        assert_eq!(infer_language("ghbdtn rfr ltkf"), Some(Language::English));
        assert_eq!(infer_language("руддщ цщкдв"), Some(Language::Russian));
        assert_eq!(infer_language("hello мир"), None);
    }
}
