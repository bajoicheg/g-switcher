use std::mem::zeroed;
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicIsize, Ordering};
use std::sync::OnceLock;

use anyhow::{anyhow, Result};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    CreateFontW, DeleteObject, GetStockObject, GetSysColorBrush, SetBkMode, DEFAULT_GUI_FONT,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::Sleep;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DestroyWindow, DispatchMessageW, GetDlgItem, GetSystemMetrics,
    GetWindowTextLengthW, GetWindowTextW, IsWindow, LoadCursorW, PeekMessageW, RegisterClassW,
    SendMessageW, SetWindowTextW, ShowWindow, TranslateMessage, BM_GETCHECK, BM_SETCHECK,
    BS_AUTOCHECKBOX, BS_DEFPUSHBUTTON, ES_AUTOVSCROLL, ES_MULTILINE, IDC_ARROW, MSG, PM_REMOVE,
    SM_CXSCREEN, SM_CYSCREEN, SW_SHOW, WM_CLOSE, WM_COMMAND, WM_CTLCOLORSTATIC, WM_DESTROY,
    WM_SETFONT, WNDCLASSW, WS_BORDER, WS_CAPTION, WS_CHILD, WS_OVERLAPPED, WS_SYSMENU,
    WS_VISIBLE, WS_VSCROLL,
};

use crate::windows_runtime::settings;

const CLASS_NAME: &str = "GSwitcher.Settings.0.7";
const ID_AUTO_CORRECT: i32 = 3101;
const ID_AUTOSTART: i32 = 3102;
const ID_EXCLUSIONS: i32 = 3103;
const ID_USER_WORDS: i32 = 3104;
const ID_SAVE: i32 = 3105;
const ID_CANCEL: i32 = 3106;
const BST_CHECKED_VALUE: u32 = 1;
const COLOR_3DFACE_INDEX: i32 = 15;
const TRANSPARENT_BK_MODE: i32 = 1;

static CLASS_REGISTERED: OnceLock<()> = OnceLock::new();
static SETTINGS_FONT: AtomicIsize = AtomicIsize::new(0);

