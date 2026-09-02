mod settings;
mod ui;

use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::OnceLock;

#[cfg(test)]
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::{anyhow, Result};
use parking_lot::Mutex;
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HINSTANCE, HWND, LPARAM, LRESULT, WPARAM,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::{CreateMutexW, Sleep};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    GetKeyState, GetKeyboardLayout, GetKeyboardLayoutList, LoadKeyboardLayoutW, SendInput,
    VkKeyScanExW, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_BACK, VK_CAPITAL,
    VK_CONTROL, VK_OEM_1, VK_OEM_2, VK_OEM_3, VK_OEM_4, VK_OEM_6, VK_OEM_7, VK_OEM_COMMA,
    VK_OEM_PERIOD, VK_RETURN, VK_SHIFT, VK_SPACE, VK_TAB,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, DispatchMessageW, GetForegroundWindow, GetGUIThreadInfo, GetMessageW,
    GetWindowThreadProcessId, PostMessageW, SetWindowsHookExW, TranslateMessage,
    UnhookWindowsHookEx, GUITHREADINFO, KBDLLHOOKSTRUCT, LLKHF_INJECTED, MSG, WH_KEYBOARD_LL,
    WM_INPUTLANGCHANGEREQUEST, WM_KEYDOWN, WM_SYSKEYDOWN,
};

use crate::detector::{correction, opposite_candidate_is_prefix};
use crate::model::Language;

const MAGIC_EXTRA_INFO: usize = 0x4753_5749_5443_4845;
const SINGLE_INSTANCE_NAME: &str = "Local\\GSwitcher.SingleInstance.v0.6";

static ENGINE: OnceLock<Mutex<Engine>> = OnceLock::new();

#[cfg(test)]
static TEST_ACCEPT_INJECTED_INPUT: AtomicBool = AtomicBool::new(false);

#[derive(Debug, Clone, Copy)]
struct FocusTarget {
    hwnd: HWND,
    thread_id: u32,
    hkl: isize,
    language: Language,
}

#[derive(Debug, Clone, Copy)]
struct Stroke {
    vk: u16,
    shift: bool,
}

#[derive(Debug, Clone, Copy)]
enum Delimiter {
    VirtualKey(u16),
    Character(char),
}

#[derive(Debug, Clone)]
struct RuntimeUndo {
    focus: isize,
    source_hkl: isize,
    source_language: Language,
    original_strokes: Vec<Stroke>,
    corrected_len: usize,
    delimiter: Delimiter,
}

#[derive(Default)]
struct Engine {
    candidate: String,
    strokes: Vec<Stroke>,
    candidate_focus: isize,
    undo: Option<RuntimeUndo>,
}

enum HookDecision {
    Pass,
    Suppress,
}

pub fn run() -> Result<()> {
    let mutex = SingleInstance::acquire()?;
    if !mutex.is_primary {
        return Ok(());
    }

    if !settings::first_run_completed() {
        let enable_autostart = ui::show_first_run()?;
        if enable_autostart {
            settings::set_autostart(true)?;
        }
        settings::mark_first_run_completed()?;
    }

    let tray = ui::TrayGuard::install()?;
    ENGINE.get_or_init(|| Mutex::new(Engine::default()));
    let hook = KeyboardHook::install()?;

    let mut message: MSG = unsafe { zeroed() };
    loop {
        let result = unsafe { GetMessageW(&mut message, null_mut(), 0, 0) };
        if result <= 0 {
            break;
        }
        unsafe {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }

    drop(hook);
    drop(tray);
    drop(mutex);
    Ok(())
}

struct SingleInstance {
    handle: *mut core::ffi::c_void,
    is_primary: bool,
}

impl SingleInstance {
    fn acquire() -> Result<Self> {
        let name = wide(SINGLE_INSTANCE_NAME);
        let handle = unsafe { CreateMutexW(null(), 0, name.as_ptr()) };
        if handle.is_null() {
            return Err(anyhow!("CreateMutexW failed"));
        }
        let is_primary = unsafe { GetLastError() } != ERROR_ALREADY_EXISTS;
        Ok(Self { handle, is_primary })
    }
}

impl Drop for SingleInstance {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                CloseHandle(self.handle);
            }
        }
    }
}

