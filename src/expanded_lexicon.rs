use crate::model::Language;

// Corpus-driven additions discovered against the Russian Wikipedia article on
// information security. Keep this table local and deterministic: no runtime
// network lookup or user-text telemetry is involved.
const RU_SECURITY: &str = "англ атак атаки важны века вещей виде вне впервые вся гост дел задач ибп интернетом иными исо команд кцд лиц мест мэк над наименьшими наука норм оэср политик правил программ работ сей систем системы собой спрос ссср сторон сумел сша термин термина требует гост исо мэк оэср ссср сша ибп";
const EN_SECURITY: &str = "accountability availability bombe capability cia cism cissp crime denial dlp dos gdpr hexad identity ids iii infosec integrity ips isc ism iso nist non reliability unauthorized utility xix xviii xxi";

// One- and two-letter tokens are intrinsically ambiguous. They are eligible for
// correction only when the detector has strong same-language context.
const RU_SHORT_TARGETS: &str = "и в с а к о у я не на по из от до за во со но то же бы мы вы он их ее её ну ли ты";
const EN_SHORT_TARGETS: &str = "a i of to in it is be as at by or an my no up if me we he do so go us";

pub(crate) fn contains(language: Language, token: &str) -> bool {
    contains_word(long_table(language), token)
}

pub(crate) fn has_prefix(language: Language, token: &str) -> bool {
    long_table(language)
        .split_whitespace()
        .any(|word| word.starts_with(token) && word.len() > token.len())
}

pub(crate) fn is_short_target(language: Language, token: &str) -> bool {
    contains_word(short_table(language), token)
}

fn long_table(language: Language) -> &'static str {
    match language {
        Language::Russian => RU_SECURITY,
        Language::English => EN_SECURITY,
    }
}

fn short_table(language: Language) -> &'static str {
    match language {
        Language::Russian => RU_SHORT_TARGETS,
        Language::English => EN_SHORT_TARGETS,
    }
}

fn contains_word(table: &str, token: &str) -> bool {
    table.split_whitespace().any(|word| word == token)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn security_corpus_terms_are_local_lexicon_words() {
        for word in ["availability", "integrity", "unauthorized", "cissp", "nist", "gdpr"] {
            assert!(contains(Language::English, word), "missing EN term: {word}");
        }
        for word in ["сша", "ссср", "гост", "исо", "ибп", "правил", "системы"] {
            assert!(contains(Language::Russian, word), "missing RU term: {word}");
        }
    }

    #[test]
    fn short_targets_are_explicit_and_small() {
        assert!(is_short_target(Language::Russian, "и"));
        assert!(is_short_target(Language::Russian, "на"));
        assert!(is_short_target(Language::English, "to"));
        assert!(!is_short_target(Language::Russian, "иб"));
        assert!(!is_short_target(Language::English, "xx"));
    }
}
