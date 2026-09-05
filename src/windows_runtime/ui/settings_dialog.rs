use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicIsize, Ordering};
use std::sync::OnceLock;

use anyhow::{anyhow, Result};
use windows_sys::Win32::Foundation::{
    CloseHandle, HWND, INVALID_HANDLE_VALUE, LPARAM, LRESULT, RECT, WPARAM,
};
use windows_sys::Win32::Graphics::Gdi::{
    CreateFontW, DeleteObject, GetStockObject, GetSysColorBrush, SetBkMode, DEFAULT_GUI_FONT,
};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::Sleep;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::EnableWindow;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AdjustWindowRectEx, CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW,
    GetDlgItem, GetSystemMetrics, GetWindowTextLengthW, GetWindowTextW, IsDialogMessageW, IsWindow,
    LoadCursorW, MessageBoxW, PeekMessageW, RegisterClassW, SendMessageW, SetForegroundWindow,
    SetWindowTextW, ShowWindow, SystemParametersInfoW, TranslateMessage, BM_GETCHECK, BM_SETCHECK,
    BS_AUTOCHECKBOX, BS_DEFPUSHBUTTON, BS_GROUPBOX, CBS_DROPDOWNLIST, CB_ADDSTRING, CB_GETCURSEL,
    CB_GETLBTEXT, CB_GETLBTEXTLEN, CB_SETCURSEL, ES_AUTOHSCROLL, ES_AUTOVSCROLL, ES_MULTILINE,
    ES_READONLY, IDC_ARROW, MB_ICONWARNING, MB_OK, MSG, PM_REMOVE, SM_CXSCREEN, SM_CYSCREEN,
    SPI_GETWORKAREA, SW_SHOW, WM_CLOSE, WM_COMMAND, WM_CTLCOLORSTATIC, WM_DESTROY, WM_SETFONT,
    WNDCLASSW, WS_BORDER, WS_CAPTION, WS_CHILD, WS_OVERLAPPED, WS_SYSMENU, WS_TABSTOP, WS_VISIBLE,
    WS_VSCROLL,
};

use crate::windows_runtime::{current_process_name, settings};

const CLASS_NAME: &str = concat!("GSwitcher.Settings.", env!("CARGO_PKG_VERSION"));
const ID_AUTO_CORRECT: i32 = 3101;
const ID_AUTOSTART: i32 = 3102;
const ID_DISABLED_APPS: i32 = 3103;
const ID_MANUAL_ONLY_APPS: i32 = 3104;
const ID_USER_WORDS: i32 = 3105;
const ID_HOTKEY_CURRENT: i32 = 3106;
const ID_HOTKEY_PREVIOUS: i32 = 3107;
const ID_HOTKEY_UNDO: i32 = 3108;
const ID_HOTKEY_PAUSE: i32 = 3109;
const ID_SAVE: i32 = 1;
const ID_CANCEL: i32 = 2;
const ID_PROCESS_PICKER: i32 = 3112;
const ID_MODE_AUTO: i32 = 3113;
const ID_MODE_MANUAL: i32 = 3114;
const ID_MODE_DISABLED: i32 = 3115;
const ID_SENSITIVITY: i32 = 3116;
const ID_HOTKEY_SELECTED: i32 = 3117;
const ID_SOUND_ENABLED: i32 = 3118;
const ID_SOUND_VOLUME: i32 = 3119;
const BST_CHECKED_VALUE: u32 = 1;
const COLOR_3DFACE_INDEX: i32 = 15;
const TRANSPARENT_BK_MODE: i32 = 1;

static CLASS_REGISTERED: OnceLock<()> = OnceLock::new();
static SETTINGS_WINDOW: AtomicIsize = AtomicIsize::new(0);
static TITLE_FONT: AtomicIsize = AtomicIsize::new(0);
static SECTION_FONT: AtomicIsize = AtomicIsize::new(0);
static BODY_FONT: AtomicIsize = AtomicIsize::new(0);
static HINT_FONT: AtomicIsize = AtomicIsize::new(0);

#[derive(Clone, Copy)]
struct UiRect {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
}

impl UiRect {
    const fn new(x: i32, y: i32, width: i32, height: i32) -> Self {
        Self {
            x,
            y,
            width,
            height,
        }
    }
}

