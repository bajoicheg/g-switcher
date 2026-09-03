$ErrorActionPreference = 'Stop'

function Replace-Required([string]$Path, [string]$Old, [string]$New) {
    $text = Get-Content -Raw -Encoding UTF8 $Path
    if (-not $text.Contains($Old)) {
        if ($text.Contains($New)) {
            return
        }
        throw "Expected text not found in ${Path}: ${Old}"
    }
    $text = $text.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $text -Encoding UTF8 -NoNewline
}

# Detector: built-in frequency lexicon becomes authoritative source protection and target evidence.
$path = 'src/detector.rs'
$text = Get-Content -Raw -Encoding UTF8 $path
$old = @'
    let source = infer_language(token)?;
    let normalized = normalize(token, source);
    if dictionary_contains(source, &normalized, user_words) {
        return None;
    }

    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    let mapped_normalized = normalize(&mapped, target);
    if !candidate_shape_is_valid(&mapped, target) {
        return None;
    }

    if dictionary_contains(target, &mapped_normalized, user_words) {
        return Some(Detection {
            source,
            target,
            corrected: mapped,
            confidence: 100,
        });
    }
'@
$new = @'
    let source = infer_language(token)?;
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
'@
if ($text.Contains($old)) {
    $text = $text.Replace($old, $new)
} elseif (-not $text.Contains('dictionary_contains(source, &normalized, user_words) || source_frequency >= 15')) {
    throw 'Detector source/target known-word block not found.'
}

$legacyFrequencyBlock = @'
    let source_frequency = frequency_model::word_score(source, &normalized);
    let target_frequency = frequency_model::word_score(target, &mapped_normalized);

    // A frequent real source-language word is strong preservation evidence.
    if source_frequency >= 15 && target_frequency == 0 {
        return None;
    }

'@
$text = $text.Replace($legacyFrequencyBlock, '')

$oldPrefixFunction = @'
pub fn opposite_candidate_is_prefix_with_user_words(token: &str, user_words: &[String]) -> bool {
    let Some(source) = infer_language(token) else {
        return false;
    };
    let target = opposite(source);
    let mapped = opposite_layout_text(token, source);
    if !candidate_shape_is_valid(&mapped, target) {
        return false;
    }
    is_target_word_prefix(&normalize(&mapped, target), target, user_words)
}
'@
$newPrefixFunction = @'
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
'@
if ($text.Contains($oldPrefixFunction)) {
    $text = $text.Replace($oldPrefixFunction, $newPrefixFunction)
} elseif (-not $text.Contains('pub fn opposite_candidate_is_prefix_for_language')) {
    throw 'Detector explicit-source prefix function insertion failed.'
}

