$ErrorActionPreference = 'Stop'

function Replace-Required([string]$Path, [string]$Old, [string]$New) {
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $text.Contains($Old)) { throw "Expected text not found in $Path" }
    $text = $text.Replace($Old, $New)
    Set-Content -LiteralPath $Path -Value $text -Encoding UTF8 -NoNewline
}

$old = @'
fn send_inputs(inputs: &[INPUT]) -> bool {
    if inputs.is_empty() {
        return true;
    }
    unsafe {
        SendInput(
            inputs.len() as u32,
            inputs.as_ptr(),
            size_of::<INPUT>() as i32,
        ) == inputs.len() as u32
    }
}
'@
$new = @'
const SEND_INPUT_STALL_RETRY_LIMIT: usize = 32;

fn send_inputs(inputs: &[INPUT]) -> bool {
    deliver_inputs_with_retry(inputs.len(), |offset, remaining| unsafe {
        SendInput(
            remaining as u32,
            inputs[offset..].as_ptr(),
            size_of::<INPUT>() as i32,
        ) as usize
    })
}

fn deliver_inputs_with_retry(
    total: usize,
    mut send: impl FnMut(usize, usize) -> usize,
) -> bool {
    if total == 0 {
        return true;
    }

    let mut offset = 0usize;
    let mut stalled = 0usize;
    while offset < total {
        let remaining = total - offset;
        let sent = send(offset, remaining).min(remaining);
        if sent == 0 {
            if offset == 0 {
                return false;
            }
            stalled += 1;
            if stalled >= SEND_INPUT_STALL_RETRY_LIMIT {
                return false;
            }
            unsafe { Sleep(1) };
            continue;
        }

        offset += sent;
        stalled = 0;
    }
    true
}
'@
Replace-Required 'src/windows_runtime/mod.rs' $old $new

$old = @'
    #[test]
    fn configured_hotkey_requires_exact_modifiers() {
'@
$new = @'
    #[test]
    fn partial_sendinput_delivery_resumes_from_unsent_tail() {
        let mut calls = Vec::new();
        let mut attempt = 0usize;
        let delivered = deliver_inputs_with_retry(10, |offset, remaining| {
            calls.push((offset, remaining));
            attempt += 1;
            match attempt {
                1 => 4,
                2 => 0,
                _ => remaining,
            }
        });
        assert!(delivered);
        assert_eq!(calls, vec![(0, 10), (4, 6), (4, 6)]);
    }

    #[test]
    fn zero_progress_sendinput_fails_without_deleting_any_tail() {
        let mut calls = 0usize;
        let delivered = deliver_inputs_with_retry(10, |offset, remaining| {
            calls += 1;
            assert_eq!((offset, remaining), (0, 10));
            0
        });
        assert!(!delivered);
        assert_eq!(calls, 1);
    }

    #[test]
    fn configured_hotkey_requires_exact_modifiers() {
'@
Replace-Required 'src/windows_runtime/mod.rs' $old $new

Replace-Required 'src/frequency_model.rs' 'защита коробка свобода свободу' 'защита коробка коробочка свобода свободу'
