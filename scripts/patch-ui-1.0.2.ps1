$ErrorActionPreference = 'Stop'

function Replace-Required([string]$Path, [string]$Old, [string]$New) {
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $text.Contains($Old)) {
        throw "Expected text not found in $Path"
    }
    $text = $text.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $text -Encoding UTF8 -NoNewline
}

Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'const CLASS_NAME: &str = "GSwitcher.Settings.1.0.1";' 'const CLASS_NAME: &str = "GSwitcher.Settings.1.0.2";'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'let client_height = 825;' 'let client_height = 855;'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '"Настройки G-switcher 1.0.1"' '"Настройки G-switcher 1.0.2"'

$old = @'
        "Детектор v3 работает локально; контекст — максимум два слова в RAM. Поля паролей, PIN и OTP всегда защищены.",
        UiRect::new(28, 54, 840, 22),
'@
$new = @'
        "Работает локально. Контекст: до 2 слов в RAM. Пароли, PIN и OTP не обрабатываются.",
        UiRect::new(28, 54, 840, 24),
'@
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' $old $new

$old = @'
        "Консервативный = меньше ложных замен; Агрессивный = больше автокоррекций.",
        UiRect::new(420, 145, 426, 22),
'@
$new = @'
        "Консервативный — меньше ложных замен.\r\nАгрессивный — больше автокоррекций.",
        UiRect::new(420, 137, 426, 42),
'@
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' $old $new

$old = @'
        "Пауза / продолжить",
        UiRect::new(44, 704, 140, 24),
'@
$new = @'
        "Пауза",
        UiRect::new(44, 704, 140, 28),
'@
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' $old $new

$old = @'
        "Пауза временная. Защищённые поля блокируют автозамену и все горячие клавиши конвертации.",
        UiRect::new(420, 704, 436, 24),
'@
$new = @'
        "Пауза действует до перезапуска.\r\nВ защищённых полях автозамена и конвертация отключены.",
        UiRect::new(420, 694, 436, 44),
'@
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' $old $new

Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'UiRect::new(28, 779, 500, 22)' 'UiRect::new(28, 809, 500, 22)'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'UiRect::new(644, 769, 104, 34)' 'UiRect::new(644, 799, 104, 34)'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'UiRect::new(762, 769, 104, 34)' 'UiRect::new(762, 799, 104, 34)'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '("Pause/Resume", pause_hotkey.as_str()),' '("паузы", pause_hotkey.as_str()),'

Replace-Required 'src/windows_runtime/ui.rs' 'let client_height = 530;' 'let client_height = 550;'
Replace-Required 'src/windows_runtime/ui.rs' '"Горячие клавиши и режимы приложений настраиваются через значок G-switcher в трее → «Настройки».",' '"Горячие клавиши и режимы приложений: значок G-switcher в трее → «Настройки».",'

$old = @'
        36,
        358,
        608,
        52,
        hwnd,
'@
$new = @'
        36,
        358,
        608,
        46,
        hwnd,
'@
Replace-Required 'src/windows_runtime/ui.rs' $old $new

$old = @'
        36,
        414,
        608,
        2,
'@
$new = @'
        36,
        422,
        608,
        2,
'@
Replace-Required 'src/windows_runtime/ui.rs' $old $new

$old = @'
        36,
        432,
        390,
        28,
'@
$new = @'
        36,
        442,
        390,
        28,
'@
Replace-Required 'src/windows_runtime/ui.rs' $old $new

$old = @'
        36,
        500,
        300,
        20,
'@
$new = @'
        36,
        516,
        300,
        20,
'@
Replace-Required 'src/windows_runtime/ui.rs' $old $new

$old = @'
        532,
        427,
        112,
        36,
'@
$new = @'
        532,
        437,
        112,
        36,
'@
Replace-Required 'src/windows_runtime/ui.rs' $old $new

foreach ($path in @('Cargo.toml', 'src/lib.rs', 'build.rs', 'scripts/release-check.ps1', '.github/workflows/windows-ci.yml')) {
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $text = $text.Replace('1.0.1', '1.0.2')
    Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline
}

foreach ($path in @('README.md', 'docs/FUNCTIONAL_SPEC.md')) {
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $text = $text.Replace('1.0.1', '1.0.2')
    Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline
}