pub fn show() -> Result<()> {
    ensure_class()?;
    unsafe {
        let existing = SETTINGS_WINDOW.load(Ordering::SeqCst) as HWND;
        if !existing.is_null() && IsWindow(existing) != 0 {
            SetForegroundWindow(existing);
            return Ok(());
        }

        let module = GetModuleHandleW(null());
        let client_width = 900;
        let client_height = 680;
        let style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU;
        let mut rect = RECT {
            left: 0,
            top: 0,
            right: client_width,
            bottom: client_height,
        };
        if AdjustWindowRectEx(&mut rect, style, 0, 0) == 0 {
            return Err(anyhow!("AdjustWindowRectEx for settings failed"));
        }

        let width = rect.right - rect.left;
        let height = rect.bottom - rect.top;
        let (x, y) = centered_in_work_area(width, height);
        let class = wide(CLASS_NAME);
        let title = wide("G-switcher — настройки");
        let hwnd = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            style,
            x,
            y,
            width,
            height,
            null_mut(),
            null_mut(),
            module,
            null(),
        );
        if hwnd.is_null() {
            return Err(anyhow!("CreateWindowExW for settings failed"));
        }
        SETTINGS_WINDOW.store(hwnd as isize, Ordering::SeqCst);
        ShowWindow(hwnd, SW_SHOW);

        let mut message: MSG = zeroed();
        while IsWindow(hwnd) != 0 {
            while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
                if IsDialogMessageW(hwnd, &message) == 0 {
                    TranslateMessage(&message);
                    DispatchMessageW(&message);
                }
            }
            Sleep(10);
        }
    }
    Ok(())
}

fn ensure_class() -> Result<()> {
    if CLASS_REGISTERED.get().is_some() {
        return Ok(());
    }

    unsafe {
        let module = GetModuleHandleW(null());
        let class = wide(CLASS_NAME);
        let window_class = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(settings_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: module,
            hIcon: super::load_app_icon(),
            hCursor: LoadCursorW(null_mut(), IDC_ARROW),
            hbrBackground: GetSysColorBrush(COLOR_3DFACE_INDEX),
            lpszMenuName: null(),
            lpszClassName: class.as_ptr(),
        };
        if RegisterClassW(&window_class) == 0 {
            return Err(anyhow!("RegisterClassW for settings failed"));
        }
    }

    let _ = CLASS_REGISTERED.set(());
    Ok(())
}

