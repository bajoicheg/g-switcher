$ErrorActionPreference = 'Stop'

function Replace-Required([string]$Path, [string]$Old, [string]$New) {
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $text.Contains($Old)) {
        throw "Expected text not found in $Path`: $Old"
    }
    $text = $text.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $text -Encoding UTF8 -NoNewline
}

# Settings: reserve more client height and stop forcing long Russian hints into single-line rectangles.
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'const CLASS_NAME: &str = "GSwitcher.Settings.1.0.1";' 'const CLASS_NAME: &str = "GSwitcher.Settings.1.0.2";'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'let client_height = 825;' 'let client_height = 855;'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '"Настройки G-switcher 1.0.1"' '"Настройки G-switcher 1.0.2"'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '"Детектор v3 работает локально; контекст — максимум два слова в RAM. Поля паролей, PIN и OTP всегда защищены.",`n        UiRect::new(28, 54, 840, 22),' '"Работает локально. Контекст: до 2 слов в RAM. Пароли, PIN и OTP не обрабатываются.",`n        UiRect::new(28, 54, 840, 24),'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '"Консервативный = меньше ложных замен; Агрессивный = больше автокоррекций.",`n        UiRect::new(420, 145, 426, 22),' '"Консервативный — меньше ложных замен.\r\nАгрессивный — больше автокоррекций.",`n        UiRect::new(420, 137, 426, 42),'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '"Пауза / продолжить",`n        UiRect::new(44, 704, 140, 24),' '"Пауза",`n        UiRect::new(44, 704, 140, 28),'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '"Пауза временная. Защищённые поля блокируют автозамену и все горячие клавиши конвертации.",`n        UiRect::new(420, 704, 436, 24),' '"Пауза действует до перезапуска.\r\nВ защищённых полях автозамена и конвертация отключены.",`n        UiRect::new(420, 694, 436, 44),'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'UiRect::new(28, 779, 500, 22)' 'UiRect::new(28, 809, 500, 22)'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'UiRect::new(644, 769, 104, 34)' 'UiRect::new(644, 799, 104, 34)'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' 'UiRect::new(762, 769, 104, 34)' 'UiRect::new(762, 799, 104, 34)'
Replace-Required 'src/windows_runtime/ui/settings_dialog.rs' '("Pause/Resume", pause_hotkey.as_str()),' '("паузы", pause_hotkey.as_str()),'

# First-run: add a little more breathing room at the bottom and shorten the settings hint.
Replace-Required 'src/windows_runtime/ui.rs' 'let client_height = 530;' 'let client_height = 550;'
Replace-Required 'src/windows_runtime/ui.rs' '"Горячие клавиши и режимы приложений настраиваются через значок G-switcher в трее → «Настройки».",' '"Горячие клавиши и режимы приложений: значок G-switcher в трее → «Настройки».",'
Replace-Required 'src/windows_runtime/ui.rs' '        52,`n        hwnd,' '        46,`n        hwnd,'
Replace-Required 'src/windows_runtime/ui.rs' '        414,`n        608,' '        422,`n        608,'
Replace-Required 'src/windows_runtime/ui.rs' '        432,`n        390,' '        442,`n        390,'
Replace-Required 'src/windows_runtime/ui.rs' '        500,`n        300,' '        516,`n        300,'
Replace-Required 'src/windows_runtime/ui.rs' '        427,`n        112,' '        437,`n        112,'

# Patch version metadata and checked artifact naming.
foreach ($path in @('Cargo.toml', 'src/lib.rs', 'build.rs', 'scripts/release-check.ps1', '.github/workflows/windows-ci.yml')) {
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $text = $text.Replace('1.0.1', '1.0.2')
    Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline
}

# Keep README/spec version claims aligned with the UI-only patch.
foreach ($path in @('README.md', 'docs/FUNCTIONAL_SPEC.md')) {
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $text = $text.Replace('1.0.1', '1.0.2')
    Set-Content -LiteralPath $path -Value $text -Encoding UTF8 -NoNewline
}
