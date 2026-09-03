$ErrorActionPreference = 'Stop'

function Replace-Required([string]$Path, [string]$Old, [string]$New) {
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $text.Contains($Old)) { throw "Expected text not found in $Path" }
    $text = $text.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $text -Encoding UTF8 -NoNewline
}

$old = @'
        assert_eq!(decide("rjhj,rf"), Decision::CorrectTo(Language::Russian));
        assert_eq!(decide("cdj,jle"), Decision::CorrectTo(Language::Russian));
'@
$new = @'
        assert_eq!(decide("rjhj,rf"), Decision::CorrectTo(Language::Russian));
        assert_eq!(
            correction("rjhj,jxrf"),
            Some((Language::English, Language::Russian, "коробочка".to_owned()))
        );
        assert_eq!(decide("cdj,jle"), Decision::CorrectTo(Language::Russian));
'@
Replace-Required 'src/detector.rs' $old $new

$old = @'
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(b'C'),
'@
$new = @'
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(b'R'),
            key(b'J'),
            key(b'H'),
            key(b'J'),
            key(VK_OEM_COMMA as u8),
            key(b'J'),
            key(b'X'),
            key(b'R'),
            key(b'F'),
            key(VK_OEM_PERIOD as u8),
        ],
        "коробочка.",
    );
    run_case(
        window,
        edit,
        ui_thread_id,
        Language::English,
        &[
            key(b'C'),
'@
Replace-Required 'src/windows_runtime/e2e_tests.rs' $old $new
