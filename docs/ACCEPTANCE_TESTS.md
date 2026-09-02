# G-switcher acceptance tests

The Windows release gate must test the full path from keyboard hook through focused-control layout selection and input injection into a real Win32 edit control.

## Core correction

- `ghbdtn ` → `привет `
- `руддщ ` → `hello `
- `руддщ ghbdtn ` → `hello привет `
- `cdj,jle ` → `свободу `
- the same cases using Enter instead of Space
- `ghbdtn` + Tab → `привет` + Tab

## Punctuation

- `ghbdtn/` → `привет/`
- `ghbdtn,` → `привет,`
- `ghbdtn.` → `привет.`
- `rjhj,rf ` → `коробка `
- `cdj,jle ` → `свободу `; the internal physical comma key is the Russian letter `б`, not a boundary
- `руддщ.` → `hello.`
- punctuation is never lost when correction fails

## Editing

- type `ghbdtn/`, Backspace, Space → `привет `
- multiple Backspace operations reconstruct the remaining candidate correctly
- deleting the entire candidate leaves an empty candidate
- caret movement invalidates stale correction state

## False-positive protection

These examples must remain unchanged when typed correctly:

- `беру`
- `берут`
- `ещё`
- `еще`
- `ёлка`
- `всё`
- `моё`
- `объект`
- `подъезд`
- `hello`
- `the`
- `then`

## Case

- `Ghbdtn ` → `Привет `
- `GHBDTN ` → `ПРИВЕТ `
- `Руддщ ` → `Hello `
- `РУДДЩ ` → `HELLO `

## Code-safe

The following classes are not automatically rewritten unless explicitly configured by the user:

- `HOST-SRV-01`
- `10.20.30.40`
- `10.20.0.0/16`
- `C:\Windows\System32`
- `/usr/local/bin`
- `user@example.test`
- `https://example.test/path`
- `550e8400-e29b-41d4-a716-446655440000`
- `sha256:abcdef0123456789`
- `SomeVariable42`
- `some_variable`
- `--background`

## Undo

- after `ghbdtn ` becomes `привет `, immediate Ctrl+Backspace restores `ghbdtn ` and the original input locale
- the first-run window explicitly tells the user that immediate `Ctrl+Backspace` undoes the last automatic replacement and restores the previous layout
- Undo is rejected after focus moves to another control
- Undo is rejected after unrelated text is typed

## First-run UX

- the G-on-shield artwork is prominent and substantially larger than the tray icon
- the whole client area, including text/icon areas, uses one consistent neutral gray system background
- the dialog uses Windows-native Segoe UI typography with a clear visual hierarchy
- the dialog includes short `ghbdtn → привет` and `руддщ → hello` examples
- autostart is checked by default
- the dialog stays centered on the primary display and requires only one `OK` action

## Layout matrix

- Russian + US English
- Russian + UK English
- Russian + English plus a third installed layout
- manual user shortcut set to Win+Space, Ctrl+Shift, Alt+Shift or another supported Windows configuration: automatic behavior remains identical

## Privilege boundary

- normal target at the same integrity level: correction works
- elevated target from standard-user G-switcher: original text and delimiter are preserved without partial correction

## Process behavior

- second instance does not install a second keyboard hook
- tray exit removes the hook
- first-run state is per-user
- per-user autostart does not require local administrator rights