unsafe extern "system" fn settings_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match message {
        windows_sys::Win32::UI::WindowsAndMessaging::WM_CREATE => {
            create_controls(hwnd);
            0
        }
        WM_COMMAND => {
            match (wparam & 0xffff) as i32 {
                ID_SAVE => save_and_close(hwnd),
                ID_CANCEL => {
                    DestroyWindow(hwnd);
                }
                ID_MODE_AUTO => apply_selected_process_mode(hwnd, settings::AppMode::Auto),
                ID_MODE_MANUAL => apply_selected_process_mode(hwnd, settings::AppMode::ManualOnly),
                ID_MODE_DISABLED => apply_selected_process_mode(hwnd, settings::AppMode::Disabled),
                ID_SOUND_ENABLED => update_volume_enabled(hwnd),
                _ => {}
            }
            0
        }
        WM_CTLCOLORSTATIC => {
            SetBkMode(wparam as *mut core::ffi::c_void, TRANSPARENT_BK_MODE);
            GetSysColorBrush(COLOR_3DFACE_INDEX) as LRESULT
        }
        WM_CLOSE => {
            DestroyWindow(hwnd);
            0
        }
        WM_DESTROY => {
            SETTINGS_WINDOW.store(0, Ordering::SeqCst);
            cleanup_fonts();
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

unsafe fn save_and_close(hwnd: HWND) {
    let auto_correct = is_checked(hwnd, ID_AUTO_CORRECT);
    let autostart = is_checked(hwnd, ID_AUTOSTART);
    let sound_enabled = is_checked(hwnd, ID_SOUND_ENABLED);
    let sound_volume = selected_volume(GetDlgItem(hwnd, ID_SOUND_VOLUME));
    let sensitivity = selected_combo_text(GetDlgItem(hwnd, ID_SENSITIVITY))
        .unwrap_or_else(|| "Нормальный".to_owned());
    let disabled_apps = control_text(GetDlgItem(hwnd, ID_DISABLED_APPS));
    let manual_only_apps = control_text(GetDlgItem(hwnd, ID_MANUAL_ONLY_APPS));
    let user_words = control_text(GetDlgItem(hwnd, ID_USER_WORDS));
    let selected_hotkey = control_text(GetDlgItem(hwnd, ID_HOTKEY_SELECTED));
    let current_hotkey = control_text(GetDlgItem(hwnd, ID_HOTKEY_CURRENT));
    let previous_hotkey = control_text(GetDlgItem(hwnd, ID_HOTKEY_PREVIOUS));
    let undo_hotkey = control_text(GetDlgItem(hwnd, ID_HOTKEY_UNDO));
    let pause_hotkey = control_text(GetDlgItem(hwnd, ID_HOTKEY_PAUSE));

    let hotkeys = [
        ("выделенного текста", selected_hotkey.as_str()),
        ("текущего слова", current_hotkey.as_str()),
        ("предыдущего слова", previous_hotkey.as_str()),
        ("отмены", undo_hotkey.as_str()),
        ("паузы", pause_hotkey.as_str()),
    ];
    let mut parsed_hotkeys = Vec::with_capacity(hotkeys.len());
    for (name, value) in hotkeys {
        let Some(hotkey) = settings::parse_hotkey(value) else {
            show_warning(
                hwnd,
                &format!(
                    "Некорректная горячая клавиша для {name}: {value}\r\n\r\nИспользуйте Ctrl/Shift/Alt + F1–F12, букву, цифру, Space или Backspace."
                ),
            );
            return;
        };
        parsed_hotkeys.push(hotkey);
    }
    if let Some((left, right)) = settings::first_duplicate_hotkey(&parsed_hotkeys) {
        show_warning(
            hwnd,
            &format!(
                "Одинаковая горячая клавиша назначена для «{}» и «{}».\r\n\r\nНазначьте разные сочетания.",
                hotkeys[left].0, hotkeys[right].0
            ),
        );
        return;
    }

    let runtime = settings::settings_from_text(
        auto_correct,
        &sensitivity,
        sound_enabled,
        sound_volume,
        &disabled_apps,
        &manual_only_apps,
        &user_words,
        &selected_hotkey,
        &current_hotkey,
        &previous_hotkey,
        &undo_hotkey,
        &pause_hotkey,
    );
    if settings::save_runtime_settings(runtime).is_ok()
        && settings::set_autostart(autostart).is_ok()
    {
        DestroyWindow(hwnd);
    } else {
        show_warning(hwnd, "Не удалось сохранить настройки G-switcher.");
    }
}

unsafe fn apply_selected_process_mode(hwnd: HWND, mode: settings::AppMode) {
    let picker = GetDlgItem(hwnd, ID_PROCESS_PICKER);
    let Some(process_name) = selected_combo_text(picker) else {
        show_warning(hwnd, "Выберите приложение из списка запущенных процессов.");
        return;
    };

    let disabled_control = GetDlgItem(hwnd, ID_DISABLED_APPS);
    let manual_control = GetDlgItem(hwnd, ID_MANUAL_ONLY_APPS);
    let mut disabled = process_entries(&control_text(disabled_control));
    let mut manual = process_entries(&control_text(manual_control));

    disabled.retain(|entry| !entry.eq_ignore_ascii_case(&process_name));
    manual.retain(|entry| !entry.eq_ignore_ascii_case(&process_name));

    match mode {
        settings::AppMode::Auto => {}
        settings::AppMode::ManualOnly => manual.push(process_name),
        settings::AppMode::Disabled => disabled.push(process_name),
    }

    normalize_process_entries(&mut disabled);
    normalize_process_entries(&mut manual);
    set_control_text(disabled_control, &disabled.join("\r\n"));
    set_control_text(manual_control, &manual.join("\r\n"));
}

unsafe fn show_warning(hwnd: HWND, text: &str) {
    let text = wide(text);
    let title = wide("G-switcher");
    MessageBoxW(hwnd, text.as_ptr(), title.as_ptr(), MB_OK | MB_ICONWARNING);
}

unsafe fn create_controls(hwnd: HWND) {
    let module = GetModuleHandleW(null());
    let static_class = wide("STATIC");
    let button_class = wide("BUTTON");
    let edit_class = wide("EDIT");
    let combo_class = wide("COMBOBOX");
    let runtime = settings::runtime_settings();

    let default_font = GetStockObject(DEFAULT_GUI_FONT);
    let title_font = create_ui_font(-25, 600);
    let section_font = create_ui_font(-16, 600);
    let body_font = create_ui_font(-16, 400);
    let hint_font = create_ui_font(-13, 400);
    store_font(&TITLE_FONT, title_font);
    store_font(&SECTION_FONT, section_font);
    store_font(&BODY_FONT, body_font);
    store_font(&HINT_FONT, hint_font);
    let title_font = choose_font(title_font, default_font);
    let section_font = choose_font(section_font, default_font);
    let body_font = choose_font(body_font, default_font);
    let hint_font = choose_font(hint_font, body_font);

    let title = create_static(
        hwnd,
        module,
        &static_class,
        concat!("Настройки G-switcher ", env!("CARGO_PKG_VERSION")),
        UiRect::new(28, 14, 840, 32),
    );
    set_font(title, title_font);

    let privacy = create_static(
        hwnd,
        module,
        &static_class,
        "Работает локально. Контекст — до 2 слов только в RAM. Нативные защищённые поля не обрабатываются.",
        UiRect::new(28, 48, 840, 20),
    );
    set_font(privacy, hint_font);

    let general_group = create_group_box(
        hwnd,
        module,
        &button_class,
        "Основное",
        UiRect::new(24, 70, 852, 116),
    );
    set_font(general_group, section_font);

    let auto_correct = create_checkbox(
        hwnd,
        module,
        &button_class,
        "Автоматически исправлять неверную раскладку",
        ID_AUTO_CORRECT,
        UiRect::new(44, 92, 390, 28),
    );
    SendMessageW(
        auto_correct,
        BM_SETCHECK,
        usize::from(runtime.auto_correct) * BST_CHECKED_VALUE as usize,
        0,
    );
    set_font(auto_correct, body_font);

    let autostart = create_checkbox(
        hwnd,
        module,
        &button_class,
        "Запускать G-switcher при входе в Windows",
        ID_AUTOSTART,
        UiRect::new(466, 92, 380, 28),
    );
    SendMessageW(
        autostart,
        BM_SETCHECK,
        usize::from(settings::autostart_enabled()) * BST_CHECKED_VALUE as usize,
        0,
    );
    set_font(autostart, body_font);

    let sound_enabled = create_checkbox(
        hwnd,
        module,
        &button_class,
        "Звуковой сигнал после исправления",
        ID_SOUND_ENABLED,
        UiRect::new(44, 122, 390, 28),
    );
    SendMessageW(
        sound_enabled,
        BM_SETCHECK,
        usize::from(runtime.sound_enabled) * BST_CHECKED_VALUE as usize,
        0,
    );
    set_font(sound_enabled, body_font);

    let volume_label = create_static(
        hwnd,
        module,
        &static_class,
        "Громкость",
        UiRect::new(466, 124, 98, 24),
    );
    set_font(volume_label, body_font);
    let volume = create_combo_box(
        hwnd,
        module,
        &combo_class,
        ID_SOUND_VOLUME,
        UiRect::new(570, 117, 160, 260),
    );
    populate_volume(volume, runtime.sound_volume);
    set_font(volume, body_font);
    update_volume_enabled(hwnd);

    let sensitivity_label = create_static(
        hwnd,
        module,
        &static_class,
        "Чувствительность",
        UiRect::new(44, 153, 142, 24),
    );
    set_font(sensitivity_label, body_font);
    let sensitivity = create_combo_box(
        hwnd,
        module,
        &combo_class,
        ID_SENSITIVITY,
        UiRect::new(190, 147, 210, 120),
    );
    populate_sensitivity(sensitivity, runtime.sensitivity);
    set_font(sensitivity, body_font);
    let sensitivity_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Консервативный — меньше ложных замен.\r\nАгрессивный — больше автокоррекций.",
        UiRect::new(420, 145, 426, 38),
    );
    set_font(sensitivity_hint, hint_font);

    let apps_group = create_group_box(
        hwnd,
        module,
        &button_class,
        "Режимы приложений",
        UiRect::new(24, 194, 852, 168),
    );
    set_font(apps_group, section_font);

    let picker_label = create_static(
        hwnd,
        module,
        &static_class,
        "Приложение",
        UiRect::new(44, 219, 94, 24),
    );
    set_font(picker_label, body_font);
    let process_picker = create_combo_box(
        hwnd,
        module,
        &combo_class,
        ID_PROCESS_PICKER,
        UiRect::new(140, 213, 360, 220),
    );
    populate_process_picker(process_picker, &runtime);
    set_font(process_picker, body_font);

    let auto_button = create_button(
        hwnd,
        module,
        &button_class,
        "Авто",
        ID_MODE_AUTO,
        UiRect::new(516, 212, 88, 31),
        false,
    );
    set_font(auto_button, body_font);
    let manual_button = create_button(
        hwnd,
        module,
        &button_class,
        "Только вручную",
        ID_MODE_MANUAL,
        UiRect::new(612, 212, 134, 31),
        false,
    );
    set_font(manual_button, body_font);
    let disabled_button = create_button(
        hwnd,
        module,
        &button_class,
        "Отключить",
        ID_MODE_DISABLED,
        UiRect::new(754, 212, 102, 31),
        false,
    );
    set_font(disabled_button, body_font);

    let picker_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Выберите запущенный процесс и назначьте режим. «Авто» удаляет индивидуальное исключение.",
        UiRect::new(44, 247, 812, 20),
    );
    set_font(picker_hint, hint_font);

    let disabled_label = create_static(
        hwnd,
        module,
        &static_class,
        "Отключено — без анализа и горячих клавиш",
        UiRect::new(44, 272, 386, 22),
    );
    set_font(disabled_label, section_font);
    let disabled = create_multiline_edit(
        hwnd,
        module,
        &edit_class,
        ID_DISABLED_APPS,
        UiRect::new(44, 296, 386, 48),
        true,
    );
    set_control_text(disabled, &runtime.disabled_apps_text());
    set_font(disabled, body_font);

    let manual_label = create_static(
        hwnd,
        module,
        &static_class,
        "Только вручную — без автозамены",
        UiRect::new(470, 272, 386, 22),
    );
    set_font(manual_label, section_font);
    let manual_only = create_multiline_edit(
        hwnd,
        module,
        &edit_class,
        ID_MANUAL_ONLY_APPS,
        UiRect::new(470, 296, 386, 48),
        true,
    );
    set_control_text(manual_only, &runtime.manual_only_apps_text());
    set_font(manual_only, body_font);

    let dictionary_group = create_group_box(
        hwnd,
        module,
        &button_class,
        "Пользовательский словарь",
        UiRect::new(24, 370, 852, 94),
    );
    set_font(dictionary_group, section_font);
    let dictionary_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Одно слово на строку. Словарь защищает допустимые слова от ложных исправлений.",
        UiRect::new(44, 393, 812, 20),
    );
    set_font(dictionary_hint, hint_font);
    let dictionary = create_multiline_edit(
        hwnd,
        module,
        &edit_class,
        ID_USER_WORDS,
        UiRect::new(44, 414, 812, 38),
        false,
    );
    set_control_text(dictionary, &runtime.user_words_text());
    set_font(dictionary, body_font);

    let hotkeys_group = create_group_box(
        hwnd,
        module,
        &button_class,
        "Горячие клавиши",
        UiRect::new(24, 472, 852, 142),
    );
    set_font(hotkeys_group, section_font);
    let hotkey_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Выделенный текст обрабатывается в стандартных Edit/RichEdit без буфера обмена.",
        UiRect::new(44, 494, 812, 20),
    );
    set_font(hotkey_hint, hint_font);

    let selected_label = create_static(
        hwnd,
        module,
        &static_class,
        "Выделенный текст",
        UiRect::new(44, 520, 140, 24),
    );
    set_font(selected_label, body_font);
    let selected_hotkey = create_single_edit(
        hwnd,
        module,
        &edit_class,
        ID_HOTKEY_SELECTED,
        UiRect::new(190, 515, 190, 28),
    );
    set_control_text(selected_hotkey, &runtime.selected_text_hotkey.to_text());
    set_font(selected_hotkey, body_font);

    let current_label = create_static(
        hwnd,
        module,
        &static_class,
        "Текущее слово",
        UiRect::new(462, 520, 156, 24),
    );
    set_font(current_label, body_font);
    let current_hotkey = create_single_edit(
        hwnd,
        module,
        &edit_class,
        ID_HOTKEY_CURRENT,
        UiRect::new(626, 515, 230, 28),
    );
    set_control_text(current_hotkey, &runtime.manual_current_hotkey.to_text());
    set_font(current_hotkey, body_font);

    let previous_label = create_static(
        hwnd,
        module,
        &static_class,
        "Предыдущее слово",
        UiRect::new(44, 556, 140, 24),
    );
    set_font(previous_label, body_font);
    let previous_hotkey = create_single_edit(
        hwnd,
        module,
        &edit_class,
        ID_HOTKEY_PREVIOUS,
        UiRect::new(190, 551, 190, 28),
    );
    set_control_text(previous_hotkey, &runtime.previous_word_hotkey.to_text());
    set_font(previous_hotkey, body_font);

    let undo_label = create_static(
        hwnd,
        module,
        &static_class,
        "Отмена замены",
        UiRect::new(462, 556, 156, 24),
    );
    set_font(undo_label, body_font);
    let undo_hotkey = create_single_edit(
        hwnd,
        module,
        &edit_class,
        ID_HOTKEY_UNDO,
        UiRect::new(626, 551, 230, 28),
    );
    set_control_text(undo_hotkey, &runtime.undo_hotkey.to_text());
    set_font(undo_hotkey, body_font);

    let pause_label = create_static(
        hwnd,
        module,
        &static_class,
        "Пауза",
        UiRect::new(44, 592, 140, 22),
    );
    set_font(pause_label, body_font);
    let pause_hotkey = create_single_edit(
        hwnd,
        module,
        &edit_class,
        ID_HOTKEY_PAUSE,
        UiRect::new(190, 587, 190, 25),
    );
    set_control_text(pause_hotkey, &runtime.pause_hotkey.to_text());
    set_font(pause_hotkey, body_font);

    let pause_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Пауза действует до перезапуска.\r\nЗащищённые нативные поля исключены из обработки.",
        UiRect::new(420, 581, 436, 32),
    );
    set_font(pause_hint, hint_font);

    let footer_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Изменения применяются сразу после сохранения.",
        UiRect::new(28, 640, 500, 22),
    );
    set_font(footer_hint, hint_font);

    let save = create_button(
        hwnd,
        module,
        &button_class,
        "Сохранить",
        ID_SAVE,
        UiRect::new(644, 630, 104, 34),
        true,
    );
    set_font(save, body_font);
    let cancel = create_button(
        hwnd,
        module,
        &button_class,
        "Отмена",
        ID_CANCEL,
        UiRect::new(762, 630, 104, 34),
        false,
    );
    set_font(cancel, body_font);
}

