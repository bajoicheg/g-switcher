#![cfg(windows)]

use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

const DEFAULT_OUTPUT: &str = "compatibility-results-2.0.1.md";
const REQUIRED_APPLICATIONS: [&str; 7] = [
    "Notepad",
    "Microsoft Word",
    "Microsoft Edge",
    "Google Chrome",
    "Telegram Desktop",
    "Visual Studio Code",
    "Windows Terminal",
];

const CORE_PASS_ONLY: [&str; 2] = ["Microsoft Edge", "Google Chrome"];
const CORE_RESULTS: [&str; 2] = ["PASS", "UNSUPPORTED/FAIL-OPEN"];
const OPTIONAL_RESULTS: [&str; 3] = ["PASS", "N/A", "UNSUPPORTED/FAIL-OPEN"];

#[derive(Debug, Clone)]
struct Row {
    application: String,
    version: String,
    windows_build: String,
    auto: String,
    manual: String,
    selected: String,
    undo: String,
    password: String,
    notes: String,
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("ERROR: {error}");
            ExitCode::from(1)
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "record".to_owned());
    match command.to_ascii_lowercase().as_str() {
        "record" => {
            let path = args
                .next()
                .map(PathBuf::from)
                .unwrap_or_else(|| DEFAULT_OUTPUT.into());
            record(&path, false)
        }
        "resume" => {
            let path = args
                .next()
                .map(PathBuf::from)
                .unwrap_or_else(|| DEFAULT_OUTPUT.into());
            record(&path, true)
        }
        "verify" => {
            let path = args
                .next()
                .map(PathBuf::from)
                .unwrap_or_else(|| DEFAULT_OUTPUT.into());
            verify_path(&path)
        }
        "scaffold" => {
            let path = args
                .next()
                .map(PathBuf::from)
                .unwrap_or_else(|| DEFAULT_OUTPUT.into());
            scaffold(&path)
        }
        "--help" | "-h" | "help" => {
            print_help();
            Ok(())
        }
        other => Err(format!(
            "unknown command '{other}'. Use record, resume, verify, scaffold, or --help."
        )),
    }
}

fn print_help() {
    println!("G-switcher 2.0.1 compatibility tool");
    println!("  g-switcher-compatibility.exe record [output.md]");
    println!("  g-switcher-compatibility.exe resume [output.md]");
    println!("  g-switcher-compatibility.exe verify [matrix.md]");
    println!("  g-switcher-compatibility.exe scaffold [output.md]");
    println!();
    println!(
        "The recorder saves after every application. Resume keeps rows that already satisfy the strict release gate."
    );
    println!(
        "This executable does not change PowerShell execution policy and does not require PowerShell."
    );
}

