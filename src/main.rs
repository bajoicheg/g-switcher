#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(windows)]
fn main() {
    if std::env::args().any(|argument| argument == "--word-broker") {
        let _ = g_switcher::windows_runtime::run_word_broker();
        return;
    }
    if let Err(error) = g_switcher::windows_runtime::run() {
        g_switcher::windows_runtime::show_fatal_error(&format!(
            "G-switcher не удалось запустить.\r\n\r\n{error:#}"
        ));
    }
}

#[cfg(not(windows))]
fn main() {}
