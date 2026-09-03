from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


detector = Path("src/detector.rs")
text = detector.read_text(encoding="utf-8").replace("\r\n", "\n")
if "expanded_lexicon," not in text:
    replace_once(detector, "    frequency_model,\n", "    expanded_lexicon, frequency_model,\n")

replace_once(
    detector,
    """    if is_code_safe_token(token) || token.chars().count() < 3 {
        return None;
    }

    let source = infer_language(token)?;
""",
    """    let source = infer_language(token)?;
    if token.chars().count() < 3 {
        return detect_short_with_context(token, source, user_words, previous_tokens);
    }
""",
)

replace_once(
    detector,
    """    // OEM punctuation can map to a letter in the opposite layout. Keep a known
    // target prefix intact until the remaining physical keys arrive.
""",
    """    // Known target words beat generic identifier/code protection. This is
    // important for wrong-layout acronyms such as CIF -> США, while known
    // source acronyms such as NIST remain protected above.
    if is_code_safe_token(token) {
        return None;
    }

    // OEM punctuation can map to a letter in the opposite layout. Keep a known
    // target prefix intact until the remaining physical keys arrive.
""",
)

replace_once(
    detector,
    "pub fn correction(token: &str) -> Option<(Language, Language, String)> {\n",
    """fn detect_short_with_context(
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

    // One/two-key sequences are too ambiguous on their own. Require both
    // volatile context slots to agree with the target language (7 + 4 points).
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
""",
)

replace_once(
    detector,
    """    frequency_model::has_word_prefix(language, token)
        || exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
""",
    """    frequency_model::has_word_prefix(language, token)
        || expanded_lexicon::has_prefix(language, token)
        || exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
""",
)

replace_once(
    detector,
    """    exact_words(language).any(|word| word == token)
        || user_words.iter().any(|word| {
""",
    """    expanded_lexicon::contains(language, token)
        || exact_words(language).any(|word| word == token)
        || user_words.iter().any(|word| {
""",
)

runtime = Path("src/windows_runtime/mod.rs")
replace_once(
    runtime,
    """        (Language::English, VK_OEM_3, false) => Some('`'),
        (Language::English, VK_OEM_4, false) => Some('['),
        (Language::English, VK_OEM_6, false) => Some(']'),
        (Language::English, VK_OEM_1, false) => Some(';'),
        (Language::English, VK_OEM_7, false) => Some('\\''),
        (Language::English, VK_OEM_COMMA, false) => Some(','),
        (Language::English, VK_OEM_PERIOD, false) => Some('.'),
        (Language::English, VK_OEM_2, false) => Some('/'),
""",
    """        (Language::English, VK_OEM_3, false) => Some('`'),
        (Language::English, VK_OEM_3, true) => Some('~'),
        (Language::English, VK_OEM_4, false) => Some('['),
        (Language::English, VK_OEM_4, true) => Some('{'),
        (Language::English, VK_OEM_6, false) => Some(']'),
        (Language::English, VK_OEM_6, true) => Some('}'),
        (Language::English, VK_OEM_1, false) => Some(';'),
        (Language::English, VK_OEM_1, true) => Some(':'),
        (Language::English, VK_OEM_7, false) => Some('\\''),
        (Language::English, VK_OEM_7, true) => Some('"'),
        (Language::English, VK_OEM_COMMA, false) => Some(','),
        (Language::English, VK_OEM_COMMA, true) => Some('<'),
        (Language::English, VK_OEM_PERIOD, false) => Some('.'),
        (Language::English, VK_OEM_PERIOD, true) => Some('>'),
        (Language::English, VK_OEM_2, false) => Some('/'),
        (Language::English, VK_OEM_2, true) => Some('?'),
""",
)