unsafe fn populate_sensitivity(combo: HWND, current: settings::SensitivityProfile) {
    let labels = ["Консервативный", "Нормальный", "Агрессивный"];
    for label in labels {
        let label = wide(label);
        SendMessageW(combo, CB_ADDSTRING, 0, label.as_ptr() as LPARAM);
    }
    let index = match current {
        settings::SensitivityProfile::Conservative => 0,
        settings::SensitivityProfile::Normal => 1,
        settings::SensitivityProfile::Aggressive => 2,
    };
    SendMessageW(combo, CB_SETCURSEL, index, 0);
}

unsafe fn populate_volume(combo: HWND, current: u8) {
    for volume in (0..=settings::MAX_SOUND_VOLUME).step_by(5) {
        let label = wide(&format!("{volume} %"));
        SendMessageW(combo, CB_ADDSTRING, 0, label.as_ptr() as LPARAM);
    }
    let index = ((u16::from(current.min(settings::MAX_SOUND_VOLUME)) + 2) / 5) as usize;
    SendMessageW(combo, CB_SETCURSEL, index, 0);
}

unsafe fn selected_volume(combo: HWND) -> u8 {
    let index = SendMessageW(combo, CB_GETCURSEL, 0, 0);
    if index < 0 {
        settings::DEFAULT_SOUND_VOLUME
    } else {
        (index as u8)
            .saturating_mul(5)
            .min(settings::MAX_SOUND_VOLUME)
    }
}