fn record(path: &Path, resume: bool) -> Result<(), String> {
    let windows_build = detect_windows_build().unwrap_or_else(|| "UNKNOWN".to_owned());
    let mut completed = if resume && path.is_file() {
        let text = fs::read_to_string(path)
            .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
        parse_matrix(&text)?
            .into_iter()
            .map(|row| (row.application.clone(), row))
            .collect::<HashMap<_, _>>()
    } else {
        HashMap::new()
    };

    println!("G-switcher 2.0.1 manual compatibility gate");
    println!("Windows build: {windows_build}");
    println!("Do not use real passwords, PINs, OTPs, API keys, or other secrets.");
    println!("Core results: PASS / UNSUPPORTED/FAIL-OPEN / FAIL.");
    println!("Edge and Chrome ordinary editable fields require PASS for public 2.0.1.");
    println!("Undo/password may also be N/A only when genuinely not applicable.");
    println!("Progress is saved after every application.\n");

    for application in REQUIRED_APPLICATIONS {
        if resume {
            if let Some(existing) = completed.get(application) {
                if row_passes_release_gate(existing) {
                    println!("{application}: existing passing row kept.");
                    continue;
                }
                println!("{application}: existing row is incomplete/blocking and will be retested.");
            }
        }

        println!("============================================================");
        println!("{application}");
        println!("Complete these checks in the actual application before answering:");
        println!("  1. Auto: type ghbdtn<space> under EN -> привет<space>, adjacent text intact.");
        println!(
            "  2. Manual-only: ghbdtn + current-word hotkey -> привет; Undo restores exactly."
        );
        println!("  3. Select ghbdtn rfr ltkf -> selected-text conversion -> привет как дела; Undo exact.");
        println!("  4. Move caret with mouse/arrows before a pending boundary; stale correction must not fire.");
        println!("  5. Switch focus while correction could be pending; neither old nor new field may be corrupted.");
        println!("  6. Dummy password/PIN/credential field: no mutation and no layout change.");
        println!("  7. Pause/Resume + Auto/Manual-only/Disabled modes.");
        println!("  8. If unsupported, original input/hotkeys must remain non-destructive.");

        let detected = detect_application_version(application);
        if let Some(value) = &detected {
            println!("Detected version: {value}");
        }
        let existing_version = completed
            .get(application)
            .map(|row| row.version.as_str())
            .filter(|value| !metadata_is_blocking(value));
        let version_default = detected.as_deref().or(existing_version).unwrap_or("");
        let version = prompt_text("Version tested", version_default, false)?;
        let build = prompt_text("Windows build", &windows_build, false)?;
        let auto = prompt_result("Auto", false)?;
        let manual = prompt_result("Manual current word", false)?;
        let selected = prompt_result("Selected text", false)?;
        let undo = prompt_result("Undo", true)?;
        let password = prompt_result("Password/sensitive fields", true)?;
        let notes = prompt_text("Result / notes", "", true)?;

        completed.insert(
            application.to_owned(),
            Row {
                application: application.to_owned(),
                version,
                windows_build: build,
                auto,
                manual,
                selected,
                undo,
                password,
                notes,
            },
        );
        save_progress(path, &completed, &windows_build)?;
        println!("Progress saved: {}\n", path.display());
    }

    let rows = ordered_rows(&completed, &windows_build);
    save_rows(path, &rows)?;
    println!("Saved final matrix: {}", path.display());
    match verify_rows(&rows) {
        Ok(()) => {
            println!("G-switcher 2.0.1 manual compatibility gate PASSED.");
            Ok(())
        }
        Err(error) => {
            println!("Matrix saved, but the release gate is BLOCKED: {error}");
            Err(error)
        }
    }
}

fn scaffold(path: &Path) -> Result<(), String> {
    let windows_build = detect_windows_build().unwrap_or_else(|| "UNKNOWN".to_owned());
    let rows = REQUIRED_APPLICATIONS
        .iter()
        .map(|application| pending_row(application, &windows_build))
        .collect::<Vec<_>>();
    save_rows(path, &rows)?;
    println!("Saved scaffold: {}", path.display());
    Ok(())
}

fn save_progress(
    path: &Path,
    completed: &HashMap<String, Row>,
    windows_build: &str,
) -> Result<(), String> {
    save_rows(path, &ordered_rows(completed, windows_build))
}

fn save_rows(path: &Path, rows: &[Row]) -> Result<(), String> {
    let temporary = path.with_extension("md.tmp");
    fs::write(&temporary, render_matrix(rows))
        .map_err(|error| format!("cannot write {}: {error}", temporary.display()))?;
    if path.exists() {
        fs::remove_file(path)
            .map_err(|error| format!("cannot replace {}: {error}", path.display()))?;
    }
    fs::rename(&temporary, path)
        .map_err(|error| format!("cannot finalize {}: {error}", path.display()))
}

fn ordered_rows(completed: &HashMap<String, Row>, windows_build: &str) -> Vec<Row> {
    REQUIRED_APPLICATIONS
        .iter()
        .map(|application| {
            completed
                .get(*application)
                .cloned()
                .unwrap_or_else(|| pending_row(application, windows_build))
        })
        .collect()
}

fn pending_row(application: &str, windows_build: &str) -> Row {
    Row {
        application: application.to_owned(),
        version: "UNKNOWN".to_owned(),
        windows_build: windows_build.to_owned(),
        auto: "PENDING".to_owned(),
        manual: "PENDING".to_owned(),
        selected: "PENDING".to_owned(),
        undo: "PENDING".to_owned(),
        password: "PENDING".to_owned(),
        notes: String::new(),
    }
}

fn verify_path(path: &Path) -> Result<(), String> {
    let text = fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let rows = parse_matrix(&text)?;
    verify_rows(&rows)?;
    println!("G-switcher 2.0.1 manual compatibility gate PASSED for all required applications.");
    Ok(())
}