struct KeyboardHook {
    handle: *mut core::ffi::c_void,
}

impl KeyboardHook {
    fn install() -> Result<Self> {
        let module = unsafe { GetModuleHandleW(null()) } as HINSTANCE;
        let handle = unsafe { SetWindowsHookExW(WH_KEYBOARD_LL, Some(keyboard_proc), module, 0) };
        if handle.is_null() {
            return Err(anyhow!("SetWindowsHookExW failed"));
        }
        Ok(Self { handle })
    }
}

impl Drop for KeyboardHook {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                UnhookWindowsHookEx(self.handle);
            }
        }
    }
}

unsafe extern "system" fn keyboard_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if code < 0 || (wparam as u32 != WM_KEYDOWN && wparam as u32 != WM_SYSKEYDOWN) {
        return CallNextHookEx(null_mut(), code, wparam, lparam);
    }

    let event = &*(lparam as *const KBDLLHOOKSTRUCT);
    if should_ignore_hook_event(event) {
        return CallNextHookEx(null_mut(), code, wparam, lparam);
    }

    let Some(engine) = ENGINE.get() else {
        return CallNextHookEx(null_mut(), code, wparam, lparam);
    };

    let decision = engine.lock().on_key_down(event.vkCode as u16);
    match decision {
        HookDecision::Pass => CallNextHookEx(null_mut(), code, wparam, lparam),
        HookDecision::Suppress => 1,
    }
}

fn should_ignore_hook_event(event: &KBDLLHOOKSTRUCT) -> bool {
    if event.dwExtraInfo == MAGIC_EXTRA_INFO {
        return true;
    }
    if event.flags & LLKHF_INJECTED == 0 {
        return false;
    }

    #[cfg(test)]
    if TEST_ACCEPT_INJECTED_INPUT.load(Ordering::SeqCst) {
        return false;
    }

    true
}

impl Engine {
    fn on_key_down(&mut self, vk: u16) -> HookDecision {
        let Some(target) = focused_target() else {
            self.reset_candidate();
            self.undo = None;
            return HookDecision::Pass;
        };

        // Modifier key-down events must not destroy the candidate or the transient undo record.
        // The following non-modifier key decides whether a shortcut should invalidate state.
        if is_modifier_vk(vk) {
            return HookDecision::Pass;
        }

        if is_control_down() && vk == VK_BACK {
            return if self.try_undo(target) {
                HookDecision::Suppress
            } else {
                self.reset_candidate();
                HookDecision::Pass
            };
        }

        if is_control_down() {
            self.reset_candidate();
            self.undo = None;
            return HookDecision::Pass;
        }

        let target_id = target.hwnd as isize;
        if self.candidate_focus != 0 && self.candidate_focus != target_id {
            self.reset_candidate();
        }
        if self.candidate_focus == 0 {
            self.candidate_focus = target_id;
        }

        if self.undo.is_some() {
            self.undo = None;
        }

        match vk {
            VK_BACK => {
                self.candidate.pop();
                self.strokes.pop();
                if self.candidate.is_empty() {
                    self.reset_candidate();
                }
                HookDecision::Pass
            }
            VK_SPACE => self.handle_boundary(target, Delimiter::VirtualKey(VK_SPACE)),
            VK_RETURN => self.handle_boundary(target, Delimiter::VirtualKey(VK_RETURN)),
            VK_TAB => self.handle_boundary(target, Delimiter::VirtualKey(VK_TAB)),
            VK_OEM_2 => self.handle_punctuation(target, vk),
            VK_OEM_COMMA | VK_OEM_PERIOD if target.language == Language::English => {
                self.handle_punctuation(target, vk)
            }
            _ => {
                if let Some(ch) = visible_char(vk, target.language) {
                    self.candidate.push(ch);
                    self.strokes.push(Stroke {
                        vk,
                        shift: is_shift_down(),
                    });
                } else {
                    self.reset_candidate();
                }
                HookDecision::Pass
            }
        }
    }