unsafe fn update_volume_enabled(hwnd: HWND) {
    EnableWindow(
        GetDlgItem(hwnd, ID_SOUND_VOLUME),
        i32::from(is_checked(hwnd, ID_SOUND_ENABLED)),
    );
}

unsafe fn centered_in_work_area(width: i32, height: i32) -> (i32, i32) {
    let mut work_area = RECT {
        left: 0,
        top: 0,
        right: GetSystemMetrics(SM_CXSCREEN),
        bottom: GetSystemMetrics(SM_CYSCREEN),
    };
    let _ = SystemParametersInfoW(
        SPI_GETWORKAREA,
        0,
        &mut work_area as *mut RECT as *mut core::ffi::c_void,
        0,
    );
    let available_width = work_area.right - work_area.left;
    let available_height = work_area.bottom - work_area.top;
    let x = work_area.left + (available_width - width).max(0) / 2;
    let y = work_area.top + (available_height - height).max(0) / 2;
    (x, y)
}

unsafe fn populate_process_picker(combo: HWND, runtime: &settings::RuntimeSettings) {
    let mut names = running_process_names();
    names.extend(runtime.disabled_apps.iter().cloned());
    names.extend(runtime.manual_only_apps.iter().cloned());
    normalize_process_entries(&mut names);

    if let Some(current) = current_process_name() {
        if let Some(index) = names
            .iter()
            .position(|name| name.eq_ignore_ascii_case(&current))
        {
            names.swap(0, index);
        } else {
            names.insert(0, current);
        }
    }

    for name in names {
        let name = wide(&name);
        SendMessageW(combo, CB_ADDSTRING, 0, name.as_ptr() as LPARAM);
    }
    if SendMessageW(combo, CB_GETCURSEL, 0, 0) < 0 {
        SendMessageW(combo, CB_SETCURSEL, 0, 0);
    }
}