fn prompt_text(label: &str, default: &str, allow_empty: bool) -> Result<String, String> {
    loop {
        if default.is_empty() {
            print!("{label}: ");
        } else {
            print!("{label} [{default}]: ");
        }
        io::stdout().flush().map_err(|error| error.to_string())?;
        let mut input = String::new();
        io::stdin()
            .read_line(&mut input)
            .map_err(|error| error.to_string())?;
        let value = input.trim();
        let value = if value.is_empty() { default } else { value };
        if allow_empty || !value.trim().is_empty() {
            return Ok(value.trim().to_owned());
        }
        println!("A non-empty value is required.");
    }
}

fn prompt_result(label: &str, optional: bool) -> Result<String, String> {
    loop {
        if optional {
            print!("{label} [1=PASS, 2=UNSUPPORTED/FAIL-OPEN, 3=FAIL, 4=N/A]: ");
        } else {
            print!("{label} [1=PASS, 2=UNSUPPORTED/FAIL-OPEN, 3=FAIL]: ");
        }
        io::stdout().flush().map_err(|error| error.to_string())?;
        let mut input = String::new();
        io::stdin()
            .read_line(&mut input)
            .map_err(|error| error.to_string())?;
        match input.trim().to_ascii_uppercase().as_str() {
            "1" | "PASS" => return Ok("PASS".to_owned()),
            "2" | "UNSUPPORTED/FAIL-OPEN" => return Ok("UNSUPPORTED/FAIL-OPEN".to_owned()),
            "3" | "FAIL" => return Ok("FAIL".to_owned()),
            "4" | "N/A" if optional => return Ok("N/A".to_owned()),
            _ => println!("Invalid result. Please choose one of the displayed values."),
        }
    }
}

fn render_matrix(rows: &[Row]) -> String {
    let mut out = String::from(
        "# G-switcher 2.0.1 - manual compatibility results\n\n## Manual application matrix\n\n\
         | Application | Version tested | Windows build | Auto | Manual current word | Selected text | Undo | Password/sensitive fields | Result / notes |\n\
         |---|---|---|---|---|---|---|---|---|\n",
    );
    for row in rows {
        out.push_str(&format!(
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} |\n",
            escape_cell(&row.application),
            escape_cell(&row.version),
            escape_cell(&row.windows_build),
            escape_cell(&row.auto),
            escape_cell(&row.manual),
            escape_cell(&row.selected),
            escape_cell(&row.undo),
            escape_cell(&row.password),
            escape_cell(&row.notes),
        ));
    }
    out.push_str("\n## End manual results\n");
    out
}

fn escape_cell(value: &str) -> String {
    value
        .replace('|', "\\|")
        .replace('\r', " ")
        .replace('\n', " ")
}

fn parse_matrix(text: &str) -> Result<Vec<Row>, String> {
    let start = text
        .lines()
        .position(|line| line.trim() == "## Manual application matrix")
        .ok_or_else(|| "Manual application matrix section is missing.".to_owned())?;

    let mut rows = Vec::new();
    for line in text.lines().skip(start + 1) {
        if line.starts_with("## ") {
            break;
        }
        if !line.trim_start().starts_with('|')
            || line.contains("|---")
            || line.contains("| Application |")
        {
            continue;
        }
        let cells = split_markdown_row(line);
        if cells.len() < 9 {
            return Err(format!("Malformed compatibility row: {line}"));
        }
        rows.push(Row {
            application: cells[0].clone(),
            version: cells[1].clone(),
            windows_build: cells[2].clone(),
            auto: cells[3].clone(),
            manual: cells[4].clone(),
            selected: cells[5].clone(),
            undo: cells[6].clone(),
            password: cells[7].clone(),
            notes: cells[8..].join(" | "),
        });
    }
    Ok(rows)
}

fn split_markdown_row(line: &str) -> Vec<String> {
    let trimmed = line.trim().trim_matches('|');
    let mut cells = Vec::new();
    let mut current = String::new();
    let mut escaped = false;
    for ch in trimmed.chars() {
        if escaped {
            current.push(ch);
            escaped = false;
        } else if ch == '\\' {
            escaped = true;
        } else if ch == '|' {
            cells.push(current.trim().to_owned());
            current.clear();
        } else {
            current.push(ch);
        }
    }
    if escaped {
        current.push('\\');
    }
    cells.push(current.trim().to_owned());
    cells
}

