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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Script {
    Russian,
    Latin,
}

#[derive(Debug)]
struct Token {
    script: Script,
    text: String,
}

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

#[derive(Default)]
struct FalsePositiveAgg {
    occurrences: usize,
    corrected: BTreeSet<String>,
    confidences: BTreeSet<String>,
    sample_contexts: Vec<String>,
}

fn is_ru_letter(ch: char) -> bool {
    matches!(ch, 'а'..='я' | 'А'..='Я' | 'ё' | 'Ё')
}

fn is_latin_letter(ch: char) -> bool {
    ch.is_ascii_alphabetic()
        || matches!(ch, '\u{00c0}'..='\u{00ff}' | '\u{0100}'..='\u{024f}')
}

fn is_combining_mark(ch: char) -> bool {
    matches!(ch, '\u{0300}'..='\u{036f}')
}

fn tokenize(text: &str) -> Vec<Token> {
    let mut out = Vec::new();
    let mut current = String::new();
    let mut script: Option<Script> = None;

    let flush = |out: &mut Vec<Token>, current: &mut String, script: &mut Option<Script>| {
        if let Some(kind) = script.take() {
            if !current.is_empty() {
                out.push(Token {
                    script: kind,
                    text: std::mem::take(current),
                });
            }
        } else {
            current.clear();
        }
    };

    for ch in text.chars() {
        let next_script = if is_ru_letter(ch) {
            Some(Script::Russian)
        } else if is_latin_letter(ch) {
            Some(Script::Latin)
        } else {
            None
        };

        if is_combining_mark(ch) && !current.is_empty() {
            continue;
        }

        match (script, next_script) {
            (Some(existing), Some(next)) if existing == next => current.push(ch),
            (_, Some(next)) => {
                flush(&mut out, &mut current, &mut script);
                script = Some(next);
                current.push(ch);
            }
            (_, None) => flush(&mut out, &mut current, &mut script),
        }
    }
    flush(&mut out, &mut current, &mut script);
    out
}

