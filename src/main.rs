#![cfg_attr(windows, windows_subsystem = "windows")]

#[cfg(windows)]
fn main() {
    if let Err(error) = g_switcher::windows_runtime::run() {
        eprintln!("G-switcher failed: {error:#}");
    }
}

#[cfg(not(windows))]
fn main() {}