unsafe fn selected_combo_text(combo: HWND) -> Option<String> {
    let index = SendMessageW(combo, CB_GETCURSEL, 0, 0);
    if index < 0 {
        return None;
    }
    let length = SendMessageW(combo, CB_GETLBTEXTLEN, index as usize, 0);
    if length <= 0 {
        return None;
    }
    let mut buffer = vec![0u16; length as usize + 1];
    let copied = SendMessageW(
        combo,
        CB_GETLBTEXT,
        index as usize,
        buffer.as_mut_ptr() as LPARAM,
    );
    if copied <= 0 {
        return None;
    }
    Some(String::from_utf16_lossy(&buffer[..copied as usize]))
}

fn running_process_names() -> Vec<String> {
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snapshot == INVALID_HANDLE_VALUE {
            return Vec::new();
        }

        let mut names = Vec::new();
        let mut entry: PROCESSENTRY32W = zeroed();
        entry.dwSize = size_of::<PROCESSENTRY32W>() as u32;
        if Process32FirstW(snapshot, &mut entry) != 0 {
            loop {
                let end = entry
                    .szExeFile
                    .iter()
                    .position(|value| *value == 0)
                    .unwrap_or(entry.szExeFile.len());
                if end > 0 {
                    names.push(
                        String::from_utf16_lossy(&entry.szExeFile[..end]).to_ascii_lowercase(),
                    );
                }
                if Process32NextW(snapshot, &mut entry) == 0 {
                    break;
                }
            }
        }
        CloseHandle(snapshot);
        normalize_process_entries(&mut names);
        names
    }
}

