//! Narrow reconciliation of Word's paragraph-start AutoCorrect capitalization.
//! Classification is never a substitute for exact native range verification.

pub fn prepare_once(
    read_prefix: impl FnOnce() -> Option<String>,
    expected: &str,
    replacement: &str,
) -> Option<(String, String)> {
    reconcile_suffix(&read_prefix()?, expected, replacement)
}

pub fn reconcile_suffix(
    prefix: &str,
    expected: &str,
    replacement: &str,
) -> Option<(String, String)> {
    if expected.is_empty() {
        return None;
    }
    if prefix.ends_with(expected) {
        return Some((expected.into(), replacement.into()));
    }
    let size = expected.chars().count();
    if size > 128 || replacement.chars().count() != size {
        return None;
    }
    let mut chars = expected.chars();
    let first = chars.next()?;
    if !first.is_lowercase() {
        return None;
    }
    let mut upper = first.to_uppercase();
    let capital = upper.next()?;
    if upper.next().is_some() || capital.len_utf16() != 1 || first.len_utf16() != 1 {
        return None;
    }
    let actual = format!("{capital}{}", chars.as_str());
    let before = prefix.strip_suffix(&actual)?;
    if !before.is_empty() && !before.ends_with('\r') {
        return None;
    }
    let mut chars = replacement.chars();
    let first = chars.next()?;
    if !first.is_lowercase() {
        return None;
    }
    let mut upper = first.to_uppercase();
    let capital = upper.next()?;
    if upper.next().is_some() || capital.len_utf16() != 1 || first.len_utf16() != 1 {
        return None;
    }
    Some((actual, format!("{capital}{}", chars.as_str())))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn word_autocapitalization_at_document_start_preserves_case_and_original() {
        assert_eq!(
            reconcile_suffix("Ghbdtn ", "ghbdtn ", "привет "),
            Some(("Ghbdtn ".into(), "Привет ".into()))
        );
    }

    #[test]
    fn later_native_paragraph_and_enter_delimiter_preserve_exact_boundaries() {
        assert_eq!(
            reconcile_suffix("text\rGhbdtn\r", "ghbdtn\r", "привет\r"),
            Some(("Ghbdtn\r".into(), "Привет\r".into()))
        );
        assert_eq!(
            reconcile_suffix("Привет\t", "привет\t", "ghbdtn\t"),
            Some(("Привет\t".into(), "Ghbdtn\t".into()))
        );
    }

    #[test]
    fn ordinary_exact_suffix_stays_exact_without_case_changes() {
        assert_eq!(
            reconcile_suffix("text ghbdtn ", "ghbdtn ", "привет "),
            Some(("ghbdtn ".into(), "привет ".into()))
        );
        assert_eq!(
            reconcile_suffix("GhbDtn", "GhbDtn", "ПриВет"),
            Some(("GhbDtn".into(), "ПриВет".into()))
        );
    }

    #[test]
    fn arbitrary_edits_delimiter_drift_and_nonparagraph_case_drift_are_refused() {
        for prefix in [
            "x Ghbdtn ",
            " Ghbdtn ",
            "Ghbdtm ",
            "GHBDTN ",
            "Ghbdtn",
            "Ghbdtn!",
            "Ghbdtn  ",
        ] {
            assert!(
                reconcile_suffix(prefix, "ghbdtn ", "привет ").is_none(),
                "{prefix}"
            );
        }
        assert!(reconcile_suffix("", "", "").is_none());
        assert!(reconcile_suffix("SS ", "ß ", "a ").is_none());
    }

    #[test]
    fn permanent_word_mismatch_reads_only_once_without_retry() {
        let mut reads = 0;
        let result = prepare_once(
            || {
                reads += 1;
                Some("different ".into())
            },
            "ghbdtn ",
            "привет ",
        );
        assert!(result.is_none());
        assert_eq!(reads, 1);
    }
}
