//! Pure, conservative planning for Word's native main-story coordinates.

pub const MAX_DOCUMENT_UNITS: usize = 1_048_576;
pub const MAX_REPLACEMENT_UNITS: usize = 128;

pub fn normalize_newlines(value: &str) -> String {
    value.replace("\r\n", "\r")
}

pub fn is_word_target(class: &str, executable: &str) -> bool {
    class == "_WwG"
        && executable
            .rsplit(['\\', '/'])
            .next()
            .is_some_and(|name| name.eq_ignore_ascii_case("WINWORD.EXE"))
}

pub fn mapped_document(document: &str, start: u32, end: u32) -> bool {
    start == 0
        && document.len() <= MAX_DOCUMENT_UNITS * 3
        && document.chars().all(|c| c.len_utf16() == 1)
        && document.encode_utf16().count() <= MAX_DOCUMENT_UNITS
        && document.encode_utf16().count() == end as usize
        && document.ends_with('\r')
}

pub fn available_selection(
    document: &str,
    document_start: u32,
    document_end: u32,
    start: u32,
    end: u32,
) -> bool {
    if !mapped_document(document, document_start, document_end) || start > end {
        return false;
    }
    if start == end {
        return end < document_end;
    }
    let Some((end, text)) = selection_text(document, document_start, document_end, start, end)
    else {
        return false;
    };
    Plan::new(
        document,
        document_start,
        document_end,
        start,
        end,
        &text,
        &text,
    )
    .is_some()
}

pub fn selection_text(
    document: &str,
    document_start: u32,
    document_end: u32,
    start: u32,
    mut end: u32,
) -> Option<(u32, String)> {
    if !mapped_document(document, document_start, document_end)
        || start >= end
        || end > document_end
    {
        return None;
    }
    if end == document_end {
        end = end.checked_sub(1)?;
    }
    if start >= end {
        return None;
    }
    Some((
        end,
        document
            .chars()
            .skip(start as usize)
            .take((end - start) as usize)
            .collect(),
    ))
}

pub fn selection_matches(
    selected_start: u32,
    selected_end: u32,
    start: u32,
    end: u32,
    document_end: u32,
) -> bool {
    (selected_start == start && selected_end == end)
        || (selected_start == end && selected_end == end)
        || (selected_start == start
            && selected_end == document_end
            && end.checked_add(1) == Some(document_end))
}

#[derive(Debug)]
pub struct Plan {
    pub before: String,
    pub after: String,
    pub start: u32,
    pub end: u32,
    pub replacement: Vec<char>,
    pub original: Vec<char>,
}

impl Plan {
    pub fn new(
        document: &str,
        document_start: u32,
        document_end: u32,
        start: u32,
        end: u32,
        expected: &str,
        replacement: &str,
    ) -> Option<Self> {
        let safe = |value: &str| {
            value.chars().all(|c| {
                c.len_utf16() == 1
                    && (!c.is_control() || matches!(c, '\r' | '\t'))
                    && c != '\u{fffc}'
            })
        };
        let size = expected.chars().count();
        if !mapped_document(document, document_start, document_end)
            || size == 0
            || size > MAX_REPLACEMENT_UNITS
            || replacement.chars().count() != size
            || !safe(expected)
            || !safe(replacement)
            || end.checked_sub(start)? as usize != size
            || end >= document_end
        {
            return None;
        }
        if expected
            .chars()
            .zip(replacement.chars())
            .any(|(a, b)| (a.is_control() || b.is_control()) && a != b)
        {
            return None;
        }
        let selected: String = document.chars().skip(start as usize).take(size).collect();
        if selected != expected {
            return None;
        }
        let replacement: Vec<char> = replacement.chars().collect();
        let mut plan = Self {
            before: document.into(),
            after: String::new(),
            start,
            end,
            replacement,
            original: expected.chars().collect(),
        };
        plan.after = plan.progress(size);
        Some(plan)
    }

    pub fn progress(&self, completed: usize) -> String {
        let mut characters: Vec<char> = self.before.chars().collect();
        for (offset, value) in self.replacement.iter().take(completed).enumerate() {
            characters[self.start as usize + offset] = *value;
        }
        characters.into_iter().collect()
    }