fn process_entries(value: &str) -> Vec<String> {
    let mut entries: Vec<String> = value
        .split(['\r', '\n', ';'])
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(|entry| entry.to_ascii_lowercase())
        .collect();
    normalize_process_entries(&mut entries);
    entries
}

fn normalize_process_entries(entries: &mut Vec<String>) {
    for entry in entries.iter_mut() {
        *entry = entry.trim().to_ascii_lowercase();
    }
    entries.retain(|entry| !entry.is_empty());
    entries.sort_unstable();
    entries.dedup_by(|left, right| left.eq_ignore_ascii_case(right));
}

unsafe fn create_static(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    text: &str,
    rect: UiRect,
) -> HWND {
    let text = wide(text);
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        null_mut(),
        module,
        null(),
    )
}

unsafe fn create_group_box(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    text: &str,
    rect: UiRect,
) -> HWND {
    let text = wide(text);
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE | BS_GROUPBOX as u32,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        null_mut(),
        module,
        null(),
    )
}

unsafe fn create_checkbox(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    text: &str,
    id: i32,
    rect: UiRect,
) -> HWND {
    let text = wide(text);
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX as u32,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

unsafe fn create_multiline_edit(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    id: i32,
    rect: UiRect,
    read_only: bool,
) -> HWND {
    let empty = wide("");
    let mut style = WS_CHILD | WS_VISIBLE | WS_BORDER | ES_MULTILINE as u32 | ES_AUTOVSCROLL as u32;
    if read_only {
        style |= ES_READONLY as u32;
    } else {
        style |= WS_VSCROLL;
    }
    style |= WS_TABSTOP;
    CreateWindowExW(
        0,
        class.as_ptr(),
        empty.as_ptr(),
        style,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

unsafe fn create_single_edit(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    id: i32,
    rect: UiRect,
) -> HWND {
    let empty = wide("");
    CreateWindowExW(
        0,
        class.as_ptr(),
        empty.as_ptr(),
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_BORDER | ES_AUTOHSCROLL as u32,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

unsafe fn create_combo_box(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    id: i32,
    rect: UiRect,
) -> HWND {
    let empty = wide("");
    CreateWindowExW(
        0,
        class.as_ptr(),
        empty.as_ptr(),
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_VSCROLL | CBS_DROPDOWNLIST as u32,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

unsafe fn create_button(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    text: &str,
    id: i32,
    rect: UiRect,
    default: bool,
) -> HWND {
    let text = wide(text);
    let style = if default { BS_DEFPUSHBUTTON } else { 0 };
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | style as u32,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

unsafe fn is_checked(hwnd: HWND, id: i32) -> bool {
    SendMessageW(GetDlgItem(hwnd, id), BM_GETCHECK, 0, 0) as u32 == BST_CHECKED_VALUE
}

unsafe fn control_text(hwnd: HWND) -> String {
    let length = GetWindowTextLengthW(hwnd);
    if length <= 0 {
        return String::new();
    }
    let mut buffer = vec![0u16; length as usize + 1];
    let copied = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
    String::from_utf16_lossy(&buffer[..copied.max(0) as usize])
}

unsafe fn set_control_text(hwnd: HWND, value: &str) {
    let value = wide(value);
    SetWindowTextW(hwnd, value.as_ptr());
}

unsafe fn set_font(hwnd: HWND, font: *mut core::ffi::c_void) {
    SendMessageW(hwnd, WM_SETFONT, font as usize, 1);
}

fn choose_font(
    preferred: *mut core::ffi::c_void,
    fallback: *mut core::ffi::c_void,
) -> *mut core::ffi::c_void {
    if preferred.is_null() {
        fallback
    } else {
        preferred
    }
}

fn store_font(slot: &AtomicIsize, font: *mut core::ffi::c_void) {
    if !font.is_null() {
        slot.store(font as isize, Ordering::SeqCst);
    }
}

unsafe fn create_ui_font(height: i32, weight: i32) -> *mut core::ffi::c_void {
    let face = wide("Segoe UI");
    CreateFontW(
        height,
        0,
        0,
        0,
        weight,
        0,
        0,
        0,
        1,
        0,
        0,
        5,
        0,
        face.as_ptr(),
    )
}

unsafe fn cleanup_fonts() {
    for slot in [&TITLE_FONT, &SECTION_FONT, &BODY_FONT, &HINT_FONT] {
        let font = slot.swap(0, Ordering::SeqCst);
        if font != 0 {
            DeleteObject(font as *mut core::ffi::c_void);
        }
    }
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}
