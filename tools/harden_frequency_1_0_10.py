from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def harden_generator() -> None:
    path = Path("tools/generate_frequency_lexicon.py")
    text = path.read_text(encoding="utf-8")
    replacements = [
        ("    if length == 3:\n        return 3_000", "    if length == 3:\n        return 0"),
        (
            "// Source protection keeps the first 30,000 corpus rows per language.\n// Target promotion is deliberately narrower: ranks <= 3,000 for 3-letter\n// forms, <= 10,000 for 4-letter forms, and <= 15,000 for 5+ letters.",
            "// Generated runtime frequency evidence starts at 4 letters; 3-letter forms\n// remain under the existing context-sensitive detector policy. Source protection\n// keeps 4+ letter forms from the first 30,000 corpus rows per language. Target\n// promotion is <= 10,000 for 4-letter forms and <= 15,000 for 5+ letters.",
        ),
        ("        3 => 3_000,", "        3 => 0,"),
        (
            "pub fn has_target_prefix(language: Language, prefix: &str) -> bool {{\n    if prefix.is_empty() {{",
            "pub fn has_target_prefix(language: Language, prefix: &str) -> bool {{\n    if prefix.chars().count() < 4 {{",
        ),
        (
            "- Source protection: every normalized alphabetic form whose raw source rank is <= {SOURCE_RANK_LIMIT:,}; this layer is deliberately broad.\n- Automatic target promotion: rank <= 3,000 for 3-letter forms, <= 10,000 for 4-letter forms, <= 15,000 for 5+ letter forms.",
            "- Generated runtime frequency evidence starts at 4 letters. Three-letter corpus forms and generated prefixes shorter than 4 letters are deliberately held out so the existing context-sensitive short-word policy remains unchanged.\n- Source protection: every normalized alphabetic 4+ letter form whose raw source rank is <= {SOURCE_RANK_LIMIT:,}; this layer is deliberately broad.\n- Automatic target promotion: rank <= 10,000 for 4-letter forms and <= 15,000 for 5+ letter forms.\n- Curated G-switcher target words override generated-only source protection; curated source words still always win.",
        ),
        (
            "    ru_source = {word: data for word, data in ru.items() if data[0] <= SOURCE_RANK_LIMIT}\n    en_source = {word: data for word, data in en.items() if data[0] <= SOURCE_RANK_LIMIT}",
            "    ru_source = {\n        word: data\n        for word, data in ru.items()\n        if data[0] <= SOURCE_RANK_LIMIT and len(word) >= 4\n    }\n    en_source = {\n        word: data\n        for word, data in en.items()\n        if data[0] <= SOURCE_RANK_LIMIT and len(word) >= 4\n    }",
        ),
        (
            "    patch_runtime()\n    patch_tests()\n    write_docs(ru, en, ru_rows, en_rows, ru_source, en_source)",
            "    if \"mod frequent_forms;\" not in Path(\"src/lib.rs\").read_text(encoding=\"utf-8\"):\n        patch_runtime()\n        patch_tests()\n    write_docs(ru, en, ru_rows, en_rows, ru_source, en_source)",
        ),
    ]
    for old, new in replacements:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"generator: expected one match, got {count}: {old[:120]!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def harden_runtime() -> None:
    replace_once(
        "src/frequency_model.rs",
        "fn curated_word_score(language: Language, token: &str) -> i32 {",
        "pub fn curated_word_score(language: Language, token: &str) -> i32 {",
    )

    replace_once(
        "src/detector.rs",
        """    let normalized = normalize(token, source);\n    let source_frequency = frequency_model::source_word_score(source, &normalized);\n    if dictionary_contains(source, &normalized, user_words) || source_frequency >= 15 {\n        return None;\n    }\n\n    let target = opposite(source);\n    let mapped = opposite_layout_text(token, source);\n    let mapped_normalized = normalize(&mapped, target);\n    if !candidate_shape_is_valid(&mapped, target) {\n        return None;\n    }\n\n    let target_frequency = frequency_model::word_score(target, &mapped_normalized);\n    if dictionary_contains(target, &mapped_normalized, user_words) || target_frequency >= 15 {\n""",
        """    let normalized = normalize(token, source);\n    let source_frequency = frequency_model::source_word_score(source, &normalized);\n    let source_curated = frequency_model::curated_word_score(source, &normalized);\n    if dictionary_contains(source, &normalized, user_words) || source_curated >= 15 {\n        return None;\n    }\n\n    let target = opposite(source);\n    let mapped = opposite_layout_text(token, source);\n    let mapped_normalized = normalize(&mapped, target);\n    if !candidate_shape_is_valid(&mapped, target) {\n        return None;\n    }\n\n    let target_is_explicit = dictionary_contains(target, &mapped_normalized, user_words);\n    let target_curated = frequency_model::curated_word_score(target, &mapped_normalized);\n    if source_frequency >= 15 && !target_is_explicit && target_curated < 15 {\n        return None;\n    }\n\n    let target_frequency = frequency_model::word_score(target, &mapped_normalized);\n    if target_is_explicit || target_frequency >= 15 {\n""",
    )


def add_tests() -> None:
    anchor = """    #[test]\n    fn corrects_known_wrong_layout_words() {"""
    extra = """    #[test]\n    fn curated_targets_override_generated_only_source_protection() {\n        let detection = correction_at_boundary_with_context(\n            \"cath\",\n            &[],\n            DEFAULT_CONFIDENCE_THRESHOLD,\n            &[],\n        )\n        .expect(\"curated Russian target must override generated-only English source evidence\");\n        assert_eq!(detection.corrected, \"сфер\");\n        assert_eq!(detection.confidence, 100);\n    }\n\n    #[test]\n    fn generated_source_forms_stay_fail_open_unless_curated_target_overrides() {\n        for source in [Language::Russian, Language::English] {\n            for &(word, _rank) in crate::frequent_forms::forms(source) {\n                let mapped = opposite_layout_text(word, source);\n                let target = opposite(source);\n                let mapped_normalized = normalize(&mapped, target);\n                let source_curated = frequency_model::curated_word_score(source, word) >= 15;\n                let target_curated =\n                    frequency_model::curated_word_score(target, &mapped_normalized) >= 15;\n                let detection = correction_at_boundary_with_context(\n                    word,\n                    &[],\n                    DEFAULT_CONFIDENCE_THRESHOLD,\n                    &[],\n                );\n                if source_curated || !target_curated {\n                    assert!(\n                        detection.is_none(),\n                        \"generated source form was not preserved: {word} -> {mapped}\"\n                    );\n                } else {\n                    let detection = detection.unwrap_or_else(|| {\n                        panic!(\n                            \"curated target did not override generated-only source: {word} -> {mapped}\"\n                        )\n                    });\n                    assert_eq!(normalize(&detection.corrected, target), mapped_normalized);\n                }\n            }\n        }\n    }\n\n    #[test]\n    fn corrects_known_wrong_layout_words() {"""
    replace_once("src/detector.rs", anchor, extra)


def main() -> None:
    harden_generator()
    harden_runtime()
    add_tests()


if __name__ == "__main__":
    main()