fn row_passes_release_gate(row: &Row) -> bool {
    let allowed_core: &[&str] = if CORE_PASS_ONLY.contains(&row.application.as_str()) {
        &["PASS"]
    } else {
        &CORE_RESULTS
    };
    !metadata_is_blocking(&row.version)
        && !metadata_is_blocking(&row.windows_build)
        && result_allowed(&row.auto, allowed_core)
        && result_allowed(&row.manual, allowed_core)
        && result_allowed(&row.selected, allowed_core)
        && result_allowed(&row.undo, &OPTIONAL_RESULTS)
        && result_allowed(&row.password, &OPTIONAL_RESULTS)
}

fn verify_rows(rows: &[Row]) -> Result<(), String> {
    let mut by_app = HashMap::new();
    for row in rows {
        if by_app.insert(row.application.as_str(), row).is_some() {
            return Err(format!("duplicate compatibility row for {}", row.application));
        }
    }

    for application in REQUIRED_APPLICATIONS {
        let row = by_app
            .get(application)
            .ok_or_else(|| format!("missing required compatibility row for {application}"))?;
        validate_metadata(application, "Version tested", &row.version)?;
        validate_metadata(application, "Windows build", &row.windows_build)?;

        let allowed_core: &[&str] = if CORE_PASS_ONLY.contains(&application) {
            &["PASS"]
        } else {
            &CORE_RESULTS
        };
        validate_result(application, "Auto", &row.auto, allowed_core)?;
        validate_result(
            application,
            "Manual current word",
            &row.manual,
            allowed_core,
        )?;
        validate_result(application, "Selected text", &row.selected, allowed_core)?;
        validate_result(application, "Undo", &row.undo, &OPTIONAL_RESULTS)?;
        validate_result(
            application,
            "Password/sensitive fields",
            &row.password,
            &OPTIONAL_RESULTS,
        )?;
    }
    Ok(())
}

fn metadata_is_blocking(value: &str) -> bool {
    let normalized = value.trim().to_ascii_uppercase();
    [
        "",
        "PENDING",
        "UNKNOWN",
        "N/A",
        "NOT INSTALLED",
        "UNAVAILABLE",
    ]
    .contains(&normalized.as_str())
}

fn validate_metadata(application: &str, column: &str, value: &str) -> Result<(), String> {
    if metadata_is_blocking(value) {
        return Err(format!("{application} / {column} is incomplete: '{value}'"));
    }
    Ok(())
}

fn result_allowed(value: &str, allowed: &[&str]) -> bool {
    let normalized = value.trim().to_ascii_uppercase();
    allowed.contains(&normalized.as_str())
}

fn validate_result(
    application: &str,
    column: &str,
    value: &str,
    allowed: &[&str],
) -> Result<(), String> {
    if !result_allowed(value, allowed) {
        return Err(format!(
            "{application} / {column} contains blocking result '{value}'. Allowed: {}",
            allowed.join(", ")
        ));
    }
    Ok(())
}

fn detect_windows_build() -> Option<String> {
    query_registry_value(
        r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        "CurrentBuildNumber",
    )
}

fn detect_application_version(application: &str) -> Option<String> {
    match application {
        // Do not launch GUI applications merely to ask for their version. Some
        // Chromium builds delegate to a long-lived browser process, which can
        // hang a recorder or CI smoke test. BLBeacon is read-only registry
        // metadata maintained by Chromium installers/updaters.
        "Microsoft Edge" => query_first_registry_value(
            &[
                r"HKCU\Software\Microsoft\Edge\BLBeacon",
                r"HKLM\Software\Microsoft\Edge\BLBeacon",
                r"HKLM\Software\WOW6432Node\Microsoft\Edge\BLBeacon",
            ],
            "version",
        ),
        "Google Chrome" => query_first_registry_value(
            &[
                r"HKCU\Software\Google\Chrome\BLBeacon",
                r"HKLM\Software\Google\Chrome\BLBeacon",
                r"HKLM\Software\WOW6432Node\Google\Chrome\BLBeacon",
            ],
            "version",
        ),
        _ => None,
    }
}

