use std::collections::{BTreeMap, VecDeque};
use std::env;
use std::fs;
use std::mem::{size_of, zeroed};
use std::path::PathBuf;
use std::ptr::{null, null_mut};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    ActivateKeyboardLayout, GetKeyboardLayout, SendInput, SetFocus, VkKeyScanExW, INPUT, INPUT_0,
    INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_SHIFT,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetForegroundWindow, GetMessageW,
    GetWindowTextLengthW, GetWindowTextW, PeekMessageW, PostMessageW, PostQuitMessage,
    RegisterClassW, SetForegroundWindow, SetWindowTextW, ShowWindow, TranslateMessage, PM_REMOVE,
    SW_SHOW, WM_APP, WM_CLOSE, WM_DESTROY, WNDCLASSW, WS_CAPTION, WS_CHILD, WS_OVERLAPPED,
    WS_SYSMENU, WS_VISIBLE,
};

use super::*;

const WM_CORPUS_SET_LAYOUT_AND_FOCUS: u32 = WM_APP + 0x71;
const CORPUS_USER_EXTRA_INFO: usize = 0x4753_434F_5250_5553;
const WS_BORDER_STYLE: u32 = 0x0080_0000;
const ES_MULTILINE_STYLE: u32 = 0x0004;
const ES_AUTOHSCROLL_STYLE: u32 = 0x0080;
const ES_WANTRETURN_STYLE: u32 = 0x1000;

struct InjectedInputGuard;

impl InjectedInputGuard {
    fn enable() -> Self {
        TEST_ACCEPT_INJECTED_INPUT.store(true, Ordering::SeqCst);
        Self
    }
}

impl Drop for InjectedInputGuard {
    fn drop(&mut self) {
        TEST_ACCEPT_INJECTED_INPUT.store(false, Ordering::SeqCst);
    }
}

#[derive(Clone)]
struct CorpusOccurrence {
    expected: String,
    language: Language,
    context: Vec<String>,
}

#[derive(Default)]
struct FailureAggregate {
    occurrences: usize,
    expected: String,
    synthetic: String,
    actual: String,
    language: String,
    reason: String,
    context: String,
}

