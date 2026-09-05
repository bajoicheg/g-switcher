# G-switcher 2.0.0 security model

G-switcher is designed as a small local desktop utility with a deliberately narrow trust boundary.

- No network activity is required for runtime operation.
- Current candidate text is never persisted by the normal runtime.
- The runtime may retain exactly one immediately previous completed token for previous-word manual conversion and at most two completed context words for Detector v3. Both stores exist only in process memory and are never written to disk or transmitted.
- Detector v3 uses only baked-in local RU/EN frequency and n-gram data plus local volatile context. It has no cloud model, remote dictionary or telemetry dependency.
- The pinned 1.0.10 OpenSubtitles2018-derived frequency layer and earlier corpus additions are compiled local lexical/source-protection entries only. Source corpora and generation inputs are not downloaded during runtime.
- Contextual words are cleared when focus/process context changes, on Pause, on unrelated Ctrl/Alt command context, on secure-input entry, and on Undo. Context cannot override exact source system/user-dictionary protection.
- Selected text is read only after the explicit selected-text hotkey is invoked and only from the currently focused supported native Win32 text control. The selected content is held transiently only long enough to perform replacement/Undo state.
- The clipboard is not used for selected-text conversion.
- Native password controls and recognized Windows credential/secure targets are excluded from automatic correction, manual conversion, selected-text conversion and text-restoring Undo operations. Entering a detected secure target clears transient G-switcher text state and original keystrokes pass through unchanged.
- Browser DOM password fields and arbitrary custom-rendered controls may not expose secure state through the native focused HWND. G-switcher does not inspect DOM content or arbitrary accessibility trees. Per-application `Disabled` mode is the explicit safety boundary where secure-state detection cannot be verified.
- Secure-input protection overrides application mode and sensitivity settings.
- Pause state is process-local, clears transient correction/selection state, and is never persisted.
- Configuration is stored per user.
- Persisted configuration is limited to explicit choices: automatic-correction state, sensitivity profile, sound state/volume, Disabled/Manual-only executable basenames, explicit user-dictionary words, hotkey definitions and autostart state.
- The user dictionary is never learned automatically from typing.
- Per-application modes are matched locally against the focused process executable basename.
- Settings enumerates local running-process basenames only to let the user select an application mode; the process list is neither persisted as history nor transmitted.
- `Manual only` disables automatic replacement while preserving explicit actions outside secure input; `Disabled` performs no text conversion.
- Tray status is derived locally from current process mode/layout and the latest correction/undo. It is not persisted or transmitted.
- Normal operation does not request elevation.
- Input injection failures are fail-open for the user's original keystroke where Windows permits safe recovery. Partial `SendInput` batches are continued from the exact unsent INPUT with bounded retries so already-delivered Backspace events are not silently abandoned.
- Queued manual correction restores only modifier keys that remain physically active when the queued operation executes, preventing stale Ctrl/Shift/Alt state from being synthetically reintroduced after hotkey release.
- Automatic and manual token conversion use the same focused-control, layout-switch and integrity boundaries.
- Hotkeys are matched locally and no global online service is involved.
- Correction audio is a fixed short PCM waveform generated in memory. Its amplitude is derived only from the explicit volume setting; typed or selected text never influences audio bytes. Playback does not write an audio file or change the system master volume.
- The production binary is built on a Windows CI runner from the reviewed Rust source tree.
- The release gate includes a real Win32 hook-to-EDIT test covering automatic correction/Undo, article-derived detector cases, application modes, selected-text conversion/Undo and password EDIT protection.
- Release artifacts include SHA-256 hashes and are intended to be Authenticode-signed in a separate protected release step when a trusted signing environment is available.
- CI receives read-only repository contents unless a specific release job requires release publication rights.
- The `v2.0.0` publication workflow consumes only the checked artifact from a successful `main` push Windows CI run, re-verifies EXE/ZIP SHA-256 values, and confirms that the packaged EXE is byte-identical before creating the GitHub Release.