fn query_first_registry_value(keys: &[&str], name: &str) -> Option<String> {
    keys.iter()
        .find_map(|key| query_registry_value(key, name))
}

fn query_registry_value(key: &str, name: &str) -> Option<String> {
    let output = Command::new("reg.exe")
        .args(["query", key, "/v", name])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    parse_reg_value(&String::from_utf8_lossy(&output.stdout), name)
}

fn parse_reg_value(output: &str, name: &str) -> Option<String> {
    output.lines().find_map(|line| {
        let trimmed = line.trim();
        if !trimmed
            .to_ascii_lowercase()
            .starts_with(&name.to_ascii_lowercase())
        {
            return None;
        }
        let mut parts = trimmed.split_whitespace();
        let _name = parts.next()?;
        let _kind = parts.next()?;
        let value = parts.collect::<Vec<_>>().join(" ");
        (!value.is_empty()).then_some(value)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_rows() -> Vec<Row> {
        REQUIRED_APPLICATIONS
            .iter()
            .map(|application| Row {
                application: (*application).to_owned(),
                version: "1.0.0".to_owned(),
                windows_build: "26100".to_owned(),
                auto: "PASS".to_owned(),
                manual: "PASS".to_owned(),
                selected: "PASS".to_owned(),
                undo: "PASS".to_owned(),
                password: "PASS".to_owned(),
                notes: "fixture".to_owned(),
            })
            .collect()
    }

    #[test]
    fn valid_complete_matrix_passes() {
        assert!(verify_rows(&valid_rows()).is_ok());
    }

    #[test]
    fn edge_and_chrome_require_actual_core_pass() {
        let mut rows = valid_rows();
        rows.iter_mut()
            .find(|row| row.application == "Microsoft Edge")
            .unwrap()
            .auto = "UNSUPPORTED/FAIL-OPEN".to_owned();
        assert!(verify_rows(&rows).is_err());
    }

    #[test]
    fn unsupported_is_allowed_for_non_browser_core_target() {
        let mut rows = valid_rows();
        let terminal = rows
            .iter_mut()
            .find(|row| row.application == "Windows Terminal")
            .unwrap();
        terminal.auto = "UNSUPPORTED/FAIL-OPEN".to_owned();
        terminal.manual = "UNSUPPORTED/FAIL-OPEN".to_owned();
        terminal.selected = "UNSUPPORTED/FAIL-OPEN".to_owned();
        terminal.undo = "N/A".to_owned();
        terminal.password = "N/A".to_owned();
        assert!(verify_rows(&rows).is_ok());
        assert!(row_passes_release_gate(terminal));
    }

    #[test]
    fn pending_and_unknown_block() {
        let mut rows = valid_rows();
        rows[0].auto = "PENDING".to_owned();
        assert!(verify_rows(&rows).is_err());
        rows[0].auto = "PASS".to_owned();
        rows[1].version = "UNKNOWN".to_owned();
        assert!(verify_rows(&rows).is_err());
    }

    #[test]
    fn duplicate_application_rows_block() {
        let mut rows = valid_rows();
        rows.push(rows[0].clone());
        assert!(verify_rows(&rows).is_err());
    }

    #[test]
    fn markdown_roundtrip_preserves_escaped_notes() {
        let mut rows = valid_rows();
        rows[0].notes = "left | right".to_owned();
        let text = render_matrix(&rows);
        let parsed = parse_matrix(&text).unwrap();
        assert_eq!(parsed.len(), REQUIRED_APPLICATIONS.len());
        assert_eq!(parsed[0].notes, "left | right");
        assert!(verify_rows(&parsed).is_ok());
    }

    #[test]
    fn progress_matrix_keeps_pending_rows() {
        let mut completed = HashMap::new();
        completed.insert("Notepad".to_owned(), valid_rows()[0].clone());
        let rows = ordered_rows(&completed, "26100");
        assert_eq!(rows.len(), REQUIRED_APPLICATIONS.len());
        assert_eq!(rows[0].auto, "PASS");
        assert_eq!(rows[1].auto, "PENDING");
    }

    #[test]
    fn registry_parser_extracts_value() {
        let sample = "    CurrentBuildNumber    REG_SZ    26100\r\n";
        assert_eq!(
            parse_reg_value(sample, "CurrentBuildNumber"),
            Some("26100".to_owned())
        );
    }
}
