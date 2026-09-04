# G-switcher 1.0.10 frequency lexicon audit

Generated from the OpenSubtitles2018 surface-form frequency lists mirrored by `kapzam123/subtitle-frequency`, pinned to commit `b5ff7d0d26df0863b9b6c5e8f946961ea9fef1f3`. The original frequency data is CC BY 3.0.

The runtime tables intentionally use **surface forms**, because G-switcher must recognize what a person actually types (`мама`, `маме`, `маму`, `wanted`, `looking`, etc.), not only dictionary lemmas. OpenCorpora's current downloadable unigram lists and the Lyashevskaya–Sharoff/NKRYa frequency dictionary were reviewed as independent Russian-frequency references during design; their data is not copied into the generated runtime table.

## Selection policy

- Generated runtime frequency evidence starts at 4 letters. Three-letter corpus forms and generated prefixes shorter than 4 letters are deliberately held out so the existing context-sensitive short-word policy remains unchanged.
- Source protection: every normalized alphabetic 4+ letter form whose raw source rank is <= 30,000; this layer is deliberately broad.
- Automatic target promotion: rank <= 10,000 for 4-letter forms and <= 15,000 for 5+ letter forms.
- Precedence is explicit source > curated source > curated target > generated source/target. Generated-vs-generated collisions stay fail-open.
- Russian `ё` is normalized to `е`, matching the detector's existing normalization.
- Tokens shorter than 3 letters and non-alphabetic rows are excluded because automatic correction already ignores them or treats them as special input.
- If a target's physical wrong-layout spelling is itself a frequent source form in the opposite language, source protection wins and the case stays fail-open.
- Global confidence thresholds are unchanged.

## Pinned corpus statistics

| Metric | Russian | English |
| --- | ---: | ---: |
| Raw CSV rows | 30,000 | 30,000 |
| Clean unique >=3-letter forms | 29,121 | 29,084 |
| Embedded source-protection forms | 28,235 | 27,801 |
| Target-promoted forms before collision/code-safe gates | 13,648 | 13,351 |
| Source-layer token mass within clean pinned list | 76.5207% | 68.3613% |
| Target-promotion token mass within clean pinned list | 70.4469% | 66.2075% |
| Frequent cross-layout collisions kept fail-open | 6 | 3 |

## Everyday probes — Russian

- `мама`: raw rank 190
- `мыла`: raw rank 15,279
- `раму`: not present in pinned top-30k
- `знаешь`: raw rank 79
- `хочешь`: raw rank 107
- `сказала`: raw rank 194
- `домой`: raw rank 222
- `машина`: raw rank 688
- `работу`: raw rank 299
- `детей`: raw rank 410

## Everyday probes — English

- `mother`: raw rank 239
- `wanted`: raw rank 221
- `looking`: raw rank 245
- `friends`: raw rank 340
- `home`: raw rank 169
- `children`: raw rank 472
- `worked`: raw rank 665
- `going`: raw rank 80
- `please`: raw rank 122
- `sorry`: raw rank 123

## Highest-frequency cross-layout collisions

- RU `руки` ↔ EN source `herb` (RU rank 348, EN rank 7121)
- RU `руку` ↔ EN source `here` (RU rank 666, EN rank 38)
- RU `душа` ↔ EN source `leif` (RU rank 2187, EN rank 28434)
- RU `луны` ↔ EN source `keys` (RU rank 6442, EN rank 1267)
- RU `внук` ↔ EN source `dyer` (RU rank 9484, EN rank 28259)
- RU `штуке` ↔ EN source `inert` (RU rank 13920, EN rank 28471)
- EN `here` ↔ RU source `руку` (EN rank 38, RU rank 666)
- EN `keys` ↔ RU source `луны` (EN rank 1267, RU rank 6442)
- EN `herb` ↔ RU source `руки` (EN rank 7121, RU rank 348)

The exhaustive Rust regression checks every embedded source form for preservation and every promoted target form for deterministic restoration unless it is an explicit frequent-source collision or a protected code-like token. Real Win32 E2E additionally exercises representative RU and EN wordforms through the low-level keyboard hook and `SendInput` path.