#[test]
#[ignore = "downloads are external; set G_SWITCHER_CORPUS_PATH for the reproducible corpus gate"]
fn wikipedia_article_layout_corpus_e2e() {
    let corpus_path = PathBuf::from(
        env::var("G_SWITCHER_CORPUS_PATH").expect("G_SWITCHER_CORPUS_PATH is required"),
    );
    let report_path = PathBuf::from(
        env::var("G_SWITCHER_CORPUS_REPORT")
            .unwrap_or_else(|_| "target/wiki-corpus-failures.csv".to_owned()),
    );
    let summary_path = PathBuf::from(
        env::var("G_SWITCHER_CORPUS_SUMMARY")
            .unwrap_or_else(|_| "target/wiki-corpus-summary.txt".to_owned()),
    );
    let strict = env::var("G_SWITCHER_CORPUS_STRICT")
        .map(|value| value == "1")
        .unwrap_or(false);

    let article = fs::read_to_string(&corpus_path).expect("failed to read corpus text");
    let occurrences = corpus_occurrences(&article);
    assert!(!occurrences.is_empty(), "corpus did not contain RU/EN words");

    let _injected_guard = InjectedInputGuard::enable();
    let original_runtime =
        settings::replace_runtime_settings_for_test(settings::RuntimeSettings::default());
    settings::set_paused(false);

    let (ready_tx, ready_rx) = mpsc::sync_channel(1);
    let ui_thread = thread::spawn(move || run_corpus_window(ready_tx));
    let (window_value, edit_value) = ready_rx
        .recv_timeout(Duration::from_secs(5))
        .expect("corpus Win32 window did not start");
    let window = window_value as HWND;
    let edit = edit_value as HWND;
    let ui_thread_id = unsafe { GetWindowThreadProcessId(edit, null_mut()) };
    assert_ne!(ui_thread_id, 0, "failed to resolve corpus EDIT thread");

    let engine = ENGINE.get_or_init(|| Mutex::new(Engine::default()));
    *engine.lock() = Engine::default();
    let hook = KeyboardHook::install().expect("failed to install corpus WH_KEYBOARD_LL hook");
    let input_worker = InputWorker::start();
    let process_name = process_name_for_pid(std::process::id()).unwrap_or_default();

    let mut failures: BTreeMap<String, FailureAggregate> = BTreeMap::new();
    let mut tested = 0usize;
    let mut unsupported = 0usize;

    for occurrence in &occurrences {
        let source_language = opposite_language(occurrence.language);
        let synthetic = opposite_layout_text(&occurrence.expected, occurrence.language);
        let source_hkl = select_layout(source_language).expect("required source HKL unavailable");
        let Some(mut strokes) = strokes_for_text(&synthetic, source_hkl) else {
            unsupported += 1;
            continue;
        };
        strokes.push(Stroke {
            vk: VK_SPACE,
            shift: false,
        });

        prepare_corpus_case(
            window,
            edit,
            ui_thread_id,
            source_language,
            &occurrence.context,
            &process_name,
        );
        input_worker.inject(&strokes);
        let expected_with_space = format!("{} ", occurrence.expected);
        let actual = settle_text(edit, &expected_with_space);
        tested += 1;

        if actual != expected_with_space {
            let actual_trimmed = actual.strip_suffix(' ').unwrap_or(&actual).to_owned();
            let reason = classify_failure(&occurrence.expected, &synthetic, &actual_trimmed);
            let context = occurrence.context.join(" ");
            let key = format!(
                "{}\u{1f}{}\u{1f}{}\u{1f}{}",
                occurrence.expected, synthetic, actual_trimmed, context
            );
            let entry = failures.entry(key).or_insert_with(|| FailureAggregate {
                expected: occurrence.expected.clone(),
                synthetic: synthetic.clone(),
                actual: actual_trimmed,
                language: language_name(occurrence.language).to_owned(),
                reason: reason.to_owned(),
                context,
                ..FailureAggregate::default()
            });
            entry.occurrences += 1;
        }
    }

    write_report(&report_path, &failures);
    write_summary(
        &summary_path,
        occurrences.len(),
        tested,
        unsupported,
        &failures,
    );

    settings::replace_runtime_settings_for_test(original_runtime);
    settings::set_paused(false);
    drop(input_worker);
    drop(hook);
    unsafe {
        PostMessageW(window, WM_CLOSE, 0, 0);
    }
    ui_thread.join().expect("corpus Win32 UI thread panicked");

    let failed_occurrences: usize = failures.values().map(|item| item.occurrences).sum();
    eprintln!(
        "G-switcher Wikipedia corpus: occurrences={} tested={} unsupported={} failure_variants={} failed_occurrences={}",
        occurrences.len(),
        tested,
        unsupported,
        failures.len(),
        failed_occurrences
    );

    if strict {
        assert!(
            failures.is_empty(),
            "Wikipedia corpus has {} failure variants / {} failed occurrences; see {}",
            failures.len(),
            failed_occurrences,
            report_path.display()
        );
    }
}

fn corpus_occurrences(text: &str) -> Vec<CorpusOccurrence> {
    let mut result = Vec::new();
    let mut current = String::new();
    let mut current_language = None;
    let mut context: VecDeque<String> = VecDeque::new();

    let flush = |result: &mut Vec<CorpusOccurrence>,
                 current: &mut String,
                 current_language: &mut Option<Language>,
                 context: &mut VecDeque<String>| {
        let Some(language) = *current_language else {
            current.clear();
            return;
        };
        if current.is_empty() {
            *current_language = None;
            return;
        }
        let expected = current.clone();
        result.push(CorpusOccurrence {
            expected: expected.clone(),
            language,
            context: context.iter().cloned().collect(),
        });
        if context.len() >= MAX_CONTEXT_WORDS {
            context.pop_front();
        }
        context.push_back(expected);
        current.clear();
        *current_language = None;
    };

    for ch in text.chars().chain(std::iter::once(' ')) {
        let language = char_language(ch);
        match (current_language, language) {
            (Some(active), Some(next)) if active == next => current.push(ch),
            (None, Some(next)) => {
                current_language = Some(next);
                current.push(ch);
            }
            (Some(_), Some(next)) => {
                flush(
                    &mut result,
                    &mut current,
                    &mut current_language,
                    &mut context,
                );
                current_language = Some(next);
                current.push(ch);
            }
            (Some(_), None) => flush(
                &mut result,
                &mut current,
                &mut current_language,
                &mut context,
            ),
            (None, None) => {}
        }
    }

    result
}

fn char_language(ch: char) -> Option<Language> {
    if matches!(ch, 'а'..='я' | 'А'..='Я' | 'ё' | 'Ё') {
        Some(Language::Russian)
    } else if ch.is_ascii_alphabetic() {
        Some(Language::English)
    } else {
        None
    }
}