    fn handle_boundary(&mut self, target: FocusTarget, delimiter: Delimiter) -> HookDecision {
        if self.try_correct(target, delimiter) {
            HookDecision::Suppress
        } else {
            self.reset_candidate();
            HookDecision::Pass
        }
    }

    fn handle_punctuation(&mut self, target: FocusTarget, vk: u16) -> HookDecision {
        let Some(ch) = visible_char(vk, target.language) else {
            self.reset_candidate();
            return HookDecision::Pass;
        };

        if self.try_correct(target, Delimiter::Character(ch)) {
            return HookDecision::Suppress;
        }

        if punctuation_can_extend_candidate(vk, target.language)
            && opposite_candidate_is_prefix(&self.candidate)
        {
            self.candidate.push(ch);
            self.strokes.push(Stroke {
                vk,
                shift: is_shift_down(),
            });
        } else {
            self.reset_candidate();
        }
        HookDecision::Pass
    }

    fn try_correct(&mut self, source: FocusTarget, delimiter: Delimiter) -> bool {
        if self.candidate.is_empty() || self.strokes.is_empty() {
            return false;
        }

        let Some((detected_source, target_language, corrected)) = correction(&self.candidate)
        else {
            return false;
        };
        if detected_source != source.language {
            return false;
        }

        let Some(target_hkl) = select_layout(target_language) else {
            return false;
        };
        if !switch_layout(source.hwnd, source.thread_id, target_hkl) {
            return false;
        }

        let mut inputs = Vec::new();
        append_backspaces(&mut inputs, self.candidate.chars().count());
        for stroke in &self.strokes {
            append_stroke(&mut inputs, *stroke);
        }
        if !append_delimiter(&mut inputs, delimiter, target_hkl) {
            let _ = switch_layout(source.hwnd, source.thread_id, source.hkl);
            return false;
        }

        if !send_inputs(&inputs) {
            let _ = switch_layout(source.hwnd, source.thread_id, source.hkl);
            self.reset_candidate();
            return false;
        }

        self.undo = Some(RuntimeUndo {
            focus: source.hwnd as isize,
            source_hkl: source.hkl,
            source_language: source.language,
            original_strokes: self.strokes.clone(),
            corrected_len: corrected.chars().count(),
            delimiter,
        });
        self.reset_candidate();
        true
    }

    fn try_undo(&mut self, target: FocusTarget) -> bool {
        let Some(undo) = self.undo.take() else {
            return false;
        };
        if undo.focus != target.hwnd as isize {
            return false;
        }
        if !switch_layout(target.hwnd, target.thread_id, undo.source_hkl) {
            return false;
        }

        let mut inputs = Vec::new();
        append_backspaces(&mut inputs, undo.corrected_len + 1);
        for stroke in &undo.original_strokes {
            append_stroke(&mut inputs, *stroke);
        }
        if !append_delimiter(&mut inputs, undo.delimiter, undo.source_hkl) {
            return false;
        }

        let result = send_inputs(&inputs);
        if result {
            self.candidate_focus = target.hwnd as isize;
        }
        let _ = undo.source_language;
        result
    }

    fn reset_candidate(&mut self) {
        self.candidate.clear();
        self.strokes.clear();
        self.candidate_focus = 0;
    }
}

fn focused_target() -> Option<FocusTarget> {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            return None;
        }
        let foreground_thread = GetWindowThreadProcessId(foreground, null_mut());
        if foreground_thread == 0 {
            return None;
        }

        let mut info: GUITHREADINFO = zeroed();
        info.cbSize = size_of::<GUITHREADINFO>() as u32;
        let hwnd =
            if GetGUIThreadInfo(foreground_thread, &mut info) != 0 && !info.hwndFocus.is_null() {
                info.hwndFocus
            } else {
                foreground
            };
        let thread_id = GetWindowThreadProcessId(hwnd, null_mut());
        if thread_id == 0 {
            return None;
        }
        let hkl = GetKeyboardLayout(thread_id) as isize;
        let language = language_from_hkl(hkl)?;
        Some(FocusTarget {
            hwnd,
            thread_id,
            hkl,
            language,
        })
    }
}

