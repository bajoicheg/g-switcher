use crate::{frequent_forms, model::Language};

const EN_TOP: &str = "the be to of and a in that have i it for not on with he as you do at this but his by from they we say her she or an will my one all would there their what so up out if about who get which go me when make can like time no just him know take people into year your good some could them see other than then now look only come its over think also back after use two how our work first well way even new want because these give day most us";
const EN_COMMON: &str = concat!(
    "abc adieu avec ayez bah bas bien bon bonsoir causons cela celui ces chef comme contez contrat croyez dans das des devriez die dieu dont ein elle enfant enfin epe euer faire fait fameuse faut feu fil filez gobelins gott homme ils jeu jeune joseph julie lanfrey lle macht merci mes monsieur mot mots nichts nocturne omme ont pas peut pitt poltawa prime que quel quelle quelques quos sans sic sire sobriquet son sophie soyez sublime sur tant tutti une urienne vaut venez vienne vos votre voyez zum dyer ren ytd cnf lev hello world system server user security window windows data code check object root linux docker json http api sql vpn edr soc network service file application process input keyboard layout settings manual auto automatic current previous selected text word test release build update local private privacy password secure ",
    "truth true false fact facts real reality reason result answer question idea ideas mind thought thoughts knowledge information message messages email chat browser chrome edge firefox terminal powershell github git rust computer software hardware device devices screen display mouse key keys button buttons menu dialog form field fields list lists dictionary lexicon frequency confidence sensitivity conservative normal aggressive ",
    "convert conversion correction undo hotkey pause resume start stop run running open close save cancel add remove change changed create delete edit read write search find show hide enable disable enabled disabled allow block protect protected protection safe unsafe error errors warning warnings problem problems issue issues bug bugs fix fixes version versions package packages install installed setup ",
    "account accounts admin administrator client clients host hosts domain domains address addresses port ports protocol protocols internet web website websites page pages link links url path paths folder folders disk drive drives memory ram cpu gpu thread threads event events state states status mode modes rule rules policy policies access login logon logout signin signout authentication authorization token tokens certificate certificates secret secrets cloud telemetry clipboard history context remote public internal external ",
    "company business office home house room street road city country countries people person persons man men woman women child children family families friend friends team teams group groups member members customer customers partner partners project projects product products work works working job jobs task tasks case cases time times day days week weeks month months year years today tomorrow yesterday morning evening night now later early late ",
    "first second third last next old good better best bad worse worst big small large little long short high low right left top bottom inside outside before after during while until since always never often sometimes usually again already almost enough more most less least many much few several some any every each both either neither another other same different important possible impossible available ready free busy hard easy simple complex fast slow strong weak full empty common normal general special main major minor basic advanced final initial original future past ",
    "value values number numbers amount total part parts side sides point points line lines name names type types kind kinds form forms level levels order orders place places area areas body head hand hands face eye eyes voice sound food water air fire earth money market markets price prices cost costs power energy health school education study studies learn learning book books story stories language languages english russian love hate ",
    "want need needs use uses using make makes made get gets got give gives gave take takes took keep keeps kept know knows knew think thinks thought feel feels felt see sees saw look looks looked come comes came go goes went say says said tell tells told ask asks asked call calls called try tries tried help helps helped move moves moved live lives lived believe believes believed understand understands understood remember remembers remembered forget forgot find finds found lose loses lost win wins won play plays played read reads write writes written speak speaks spoke listen hear heard wait waits waited happen happens happened become becomes became seem seems seemed leave leaves left bring brings brought hold holds held follow follows followed meet meets met pay pays paid sit sits sat stand stands stood include includes included continue continues continued set sets lead leads led watch watches watched turn turns turned show shows showed grow grows grew buy buys bought send sends sent fall falls fell cut cuts reach reaches reached remain remains suggest suggests raise raises pass passes sell sells sold require requires report reports reported decide decides decided pull pulls return returns explain explains hope hopes develop develops carry carries break breaks broke receive receives received agree agrees support supports hit hits produce produces eat eats ate cover covers catch catches caught draw draws drew choose chooses chose cause causes caused realize involve increase improve improves join reduce pick wear wears wore drive drives drove deal deals ",
    "fuck fucking fucked fucks fucker fuckers shit shitty shits bullshit bitch bitches bastard bastards ass asses asshole assholes dick dicks pussy pussies cunt cunts damn damned crap motherfucker motherfuckers hell sex sexy porn cock cocks tits tit boob boobs jerk jerks idiot idiots stupid dumb moron morons wtf omg god"
);
const RU_TOP: &str = "и в не на я быть он с что а по это она этот к но они мы как из у который то за свой весь год от так о для ты же все тот мочь вы человек такой его сказать только или ещё бы себя один уже до время если сам когда другой вот говорить наш мой знать стать при чтобы дело жизнь кто первый очень два день ее новый рука даже во со раз где там под можно ну какой после их работа без самый потом надо хотеть ли слово идти большой";
const RU_COMMON: &str = concat!(
    "альфонс анне вдруг вернейший взглянув внук вокруг вошла враг всего вышел вышла граф графиня давно даму донесенья другая думал душевно знавшие княгиня князь крикнул курагина кутузов лучшие мешала мишо могли нашего нечего одна одни откинув откуда паулучи пленные пусти пфуль пьеру решил руку ста сын тетушку туда турки туче умно ура фигура фока фыркнув шелингу шерер шосс штраф автомат блоки ведут вещающих внутрь встреча выделен выучку герц герцшпрунга говорит голов гонтарук длин доступны европа здоров инструкцию интерференции кома крузенштерна куйбышеве культуру курляндскую кючук математика образ образов пешей почт продолжит прото реально росс русскую свободны семь скупку солнечная союз структурную тепе трук увеличив устройств уходит учеб физика чешку якуты культур культ евро математик физик привет система сервер пользователь безопасность окно данные код проверка объект сеть служба файл приложение процесс ввод клавиатура раскладка настройки ручной автоматический текущий предыдущий выделенный текст слово тест релиз сборка обновление локальный приватность пароль защита коробка коробочка свобода свободу свободный хорошо работает работаю ",
    "политик систем спрос программ лиц дел правил команд виде работ инструкции важны норм ",
    "автоматически автор англ блок боукы будут бук бурундук быт верит вес взят видео внук руку ста сказал сказала включен вне вод встреч высоки гвт герцшпрунгу глав гольштейн групп дат доме доп дорог достиг дума женщин жэхэ задач игр идут имен интернешнл интерфакс интерфейс квт кгц книг кот кпк крк крупнейшее крупнейшей кук куклу курируют лев луны люфтваффе маршрут маршрутных маршруту маршруты мгц меня мест млн млрд москва москъвь мпк мужчин мыс над науку начал нефтиду норма нос носит образован основ ост отв пар перу плохо показа пол получит пор пот прав приносит приходит причин проблем просто проходит путей россия рук руках рус сбор свобод сего сей сил сильны слов слова служб смотре сост спб став ставит сторон стоя стоят стран страниц строит структур структуру структуры сферу тел теле термин термина трети трлн труд труду уверен уверенно удар улиц управ уход уча финал финляндскую форм фрукты цен час чел чувство школ эйнштейн эйнштейна якутскую нефти наук сфер ",
    "правда правильный правильно ложь факт факты реальность причина результат ответ вопрос идея идеи мысль мысли знание информация сообщение сообщения почта чат браузер хром терминал компьютер программа железо устройство экран мышь клавиша клавиши кнопка кнопки меню диалог форма поле поля список списки словарь частота уверенность чувствительность консервативный нормальный агрессивный исправить исправление конвертация отмена горячая пауза продолжить старт стоп запуск остановка сохранить отменить добавить удалить изменить создать читать писать поиск найти показать скрыть включить выключить включено выключено разрешить блокировать защитить безопасный ошибка ошибки предупреждение проблема проблемы баг баги версия версии пакет установка ",
    "аккаунт аккаунты админ администратор клиент клиенты хост хосты домен домены адрес адреса порт порты протокол протоколы интернет сайт сайты страница страницы ссылка ссылки путь пути папка папки диск память процессор видеокарта поток потоки событие события состояние статус режим режимы правило правила политика политики доступ вход выход аутентификация авторизация токен токены сертификат сертификаты ключ секрет секреты облако телеметрия буфер история контекст удаленный публичный внутренний внешний ",
    "компания бизнес офис дом комната улица дорога город страна страны люди человек мужчина мужчины женщина женщины ребенок дети семья семьи мама маму папа папу мыла мыло моет рама раму раме рамой дома домой дочь друг друзья команда команды группа группы участник участники партнер проект проекты продукт продукты работа работы задача задачи случай случаи время день дни неделя недели месяц месяцы год годы сегодня завтра вчера утро вечер ночь сейчас потом рано поздно первый второй третий последний следующий новый старый хороший лучше лучший плохой хуже худший большой маленький длинный короткий высокий низкий правый левый верх низ внутри снаружи до после пока всегда никогда часто иногда обычно снова уже почти достаточно больше меньше много мало несколько некоторый любой каждый оба другой разный важный возможно невозможный доступный готов занят трудный легкий простой сложный быстрый медленный сильный слабый полный пустой общий специальный главный основной дополнительный финальный начальный оригинальный будущий прошлый ",
    "значение значения число числа количество сумма часть части сторона стороны точка точки строка строки имя имена тип типы вид виды уровень уровни порядок место места область области тело голова рука руки лицо глаз глаза голос звук еда вода воздух огонь земля деньги рынок рынки цена цены стоимость сила энергия здоровье школа образование учеба учиться книга книги рассказ язык языки английский русский любовь ненависть любить хотеть нужно использовать сделать делать получить дать взять держать знать думать чувствовать видеть смотреть приходить идти говорить сказать рассказать спросить звонить пытаться помогать начинать заканчивать двигаться жить верить понимать помнить забыть находить терять выигрывать играть слушать слышать ждать случаться становиться казаться уходить приносить следовать встречать платить сидеть стоять включать продолжать ставить учить менять вести поворачивать показывать расти покупать отправлять строить падать резать достигать оставаться предлагать поднимать проходить продавать требовать сообщать решать тянуть возвращать объяснять надеяться развивать нести ломать соглашаться поддерживать ударять производить есть покрывать ловить рисовать выбирать вызывать участвовать увеличивать улучшать присоединяться уменьшать носить ехать управлять сделка дела жизнь ",
    "бля блядь блять блядский блядская блядские блядство пизда пиздец пиздеж пиздеть пиздит пиздят пизду пизды пизде пиздой пиздануть пиздатый пиздатая пиздато хуй хуя хую хуе хуем хуи хуев хуйня хуйню хуйни хуйне хуйло ебать ебет ебал ебала ебали ебаный ебаная ебаное ебаные ебучий ебучая ебучее ебучие еблан ебланы заебал заебала заебали заебись заебать наебать наебал наебали поебать похуй нахуй охуеть охуел охуела охуенный охуенно сука суки суке суку сукой сучка сучки сучку мудак мудаки мудака мудаку мудачок долбоеб долбоебы долбоеба говно говна говноед жопа жопу жопы жопе дерьмо шлюха шлюхи трахать трахаться хер хера херово черт чертов дебил дебилы идиот идиоты тупой тупая придурок придурки козел козлы сволочь сволочи урод уроды"
);

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
    let curated = curated_word_score(language, token);
    if curated > 0 {
        return curated;
    }
    frequent_forms::target_word_score(language, token)
}

