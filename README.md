# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 1.0.9 restores basic Russian everyday-word coverage after the missing-lexicon regression found with `Vfvf vskf hfve ghbdtn` → `Мама мыла раму привет`. The fix adds only conservative known-word entries; global detector confidence thresholds are unchanged. Version 1.0.8 first-run/autostart fixes remain intact, and Detector v3 retains the 1.0.7 full-novel baseline: 340,059/342,237 eligible wrong-layout Russian occurrences restored (99.3636%) with zero false automatic corrections across 342,237 correct Russian and 11,594 correct Latin-layout occurrences in the mixed Russian/French/German `War and Peace` corpus.

## 1.0.9 behavior

- Russian ↔ English automatic layout correction.
- Detector v3 combines conservative layout heuristics with a baked-in local RU/EN frequency model, common n-gram scoring, word-shape signals, exact known-word protection and volatile two-word context.
- Basic everyday Russian forms now include `мама`, `маму`, `папа`, `папу`, `мыла`, `мыло`, `моет`, `рама`, `раму`, `раме`, `рамой`, `дома`, `домой` and `дочь`; their wrong-layout forms are deterministic known-target corrections without lowering global thresholds.
- The exact regression `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет ` is a permanent real Win32 E2E release gate, with separate E2E cases for `Vfvf` → `Мама`, `vskf` → `мыла`, and `hfve` → `раму`.
- Space/Enter/Tab boundaries evaluate complete opposite-layout words without the OEM prefix hold; punctuation entry keeps the prefix hold required by embedded physical comma/period keys.
- Full-novel source protections preserve observed Russian forms and common French/German/Latin-layout words; deliberate valid-source collisions such as `here`/`her` remain fail-open.
- The built-in common-word lexicons include everyday, technical, colloquial and common obscene vocabulary in both languages.
- Recognized frequent source-language words such as `truth`, `fuck`, `пизда`, `бля`, `блять`, `хуй` and `ебать` are protected from automatic rewriting; wrong-layout forms of recognized target words receive deterministic target recognition.
- Ten-article follow-up corpus coverage adds 55 safe Russian target forms while explicitly protecting valid/ambiguous English source tokens including `keys`, `dyer`, `ytd`, `cnf`, `lev` and `ren`; global confidence thresholds are unchanged.
- OEM-key candidate tracking supports words whose opposite-layout form begins with punctuation-looking keys, including `,kz` → `бля`, `rjhj,rf` → `коробка`, `rjhj,jxrf.` → `коробочка.` and `cdj,jle` → `свободу`.
- Three sensitivity profiles control the heuristic confidence threshold: `Conservative`, `Normal` and `Aggressive`. `Normal` is the default.
- Exact user-dictionary source matches protect valid text; explicit user-dictionary target matches receive maximum confidence.
- Context is limited to at most two immediately previous completed words, remains RAM-only, and is cleared on relevant focus/process/control changes and Undo.
- Native selected-text conversion for supported Win32 Edit/RichEdit controls; default hotkey `Ctrl+Shift+F9`.
- Selected-text conversion uses the physical Russian/English keyboard mapping directly and does not use or modify the clipboard.
- Password, PIN, OTP and credential/secure input controls are excluded from G-switcher processing.
- Configurable current-word, previous-word, Undo, Pause and selected-text hotkeys.
- Per-application modes by executable basename: `Auto`, `Manual only`, and `Disabled`.
- Native Settings process picker enumerates running processes plus already configured applications.
- Settings reserve a 900×855 client area and provide dedicated two-line help regions for sensitivity and Pause instead of forcing long Russian text into one-line rectangles.
- The Pause label is shortened, footer controls are moved down, and long help text is split deliberately so it cannot overlap adjacent controls.
- The first-run description uses four explicit bounded lines in one control, preventing text overlap; its autostart checkbox reflects the actual Windows Run state.
- Settings and first-run headings use the package version dynamically, and the Settings title bar uses the G-switcher application icon.
- An unchecked first-run autostart choice now explicitly removes any existing G-switcher Run entry instead of leaving stale autostart enabled.
- Read-only application-mode lists remain clean; the editable user dictionary keeps normal scrolling.
- Live tray tooltip shows the active mode, current process/layout and the latest correction/undo when applicable.
- Partial `SendInput` delivery resumes from the first unsent INPUT instead of abandoning a correction after already-delivered Backspace events; zero initial progress still fails open without modifying text.
- Standard-user operation with fail-open input behavior.
- Single-instance protection, per-user settings and autostart.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory. G-switcher retains the current candidate token, at most one previous token for manual previous-word conversion, and at most two completed context words in RAM. These values are cleared on relevant context changes and are never persisted or transmitted.

Selected text is read only when the user invokes the selected-text hotkey, only from the currently focused supported Win32 text control, and only for the duration required to replace that selection. The clipboard is not used. Secure/password/PIN/OTP/credential fields are excluded from G-switcher processing.

Persisted data is limited to explicit user configuration: automatic-correction state, sensitivity profile, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state, typed candidate text, previous-token text, contextual words and selected text are not persisted.

## Release assurance

The Windows CI gate runs formatting, unit/integration tests, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The E2E covers automatic correction and Undo, Pause, Manual-only/Disabled modes, selected-text conversion and Undo, password EDIT protection, OEM-key regressions, article-derived correction cases, the OEM-only `жэхэ` case, ten-corpus corrections such as `математика`/`европа`/`физика`, `keys`/`her`/`dyer`/`ytd`/`cnf` source-collision protection, and the exact basic phrase `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет `. The built EXE is then checked for Windows GUI subsystem, G-switcher 1.0.9 version metadata, forbidden legacy-brand residue, and a SHA-256 file is generated before the artifact is uploaded.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.