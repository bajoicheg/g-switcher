$ErrorActionPreference = 'Stop'

function Replace-Once([string]$Path, [string]$Old, [string]$New) {
    $text = [IO.File]::ReadAllText($Path)
    $count = ([regex]::Matches($text, [regex]::Escape($Old))).Count
    if ($count -ne 1) { throw "${Path}: expected one match, got $count" }
    [IO.File]::WriteAllText($Path, $text.Replace($Old, $New), [Text.UTF8Encoding]::new($false))
}

$detector = 'src/detector.rs'
$text = [IO.File]::ReadAllText($detector)
if (-not $text.Contains('expanded_lexicon,')) {
    Replace-Once $detector "    frequency_model,`n" "    expanded_lexicon, frequency_model,`n"
}

Replace-Once $detector @'
    if is_code_safe_token(token) || token.chars().count() < 3 {
        return None;
    }

    let source = infer_language(token)?;
'@ @'
    let source = infer_language(token)?;
    if token.chars().count() < 3 {
        return detect_short_with_context(token, source, user_words, previous_tokens);
    }
'@

Replace-Once $detector @'
    // OEM punctuation can map to a letter in the opposite layout. Keep a known
    // target prefix intact until the remaining physical keys arrive.
'@ @'
    // Known target words beat generic identifier/code protection. This is
    // important for wrong-layout acronyms such as CIF -> США, while known
    // source acronyms such as NIST remain protected above.
    if is_code_safe_token(token) {
        return None;
    }

    // OEM punctuation can map to a letter in the opposite layout. Keep a known
    // target prefix intact until the remaining physical keys arrive.
'@

Replace-Once $detector @'
pub fn correction(token: &str) -> Option<(Language, Language, String)> {
'@ @'
fn detect_short_with_context(
    token: &str,
    source: Language,
    user_words: &[String],
    previous_tokens: &[String],
) -> Option<Detection> {
    if is_code_safe_token(token) {
        return None;
    }

    let normalized = normalize(token, source);
    if dictionary_contains(source, &normalized, user_words)
        || frequency_model::word_score(source, &normalized) >= 15
    {
        return None;
    }

    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    let mapped_normalized = normalize(&mapped, target);
    if !candidate_shape_is_valid(&mapped, target)
        || !expanded_lexicon::is_short_target(target, &mapped_normalized)
    {
        return None;
    }

    // A single/two-key sequence is too ambiguous on its own. Require both
    // volatile context slots to point to the target language (7 + 4 points).
    if context_bonus(target, &mapped_normalized, previous_tokens) < 10 {
        return None;
    }

    Some(Detection {
        source,
        target,
        corrected: mapped,
        confidence: 94,
    })
}

pub fn correction(token: &str) -> Option<(Language, Language, String)> {
'@

Replace-Once $detector @'
    frequency_model::has_word_prefix(language, token)
        || exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
'@ @'
    frequency_model::has_word_prefix(language, token)
        || expanded_lexicon::has_prefix(language, token)
        || exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
'@

Replace-Once $detector @'
    exact_words(language).any(|word| word == token)
        || user_words.iter().any(|word| {
'@ @'
    expanded_lexicon::contains(language, token)
        || exact_words(language).any(|word| word == token)
        || user_words.iter().any(|word| {
'@

Replace-Once $detector @'
    #[test]
    fn exact_dictionary_match_has_maximum_confidence() {
'@ @'
    #[test]
    fn corpus_security_terms_and_acronyms_are_corrected() {
        for expected in ["availability", "integrity", "unauthorized", "cissp", "nist", "gdpr"] {
            let wrong = opposite_layout_text(expected, Language::English);
            let detection = detect(&wrong, &[]).expect("EN corpus word should correct");
            assert_eq!(detection.corrected.to_lowercase(), expected);
            assert_eq!(detection.confidence, 100);
            assert!(detect(expected, &[]).is_none(), "correct EN source changed: {expected}");
        }
        for expected in ["сша", "сср", "гост", "исо", "ибп"] {
            let wrong = opposite_layout_text(expected, Language::Russian);
            let detection = detect(&wrong, &[]).expect("RU acronym should correct");
            assert_eq!(detection.corrected.to_lowercase(), expected);
            assert_eq!(detection.confidence, 100);
        }
    }

    #[test]
    fn short_function_words_require_strong_target_context() {
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
    fn exact_dictionary_match_has_maximum_confidence() {
'@

$runtime = 'src/windows_runtime/mod.rs'
Replace-Once $runtime @'
        (Language::English, VK_OEM_3, false) => Some('`'),
        (Language::English, VK_OEM_4, false) => Some('['),
        (Language::English, VK_OEM_6, false) => Some(']'),
        (Language::English, VK_OEM_1, false) => Some(';'),
        (Language::English, VK_OEM_7, false) => Some('\''),
        (Language::English, VK_OEM_COMMA, false) => Some(','),
        (Language::English, VK_OEM_PERIOD, false) => Some('.'),
        (Language::English, VK_OEM_2, false) => Some('/'),
'@ @'
        (Language::English, VK_OEM_3, false) => Some('`'),
        (Language::English, VK_OEM_3, true) => Some('~'),
        (Language::English, VK_OEM_4, false) => Some('['),
        (Language::English, VK_OEM_4, true) => Some('{'),
        (Language::English, VK_OEM_6, false) => Some(']'),
        (Language::English, VK_OEM_6, true) => Some('}'),
        (Language::English, VK_OEM_1, false) => Some(';'),
        (Language::English, VK_OEM_1, true) => Some(':'),
        (Language::English, VK_OEM_7, false) => Some('\''),
        (Language::English, VK_OEM_7, true) => Some('"'),
        (Language::English, VK_OEM_COMMA, false) => Some(','),
        (Language::English, VK_OEM_COMMA, true) => Some('<'),
        (Language::English, VK_OEM_PERIOD, false) => Some('.'),
        (Language::English, VK_OEM_PERIOD, true) => Some('>'),
        (Language::English, VK_OEM_2, false) => Some('/'),
        (Language::English, VK_OEM_2, true) => Some('?'),
'@

cargo fmt --all
