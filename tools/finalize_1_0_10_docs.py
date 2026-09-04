from pathlib import Path


def main() -> None:
    readme = Path("README.md")
    text = readme.read_text(encoding="utf-8")
    old = "Version 1.0.9 restores basic Russian everyday-word coverage after the missing-lexicon regression found with `Vfvf vskf hfve ghbdtn` → `Мама мыла раму привет`. The fix adds only conservative known-word entries; global detector confidence thresholds are unchanged. Version 1.0.8 first-run/autostart fixes remain intact, and Detector v3 retains the 1.0.7 full-novel baseline: 340,059/342,237 eligible wrong-layout Russian occurrences restored (99.3636%) with zero false automatic corrections across 342,237 correct Russian and 11,594 correct Latin-layout occurrences in the mixed Russian/French/German `War and Peace` corpus."
    new = "Version 1.0.10 adds a pinned, generated everyday-frequency layer from OpenSubtitles2018 surface-form frequencies while preserving the conservative detector policy. The embedded generated source layer contains 56,036 normalized Russian/English forms of four or more letters; 26,990 frequent target forms are deterministically restorable, and nine generated cross-layout collisions remain fail-open. Three-letter corpus forms stay under the existing context-sensitive policy. The exact `Vfvf vskf hfve ghbdtn` → `Мама мыла раму привет` regression remains a permanent real Win32 release gate, and global detector confidence thresholds are unchanged."
    if old not in text:
        raise SystemExit("README version paragraph marker missing")
    text = text.replace(old, new, 1)
    text = text.replace("## 1.0.9 behavior", "## 1.0.10 behavior", 1)
    marker = "- Detector v3 combines conservative layout heuristics with a baked-in local RU/EN frequency model, common n-gram scoring, word-shape signals, exact known-word protection and volatile two-word context.\n"
    extra = marker + "- A generated frequency layer derived from pinned OpenSubtitles2018 RU/EN surface-form lists protects 56,036 common 4+ letter source forms and deterministically promotes 26,990 frequent target forms. Generated evidence never downloads at runtime.\n- Generated three-letter forms and generated prefixes shorter than four letters are deliberately excluded so ambiguous short tokens keep the existing context-sensitive behavior.\n- Detector precedence is explicit source > curated source > curated target > generated source/target; generated-vs-generated cross-layout collisions stay fail-open.\n"
    if marker not in text:
        raise SystemExit("README detector bullet marker missing")
    text = text.replace(marker, extra, 1)
    text = text.replace("G-switcher 1.0.9 version metadata", "G-switcher 1.0.10 version metadata", 1)
    readme.write_text(text, encoding="utf-8")

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text(encoding="utf-8")
    header = "# Changelog\n\n"
    if not text.startswith(header):
        raise SystemExit("CHANGELOG header missing")
    entry = """## 1.0.10 - 2026-09-04

- Adds a reproducible generated RU/EN surface-form frequency layer from OpenSubtitles2018 data pinned to a specific source commit, with CC BY 3.0 attribution recorded in `THIRD_PARTY_DATA.md`.
- Embeds 28,235 Russian and 27,801 English 4+ letter source-protection forms (56,036 total) and deterministically promotes 26,990 frequent wrong-layout target forms under the existing confidence thresholds.
- Deliberately excludes generated three-letter forms and generated prefixes shorter than four letters after safety regressions showed that short forms such as `vbh`/`мир` require context.
- Defines precedence as explicit source > curated source > curated target > generated source/target, preserving established corrections such as `cath` → `сфер` while explicit English `here` remains fail-open.
- Keeps nine generated cross-layout collisions fail-open and adds exhaustive regression coverage across every embedded generated source form and every promoted target form.
- Extends real Win32 hook-to-EDIT E2E with representative everyday forms including `знаешь`, `домой`, `машина`, `wanted` and `looking`, while retaining the exact `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет ` gate.
- Runtime remains fully local-only: the generator is development-time tooling and no frequency data is downloaded during normal application operation.

## 1.0.9 - 2026-09-04

- Restores basic everyday Russian vocabulary missing from the curated detector model, including `мама`, `мыла`, `раму` and closely related forms, without lowering global confidence thresholds.
- Adds permanent unit and real Win32 E2E gates for `Vfvf` → `Мама`, `vskf` → `мыла`, `hfve` → `раму`, and the exact sequence `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет `.
- Preserves all 1.0.8 UI/autostart fixes and previous mixed-language/collision safety behavior.

"""
    if "## 1.0.10 - 2026-09-04" not in text:
        text = header + entry + text[len(header):]
    changelog.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
