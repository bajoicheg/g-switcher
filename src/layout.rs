use crate::model::Language;

const EN_TO_RU: &[(char, char)] = &[
    ('`', 'ё'),
    ('q', 'й'),
    ('w', 'ц'),
    ('e', 'у'),
    ('r', 'к'),
    ('t', 'е'),
    ('y', 'н'),
    ('u', 'г'),
    ('i', 'ш'),
    ('o', 'щ'),
    ('p', 'з'),
    ('[', 'х'),
    (']', 'ъ'),
    ('a', 'ф'),
    ('s', 'ы'),
    ('d', 'в'),
    ('f', 'а'),
    ('g', 'п'),
    ('h', 'р'),
    ('j', 'о'),
    ('k', 'л'),
    ('l', 'д'),
    (';', 'ж'),
    ('\'', 'э'),
    ('z', 'я'),
    ('x', 'ч'),
    ('c', 'с'),
    ('v', 'м'),
    ('b', 'и'),
    ('n', 'т'),
    ('m', 'ь'),
    (',', 'б'),
    ('.', 'ю'),
];

pub fn opposite_layout_text(text: &str, source: Language) -> String {
    text.chars().map(|ch| map_char(ch, source)).collect()
}

fn map_char(ch: char, source: Language) -> char {
    match source {
        Language::English => map_en_to_ru(ch),
        Language::Russian => map_ru_to_en(ch),
    }
}

fn map_en_to_ru(ch: char) -> char {
    // Shifted OEM keys are distinct physical keystrokes. ASCII case folding
    // cannot preserve them because punctuation has no upper/lower case.
    match ch {
        '~' => return 'Ё',
        '{' => return 'Х',
        '}' => return 'Ъ',
        ':' => return 'Ж',
        '"' => return 'Э',
        '<' => return 'Б',
        '>' => return 'Ю',
        '/' => return '.',
        '?' => return ',',
        _ => {}
    }

    let lower = ch.to_ascii_lowercase();
    if let Some((_, mapped)) = EN_TO_RU.iter().find(|(en, _)| *en == lower) {
        if ch.is_ascii_uppercase() {
            mapped.to_uppercase().next().unwrap_or(*mapped)
        } else {
            *mapped
        }
    } else {
        ch
    }
}

fn map_ru_to_en(ch: char) -> char {
    match ch {
        'Ё' => return '~',
        'Х' => return '{',
        'Ъ' => return '}',
        'Ж' => return ':',
        'Э' => return '"',
        'Б' => return '<',
        'Ю' => return '>',
        '.' => return '/',
        ',' => return '?',
        _ => {}
    }

    let lower = ch.to_lowercase().next().unwrap_or(ch);
    if let Some((mapped, _)) = EN_TO_RU.iter().find(|(_, ru)| *ru == lower) {
        if ch.is_uppercase() {
            mapped.to_ascii_uppercase()
        } else {
            *mapped
        }
    } else {
        ch
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_known_examples() {
        assert_eq!(opposite_layout_text("ghbdtn", Language::English), "привет");
        assert_eq!(opposite_layout_text("руддщ", Language::Russian), "hello");
        assert_eq!(
            opposite_layout_text("rjhj,rf", Language::English),
            "коробка"
        );
    }

    #[test]
    fn preserves_case_pattern() {
        assert_eq!(opposite_layout_text("Ghbdtn", Language::English), "Привет");
        assert_eq!(opposite_layout_text("GHBDTN", Language::English), "ПРИВЕТ");
        assert_eq!(opposite_layout_text("Руддщ", Language::Russian), "Hello");
    }

    #[test]
    fn preserves_shifted_oem_letters_and_punctuation() {
        assert_eq!(
            opposite_layout_text("<>~{}:\"?", Language::English),
            "БЮЁХЪЖЭ,"
        );
        assert_eq!(
            opposite_layout_text("БЮЁХЪЖЭ,.", Language::Russian),
            "<>~{}:\"?/"
        );
        assert_eq!(
            opposite_layout_text("Безопасность", Language::Russian),
            "<tpjgfcyjcnm"
        );
        assert_eq!(
            opposite_layout_text("<tpjgfcyjcnm", Language::English),
            "Безопасность"
        );
    }
}
