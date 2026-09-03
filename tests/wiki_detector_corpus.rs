use std::collections::{BTreeMap, VecDeque};
use std::env;
use std::fs;
use std::path::PathBuf;

use g_switcher::detector::{detect_with_context, MAX_CONTEXT_WORDS};
use g_switcher::layout::opposite_layout_text;
use g_switcher::model::Language;

#[derive(Clone)]
struct Occurrence {
    expected: String,
    language: Language,
    context: Vec<String>,
}

#[derive(Default)]
struct Failure {
    occurrences: usize,
    expected: String,
    synthetic: String,
    actual: String,
    language: String,
    confidence: String,
    context: String,
}

#[test]
fn wikipedia_detector_corpus() {
    let corpus_path = PathBuf::from(env::var("G_SWITCHER_CORPUS_PATH").expect("G_SWITCHER_CORPUS_PATH"));
    let report_path = PathBuf::from(env::var("G_SWITCHER_DETECTOR_REPORT").unwrap_or_else(|_| "target/wiki-detector-failures.csv".into()));
    let summary_path = PathBuf::from(env::var("G_SWITCHER_DETECTOR_SUMMARY").unwrap_or_else(|_| "target/wiki-detector-summary.txt".into()));
    let text = fs::read_to_string(corpus_path).expect("read corpus");
    let occurrences = parse_occurrences(&text);
    let mut failures: BTreeMap<String, Failure> = BTreeMap::new();

    for item in &occurrences {
        let synthetic = opposite_layout_text(&item.expected, item.language);
        let detection = detect_with_context(&synthetic, &[], &item.context);
        let actual = detection.as_ref().map(|d| d.corrected.clone()).unwrap_or_else(|| synthetic.clone());
        if actual == item.expected {
            continue;
        }
        let confidence = detection.as_ref().map(|d| d.confidence.to_string()).unwrap_or_else(|| "none".into());
        let context = item.context.join(" ");
        let key = format!("{}\u{1f}{}\u{1f}{}\u{1f}{}", item.expected, synthetic, actual, context);
        let entry = failures.entry(key).or_insert_with(|| Failure {
            expected: item.expected.clone(),
            synthetic: synthetic.clone(),
            actual,
            language: match item.language { Language::Russian => "RU", Language::English => "EN" }.into(),
            confidence,
            context,
            ..Failure::default()
        });
        entry.occurrences += 1;
    }

    let mut csv = String::from("occurrences,language,expected,synthetic,actual,confidence,previous_context\n");
    for failure in failures.values() {
        csv.push_str(&format!("{},{},{},{},{},{},{}\n",
            failure.occurrences,
            q(&failure.language), q(&failure.expected), q(&failure.synthetic), q(&failure.actual), q(&failure.confidence), q(&failure.context)));
    }
    fs::write(&report_path, csv).expect("write report");
    let failed_occurrences: usize = failures.values().map(|f| f.occurrences).sum();
    fs::write(&summary_path, format!(
        "occurrences={}\nfailure_variants={}\nfailed_occurrences={}\n",
        occurrences.len(), failures.len(), failed_occurrences)).expect("write summary");
    eprintln!("detector corpus occurrences={} variants={} failed={}", occurrences.len(), failures.len(), failed_occurrences);
}

fn parse_occurrences(text: &str) -> Vec<Occurrence> {
    let mut result = Vec::new();
    let mut current = String::new();
    let mut language: Option<Language> = None;
    let mut context: VecDeque<String> = VecDeque::new();

    let flush = |result: &mut Vec<Occurrence>, current: &mut String, language: &mut Option<Language>, context: &mut VecDeque<String>| {
        let Some(lang) = *language else { current.clear(); return; };
        if current.is_empty() { *language = None; return; }
        let expected = current.clone();
        result.push(Occurrence { expected: expected.clone(), language: lang, context: context.iter().cloned().collect() });
        if context.len() >= MAX_CONTEXT_WORDS { context.pop_front(); }
        context.push_back(expected);
        current.clear();
        *language = None;
    };

    for ch in text.chars().chain(std::iter::once(' ')) {
        let next = char_language(ch);
        match (*language, next) {
            (Some(active), Some(n)) if active == n => current.push(ch),
            (None, Some(n)) => { *&mut language = Some(n); current.push(ch); }
            (Some(_), Some(n)) => { flush(&mut result, &mut current, &mut language, &mut context); language = Some(n); current.push(ch); }
            (Some(_), None) => flush(&mut result, &mut current, &mut language, &mut context),
            (None, None) => {}
        }
    }
    result
}

fn char_language(ch: char) -> Option<Language> {
    if matches!(ch, 'а'..='я' | 'А'..='Я' | 'ё' | 'Ё') { Some(Language::Russian) }
    else if ch.is_ascii_alphabetic() { Some(Language::English) }
    else { None }
}

fn q(value: &str) -> String { format!("\"{}\"", value.replace('"', "\"\"")) }
