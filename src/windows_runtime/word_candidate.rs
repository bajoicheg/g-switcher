//! Pure plan from a fresh security-owned suffix; never a keyboard-text buffer.
use crate::model::Language;
#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Mode {
    Auto,
    Manual,
    Disabled,
}
#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum Trigger {
    Auto,
    Boundary,
    Manual,
    Previous,
}
pub(crate) struct Candidate {
    pub(crate) start: u32,
    pub(crate) original: String,
    pub(crate) replacement: String,
    pub(crate) source: Language,
    pub(crate) target: Language,
}
pub(crate) fn prepare(
    prefix: &str,
    mode: Mode,
    trigger: Trigger,
    auto_enabled: bool,
    layout_language: Language,
    words: &[String],
    threshold: u8,
) -> Option<Candidate> {
    if mode == Mode::Disabled || prefix.encode_utf16().count() > 32768 {
        return None;
    }
    let automatic = matches!(trigger, Trigger::Auto | Trigger::Boundary);
    if automatic && (mode != Mode::Auto || !auto_enabled) {
        return None;
    }
    let mut trimmed = prefix.trim_end_matches(char::is_whitespace);
    let whitespace_boundary = trimmed.len() != prefix.len();
    let punct = trimmed
        .char_indices()
        .next_back()
        .filter(|(_, ch)| matches!(ch, ',' | '.' | '/' | '?' | '!' | ';' | ':'))
        .filter(|(offset, ch)| {
            let start = trimmed[..*offset]
                .char_indices()
                .rev()
                .find(|(_, c)| c.is_whitespace())
                .map_or(0, |(i, c)| i + c.len_utf8());
            !crate::code_safe::is_code_safe_token(&trimmed[start..])
                && !(layout_language == Language::English
                    && matches!(ch, ',' | '.')
                    && crate::detector::opposite_candidate_is_prefix_for_language(
                        &trimmed[start..],
                        layout_language,
                        words,
                    ))
        });
    let boundary = whitespace_boundary || punct.is_some();
    if trigger == Trigger::Manual && boundary {
        return None;
    }
    if trigger == Trigger::Previous {
        if !boundary || (whitespace_boundary && punct.is_some()) {
            return None;
        }
        if !whitespace_boundary {
            trimmed = &trimmed[..punct?.0];
        }
    }

    let mut byte_start = trimmed
        .char_indices()
        .rev()
        .find(|(_, c)| c.is_whitespace())
        .map_or(0, |(i, c)| i + c.len_utf8());
    let segment_start = byte_start;
    let segment = &trimmed[segment_start..];
    if automatic && crate::code_safe::is_code_safe_token(segment) {
        return None;
    }
    // Reconstruct intra-token punctuation boundaries from fresh text. Retain OEM
    // comma/period only when the actual detector recognizes a target prefix.
    for (offset, ch) in segment.char_indices() {
        if matches!(ch, ',' | '.' | '?' | '!' | ';' | ':') && offset + ch.len_utf8() < segment.len()
        {
            let end = segment_start + offset + ch.len_utf8();
            let prospective = &trimmed[byte_start..end];
            let extends = layout_language == Language::English
                && matches!(ch, ',' | '.')
                && crate::detector::opposite_candidate_is_prefix_for_language(
                    prospective,
                    layout_language,
                    words,
                );
            if !extends {
                byte_start = end;
            }
        }
    }
    let token = &trimmed[byte_start..];
    if trigger == Trigger::Previous && crate::code_safe::is_code_safe_token(token) {
        return None;
    }
    if token.is_empty() || token.chars().count() > 256 {
        return None;
    }
    let mut context = prefix[..byte_start]
        .split_whitespace()
        .filter(|t| !crate::code_safe::is_code_safe_token(t))
        .flat_map(|t| t.split([',', '.', '?', '!', ';', ':']))
        .filter(|t| {
            crate::detector::infer_language(t).is_some() && !crate::code_safe::is_code_safe_token(t)
        })
        .rev()
        .take(crate::detector::MAX_CONTEXT_WORDS)
        .map(str::to_owned)
        .collect::<Vec<_>>();
    context.reverse();
    let (source, replacement) = if !automatic {
        let source = crate::detector::infer_language(token).unwrap_or(layout_language);
        (source, crate::layout::opposite_layout_text(token, source))
    } else {
        if crate::code_safe::is_code_safe_token(token) {
            return None;
        }
        // Same punctuation decision order: correct the complete prior word first;
        // otherwise allow OEM punctuation to remain part of a known target prefix.
        let before_punctuation = token.char_indices().next_back().and_then(|(i, ch)| {
            (i > 0
                && (matches!(ch, '/' | '?')
                    || (layout_language == Language::English && matches!(ch, ',' | '.'))))
            .then_some((i, ch))
        });
        let prior = before_punctuation.and_then(|(i, ch)| {
            let detection =
                crate::detector::correction_with_context(&token[..i], words, threshold, &context)?;
            (detection.source == layout_language)
                .then_some((detection.source, format!("{}{ch}", detection.corrected)))
        });
        if let Some(prior) = prior {
            prior
        } else {
            let detection = if boundary || trigger == Trigger::Boundary {
                crate::detector::correction_at_boundary_with_context(
                    token, words, threshold, &context,
                )
            } else {
                crate::detector::correction_with_context(token, words, threshold, &context)
            }?;
            if detection.source != layout_language {
                return None;
            }
            (detection.source, detection.corrected)
        }
    };
    if replacement == token {
        return None;
    }
    let trailing = &prefix[trimmed.len()..];
    let original = token.to_owned() + trailing;
    let replacement = replacement + trailing;
    let target = match source {
        Language::English => Language::Russian,
        Language::Russian => Language::English,
    };
    Some(Candidate {
        start: prefix[..byte_start].encode_utf16().count() as u32,
        original,
        replacement,
        source,
        target,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    fn auto(text: &str) -> Option<Candidate> {
        prepare(
            text,
            Mode::Auto,
            Trigger::Auto,
            true,
            Language::English,
            &[],
            crate::detector::DEFAULT_CONFIDENCE_THRESHOLD,
        )
    }
    #[test]
    fn adjacent_punctuation_keeps_only_current_suffix() {
        let c = auto("hello,ghbdtn").unwrap();
        assert_eq!(c.start, 6);
        assert_eq!(c.original, "ghbdtn");
        assert_eq!(c.replacement, "привет");
    }
    #[test]
    fn reconstructed_context_uses_existing_detector_decision() {
        let context = vec!["это".to_owned(), "в".to_owned()];
        let threshold = crate::detector::DEFAULT_CONFIDENCE_THRESHOLD;
        let expected = crate::detector::correction_with_context("vbh", &[], threshold, &context);
        let actual = auto("это,в vbh");
        assert_eq!(
            actual.as_ref().map(|c| c.replacement.as_str()),
            expected.as_ref().map(|d| d.corrected.as_str())
        );
        assert!(
            expected.is_some(),
            "known contextual regression must actually correct"
        );
    }
    #[test]
    fn no_space_ghbdtn_auto_keeps_exact_original() {
        let c = auto("ghbdtn").unwrap();
        assert_eq!(c.original, "ghbdtn");
        assert_eq!(c.replacement, "привет");
        assert_eq!(c.start, 0);
    }
    #[test]
    fn paragraph_autocapitalized_case_is_retained() {
        let c = auto("Ghbdtn").unwrap();
        assert_eq!(c.original, "Ghbdtn");
        assert_eq!(c.replacement, "Привет");
    }
    #[test]
    fn space_and_punctuation_stay_in_exact_caret_suffix() {
        for suffix in [" ", ",", "."] {
            let c = auto(&format!("ghbdtn{suffix}")).unwrap();
            assert_eq!(c.original, format!("ghbdtn{suffix}"));
            assert_eq!(c.replacement, format!("привет{suffix}"));
        }
    }
    #[test]
    fn manual_mode_never_accepts_activity_as_auto_permission() {
        assert!(prepare(
            "ghbdtn",
            Mode::Manual,
            Trigger::Auto,
            true,
            Language::English,
            &[],
            72
        )
        .is_none());
        assert!(prepare(
            "ghbdtn",
            Mode::Manual,
            Trigger::Manual,
            true,
            Language::English,
            &[],
            72
        )
        .is_some());
    }
    #[test]
    fn disabled_denies_both_auto_and_explicit_conversion() {
        for trigger in [Trigger::Auto, Trigger::Manual] {
            assert!(prepare(
                "ghbdtn",
                Mode::Disabled,
                trigger,
                true,
                Language::English,
                &[],
                72
            )
            .is_none());
        }
    }
    #[test]
    fn code_safe_activity_is_not_split_to_convert_its_letter_component() {
        for token in [
            "HOST-ghbdtn-01",
            "user@ghbdtn.test",
            "C:\\ghbdtn\\file",
            "--ghbdtn",
        ] {
            assert!(auto(token).is_none(), "{token}");
        }
    }
    #[test]
    fn previous_preserves_actual_punctuation_and_current_manual_refuses_boundary() {
        for suffix in [" ", "?", "/", ",", "."] {
            let text = format!("ghbdtn{suffix}");
            let c = prepare(
                &text,
                Mode::Manual,
                Trigger::Previous,
                true,
                Language::English,
                &[],
                72,
            )
            .expect("recognized previous-token boundary");
            assert_eq!(c.original, text);
            assert_eq!(c.replacement, format!("привет{suffix}"));
            assert!(prepare(
                &text,
                Mode::Manual,
                Trigger::Manual,
                true,
                Language::English,
                &[],
                72
            )
            .is_none());
        }
    }
    #[test]
    fn previous_word_requires_actual_delimiter() {
        assert!(prepare(
            "ghbdtn",
            Mode::Manual,
            Trigger::Previous,
            true,
            Language::English,
            &[],
            72
        )
        .is_none());
        assert_eq!(
            prepare(
                "ghbdtn ",
                Mode::Manual,
                Trigger::Previous,
                true,
                Language::English,
                &[],
                72
            )
            .unwrap()
            .replacement,
            "привет "
        );
    }
}