    pub fn range_progress(&self, completed: usize) -> String {
        let mut characters = self.original.clone();
        for (offset, value) in self.replacement.iter().take(completed).enumerate() {
            characters[offset] = *value;
        }
        characters.into_iter().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn word_routing_requires_both_native_class_and_process() {
        assert!(is_word_target("_WwG", "C:\\Office\\WINWORD.EXE"));
        assert!(!is_word_target("_WwG", "other.exe"));
        assert!(!is_word_target("Edit", "WINWORD.EXE"));
    }

    #[test]
    fn whole_selection_excludes_only_the_final_paragraph() {
        assert_eq!(
            selection_text("one\rtwo\r", 0, 8, 0, 8),
            Some((7, "one\rtwo".into()))
        );
        assert_eq!(
            selection_text("one\rtwo\r", 0, 8, 0, 4),
            Some((4, "one\r".into()))
        );
    }

    #[test]
    fn suffix_positions_use_native_coordinates_and_preserve_surroundings() {
        let plan = Plan::new("abc привет\r", 0, 11, 4, 10, "привет", "ghbdtn").unwrap();
        assert_eq!(plan.after, "abc ghbdtn\r");
        assert_eq!(plan.progress(2), "abc ghивет\r");
        assert_eq!(plan.start, 4);
        assert_eq!(plan.end, 10);
    }

    #[test]
    fn native_enter_and_tab_delimiters_are_normalized_and_preserved() {
        let expected = normalize_newlines("ghbdtn\r\n");
        let replacement = normalize_newlines("привет\r\n");
        let plan = Plan::new("ghbdtn\r\r", 0, 8, 0, 7, &expected, &replacement).unwrap();
        assert_eq!(plan.after, "привет\r\r");
        assert_eq!(plan.replacement[6], '\r');
        assert!(Plan::new("abc\tdef\r", 0, 8, 0, 7, "abc\tdef", "ABC\tDEF").is_some());
        assert!(Plan::new("abc\tdef\r", 0, 8, 0, 7, "abc\tdef", "ABC DEF").is_none());
    }

    #[test]
    fn availability_refuses_unsupported_selection_before_hotkey_admission() {
        assert!(available_selection("abc\r", 0, 4, 3, 3));
        assert!(available_selection("abc\r", 0, 4, 0, 4));
        assert!(!available_selection("x😀abc\r", 0, 7, 6, 6));
        assert!(!available_selection("abc\r", 0, 4, 4, 4));
        let long = "x".repeat(MAX_REPLACEMENT_UNITS + 1) + "\r";
        assert!(!available_selection(
            &long,
            0,
            long.len() as u32,
            0,
            long.len() as u32
        ));
    }

    #[test]
    fn unsupported_mapping_and_structure_cannot_produce_a_write_plan() {
        for (document, start, end, expected, replacement) in [
            ("x😀abc\r", 3, 6, "abc", "def"),
            ("abc\r", 0, 3, "abc", "abcd"),
            ("abc\r", 0, 4, "abc\r", "def\r"),
            ("a\u{13}b\r", 0, 3, "a\u{13}b", "def"),
            ("abc\r", 0, 3, "wrong", "right"),
        ] {
            assert!(Plan::new(
                document,
                0,
                document.encode_utf16().count() as u32,
                start,
                end,
                expected,
                replacement
            )
            .is_none());
        }
        assert!(Plan::new("abc\r", 1, 5, 1, 4, "abc", "def").is_none());
    }

    #[test]
    fn selection_binding_accepts_exact_range_or_caret_and_terminal_paragraph_only() {
        assert!(selection_matches(2, 5, 2, 5, 9));
        assert!(selection_matches(5, 5, 2, 5, 9));
        assert!(selection_matches(0, 9, 0, 8, 9));
        assert!(!selection_matches(1, 5, 2, 5, 9));
        assert!(!selection_matches(0, 7, 0, 6, 9));
    }
}