fn is_all_caps_ru(word: &str) -> bool {
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

fn add_false_positive(
    map: &mut BTreeMap<String, FalsePositiveAgg>,
    word: &str,
    corrected: &str,
    confidence: u8,
    previous: &[String],
) {
    let entry = map.entry(word.to_owned()).or_default();
    entry.occurrences += 1;
    entry.corrected.insert(corrected.to_owned());
    entry.confidences.insert(confidence.to_string());
    if entry.sample_contexts.len() < 3 {
        entry.sample_contexts.push(previous.join(" "));
    }
}

fn main() {
    let input = env::args().nth(1).unwrap_or_else(|| {
        eprintln!("usage: war_and_peace_audit FILE");
        std::process::exit(2);
    });
    let text = fs::read_to_string(&input).unwrap_or_else(|e| panic!("failed to read {input}: {e}"));
    let tokens = tokenize(&text);

    let out_dir = Path::new("audit-output");
    fs::create_dir_all(out_dir).expect("failed to create audit-output");

    let mut context: VecDeque<String> = VecDeque::with_capacity(2);
    let mut ru_tokens_all_lengths = 0usize;
    let mut ru_excluded_short = 0usize;
    let mut ru_excluded_all_caps = 0usize;
    let mut ru_eligible_occurrences = 0usize;
    let mut ru_passed_occurrences = 0usize;
    let mut ru_failed_occurrences = 0usize;
    let mut ru_unique_eligible = BTreeSet::new();
    let mut ru_occurrence_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut ru_failures: BTreeMap<String, FailureAgg> = BTreeMap::new();
    let mut ru_source_checked = 0usize;
    let mut ru_source_false_corrections = 0usize;
    let mut ru_source_false_positive_forms: BTreeMap<String, FalsePositiveAgg> = BTreeMap::new();

    let mut latin_tokens_all_lengths = 0usize;
    let mut latin_eligible_occurrences = 0usize;
    let mut latin_source_false_corrections = 0usize;
    let mut latin_unique_eligible = BTreeSet::new();
    let mut latin_source_false_positive_forms: BTreeMap<String, FalsePositiveAgg> = BTreeMap::new();

    for token in tokens {
        let normalized = token.text.to_lowercase();
        let previous: Vec<String> = context.iter().cloned().collect();
        let len = normalized.chars().count();

        match token.script {
            Script::Russian => {
                ru_tokens_all_lengths += 1;
                *ru_occurrence_counts.entry(normalized.clone()).or_default() += 1;

                if len < 3 {
                    ru_excluded_short += 1;
                } else if is_all_caps_ru(&token.text) {
                    ru_excluded_all_caps += 1;
                } else {
                    ru_eligible_occurrences += 1;
                    ru_source_checked += 1;
                    ru_unique_eligible.insert(normalized.clone());

                    if let Some(d) = correction_with_context(
                        &normalized,
                        &[],
                        DEFAULT_CONFIDENCE_THRESHOLD,
                        &previous,
                    ) {
                        ru_source_false_corrections += 1;
                        add_false_positive(
                            &mut ru_source_false_positive_forms,
                            &normalized,
                            &d.corrected,
                            d.confidence,
                            &previous,
                        );
                    }

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
                        ru_passed_occurrences += 1;
                    } else {
                        ru_failed_occurrences += 1;
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
                        let entry = ru_failures.entry(normalized.clone()).or_default();
                        entry.failed_occurrences += 1;
                        entry.causes.insert(cause.to_owned());
                        entry.wrong = wrong.clone();
                        entry.observed.insert(observed);
                        entry.raw_confidences.insert(raw_conf);
                        entry.source_score = frequency_model::word_score(Language::English, &wrong);
                        entry.target_score =
                            frequency_model::word_score(Language::Russian, &normalized);
                        if entry.sample_contexts.len() < 3 {
                            entry.sample_contexts.push(previous.join(" "));
                        }
                    }
                }
            }
            Script::Latin => {
                latin_tokens_all_lengths += 1;
                if len >= 3 {
                    latin_eligible_occurrences += 1;
                    latin_unique_eligible.insert(normalized.clone());
                    if let Some(d) = correction_with_context(
                        &normalized,
                        &[],
                        DEFAULT_CONFIDENCE_THRESHOLD,
                        &previous,
                    ) {
                        latin_source_false_corrections += 1;
                        add_false_positive(
                            &mut latin_source_false_positive_forms,
                            &normalized,
                            &d.corrected,
                            d.confidence,
                            &previous,
                        );
                    }
                }
            }
        }

        if context.len() == 2 {
            context.pop_front();
        }
        context.push_back(normalized);
    }

    for (word, entry) in ru_failures.iter_mut() {
        entry.total_occurrences = *ru_occurrence_counts.get(word).unwrap_or(&0);
    }

    let ru_unique_failed = ru_failures.len();
    let ru_unique_fully_passed = ru_unique_eligible.len().saturating_sub(ru_unique_failed);
    let ru_occurrence_rate = if ru_eligible_occurrences == 0 {
        0.0
    } else {
        ru_passed_occurrences as f64 * 100.0 / ru_eligible_occurrences as f64
    };
    let ru_unique_rate = if ru_unique_eligible.is_empty() {
        0.0
    } else {
        ru_unique_fully_passed as f64 * 100.0 / ru_unique_eligible.len() as f64
    };
    let ru_source_keep_rate = if ru_source_checked == 0 {
        0.0
    } else {
        (ru_source_checked - ru_source_false_corrections) as f64 * 100.0 / ru_source_checked as f64
    };
    let latin_source_keep_rate = if latin_eligible_occurrences == 0 {
        0.0
    } else {
        (latin_eligible_occurrences - latin_source_false_corrections) as f64 * 100.0
            / latin_eligible_occurrences as f64
    };

    let summary = format!(
        concat!(
            "source_chars={}\n",
            "russian_tokens_all_lengths={}\n",
            "russian_excluded_short_lt3={}\n",
            "russian_excluded_all_caps={}\n",
            "russian_eligible_occurrences={}\n",
            "russian_wrong_layout_passed_occurrences={}\n",
            "russian_wrong_layout_failed_occurrences={}\n",
            "russian_wrong_layout_occurrence_rate={:.6}%\n",
            "russian_unique_eligible_forms={}\n",
            "russian_unique_fully_passed_forms={}\n",
            "russian_unique_failed_forms={}\n",
            "russian_wrong_layout_unique_rate={:.6}%\n",
            "russian_correct_source_checked={}\n",
            "russian_correct_source_false_corrections={}\n",
            "russian_correct_source_keep_rate={:.6}%\n",
            "russian_correct_source_false_positive_forms={}\n",
            "latin_tokens_all_lengths={}\n",
            "latin_eligible_occurrences={}\n",
            "latin_unique_eligible_forms={}\n",
            "latin_correct_source_false_corrections={}\n",
            "latin_correct_source_keep_rate={:.6}%\n",
            "latin_correct_source_false_positive_forms={}\n"
        ),
        text.chars().count(),
        ru_tokens_all_lengths,
        ru_excluded_short,
        ru_excluded_all_caps,
        ru_eligible_occurrences,
        ru_passed_occurrences,
        ru_failed_occurrences,
        ru_occurrence_rate,
        ru_unique_eligible.len(),
        ru_unique_fully_passed,
        ru_unique_failed,
        ru_unique_rate,
        ru_source_checked,
        ru_source_false_corrections,
        ru_source_keep_rate,
        ru_source_false_positive_forms.len(),
        latin_tokens_all_lengths,
        latin_eligible_occurrences,
        latin_unique_eligible.len(),
        latin_source_false_corrections,
        latin_source_keep_rate,
        latin_source_false_positive_forms.len(),
    );

    let mut failures_csv = String::from(
        "word,wrong_layout,total_occurrences,failed_occurrences,causes,source_en_score,target_ru_score,raw_confidences,observed,sample_contexts\n",
    );
    for (word, f) in &ru_failures {
        failures_csv.push_str(&format!(
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

    let write_fp_csv = |path: &Path, values: &BTreeMap<String, FalsePositiveAgg>| {
        let mut csv = String::from("word,false_correction_occurrences,corrected,confidences,sample_contexts\n");
        for (word, f) in values {
            csv.push_str(&format!(
                "{},{},{},{},{}\n",
                csv_escape(word),
                f.occurrences,
                csv_escape(&f.corrected.iter().cloned().collect::<Vec<_>>().join("|")),
                csv_escape(&f.confidences.iter().cloned().collect::<Vec<_>>().join("|")),
                csv_escape(&f.sample_contexts.join(" || ")),
            ));
        }
        fs::write(path, csv).expect("failed to write false-positive CSV");
    };

    fs::write(out_dir.join("summary.txt"), &summary).expect("failed to write summary");
    fs::write(out_dir.join("failures.csv"), failures_csv).expect("failed to write failures");
    write_fp_csv(
        &out_dir.join("russian_source_false_positives.csv"),
        &ru_source_false_positive_forms,
    );
    write_fp_csv(
        &out_dir.join("latin_source_false_positives.csv"),
        &latin_source_false_positive_forms,
    );
    print!("{summary}");
}
