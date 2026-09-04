use std::collections::{BTreeMap, BTreeSet, VecDeque};
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

#[derive(Default)]
struct FailureAgg {
    total_occurrences: usize,
    failed_occurrences: usize,
    causes: BTreeSet<String>,
    wrong: String,
    observed: BTreeSet<String>,
    raw_confidences: BTreeSet<String>,
    source_score: i32,
    target_score: i32,
    sample_contexts: Vec<String>,
}

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
            words.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
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
    let input = env::args().nth(1).unwrap_or_else(|| {
        eprintln!("usage: war_and_peace_audit FILE");
        std::process::exit(2);
    });
    let text = fs::read_to_string(&input).unwrap_or_else(|e| panic!("failed to read {input}: {e}"));
    let words = extract_words(&text);

    let out_dir = Path::new("audit-output");
    fs::create_dir_all(out_dir).expect("failed to create audit-output");

    let mut context: VecDeque<String> = VecDeque::with_capacity(2);
    let mut total_ru_tokens = 0usize;
    let mut excluded_short = 0usize;
    let mut excluded_all_caps = 0usize;
    let mut eligible_occurrences = 0usize;
    let mut passed_occurrences = 0usize;
    let mut failed_occurrences = 0usize;
    let mut unique_eligible = BTreeSet::new();
    let mut unique_passed_at_least_once = BTreeSet::new();
    let mut occurrence_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut failures: BTreeMap<String, FailureAgg> = BTreeMap::new();

    for original in words {
        total_ru_tokens += 1;
        let normalized = original.to_lowercase();
        *occurrence_counts.entry(normalized.clone()).or_default() += 1;
        let previous: Vec<String> = context.iter().cloned().collect();
        let len = normalized.chars().count();

        if len < 3 {
            excluded_short += 1;
        } else if is_all_caps_word(&original) {
            excluded_all_caps += 1;
        } else {
            eligible_occurrences += 1;
            unique_eligible.insert(normalized.clone());
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
                passed_occurrences += 1;
                unique_passed_at_least_once.insert(normalized.clone());
            } else {
                failed_occurrences += 1;
                let prefix = opposite_candidate_is_prefix(&wrong);
                let cause = if is_code_safe_token(&wrong) {
                    "code_safe"
                } else if prefix {
                    "target_prefix_hold"
                } else if raw.is_some() {
                    "below_threshold"
                } else {
                    "no_detection"
                };
                let observed = detection
                    .as_ref()
                    .map(|d| d.corrected.clone())
                    .unwrap_or_else(|| "KEEP".to_owned());
                let raw_conf = raw
                    .as_ref()
                    .map(|d| d.confidence.to_string())
                    .unwrap_or_else(|| "-".to_owned());
                let entry = failures.entry(normalized.clone()).or_default();
                entry.failed_occurrences += 1;
                entry.causes.insert(cause.to_owned());
                entry.wrong = wrong.clone();
                entry.observed.insert(observed);
                entry.raw_confidences.insert(raw_conf);
                entry.source_score = frequency_model::word_score(Language::English, &wrong);
                entry.target_score = frequency_model::word_score(Language::Russian, &normalized);
                if entry.sample_contexts.len() < 3 {
                    entry.sample_contexts.push(previous.join(" "));
                }
            }
        }

        if context.len() == 2 {
            context.pop_front();
        }
        context.push_back(normalized);
    }

    for (word, entry) in failures.iter_mut() {
        entry.total_occurrences = *occurrence_counts.get(word).unwrap_or(&0);
    }

    let unique_failed = failures.len();
    let unique_fully_passed = unique_eligible.len().saturating_sub(unique_failed);
    let occurrence_rate = if eligible_occurrences == 0 {
        0.0
    } else {
        passed_occurrences as f64 * 100.0 / eligible_occurrences as f64
    };
    let unique_rate = if unique_eligible.is_empty() {
        0.0
    } else {
        unique_fully_passed as f64 * 100.0 / unique_eligible.len() as f64
    };

    let summary = format!(
        concat!(
            "source_chars={}\n",
            "russian_tokens_all_lengths={}\n",
            "excluded_short_lt3={}\n",
            "excluded_all_caps={}\n",
            "eligible_occurrences={}\n",
            "passed_occurrences={}\n",
            "failed_occurrences={}\n",
            "occurrence_rate={:.6}%\n",
            "unique_eligible_forms={}\n",
            "unique_fully_passed_forms={}\n",
            "unique_failed_forms={}\n",
            "unique_rate={:.6}%\n"
        ),
        text.chars().count(),
        total_ru_tokens,
        excluded_short,
        excluded_all_caps,
        eligible_occurrences,
        passed_occurrences,
        failed_occurrences,
        occurrence_rate,
        unique_eligible.len(),
        unique_fully_passed,
        unique_failed,
        unique_rate,
    );

    let mut csv = String::from(
        "word,wrong_layout,total_occurrences,failed_occurrences,causes,source_en_score,target_ru_score,raw_confidences,observed,sample_contexts\n",
    );
    for (word, f) in &failures {
        csv.push_str(&format!(
            "{},{},{},{},{},{},{},{},{},{}\n",
            csv_escape(word),
            csv_escape(&f.wrong),
            f.total_occurrences,
            f.failed_occurrences,
            csv_escape(&f.causes.iter().cloned().collect::<Vec<_>>().join("|")),
            f.source_score,
            f.target_score,
            csv_escape(&f.raw_confidences.iter().cloned().collect::<Vec<_>>().join("|")),
            csv_escape(&f.observed.iter().cloned().collect::<Vec<_>>().join("|")),
            csv_escape(&f.sample_contexts.join(" || ")),
        ));
    }

    fs::write(out_dir.join("summary.txt"), &summary).expect("failed to write summary");
    fs::write(out_dir.join("failures.csv"), csv).expect("failed to write failures");
    print!("{summary}");
}
