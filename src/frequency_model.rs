use crate::model::Language;

const EN_TOP: &str = "the be to of and a in that have i it for not on with he as you do at this but his by from they we say her she or an will my one all would there their what so up out if about who get which go me when make can like time no just him know take people into year your good some could them see other than then now look only come its over think also back after use two how our work first well way even new want because these give day most us";
const EN_COMMON: &str = "hello world system server user security window windows data code check object root linux docker json http api sql vpn edr soc network service file application process input keyboard layout settings manual auto automatic current previous selected text word test release build update local private privacy password secure";
const RU_TOP: &str = "и в не на я быть он с что а по это она этот к но они мы как из у который то за свой весь год от так о для ты же все тот мочь вы человек такой его сказать только или ещё бы себя один уже до время если сам когда другой вот говорить наш мой знать стать при чтобы дело жизнь кто первый очень два день ее новый рука даже во со раз где там под можно ну какой после их работа без самый потом надо хотеть ли слово идти большой";
const RU_COMMON: &str = "привет система сервер пользователь безопасность окно данные код проверка объект сеть служба файл приложение процесс ввод клавиатура раскладка настройки ручной автоматический текущий предыдущий выделенный текст слово тест релиз сборка обновление локальный приватность пароль защита коробка свобода свободу свободный хорошо работает работаю";

const EN_BIGRAM_HIGH: &str =
    "th he in er an re on at en nd ti es or te of ed is it al ar st to nt ng se ha as ou io le";
const EN_TRIGRAM_HIGH: &str = "the and ing ion ent her for tha nth int ere ter est ers ati hat ate all eth hes ver his not you our rea";
const EN_RARE: &str = "qj qz jx zq xq wj jq zx xj wwq";

const RU_BIGRAM_HIGH: &str =
    "ст но то на ен ов ни ра во ко ро по пр ер ос ал го ли от ре та ть ан ор ка ло ва ит те ет";
const RU_TRIGRAM_HIGH: &str =
    "про ост ени ова ние ств ого ать это тор ско ной ель при раз как под без ист раб сер пол";
const RU_RARE: &str = "жы шы чя щя йй ъъ ьы ыы эы йь ъь";

const EN_PAIRS: &[(&str, &str, i32)] = &[
    ("hello", "world", 9),
    ("good", "morning", 8),
    ("thank", "you", 9),
    ("in", "the", 8),
    ("to", "the", 7),
    ("the", "system", 8),
    ("the", "user", 6),
    ("the", "server", 7),
    ("on", "the", 7),
    ("for", "the", 7),
];

const RU_PAIRS: &[(&str, &str, i32)] = &[
    ("добрый", "день", 9),
    ("как", "дела", 9),
    ("это", "важно", 8),
    ("в", "системе", 8),
    ("на", "работу", 7),
    ("в", "мир", 6),
    ("для", "пользователя", 7),
    ("на", "сервере", 7),
    ("в", "окне", 6),
];

pub fn lexical_score(language: Language, token: &str) -> i32 {
    word_score(language, token) + ngram_score(language, token)
}

pub fn word_score(language: Language, token: &str) -> i32 {
    let (top, common) = match language {
        Language::English => (EN_TOP, EN_COMMON),
        Language::Russian => (RU_TOP, RU_COMMON),
    };

    if let Some(index) = words(top).position(|word| word == token) {
        return match index {
            0..=19 => 26,
            20..=49 => 23,
            50..=79 => 20,
            _ => 17,
        };
    }
    if contains_word(common, token) {
        return 15;
    }
    0
}

pub fn transition_score(language: Language, previous: &str, current: &str) -> i32 {
    let pairs = match language {
        Language::English => EN_PAIRS,
        Language::Russian => RU_PAIRS,
    };
    pairs
        .iter()
        .find(|(left, right, _)| *left == previous && *right == current)
        .map(|(_, _, score)| *score)
        .unwrap_or(0)
}

fn ngram_score(language: Language, token: &str) -> i32 {
    match language {
        Language::English => ascii_ngram_score(token),
        Language::Russian => unicode_ngram_score(token),
    }
}

fn ascii_ngram_score(token: &str) -> i32 {
    let mut score = 0;
    for pair in token.as_bytes().windows(2) {
        if let Ok(pair) = std::str::from_utf8(pair) {
            if contains_word(EN_BIGRAM_HIGH, pair) {
                score += 2;
            }
            if contains_word(EN_RARE, pair) {
                score -= 5;
            }
        }
    }
    for triple in token.as_bytes().windows(3) {
        if let Ok(triple) = std::str::from_utf8(triple) {
            if contains_word(EN_TRIGRAM_HIGH, triple) {
                score += 3;
            }
        }
    }
    score.min(18)
}

fn unicode_ngram_score(token: &str) -> i32 {
    let chars: Vec<char> = token.chars().collect();
    let mut score = 0;
    for pair in chars.windows(2) {
        let pair: String = pair.iter().collect();
        if contains_word(RU_BIGRAM_HIGH, &pair) {
            score += 2;
        }
        if contains_word(RU_RARE, &pair) {
            score -= 5;
        }
    }
    for triple in chars.windows(3) {
        let triple: String = triple.iter().collect();
        if contains_word(RU_TRIGRAM_HIGH, &triple) {
            score += 3;
        }
    }
    score.min(18)
}

fn words(table: &str) -> impl Iterator<Item = &str> {
    table.split_ascii_whitespace()
}

fn contains_word(table: &str, token: &str) -> bool {
    words(table).any(|word| word == token)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frequent_words_score_higher_than_noise() {
        assert!(
            lexical_score(Language::English, "system") > lexical_score(Language::English, "qzxj")
        );
        assert!(
            lexical_score(Language::Russian, "система") > lexical_score(Language::Russian, "щжыы")
        );
    }

    #[test]
    fn common_phrase_transition_is_local_and_weighted() {
        assert!(transition_score(Language::English, "hello", "world") > 0);
        assert!(transition_score(Language::Russian, "добрый", "день") > 0);
        assert_eq!(transition_score(Language::English, "hello", "сервер"), 0);
    }
}