pub fn show() -> Result<()> {
    ensure_class()?;
    unsafe {
        let module = GetModuleHandleW(null());
        let width = 760;
        let height = 650;
        let x = (GetSystemMetrics(SM_CXSCREEN) - width) / 2;
        let y = (GetSystemMetrics(SM_CYSCREEN) - height) / 2;
        let class = wide(CLASS_NAME);
        let title = wide("G-switcher — настройки");
        let hwnd = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU,
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
        ShowWindow(hwnd, SW_SHOW);

        let mut message: MSG = zeroed();
        while IsWindow(hwnd) != 0 {
            while PeekMessageW(&mut message, null_mut(), 0, 0, PM_REMOVE) != 0 {
                TranslateMessage(&message);
                DispatchMessageW(&message);
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
            hIcon: null_mut(),
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
                ID_SAVE => {
                    let auto_correct = is_checked(hwnd, ID_AUTO_CORRECT);
                    let autostart = is_checked(hwnd, ID_AUTOSTART);
                    let exclusions = control_text(GetDlgItem(hwnd, ID_EXCLUSIONS));
                    let user_words = control_text(GetDlgItem(hwnd, ID_USER_WORDS));
                    let runtime =
                        settings::settings_from_text(auto_correct, &exclusions, &user_words);
                    if settings::save_runtime_settings(runtime).is_ok()
                        && settings::set_autostart(autostart).is_ok()
                    {
                        DestroyWindow(hwnd);
                    }
                }
                ID_CANCEL => {
                    DestroyWindow(hwnd);
                }
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
            cleanup_font();
            0
        }
        _ => DefWindowProcW(hwnd, message, wparam, lparam),
    }
}

unsafe fn create_controls(hwnd: HWND) {
    let module = GetModuleHandleW(null());
    let static_class = wide("STATIC");
    let button_class = wide("BUTTON");
    let edit_class = wide("EDIT");
    let runtime = settings::runtime_settings();

    let title = create_static(
        hwnd,
        module,
        &static_class,
        "Настройки G-switcher 0.7",
        28,
        22,
        680,
        30,
    );
    let intro = create_static(
        hwnd,
        module,
        &static_class,
        "Все параметры хранятся только в профиле текущего пользователя. История набранного текста не сохраняется.",
        28,
        58,
        690,
        42,
    );

    let auto_correct = create_checkbox(
        hwnd,
        module,
        &button_class,
        "Включить автоматическую коррекцию",
        ID_AUTO_CORRECT,
        28,
        108,
        360,
        26,
    );
    SendMessageW(
        auto_correct,
        BM_SETCHECK,
        usize::from(runtime.auto_correct) * BST_CHECKED_VALUE as usize,
        0,
    );

    let autostart = create_checkbox(
        hwnd,
        module,
        &button_class,
        "Запускать G-switcher при входе в Windows",
        ID_AUTOSTART,
        28,
        140,
        390,
        26,
    );
    SendMessageW(
        autostart,
        BM_SETCHECK,
        usize::from(settings::autostart_enabled()) * BST_CHECKED_VALUE as usize,
        0,
    );

    let exclusions_label = create_static(
        hwnd,
        module,
        &static_class,
        "Исключения по приложениям (одно имя .exe на строку)",
        28,
        186,
        520,
        24,
    );
    let exclusions_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Пример: powershell.exe, code.exe. В исключённых приложениях G-switcher не анализирует ввод и не выполняет замену.",
        28,
        212,
        690,
        40,
    );
    let exclusions = create_edit(hwnd, module, &edit_class, ID_EXCLUSIONS, 28, 255, 690, 105);
    set_control_text(exclusions, &runtime.excluded_apps_text());

    let dictionary_label = create_static(
        hwnd,
        module,
        &static_class,
        "Пользовательский словарь (одно слово на строку)",
        28,
        378,
        520,
        24,
    );
    let dictionary_hint = create_static(
        hwnd,
        module,
        &static_class,
        "Слово в своей раскладке защищается от автозамены; если неверная раскладка отображается в это слово, словарь повышает confidence до 100%.",
        28,
        404,
        690,
        40,
    );
    let dictionary = create_edit(hwnd, module, &edit_class, ID_USER_WORDS, 28, 447, 690, 105);
    set_control_text(dictionary, &runtime.user_words_text());

    let hotkey = create_static(
        hwnd,
        module,
        &static_class,
        "Ручная конвертация текущего слова: Ctrl+Shift+F12    •    Отмена последней замены: Ctrl+Backspace",
        28,
        566,
        690,
        24,
    );

    let save = create_button(
        hwnd,
        module,
        &button_class,
        "Сохранить",
        ID_SAVE,
        500,
        596,
        105,
        34,
        true,
    );
    let cancel = create_button(
        hwnd,
        module,
        &button_class,
        "Отмена",
        ID_CANCEL,
        613,
        596,
        105,
        34,
        false,
    );

    let font = create_ui_font(-17, 400);
    if !font.is_null() {
        SETTINGS_FONT.store(font as isize, Ordering::SeqCst);
    }
    let body_font = if font.is_null() {
        GetStockObject(DEFAULT_GUI_FONT)
    } else {
        font
    };
    for control in [
        title,
        intro,
        auto_correct,
        autostart,
        exclusions_label,
        exclusions_hint,
        exclusions,
        dictionary_label,
        dictionary_hint,
        dictionary,
        hotkey,
        save,
        cancel,
    ] {
        SendMessageW(control, WM_SETFONT, body_font as usize, 1);
    }
}

unsafe fn create_static(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    text: &str,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
) -> HWND {
    let text = wide(text);
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE,
        x,
        y,
        width,
        height,
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
    x: i32,
    y: i32,
    width: i32,
    height: i32,
) -> HWND {
    let text = wide(text);
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX as u32,
        x,
        y,
        width,
        height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

unsafe fn create_edit(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    id: i32,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
) -> HWND {
    let empty = wide("");
    CreateWindowExW(
        0,
        class.as_ptr(),
        empty.as_ptr(),
        WS_CHILD
            | WS_VISIBLE
            | WS_BORDER
            | WS_VSCROLL
            | ES_MULTILINE as u32
            | ES_AUTOVSCROLL as u32,
        x,
        y,
        width,
        height,
        parent,
        id as usize as *mut core::ffi::c_void,
        module,
        null(),
    )
}

#[allow(clippy::too_many_arguments)]
unsafe fn create_button(
    parent: HWND,
    module: *mut core::ffi::c_void,
    class: &[u16],
    text: &str,
    id: i32,
    x: i32,
    y: i32,
    width: i32,
    height: i32,
    default: bool,
) -> HWND {
    let text = wide(text);
    let style = if default { BS_DEFPUSHBUTTON } else { 0 };
    CreateWindowExW(
        0,
        class.as_ptr(),
        text.as_ptr(),
        WS_CHILD | WS_VISIBLE | style as u32,
        x,
        y,
        width,
        height,
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

unsafe fn cleanup_font() {
    let font = SETTINGS_FONT.swap(0, Ordering::SeqCst);
    if font != 0 {
        DeleteObject(font as *mut core::ffi::c_void);
    }
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}
