# G-switcher

G-switcher is a Windows desktop utility that automatically corrects text typed in the wrong Russian/English keyboard layout. The application is local-only: it does not require network access, telemetry, cloud services, or an online account.

Version 2.0.0 is built strictly from the reviewed 1.0.10 code line. It keeps the same conservative detector and pinned OpenSubtitles2018 frequency layer, then adds an optional in-memory correction sound, a compact 768p-safe Settings layout, conflicting-hotkey validation, work-area-aware dialog placement, clearer startup errors, and a verified public-release package.

## 2.0.0 behavior

- Russian ↔ English automatic layout correction.
- Detector v3 combines conservative layout heuristics with a baked-in local RU/EN frequency model, common n-gram scoring, word-shape signals, exact known-word protection and volatile two-word context.
- A generated frequency layer derived from pinned OpenSubtitles2018 RU/EN surface-form lists protects 56,036 common 4+ letter source forms and deterministically promotes 26,990 frequent target forms. Generated evidence never downloads at runtime.
- Generated three-letter forms and generated prefixes shorter than four letters are deliberately excluded so ambiguous short tokens keep the existing context-sensitive behavior.
- Detector precedence is explicit source > curated source > curated target > generated source/target; generated-vs-generated cross-layout collisions stay fail-open.
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
- Native password controls and recognized Windows credential/secure targets are excluded from G-switcher processing. For browser/custom controls that do not expose native secure state, use the per-application `Disabled` mode when protection cannot be verified.
- Configurable current-word, previous-word, Undo, Pause and selected-text hotkeys.
- Per-application modes by executable basename: `Auto`, `Manual only`, and `Disabled`.
- Native Settings process picker enumerates running processes plus already configured applications.
- The Pause label is shortened, footer controls are moved down, and long help text is split deliberately so it cannot overlap adjacent controls.
- The first-run description uses explicit bounded lines in one control, preventing text overlap; its autostart checkbox reflects the actual Windows Run state.
- Settings and first-run headings use the package version dynamically, and the Settings title bar uses the G-switcher application icon.
- A short local correction sound plays only after a successful automatic, manual, previous-word or selected-text conversion. It never plays for a refused/failed conversion, secure native input, Pause or Undo.
- Sound is enabled by default at 20% amplitude. The first-run window and Settings both expose an on/off checkbox and 0–100% volume control in 5% steps.
- The sound is generated as a short PCM wave in process memory; no audio asset, network request or recorded text is used.
- An unchecked first-run autostart choice now explicitly removes any existing G-switcher Run entry instead of leaving stale autostart enabled.
- Read-only application-mode lists remain clean; the editable user dictionary keeps normal scrolling.
- Settings uses a 900×680 client area and centers inside the Windows work area, keeping the complete form usable on a typical 1366×768 desktop with a taskbar.
- Settings rejects duplicate hotkeys across actions instead of saving an ambiguous mapping.
- Closing first-run setup cancels startup without marking onboarding complete, so the choices are requested again next launch.
- Startup failures are shown in a native Windows error dialog even though the release uses the GUI subsystem.
- Live tray tooltip shows the active mode, current process/layout and the latest correction/undo when applicable.
- Partial `SendInput` delivery resumes from the first unsent INPUT instead of abandoning a correction after already-delivered Backspace events; zero initial progress still fails open without modifying text.
- Standard-user operation with fail-open input behavior.
- Single-instance protection, per-user settings and autostart.
- No network access in normal runtime operation.

## Privacy

Normal typing is evaluated only in volatile memory. G-switcher retains the current candidate token, at most one previous token for manual previous-word conversion, and at most two completed context words in RAM. These values are cleared on relevant context changes and are never persisted or transmitted.

Selected text is read only when the user invokes the selected-text hotkey, only from the currently focused supported Win32 text control, and only for the duration required to replace that selection. The clipboard is not used. Native password fields and recognized Windows credential/secure targets are excluded from G-switcher processing.

Persisted data is limited to explicit user configuration: automatic-correction state, sensitivity profile, sound state/volume, application mode lists, explicitly entered dictionary words, hotkey definitions and autostart state. Pause state, typed candidate text, previous-token text, contextual words and selected text are not persisted.

## Release assurance

The Windows CI gate uses the committed dependency lockfile for resolution, then runs formatting, unit/integration tests, PCM-wave and settings regressions, a real Win32 low-level-hook-to-EDIT end-to-end test, Clippy with warnings denied, and an optimized release build. The E2E covers automatic correction and Undo, Pause, Manual-only/Disabled modes, selected-text conversion and Undo, password EDIT protection, OEM-key regressions, article-derived correction cases, the OEM-only `жэхэ` case, ten-corpus corrections such as `математика`/`европа`/`физика`, `keys`/`her`/`dyer`/`ytd`/`cnf` source-collision protection, and the exact basic phrase `Vfvf vskf hfve ghbdtn ` → `Мама мыла раму привет `. The built EXE is then checked for Windows GUI subsystem, G-switcher 2.0.0 version metadata and forbidden residue. CI produces checksums for both the standalone EXE and a ZIP containing the EXE, documentation, changelog and third-party data attribution.

The CI artifact is not Authenticode-signed. A trusted signing certificate or trusted signing service is still required for reputation-based Windows distribution without possible SmartScreen warnings.

See `docs/FUNCTIONAL_SPEC.md`, `docs/ACCEPTANCE_TESTS.md` and `docs/SECURITY_MODEL.md`.
