use std::collections::{HashSet, VecDeque};
use std::env;
use std::fs;
use std::path::Path;

use g_switcher::{
    code_safe::is_code_safe_token,
    detector::{
        correction_with_context, detect_with_context, opposite_candidate_is_prefix,
        DEFAULT_CONFIDENCE_THRESHOLD,
    },
    frequency_model,
    layout::opposite_layout_text,
    model::Language,
};

fn is_ru_letter(ch: char) -> bool {
    matches!(ch, 'а'..='я' | 'А'..='Я' | 'ё' | 'Ё')
}

fn is_combining_mark(ch: char) -> bool {
    matches!(ch, '\u{0300}'..='\u{036f}')
}

fn extract_words(text: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if is_ru_letter(ch) {
            current.push(ch);
        } else if is_combining_mark(ch) && !current.is_empty() {
            continue;
        } else if !current.is_empty() {
            if current.chars().count() >= 3 {
                words.push(std::mem::take(&mut current));
            } else {
                current.clear();
            }
        }
    }
    if current.chars().count() >= 3 {
        words.push(current);
    }
    words
}

fn is_all_caps_word(word: &str) -> bool {
    let mut has_letter = false;
    for ch in word.chars() {
        if is_ru_letter(ch) {
            has_letter = true;
            if ch.is_lowercase() {
                return false;
            }
        }
    }
    has_letter
}

fn csv_escape(value: &str) -> String {
    if value.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", value.replace('"', "\"\""))
    } else {
        value.to_owned()
    }
}

fn main() {
    let specs: Vec<String> = env::args().skip(1).collect();
    if specs.is_empty() {
        eprintln!("usage: wikipedia_corpus_audit TITLE=FILE [TITLE=FILE ...]");
        std::process::exit(2);
    }

    let out_dir = Path::new("audit-output");
    fs::create_dir_all(out_dir).expect("failed to create audit-output");

    let mut failures_csv = String::from(
        "article,word,wrong_layout,observed,confidence,raw_confidence,cause,target_prefix,target_frequency,context\n",
    );
    let mut summary = String::new();
    let mut total_unique = 0usize;
    let mut total_passed = 0usize;
    let mut total_failed = 0usize;
    let mut total_excluded_all_caps = 0usize;

    for spec in specs {
        let (title, file) = spec
            .split_once('=')
            .unwrap_or_else(|| panic!("invalid article spec: {spec}"));
        let text = fs::read_to_string(file).unwrap_or_else(|e| panic!("failed to read {file}: {e}"));
        let words = extract_words(&text);

        let mut seen = HashSet::new();
        let mut context: VecDeque<String> = VecDeque::with_capacity(2);
        let mut unique = 0usize;
        let mut passed = 0usize;
        let mut failed = 0usize;
        let mut excluded_all_caps = 0usize;

        for original in words {
            let normalized = original.to_lowercase();
            let previous: Vec<String> = context.iter().cloned().collect();

            if is_all_caps_word(&original) {
                excluded_all_caps += 1;
            } else if seen.insert(normalized.clone()) {
                unique += 1;
                let wrong = opposite_layout_text(&normalized, Language::Russian);
                let raw = detect_with_context(&wrong, &[], &previous);
                let detection = correction_with_context(
                    &wrong,
                    &[],
                    DEFAULT_CONFIDENCE_THRESHOLD,
                    &previous,
                );

                let ok = detection.as_ref().is_some_and(|d| {
                    d.target == Language::Russian && d.corrected == normalized
                });
                if ok {
                    passed += 1;
                } else {
                    failed += 1;
                    let (observed, confidence) = match detection {
                        Some(d) => (d.corrected, d.confidence.to_string()),
                        None => ("KEEP".to_owned(), String::new()),
                    };
                    let prefix = opposite_candidate_is_prefix(&wrong);
                    let target_frequency =
                        frequency_model::word_score(Language::Russian, &normalized);
                    let raw_confidence = raw
                        .as_ref()
                        .map(|d| d.confidence.to_string())
                        .unwrap_or_default();
                    let cause = if is_code_safe_token(&wrong) {
                        "code_safe"
                    } else if prefix {
                        "target_prefix_hold"
                    } else if raw.is_some() {
                        "below_threshold"
                    } else {
                        "no_detection"
                    };
                    let context_text = previous.join(" ");
                    failures_csv.push_str(&format!(
                        "{},{},{},{},{},{},{},{},{},{}\n",
                        csv_escape(title),
                        csv_escape(&normalized),
                        csv_escape(&wrong),
                        csv_escape(&observed),
                        csv_escape(&confidence),
                        csv_escape(&raw_confidence),
                        cause,
                        prefix,
                        target_frequency,
                        csv_escape(&context_text),
                    ));
                }
            }

            if context.len() == 2 {
                context.pop_front();
            }
            context.push_back(normalized);
        }

        total_unique += unique;
        total_passed += passed;
        total_failed += failed;
        total_excluded_all_caps += excluded_all_caps;
        let rate = if unique == 0 {
            0.0
        } else {
            passed as f64 * 100.0 / unique as f64
        };
        summary.push_str(&format!(
            "{title}: unique={unique} passed={passed} failed={failed} excluded_all_caps={excluded_all_caps} rate={rate:.4}%\n"
        ));
    }

    let total_rate = if total_unique == 0 {
        0.0
    } else {
        total_passed as f64 * 100.0 / total_unique as f64
    };
    summary.push_str(&format!(
        "TOTAL: unique={total_unique} passed={total_passed} failed={total_failed} excluded_all_caps={total_excluded_all_caps} rate={total_rate:.4}%\n"
    ));

    fs::write(out_dir.join("failures.csv"), failures_csv).expect("failed to write failures.csv");
    fs::write(out_dir.join("summary.txt"), &summary).expect("failed to write summary.txt");
    print!("{summary}");
}