fn language_from_hkl(hkl: isize) -> Option<Language> {
    let lang_id = hkl as usize & 0xffff;
    match lang_id & 0x03ff {
        0x09 => Some(Language::English),
        0x19 => Some(Language::Russian),
        _ => None,
    }
}

fn select_layout(language: Language) -> Option<isize> {
    unsafe {
        let count = GetKeyboardLayoutList(0, null_mut());
        if count > 0 {
            let mut layouts = vec![null_mut(); count as usize];
            let actual = GetKeyboardLayoutList(count, layouts.as_mut_ptr());
            for hkl in layouts.into_iter().take(actual.max(0) as usize) {
                let value = hkl as isize;
                if language_from_hkl(value) == Some(language) {
                    return Some(value);
                }
            }
        }

        let id = match language {
            Language::English => "00000409",
            Language::Russian => "00000419",
        };
        let id = wide(id);
        let loaded = LoadKeyboardLayoutW(id.as_ptr(), 0);
        if loaded.is_null() {
            None
        } else {
            Some(loaded as isize)
        }
    }
}

fn switch_layout(hwnd: HWND, thread_id: u32, hkl: isize) -> bool {
    unsafe {
        if GetKeyboardLayout(thread_id) as isize == hkl {
            return true;
        }
        if PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl) == 0 {
            return false;
        }
        for _ in 0..40 {
            Sleep(5);
            if GetKeyboardLayout(thread_id) as isize == hkl {
                return true;
            }
        }
        false
    }
}

fn punctuation_can_extend_candidate(vk: u16, source: Language) -> bool {
    matches!(
        (source, vk),
        (Language::English, VK_OEM_COMMA | VK_OEM_PERIOD)
    )
}

fn visible_char(vk: u16, language: Language) -> Option<char> {
    let shifted = is_shift_down();
    let caps = is_caps_lock_on();
    if (b'A' as u16..=b'Z' as u16).contains(&vk) {
        let index = (vk - b'A' as u16) as usize;
        let ch = match language {
            Language::English => "abcdefghijklmnopqrstuvwxyz".chars().nth(index)?,
            Language::Russian => "фисвуапршолдьтщзйкыегмцчня".chars().nth(index)?,
        };
        return Some(if shifted ^ caps {
            ch.to_uppercase().next().unwrap_or(ch)
        } else {
            ch
        });
    }

    match (language, vk, shifted) {
        (Language::English, VK_OEM_3, false) => Some('`'),
        (Language::English, VK_OEM_4, false) => Some('['),
        (Language::English, VK_OEM_6, false) => Some(']'),
        (Language::English, VK_OEM_1, false) => Some(';'),
        (Language::English, VK_OEM_7, false) => Some('\''),
        (Language::English, VK_OEM_COMMA, false) => Some(','),
        (Language::English, VK_OEM_PERIOD, false) => Some('.'),
        (Language::English, VK_OEM_2, false) => Some('/'),
        (Language::Russian, VK_OEM_3, false) => Some('ё'),
        (Language::Russian, VK_OEM_3, true) => Some('Ё'),
        (Language::Russian, VK_OEM_4, false) => Some('х'),
        (Language::Russian, VK_OEM_4, true) => Some('Х'),
        (Language::Russian, VK_OEM_6, false) => Some('ъ'),
        (Language::Russian, VK_OEM_6, true) => Some('Ъ'),
        (Language::Russian, VK_OEM_1, false) => Some('ж'),
        (Language::Russian, VK_OEM_1, true) => Some('Ж'),
        (Language::Russian, VK_OEM_7, false) => Some('э'),
        (Language::Russian, VK_OEM_7, true) => Some('Э'),
        (Language::Russian, VK_OEM_COMMA, false) => Some('б'),
        (Language::Russian, VK_OEM_COMMA, true) => Some('Б'),
        (Language::Russian, VK_OEM_PERIOD, false) => Some('ю'),
        (Language::Russian, VK_OEM_PERIOD, true) => Some('Ю'),
        (Language::Russian, VK_OEM_2, false) => Some('.'),
        (Language::Russian, VK_OEM_2, true) => Some(','),
        _ => None,
    }
}