fn strokes_for_text(text: &str, hkl: isize) -> Option<Vec<Stroke>> {
    let mut strokes = Vec::with_capacity(text.chars().count());
    for ch in text.chars() {
        let encoded = unsafe { VkKeyScanExW(ch as u16, hkl as *mut core::ffi::c_void) };
        if encoded == -1 {
            return None;
        }
        let encoded = encoded as u16;
        let modifiers = (encoded >> 8) & 0xff;
        if modifiers & !1 != 0 {
            return None;
        }
        strokes.push(Stroke {
            vk: encoded & 0xff,
            shift: modifiers & 1 != 0,
        });
    }
    Some(strokes)
}

fn prepare_corpus_case(
    window: HWND,
    edit: HWND,
    ui_thread_id: u32,
    source_language: Language,
    context: &[String],
    process_name: &str,
) {
    set_text(edit, "");
    {
        let mut engine = ENGINE.get_or_init(|| Mutex::new(Engine::default())).lock();
        *engine = Engine::default();
        engine.process_id = std::process::id();
        engine.process_name = process_name.to_owned();
        engine.context_tokens = context.to_vec();
    }

    let hkl = select_layout(source_language).expect("required RU/EN keyboard layout is unavailable");
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
}

fn settle_text(edit: HWND, expected: &str) -> String {
    let deadline = Instant::now() + Duration::from_millis(400);
    let mut last = String::new();
    let mut stable_since = Instant::now();

    while Instant::now() < deadline {
        pump_hook_thread();
        let current = read_text(edit);
        if current == expected {
            return current;
        }
        if current != last {
            last = current;
            stable_since = Instant::now();
        } else if stable_since.elapsed() >= Duration::from_millis(8) {
            return current;
        }
        thread::sleep(Duration::from_millis(1));
    }
    read_text(edit)
}

fn classify_failure(expected: &str, synthetic: &str, actual: &str) -> &'static str {
    if actual == synthetic {
        if expected.chars().count() < 3 {
            "short-token-not-corrected"
        } else {
            "not-corrected"
        }
    } else if actual.len() < synthetic.len() && synthetic.starts_with(actual) {
        "truncated"
    } else {
        "wrong-correction"
    }
}

fn language_name(language: Language) -> &'static str {
    match language {
        Language::Russian => "RU",
        Language::English => "EN",
    }
}

fn write_report(path: &PathBuf, failures: &BTreeMap<String, FailureAggregate>) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("failed to create report directory");
    }
    let mut csv = String::from(
        "occurrences,language,expected,synthetic,actual,reason,previous_context\n",
    );
    for failure in failures.values() {
        csv.push_str(&format!(
            "{},{},{},{},{},{},{}\n",
            failure.occurrences,
            csv_field(&failure.language),
            csv_field(&failure.expected),
            csv_field(&failure.synthetic),
            csv_field(&failure.actual),
            csv_field(&failure.reason),
            csv_field(&failure.context)
        ));
    }
    fs::write(path, csv).expect("failed to write corpus report");
}

fn write_summary(
    path: &PathBuf,
    occurrences: usize,
    tested: usize,
    unsupported: usize,
    failures: &BTreeMap<String, FailureAggregate>,
) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("failed to create summary directory");
    }
    let failed_occurrences: usize = failures.values().map(|item| item.occurrences).sum();
    let short_failures: usize = failures
        .values()
        .filter(|item| item.reason == "short-token-not-corrected")
        .map(|item| item.occurrences)
        .sum();
    let summary = format!(
        "source=https://ru.wikipedia.org/wiki/Информационная_безопасность\noccurrences={}\ntested={}\nunsupported={}\nfailure_variants={}\nfailed_occurrences={}\nshort_token_failed_occurrences={}\n",
        occurrences,
        tested,
        unsupported,
        failures.len(),
        failed_occurrences,
        short_failures
    );
    fs::write(path, summary).expect("failed to write corpus summary");
}

