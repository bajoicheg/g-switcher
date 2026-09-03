from pathlib import Path

path = Path('src/windows_runtime/corpus_e2e.rs')
text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
old = '''    let hkl = select_layout(source_language).expect("required RU/EN keyboard layout is unavailable");
    unsafe {
        assert_ne!(
            PostMessageW(
                window,
                WM_CORPUS_SET_LAYOUT_AND_FOCUS,
                hkl as usize,
                edit as isize,
            ),
            0,
            "failed to request corpus source layout"
        );
    }

    wait_until(Duration::from_secs(2), || {
        pump_hook_thread();
        let current = unsafe { GetKeyboardLayout(ui_thread_id) } as isize;
        current == hkl && unsafe { GetForegroundWindow() } == window
    });
'''
new = '''    let hkl = select_layout(source_language).expect("required RU/EN keyboard layout is unavailable");
    let layout_ready = unsafe { GetKeyboardLayout(ui_thread_id) } as isize == hkl;
    let focus_ready = unsafe { GetForegroundWindow() } == window;
    if !layout_ready || !focus_ready {
        unsafe {
            assert_ne!(
                PostMessageW(
                    window,
                    WM_CORPUS_SET_LAYOUT_AND_FOCUS,
                    hkl as usize,
                    edit as isize,
                ),
                0,
                "failed to request corpus source layout"
            );
        }

        wait_until(Duration::from_secs(2), || {
            pump_hook_thread();
            let current = unsafe { GetKeyboardLayout(ui_thread_id) } as isize;
            current == hkl && unsafe { GetForegroundWindow() } == window
        });
    }
'''
if text.count(old) != 1:
    raise SystemExit(f'expected exactly one prepare block, got {text.count(old)}')
text = text.replace(old, new)
text = text.replace('Duration::from_millis(35)', 'Duration::from_millis(8)')
path.write_text(text, encoding='utf-8', newline='\n')