fn is_modifier_vk(vk: u16) -> bool {
    matches!(
        vk,
        0x10 // VK_SHIFT
            | 0x11 // VK_CONTROL
            | 0x12 // VK_MENU
            | 0x14 // VK_CAPITAL
            | 0xA0 // VK_LSHIFT
            | 0xA1 // VK_RSHIFT
            | 0xA2 // VK_LCONTROL
            | 0xA3 // VK_RCONTROL
            | 0xA4 // VK_LMENU
            | 0xA5 // VK_RMENU
    )
}

fn is_shift_down() -> bool {
    unsafe { GetKeyState(VK_SHIFT as i32) < 0 }
}

fn is_control_down() -> bool {
    unsafe { GetKeyState(VK_CONTROL as i32) < 0 }
}

fn is_caps_lock_on() -> bool {
    unsafe { GetKeyState(VK_CAPITAL as i32) & 1 != 0 }
}

fn append_backspaces(inputs: &mut Vec<INPUT>, count: usize) {
    for _ in 0..count {
        append_stroke(
            inputs,
            Stroke {
                vk: VK_BACK,
                shift: false,
            },
        );
    }
}

fn append_delimiter(inputs: &mut Vec<INPUT>, delimiter: Delimiter, hkl: isize) -> bool {
    match delimiter {
        Delimiter::VirtualKey(vk) => {
            append_stroke(inputs, Stroke { vk, shift: false });
            true
        }
        Delimiter::Character(ch) => {
            let encoded = unsafe { VkKeyScanExW(ch as u16, hkl as *mut core::ffi::c_void) };
            if encoded == -1 {
                return false;
            }
            let vk = (encoded as u16) & 0xff;
            let shift = ((encoded as u16) >> 8) & 1 != 0;
            append_stroke(inputs, Stroke { vk, shift });
            true
        }
    }
}

fn append_stroke(inputs: &mut Vec<INPUT>, stroke: Stroke) {
    if stroke.shift {
        inputs.push(key_input(VK_SHIFT, 0));
    }
    inputs.push(key_input(stroke.vk, 0));
    inputs.push(key_input(stroke.vk, KEYEVENTF_KEYUP));
    if stroke.shift {
        inputs.push(key_input(VK_SHIFT, KEYEVENTF_KEYUP));
    }
}

fn key_input(vk: u16, flags: u32) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: MAGIC_EXTRA_INFO,
            },
        },
    }
}

fn send_inputs(inputs: &[INPUT]) -> bool {
    if inputs.is_empty() {
        return true;
    }
    unsafe {
        SendInput(
            inputs.len() as u32,
            inputs.as_ptr(),
            size_of::<INPUT>() as i32,
        ) == inputs.len() as u32
    }
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod e2e_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_ru_and_en_hkl_language_ids() {
        assert_eq!(language_from_hkl(0x0000_0409), Some(Language::English));
        assert_eq!(language_from_hkl(0x0000_0809), Some(Language::English));
        assert_eq!(language_from_hkl(0x0000_0419), Some(Language::Russian));
        assert_eq!(language_from_hkl(0x0000_0407), None);
    }

    #[test]
    fn input_struct_matches_win64_abi_on_64_bit_windows() {
        #[cfg(target_pointer_width = "64")]
        assert_eq!(size_of::<INPUT>(), 40);
    }

    #[test]
    fn modifier_keys_do_not_count_as_candidate_characters() {
        for vk in [0x10, 0x11, 0x12, 0x14, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5] {
            assert!(is_modifier_vk(vk));
        }
        assert!(!is_modifier_vk(b'A' as u16));
    }
}