fn csv_field(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

struct InputWorker {
    sender: mpsc::Sender<InputCommand>,
    join: Option<thread::JoinHandle<()>>,
}

enum InputCommand {
    Inject(Vec<(u16, u32)>, mpsc::SyncSender<(u32, u32)>),
    Stop,
}

impl InputWorker {
    fn start() -> Self {
        let (sender, receiver) = mpsc::channel::<InputCommand>();
        let join = thread::spawn(move || {
            while let Ok(command) = receiver.recv() {
                match command {
                    InputCommand::Inject(events, done) => {
                        let inputs: Vec<INPUT> = events
                            .into_iter()
                            .map(|(vk, flags)| corpus_key_input(vk, flags))
                            .collect();
                        let sent = unsafe {
                            SendInput(
                                inputs.len() as u32,
                                inputs.as_ptr(),
                                size_of::<INPUT>() as i32,
                            )
                        };
                        let _ = done.send((sent, inputs.len() as u32));
                    }
                    InputCommand::Stop => break,
                }
            }
        });
        Self {
            sender,
            join: Some(join),
        }
    }

    fn inject(&self, strokes: &[Stroke]) {
        let mut events = Vec::with_capacity(strokes.len() * 4);
        for stroke in strokes {
            if stroke.shift {
                events.push((VK_SHIFT, 0));
            }
            events.push((stroke.vk, 0));
            events.push((stroke.vk, KEYEVENTF_KEYUP));
            if stroke.shift {
                events.push((VK_SHIFT, KEYEVENTF_KEYUP));
            }
        }

        let (done_tx, done_rx) = mpsc::sync_channel(1);
        self.sender
            .send(InputCommand::Inject(events, done_tx))
            .expect("corpus input worker stopped unexpectedly");
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            pump_hook_thread();
            if let Ok((sent, expected)) = done_rx.try_recv() {
                assert_eq!(sent, expected, "corpus SendInput was incomplete");
                return;
            }
            assert!(Instant::now() < deadline, "corpus SendInput timed out");
            thread::sleep(Duration::from_millis(1));
        }
    }
}

impl Drop for InputWorker {
    fn drop(&mut self) {
        let _ = self.sender.send(InputCommand::Stop);
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}

fn wait_until(timeout: Duration, mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if condition() {
            return;
        }
        thread::sleep(Duration::from_millis(1));
    }
}

fn pump_hook_thread() {
    unsafe {
        let mut message = zeroed();
        while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
            if handle_runtime_message(&message) {
                continue;
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

fn set_text(edit: HWND, value: &str) {
    let value = wide(value);
    unsafe {
        assert_ne!(SetWindowTextW(edit, value.as_ptr()), 0, "failed to set corpus EDIT text");
    }
}

fn read_text(edit: HWND) -> String {
    unsafe {
        let length = GetWindowTextLengthW(edit);
        let mut buffer = vec![0u16; length as usize + 1];
        let copied = GetWindowTextW(edit, buffer.as_mut_ptr(), buffer.len() as i32);
        String::from_utf16_lossy(&buffer[..copied as usize])
    }
}

fn corpus_key_input(vk: u16, flags: u32) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: CORPUS_USER_EXTRA_INFO,
            },
        },
    }
}

fn run_corpus_window(ready_tx: mpsc::SyncSender<(isize, isize)>) {
    unsafe {
        let module = GetModuleHandleW(null());
        let class_name = wide("GSwitcher.Corpus.Window");
        let window_class = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(corpus_window_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: module,
            hIcon: null_mut(),
            hCursor: null_mut(),
            hbrBackground: null_mut(),
            lpszMenuName: null(),
            lpszClassName: class_name.as_ptr(),
        };
        assert_ne!(RegisterClassW(&window_class), 0, "failed to register corpus window");

        let title = wide("G-switcher Wikipedia corpus E2E");
        let window = CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
            50,
            50,
            720,
            220,
            null_mut(),
            null_mut(),
            module,
            null(),
        );
        assert!(!window.is_null(), "failed to create corpus window");

        let edit_class = wide("EDIT");
        let empty = wide("");
        let edit = CreateWindowExW(
            0,
            edit_class.as_ptr(),
            empty.as_ptr(),
            WS_CHILD
                | WS_VISIBLE
                | WS_BORDER_STYLE
                | ES_MULTILINE_STYLE
                | ES_AUTOHSCROLL_STYLE
                | ES_WANTRETURN_STYLE,
            20,
            20,
            660,
            120,
            window,
            null_mut(),
            module,
            null(),
        );
        assert!(!edit.is_null(), "failed to create corpus EDIT control");

        ShowWindow(window, SW_SHOW);
        SetForegroundWindow(window);
        SetFocus(edit);
        ready_tx
            .send((window as isize, edit as isize))
            .expect("failed to publish corpus window handles");

        let mut message = zeroed();
        while GetMessageW(&mut message, null_mut(), 0, 0) > 0 {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

unsafe extern "system" fn corpus_window_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        WM_CORPUS_SET_LAYOUT_AND_FOCUS => {
            ActivateKeyboardLayout(wparam as *mut core::ffi::c_void, 0);
            SetForegroundWindow(hwnd);
            SetFocus(lparam as HWND);
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}