pub fn source_word_score(language: Language, token: &str) -> i32 {
    let curated = curated_word_score(language, token);
    if curated > 0 {
        return curated;
    }
    frequent_forms::source_word_score(language, token)
}

fn curated_word_score(language: Language, token: &str) -> i32 {
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

pub fn has_word_prefix(language: Language, token: &str) -> bool {
    let (top, common) = match language {
        Language::English => (EN_TOP, EN_COMMON),
        Language::Russian => (RU_TOP, RU_COMMON),
    };
    words(top)
        .chain(words(common))
        .any(|word| word.starts_with(token) && word.len() > token.len())
        || frequent_forms::has_target_prefix(language, token)
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
    fn expanded_lexicon_contains_common_and_obscene_words() {
        for word in ["truth", "information", "company", "fuck", "shit"] {
            assert!(word_score(Language::English, word) >= 15, "missing {word}");
        }
        for word in ["правда", "сегодня", "пизда", "бля", "блять", "хуй", "ебать"]
        {
            assert!(word_score(Language::Russian, word) >= 15, "missing {word}");
        }
    }

    #[test]
    fn article_regression_inflections_are_known_words() {
        for word in [
            "политик",
            "систем",
            "спрос",
            "программ",
            "лиц",
            "дел",
            "правил",
            "команд",
            "виде",
            "работ",
            "инструкции",
            "важны",
            "норм",
        ] {
            assert!(word_score(Language::Russian, word) >= 15, "missing {word}");
        }
    }

    #[test]
    fn common_prefixes_are_available_to_oem_candidate_tracking() {
        assert!(has_word_prefix(Language::Russian, "б"));
        assert!(has_word_prefix(Language::Russian, "бл"));
        assert!(has_word_prefix(Language::English, "tru"));
    }

    #[test]
    fn common_phrase_transition_is_local_and_weighted() {
        assert!(transition_score(Language::English, "hello", "world") > 0);
        assert!(transition_score(Language::Russian, "добрый", "день") > 0);
        assert_eq!(transition_score(Language::English, "hello", "сервер"), 0);
    }
}