$oldTargetPrefix = @'
fn is_target_word_prefix(token: &str, language: Language, user_words: &[String]) -> bool {
    exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
        || user_words.iter().any(|word| {
'@
$newTargetPrefix = @'
fn is_target_word_prefix(token: &str, language: Language, user_words: &[String]) -> bool {
    frequency_model::has_word_prefix(language, token)
        || exact_words(language).any(|word| word.starts_with(token) && word.len() > token.len())
        || user_words.iter().any(|word| {
'@
if ($text.Contains($oldTargetPrefix)) {
    $text = $text.Replace($oldTargetPrefix, $newTargetPrefix)
} elseif (-not $text.Contains('frequency_model::has_word_prefix(language, token)')) {
    throw 'Detector frequency-prefix integration failed.'
}

if (-not $text.Contains('expanded_builtin_lexicon_protects_real_words')) {
    $testMarker = @'
    #[test]
    fn frequency_model_protects_frequent_source_words() {
'@
    $tests = @'
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

'@
    if (-not $text.Contains($testMarker)) {
        throw 'Detector test insertion marker not found.'
    }
    $text = $text.Replace($testMarker, $tests + $testMarker)
}
Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline

# Runtime OEM candidate handling: allow leading comma/period when the opposite key is a known prefix.
$path = 'src/windows_runtime/mod.rs'
$text = Get-Content -Raw -Encoding UTF8 $path
$text = $text.Replace(
    'correction_with_context, infer_language, opposite_candidate_is_prefix_with_user_words,',
    'correction_with_context, infer_language, opposite_candidate_is_prefix_for_language,'
)
$oldPunctuation = @'
        let runtime_settings = settings::runtime_settings();
        if punctuation_can_extend_candidate(vk, target.language)
            && opposite_candidate_is_prefix_with_user_words(
                &self.candidate,
                &runtime_settings.user_words,
            )
        {
'@
$newPunctuation = @'
        let runtime_settings = settings::runtime_settings();
        let mut prospective = self.candidate.clone();
        prospective.push(ch);
        if punctuation_can_extend_candidate(vk, target.language)
            && opposite_candidate_is_prefix_for_language(
                &prospective,
                target.language,
                &runtime_settings.user_words,
            )
        {
'@
if ($text.Contains($oldPunctuation)) {
    $text = $text.Replace($oldPunctuation, $newPunctuation)
} elseif (-not $text.Contains('let mut prospective = self.candidate.clone();')) {
    throw 'Runtime punctuation candidate block not found.'
}
Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline

# Real Win32 regression for a Russian obscene word whose wrong-layout form starts with OEM comma.
$path = 'src/windows_runtime/e2e_tests.rs'
$text = Get-Content -Raw -Encoding UTF8 $path
if (-not $text.Contains('"бля "')) {
    $marker = @'
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(b'C'),
            key(b'D'),
            key(b'J'),
            key(VK_OEM_COMMA as u8),
            key(b'J'),
            key(b'L'),
            key(b'E'),
            key(VK_SPACE as u8),
        ],
        "свободу ",
    );
'@
    $addition = @'
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(VK_OEM_COMMA as u8),
            key(b'K'),
            key(b'Z'),
            key(VK_SPACE as u8),
        ],
        "бля ",
    );
'@
    if (-not $text.Contains($marker)) {
        throw 'Win32 E2E insertion marker not found.'
    }
    $text = $text.Replace($marker, $marker + "`n" + $addition)
}
Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline

# First-run dialog: give the Settings hint enough vertical room and move footer below it.
$path = 'src/windows_runtime/ui.rs'
$text = Get-Content -Raw -Encoding UTF8 $path
$text = $text.Replace('let client_height = 500;', 'let client_height = 530;')
$text = $text.Replace(
    '"Горячие клавиши и режимы приложений можно изменить через значок G-switcher в трее → Настройки."',
    '"Горячие клавиши и режимы приложений настраиваются через значок G-switcher в трее → «Настройки»."'
)
$oldHintRect = @'
        36,
        358,
        608,
        36,
'@
$newHintRect = @'
        36,
        358,
        608,
        52,
'@
$text = $text.Replace($oldHintRect, $newHintRect)
$oldFooterSeparator = @'
        36,
        401,
        608,
        2,
'@
$newFooterSeparator = @'
        36,
        414,
        608,
        2,
'@
$text = $text.Replace($oldFooterSeparator, $newFooterSeparator)
$oldCheckboxRect = @'
        36,
        418,
        390,
        28,
'@
$newCheckboxRect = @'
        36,
        432,
        390,
        28,
'@
$text = $text.Replace($oldCheckboxRect, $newCheckboxRect)
$oldFooterRect = @'
        36,
        467,
        300,
        20,
'@
$newFooterRect = @'
        36,
        500,
        300,
        20,
'@
$text = $text.Replace($oldFooterRect, $newFooterRect)
$oldOkRect = @'
        532,
        413,
        112,
        36,
'@
$newOkRect = @'
        532,
        427,
        112,
        36,
'@
$text = $text.Replace($oldOkRect, $newOkRect)
Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline

# Settings dialog: restore breathing room, make dictionary genuinely multiline, remove empty read-only scrollbars, and localize labels.
$path = 'src/windows_runtime/ui/settings_dialog.rs'
$text = Get-Content -Raw -Encoding UTF8 $path
$text = $text.Replace('const CLASS_NAME: &str = "GSwitcher.Settings.1.0";', 'const CLASS_NAME: &str = "GSwitcher.Settings.1.0.1";')
$text = $text.Replace('let client_height = 760;', 'let client_height = 825;')
$text = $text.Replace('"Настройки G-switcher 1.0.0"', '"Настройки G-switcher 1.0.1"')
$text = $text.Replace(
    '"Detector v3 работает локально; контекст — максимум два слова в RAM. Password/PIN/OTP поля всегда защищены."',
    '"Детектор v3 работает локально; контекст — максимум два слова в RAM. Поля паролей, PIN и OTP всегда защищены."'
)
$text = $text.Replace('"Auto"', '"Авто"')
$text = $text.Replace(
    '"Выберите запущенный процесс и назначьте режим. Auto удаляет индивидуальное исключение."',
    '"Выберите запущенный процесс и назначьте режим. «Авто» удаляет индивидуальное исключение."'
)
$text = $text.Replace('"Отключено — без анализа и hotkey"', '"Отключено — без анализа и горячих клавиш"')
$text = $text.Replace(
    '"Выделенный текст работает в native Edit/RichEdit без использования clipboard."',
    '"Выделенный текст обрабатывается в стандартных Edit/RichEdit без буфера обмена."'
)
$text = $text.Replace('"Pause / Resume"', '"Пауза / продолжить"')
$text = $text.Replace(
    '"Pause временный. Secure-поля блокируют auto и все conversion hotkeys независимо от режима приложения."',
    '"Пауза временная. Защищённые поля блокируют автозамену и все горячие клавиши конвертации."'
)

$replacements = @{
    'UiRect::new(24, 194, 852, 190)' = 'UiRect::new(24, 194, 852, 210)'
    'UiRect::new(44, 307, 386, 56)' = 'UiRect::new(44, 307, 386, 76)'
    'UiRect::new(470, 307, 386, 56)' = 'UiRect::new(470, 307, 386, 76)'
    'UiRect::new(24, 396, 852, 98)' = 'UiRect::new(24, 416, 852, 130)'
    'UiRect::new(44, 423, 812, 20)' = 'UiRect::new(44, 443, 812, 20)'
    'UiRect::new(44, 447, 812, 32)' = 'UiRect::new(44, 467, 812, 64)'
    'UiRect::new(24, 506, 852, 190)' = 'UiRect::new(24, 558, 852, 190)'
    'UiRect::new(44, 533, 812, 20)' = 'UiRect::new(44, 585, 812, 20)'
    'UiRect::new(44, 566, 140, 24)' = 'UiRect::new(44, 618, 140, 24)'
    'UiRect::new(190, 561, 190, 30)' = 'UiRect::new(190, 613, 190, 30)'
    'UiRect::new(462, 566, 156, 24)' = 'UiRect::new(462, 618, 156, 24)'
    'UiRect::new(626, 561, 230, 30)' = 'UiRect::new(626, 613, 230, 30)'
    'UiRect::new(44, 609, 140, 24)' = 'UiRect::new(44, 661, 140, 24)'
    'UiRect::new(190, 604, 190, 30)' = 'UiRect::new(190, 656, 190, 30)'
    'UiRect::new(462, 609, 156, 24)' = 'UiRect::new(462, 661, 156, 24)'
    'UiRect::new(626, 604, 230, 30)' = 'UiRect::new(626, 656, 230, 30)'
    'UiRect::new(44, 652, 140, 24)' = 'UiRect::new(44, 704, 140, 24)'
    'UiRect::new(190, 647, 190, 30)' = 'UiRect::new(190, 699, 190, 30)'
    'UiRect::new(420, 652, 436, 24)' = 'UiRect::new(420, 704, 436, 24)'
    'UiRect::new(28, 716, 500, 22)' = 'UiRect::new(28, 779, 500, 22)'
    'UiRect::new(644, 706, 104, 34)' = 'UiRect::new(644, 769, 104, 34)'
    'UiRect::new(762, 706, 104, 34)' = 'UiRect::new(762, 769, 104, 34)'
}
foreach ($entry in $replacements.GetEnumerator()) {
    $text = $text.Replace($entry.Key, $entry.Value)
}

$oldStyle = @'
    let mut style = WS_CHILD
        | WS_VISIBLE
        | WS_BORDER
        | WS_VSCROLL
        | ES_MULTILINE as u32
        | ES_AUTOVSCROLL as u32;
    if read_only {
        style |= ES_READONLY as u32;
    }
'@
$newStyle = @'
    let mut style = WS_CHILD | WS_VISIBLE | WS_BORDER | ES_MULTILINE as u32 | ES_AUTOVSCROLL as u32;
    if read_only {
        style |= ES_READONLY as u32;
    } else {
        style |= WS_VSCROLL;
    }
'@
if ($text.Contains($oldStyle)) {
    $text = $text.Replace($oldStyle, $newStyle)
} elseif (-not $text.Contains('style |= WS_VSCROLL;')) {
    throw 'Settings multiline edit style block not found.'
}
Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline

# Cargo.lock records the package version independently from Cargo.toml.
$path = 'Cargo.lock'
$text = Get-Content -Raw -Encoding UTF8 $path
$oldLock = @'
name = "g-switcher"
version = "1.0.0"
'@
$newLock = @'
name = "g-switcher"
version = "1.0.1"
'@
if ($text.Contains($oldLock)) {
    $text = $text.Replace($oldLock, $newLock)
}
Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline
