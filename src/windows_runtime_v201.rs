#[path = "windows_runtime/secure_input.rs"]
mod secure_input;
#[path = "windows_runtime/selection.rs"]
mod selection;
#[path = "windows_runtime/settings.rs"]
mod settings;
#[path = "windows_runtime/sound.rs"]
mod sound;
#[path = "windows_runtime/tray_status.rs"]
mod tray_status;
#[path = "windows_runtime/ui.rs"]
mod ui;

use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicIsize, AtomicU32, AtomicU64, AtomicU8, Ordering};
use std::sync::{mpsc, OnceLock};
use std::thread::{self, JoinHandle};
use std::time::Instant;

#[cfg(test)]
use std::sync::atomic::AtomicBool;

use anyhow::{anyhow, Result};
use parking_lot::Mutex;
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HINSTANCE, HWND, LPARAM, LRESULT, WPARAM,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::{
    CreateMutexW, GetCurrentThreadId, OpenProcess, QueryFullProcessImageNameW, Sleep,
    PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    ActivateKeyboardLayout, GetAsyncKeyState, GetKeyState, GetKeyboardLayout, GetKeyboardLayoutList,
    LoadKeyboardLayoutW, SendInput, VkKeyScanExW, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
    KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, VK_BACK, VK_CAPITAL, VK_CONTROL, VK_END, VK_HOME,
    VK_INSERT, VK_LEFT, VK_MENU, VK_NEXT, VK_OEM_1, VK_OEM_2, VK_OEM_3, VK_OEM_4, VK_OEM_5,
    VK_OEM_6, VK_OEM_7, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD, VK_OEM_PLUS, VK_PRIOR,
    VK_RETURN, VK_RIGHT, VK_SHIFT, VK_SPACE, VK_TAB, VK_UP, VK_DOWN, VK_DELETE,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, DispatchMessageW, GetForegroundWindow, GetGUIThreadInfo, GetMessageW,
    GetWindowThreadProcessId, MessageBoxW, PeekMessageW, PostMessageW, PostThreadMessageW,
    SetWindowsHookExW, TranslateMessage, UnhookWindowsHookEx, GUITHREADINFO, KBDLLHOOKSTRUCT,
    LLKHF_INJECTED, MB_ICONERROR, MB_OK, MSG, MSLLHOOKSTRUCT, PM_NOREMOVE, WH_KEYBOARD_LL,
    WH_MOUSE_LL, WM_APP, WM_INPUTLANGCHANGEREQUEST, WM_KEYDOWN, WM_LBUTTONDOWN, WM_MBUTTONDOWN,
    WM_MOUSEWHEEL, WM_QUIT, WM_RBUTTONDOWN, WM_SYSKEYDOWN,
};

use crate::code_safe::is_code_safe_token;
use crate::detector::{
    correction_at_boundary_with_context, correction_with_context, infer_language,
    opposite_candidate_is_prefix_for_language, MAX_CONTEXT_WORDS,
};
use crate::layout::opposite_layout_text;
use crate::model::Language;
use settings::AppMode;

const MAGIC_EXTRA_INFO: usize = 0x4753_5749_5443_4845;
const SINGLE_INSTANCE_NAME: &str = "Local\\GSwitcher.SingleInstance.v2.0.1";
const WM_RUNTIME_KEY_EVENT: u32 = WM_APP + 0x60;
const WM_RUNTIME_CORRECTION: u32 = WM_APP + 0x61;
const WM_RUNTIME_SELECTION: u32 = WM_APP + 0x62;
const WM_RUNTIME_INVALIDATE: u32 = WM_APP + 0x63;

const POLICY_UNKNOWN: u8 = 0;
const POLICY_READY: u8 = 1;
const POLICY_DENY: u8 = 2;

static ENGINE: OnceLock<Mutex<Engine>> = OnceLock::new();
static RUNTIME_THREAD_ID: OnceLock<u32> = OnceLock::new();
static HOOK_FOCUS: AtomicIsize = AtomicIsize::new(0);
static HOOK_POLICY: AtomicU8 = AtomicU8::new(POLICY_UNKNOWN);
static CONTEXT_GENERATION: AtomicU32 = AtomicU32::new(1);
static HOTKEY_SELECTED: AtomicU32 = AtomicU32::new(0);
static HOTKEY_MANUAL: AtomicU32 = AtomicU32::new(0);
static HOTKEY_PREVIOUS: AtomicU32 = AtomicU32::new(0);
static HOTKEY_UNDO: AtomicU32 = AtomicU32::new(0);
static HOTKEY_PAUSE: AtomicU32 = AtomicU32::new(0);
static CALLBACK_COUNT: AtomicU64 = AtomicU64::new(0);
static CALLBACK_MAX_NS: AtomicU64 = AtomicU64::new(0);
static DROPPED_EVENTS: AtomicU64 = AtomicU64::new(0);

#[cfg(test)]
static TEST_ACCEPT_INJECTED_INPUT: AtomicBool = AtomicBool::new(false);

#[derive(Debug, Clone, Copy)]
struct FocusTarget {
    hwnd: HWND,
    thread_id: u32,
    process_id: u32,
    hkl: isize,
    language: Language,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Stroke {
    vk: u16,
    shift: bool,
}

#[derive(Debug, Clone, Copy)]
enum Delimiter {
    VirtualKey(u16),
    Character(char),
}

impl Delimiter {
    fn text(self) -> String {
        match self {
            Self::VirtualKey(VK_SPACE) => " ".to_owned(),
            Self::VirtualKey(VK_TAB) => "\t".to_owned(),
            Self::VirtualKey(VK_RETURN) => "\r\n".to_owned(),
            Self::VirtualKey(_) => String::new(),
            Self::Character(ch) => ch.to_string(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct Modifiers {
    ctrl: bool,
    shift: bool,
    alt: bool,
}

#[derive(Debug, Clone, Copy)]
struct HookEvent {
    vk: u16,
    modifiers: Modifiers,
    caps: bool,
    focus: isize,
    generation: u32,
    suppressed: bool,
}

#[derive(Debug, Clone)]
struct PreviousToken {
    focus: isize,
    process_id: u32,
    generation: u32,
    source_hkl: isize,
    source_language: Language,
    text: String,
    strokes: Vec<Stroke>,
    delimiter: Delimiter,
}

#[derive(Debug, Clone)]
struct RuntimeUndo {
    focus: isize,
    process_id: u32,
    generation: u32,
    source_hkl: isize,
    source_language: Language,
    target_hkl: isize,
    original_text: String,
    corrected_text: String,
    original_strokes: Vec<Stroke>,
    corrected_len: usize,
    delimiter: Option<Delimiter>,
}

#[derive(Debug, Clone)]
struct SelectionUndo {
    focus: isize,
    process_id: u32,
    generation: u32,
    source_hkl: isize,
    source_language: Language,
    target_hkl: isize,
    corrected: String,
    original: String,
}

#[derive(Debug, Clone)]
struct PendingCorrection {
    focus: isize,
    thread_id: u32,
    process_id: u32,
    generation: u32,
    source_hkl: isize,
    source_language: Language,
    target_hkl: isize,
    original_text: String,
    corrected: String,
    replacement_text: String,
    erase_len: usize,
    original_strokes: Vec<Stroke>,
    delimiter: Option<Delimiter>,
    held_modifiers: Modifiers,
}

#[derive(Debug, Clone, Copy)]
struct PendingSelection {
    focus: isize,
    process_id: u32,
    generation: u32,
}

#[derive(Default)]
struct Engine {
    candidate: String,
    strokes: Vec<Stroke>,
    candidate_focus: isize,
    previous: Option<PreviousToken>,
    context_tokens: Vec<String>,
    undo: Option<RuntimeUndo>,
    selection_undo: Option<SelectionUndo>,
    pending_correction: Option<PendingCorrection>,
    pending_selection: Option<PendingSelection>,
    process_id: u32,
    process_name: String,
    generation: u32,
}

pub fn run() -> Result<()> {
    let mutex = SingleInstance::acquire()?;
    if !mutex.is_primary {
        return Ok(());
    }

    settings::set_paused(false);
    if !settings::first_run_completed() {
        let Some(preferences) = ui::show_first_run()? else {
            return Ok(());
        };
        let mut runtime = settings::runtime_settings();
        runtime.sound_enabled = preferences.sound_enabled;
        runtime.sound_volume = preferences.sound_volume;
        settings::save_runtime_settings(runtime)?;
        settings::set_autostart(preferences.autostart)?;
        settings::mark_first_run_completed()?;
    }

    let runtime_thread = unsafe { GetCurrentThreadId() };
    let _ = RUNTIME_THREAD_ID.set(runtime_thread);
    unsafe {
        let mut message: MSG = zeroed();
        PeekMessageW(&mut message, null_mut(), 0, 0, PM_NOREMOVE);
    }

    publish_hotkeys(&settings::runtime_settings());
    let tray = ui::TrayGuard::install()?;
    ENGINE.get_or_init(|| Mutex::new(Engine::default()));
    let hook = KeyboardHook::install()?;

    let mut message: MSG = unsafe { zeroed() };
    loop {
        let result = unsafe { GetMessageW(&mut message, null_mut(), 0, 0) };
        if result <= 0 {
            break;
        }
        if handle_runtime_message(&message) {
            continue;
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

pub fn show_fatal_error(message: &str) {
    let message = wide(message);
    let title = wide("G-switcher — ошибка запуска");
    unsafe {
        MessageBoxW(
            null_mut(),
            message.as_ptr(),
            title.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
}

pub(crate) fn paused() -> bool {
    settings::paused()
}

pub(crate) fn toggle_pause() -> bool {
    let value = settings::toggle_paused();
    invalidate_context(false);
    if let Some(engine) = ENGINE.get() {
        engine.lock().reset_transient();
    }
    tray_status::set_paused(value);
    value
}

pub(crate) fn current_process_name() -> Option<String> {
    let engine = ENGINE.get()?;
    let process_name = engine.lock().process_name.clone();
    (!process_name.is_empty()).then_some(process_name)
}

fn handle_runtime_message(message: &MSG) -> bool {
    let Some(engine) = ENGINE.get() else {
        return false;
    };
    match message.message {
        WM_RUNTIME_KEY_EVENT => {
            let event = decode_hook_event(message.wParam, message.lParam);
            engine.lock().on_key_event(event);
            true
        }
        WM_RUNTIME_CORRECTION => {
            engine.lock().execute_pending_correction();
            true
        }
        WM_RUNTIME_SELECTION => {
            engine.lock().execute_pending_selection();
            true
        }
        WM_RUNTIME_INVALIDATE => {
            engine.lock().reset_transient();
            true
        }
        _ => false,
    }
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
            unsafe { CloseHandle(self.handle) };
        }
    }
}

struct KeyboardHook {
    thread_id: u32,
    join: Option<JoinHandle<()>>,
}

impl KeyboardHook {
    fn install() -> Result<Self> {
        let runtime_thread = unsafe { GetCurrentThreadId() };
        let _ = RUNTIME_THREAD_ID.set(runtime_thread);
        publish_hotkeys(&settings::runtime_settings());

        let (ready_tx, ready_rx) = mpsc::sync_channel::<std::result::Result<u32, String>>(1);
        let join = thread::spawn(move || hook_thread_main(ready_tx));
        let thread_id = ready_rx
            .recv()
            .map_err(|_| anyhow!("hook thread exited before initialization"))?
            .map_err(|message| anyhow!(message))?;
        Ok(Self {
            thread_id,
            join: Some(join),
        })
    }
}

impl Drop for KeyboardHook {
    fn drop(&mut self) {
        unsafe {
            PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0);
        }
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}

fn hook_thread_main(ready_tx: mpsc::SyncSender<std::result::Result<u32, String>>) {
    unsafe {
        let thread_id = GetCurrentThreadId();
        let mut message: MSG = zeroed();
        PeekMessageW(&mut message, null_mut(), 0, 0, PM_NOREMOVE);

        let module = GetModuleHandleW(null()) as HINSTANCE;
        let keyboard = SetWindowsHookExW(WH_KEYBOARD_LL, Some(keyboard_proc), module, 0);
        if keyboard.is_null() {
            let _ = ready_tx.send(Err("SetWindowsHookExW(WH_KEYBOARD_LL) failed".to_owned()));
            return;
        }
        let mouse = SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_proc), module, 0);
        if mouse.is_null() {
            UnhookWindowsHookEx(keyboard);
            let _ = ready_tx.send(Err("SetWindowsHookExW(WH_MOUSE_LL) failed".to_owned()));
            return;
        }
        let _ = ready_tx.send(Ok(thread_id));

        while GetMessageW(&mut message, null_mut(), 0, 0) > 0 {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        UnhookWindowsHookEx(mouse);
        UnhookWindowsHookEx(keyboard);
    }
}

unsafe extern "system" fn keyboard_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let started = Instant::now();
    let result = keyboard_proc_inner(code, wparam, lparam);
    record_callback_time(started.elapsed().as_nanos().min(u64::MAX as u128) as u64);
    result
}

unsafe fn keyboard_proc_inner(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if code < 0 || (wparam as u32 != WM_KEYDOWN && wparam as u32 != WM_SYSKEYDOWN) {
        return CallNextHookEx(null_mut(), code, wparam, lparam);
    }
    let event = &*(lparam as *const KBDLLHOOKSTRUCT);
    if should_ignore_hook_event(event) {
        return CallNextHookEx(null_mut(), code, wparam, lparam);
    }

    let focus = focused_hwnd_fast() as isize;
    let previous_focus = HOOK_FOCUS.swap(focus, Ordering::SeqCst);
    let mut generation = CONTEXT_GENERATION.load(Ordering::SeqCst);
    if focus == 0 || previous_focus != focus {
        generation = CONTEXT_GENERATION.fetch_add(1, Ordering::SeqCst).wrapping_add(1);
        HOOK_POLICY.store(POLICY_UNKNOWN, Ordering::SeqCst);
    }

    let modifiers = capture_modifiers();
    let caps = GetKeyState(VK_CAPITAL as i32) & 1 != 0;
    if invalidates_context(event.vkCode as u16, modifiers) {
        generation = CONTEXT_GENERATION.fetch_add(1, Ordering::SeqCst).wrapping_add(1);
    }

    let ready = focus != 0
        && HOOK_POLICY.load(Ordering::SeqCst) == POLICY_READY
        && HOOK_FOCUS.load(Ordering::SeqCst) == focus;
    let hotkey = ready && matches_published_hotkey(event.vkCode as u16, modifiers);
    let packed = encode_hook_event(
        event.vkCode as u16,
        modifiers,
        caps,
        generation,
        hotkey,
    );
    let posted = post_runtime(WM_RUNTIME_KEY_EVENT, packed, focus);
    if !posted {
        DROPPED_EVENTS.fetch_add(1, Ordering::Relaxed);
        invalidate_context(true);
        return CallNextHookEx(null_mut(), code, wparam, lparam);
    }

    if hotkey {
        1
    } else {
        CallNextHookEx(null_mut(), code, wparam, lparam)
    }
}

unsafe extern "system" fn mouse_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    let started = Instant::now();
    if code >= 0
        && matches!(
            wparam as u32,
            WM_LBUTTONDOWN | WM_RBUTTONDOWN | WM_MBUTTONDOWN | WM_MOUSEWHEEL
        )
    {
        let event = &*(lparam as *const MSLLHOOKSTRUCT);
        if event.dwExtraInfo != MAGIC_EXTRA_INFO {
            invalidate_context(true);
            let _ = post_runtime(WM_RUNTIME_INVALIDATE, 0, 0);
        }
    }
    let result = CallNextHookEx(null_mut(), code, wparam, lparam);
    record_callback_time(started.elapsed().as_nanos().min(u64::MAX as u128) as u64);
    result
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

fn focused_hwnd_fast() -> HWND {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_null() {
            return null_mut();
        }
        let foreground_thread = GetWindowThreadProcessId(foreground, null_mut());
        if foreground_thread == 0 {
            return foreground;
        }
        let mut info: GUITHREADINFO = zeroed();
        info.cbSize = size_of::<GUITHREADINFO>() as u32;
        if GetGUIThreadInfo(foreground_thread, &mut info) != 0 && !info.hwndFocus.is_null() {
            info.hwndFocus
        } else {
            foreground
        }
    }
}

fn post_runtime(message: u32, wparam: usize, lparam: isize) -> bool {
    let Some(thread_id) = RUNTIME_THREAD_ID.get().copied() else {
        return false;
    };
    unsafe { PostThreadMessageW(thread_id, message, wparam, lparam) != 0 }
}

fn invalidate_context(policy_unknown: bool) {
    CONTEXT_GENERATION.fetch_add(1, Ordering::SeqCst);
    if policy_unknown {
        HOOK_POLICY.store(POLICY_UNKNOWN, Ordering::SeqCst);
    }
}

fn record_callback_time(elapsed_ns: u64) {
    CALLBACK_COUNT.fetch_add(1, Ordering::Relaxed);
    let mut current = CALLBACK_MAX_NS.load(Ordering::Relaxed);
    while elapsed_ns > current {
        match CALLBACK_MAX_NS.compare_exchange_weak(
            current,
            elapsed_ns,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => break,
            Err(next) => current = next,
        }
    }
}

fn capture_modifiers() -> Modifiers {
    unsafe {
        Modifiers {
            ctrl: GetAsyncKeyState(VK_CONTROL as i32) < 0,
            shift: GetAsyncKeyState(VK_SHIFT as i32) < 0,
            alt: GetAsyncKeyState(VK_MENU as i32) < 0,
        }
    }
}

fn invalidates_context(vk: u16, modifiers: Modifiers) -> bool {
    matches!(
        vk,
        VK_LEFT | VK_RIGHT | VK_UP | VK_DOWN | VK_HOME | VK_END | VK_PRIOR | VK_NEXT | VK_DELETE
            | VK_INSERT
    ) || ((modifiers.ctrl || modifiers.alt) && !matches_published_hotkey(vk, modifiers))
}

fn publish_hotkeys(runtime: &settings::RuntimeSettings) {
    HOTKEY_SELECTED.store(pack_hotkey(runtime.selected_text_hotkey), Ordering::SeqCst);
    HOTKEY_MANUAL.store(pack_hotkey(runtime.manual_current_hotkey), Ordering::SeqCst);
    HOTKEY_PREVIOUS.store(pack_hotkey(runtime.previous_word_hotkey), Ordering::SeqCst);
    HOTKEY_UNDO.store(pack_hotkey(runtime.undo_hotkey), Ordering::SeqCst);
    HOTKEY_PAUSE.store(pack_hotkey(runtime.pause_hotkey), Ordering::SeqCst);
}

fn pack_hotkey(hotkey: settings::Hotkey) -> u32 {
    u32::from(hotkey.vk)
        | (u32::from(hotkey.ctrl) << 16)
        | (u32::from(hotkey.shift) << 17)
        | (u32::from(hotkey.alt) << 18)
}

fn pack_event_key(vk: u16, modifiers: Modifiers) -> u32 {
    u32::from(vk)
        | (u32::from(modifiers.ctrl) << 16)
        | (u32::from(modifiers.shift) << 17)
        | (u32::from(modifiers.alt) << 18)
}

fn matches_published_hotkey(vk: u16, modifiers: Modifiers) -> bool {
    let packed = pack_event_key(vk, modifiers);
    [
        &HOTKEY_SELECTED,
        &HOTKEY_MANUAL,
        &HOTKEY_PREVIOUS,
        &HOTKEY_UNDO,
        &HOTKEY_PAUSE,
    ]
    .iter()
    .any(|hotkey| hotkey.load(Ordering::Relaxed) == packed)
}

fn encode_hook_event(
    vk: u16,
    modifiers: Modifiers,
    caps: bool,
    generation: u32,
    suppressed: bool,
) -> usize {
    let mut value = pack_event_key(vk, modifiers) as u64;
    value |= u64::from(caps) << 19;
    value |= u64::from(suppressed) << 20;
    value |= u64::from(generation) << 32;
    value as usize
}

fn decode_hook_event(wparam: WPARAM, lparam: LPARAM) -> HookEvent {
    let value = wparam as u64;
    HookEvent {
        vk: (value & 0xffff) as u16,
        modifiers: Modifiers {
            ctrl: value & (1 << 16) != 0,
            shift: value & (1 << 17) != 0,
            alt: value & (1 << 18) != 0,
        },
        caps: value & (1 << 19) != 0,
        focus: lparam,
        generation: (value >> 32) as u32,
        suppressed: value & (1 << 20) != 0,
    }
}

impl Engine {
    fn on_key_event(&mut self, event: HookEvent) {
        let runtime_settings = settings::runtime_settings();
        publish_hotkeys(&runtime_settings);

        if self.generation != event.generation {
            self.reset_transient();
            self.generation = event.generation;
        }

        let Some(target) = focused_target() else {
            HOOK_POLICY.store(POLICY_UNKNOWN, Ordering::SeqCst);
            self.reset_transient();
            return;
        };
        if target.hwnd as isize != event.focus {
            HOOK_POLICY.store(POLICY_UNKNOWN, Ordering::SeqCst);
            self.reset_transient();
            return;
        }

        self.refresh_process_name(target.process_id);
        let app_mode = runtime_settings.app_mode(&self.process_name);
        tray_status::update_context(app_mode, &self.process_name, target.language);
        if app_mode == AppMode::Disabled {
            HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
            self.reset_transient();
            return;
        }

        if secure_input::is_secure_input(target.hwnd, &self.process_name) {
            HOOK_POLICY.store(POLICY_DENY, Ordering::SeqCst);
            self.reset_transient();
            return;
        }
        HOOK_FOCUS.store(target.hwnd as isize, Ordering::SeqCst);
        HOOK_POLICY.store(POLICY_READY, Ordering::SeqCst);

        if event.suppressed
            && runtime_settings.pause_hotkey.matches(
                event.vk,
                event.modifiers.ctrl,
                event.modifiers.shift,
                event.modifiers.alt,
            )
        {
            let value = settings::toggle_paused();
            self.reset_transient();
            tray_status::set_paused(value);
            return;
        }

        if settings::paused() {
            self.reset_transient();
            return;
        }

        if event.suppressed
            && runtime_settings.selected_text_hotkey.matches(
                event.vk,
                event.modifiers.ctrl,
                event.modifiers.shift,
                event.modifiers.alt,
            )
        {
            let _ = self.queue_selected_conversion(target, event.generation);
            return;
        }

        if event.suppressed
            && runtime_settings.manual_current_hotkey.matches(
                event.vk,
                event.modifiers.ctrl,
                event.modifiers.shift,
                event.modifiers.alt,
            )
        {
            let _ = self.try_manual_convert(target, event.modifiers, event.generation);
            return;
        }

        if event.suppressed
            && runtime_settings.previous_word_hotkey.matches(
                event.vk,
                event.modifiers.ctrl,
                event.modifiers.shift,
                event.modifiers.alt,
            )
        {
            let _ = self.try_convert_previous(target, event.modifiers, event.generation);
            return;
        }

        if event.suppressed
            && runtime_settings.undo_hotkey.matches(
                event.vk,
                event.modifiers.ctrl,
                event.modifiers.shift,
                event.modifiers.alt,
            )
        {
            let _ = self.try_undo(target, event.modifiers, event.generation);
            self.reset_candidate();
            return;
        }

        if is_modifier_vk(event.vk) {
            return;
        }
        if invalidates_context(event.vk, event.modifiers) {
            self.reset_transient();
            return;
        }
        if event.modifiers.ctrl || event.modifiers.alt {
            self.reset_transient();
            return;
        }

        let target_id = target.hwnd as isize;
        if self.candidate_focus != 0 && self.candidate_focus != target_id {
            self.reset_transient();
        }
        if self.candidate_focus == 0 {
            self.candidate_focus = target_id;
        }
        if let Some(previous) = &self.previous {
            if previous.focus != target_id
                || previous.process_id != target.process_id
                || previous.generation != event.generation
            {
                self.previous = None;
            }
        }

        if self.undo.is_some() || self.selection_undo.is_some() {
            self.undo = None;
            self.selection_undo = None;
        }

        let allow_auto = app_mode == AppMode::Auto;
        match event.vk {
            VK_BACK => {
                self.previous = None;
                self.candidate.pop();
                self.strokes.pop();
                if self.candidate.is_empty() {
                    self.reset_candidate();
                }
            }
            VK_SPACE => {
                self.handle_boundary(
                    target,
                    Delimiter::VirtualKey(VK_SPACE),
                    allow_auto,
                    event.generation,
                );
            }
            VK_RETURN => {
                self.handle_boundary(
                    target,
                    Delimiter::VirtualKey(VK_RETURN),
                    allow_auto,
                    event.generation,
                );
            }
            VK_TAB => {
                self.handle_boundary(
                    target,
                    Delimiter::VirtualKey(VK_TAB),
                    allow_auto,
                    event.generation,
                );
            }
            VK_OEM_2 => self.handle_punctuation(
                target,
                event.vk,
                allow_auto,
                event.modifiers.shift,
                event.caps,
                event.generation,
            ),
            VK_OEM_COMMA | VK_OEM_PERIOD if target.language == Language::English => {
                self.handle_punctuation(
                    target,
                    event.vk,
                    allow_auto,
                    event.modifiers.shift,
                    event.caps,
                    event.generation,
                )
            }
            _ => {
                self.previous = None;
                if let Some(ch) = visible_char(
                    event.vk,
                    target.language,
                    event.modifiers.shift,
                    event.caps,
                ) {
                    self.candidate.push(ch);
                    self.strokes.push(Stroke {
                        vk: event.vk,
                        shift: event.modifiers.shift,
                    });
                } else {
                    self.reset_candidate();
                }
            }
        }
    }

    fn refresh_process_name(&mut self, process_id: u32) {
        if self.process_id == process_id {
            return;
        }
        self.reset_transient();
        self.process_id = process_id;
        self.process_name = process_name_for_pid(process_id).unwrap_or_default();
    }

    fn handle_boundary(
        &mut self,
        target: FocusTarget,
        delimiter: Delimiter,
        allow_auto: bool,
        generation: u32,
    ) {
        if allow_auto && self.try_correct(target, delimiter, true, generation) {
            self.previous = None;
        } else {
            self.remember_previous(target, delimiter, generation);
            self.remember_context_candidate();
            self.reset_candidate();
        }
    }

    fn handle_punctuation(
        &mut self,
        target: FocusTarget,
        vk: u16,
        allow_auto: bool,
        shift: bool,
        caps: bool,
        generation: u32,
    ) {
        let Some(ch) = visible_char(vk, target.language, shift, caps) else {
            self.reset_transient();
            return;
        };
        let delimiter = Delimiter::Character(ch);

        if is_code_safe_token(&self.candidate) {
            self.previous = None;
            self.candidate.push(ch);
            self.strokes.push(Stroke { vk, shift });
            return;
        }

        if allow_auto && self.try_correct(target, delimiter, false, generation) {
            self.previous = None;
            return;
        }

        let runtime_settings = settings::runtime_settings();
        let mut prospective = self.candidate.clone();
        prospective.push(ch);
        if is_code_safe_token(&prospective)
            || (punctuation_can_extend_candidate(vk, target.language)
                && opposite_candidate_is_prefix_for_language(
                    &prospective,
                    target.language,
                    &runtime_settings.user_words,
                ))
        {
            self.previous = None;
            self.candidate.push(ch);
            self.strokes.push(Stroke { vk, shift });
        } else {
            self.remember_previous(target, delimiter, generation);
            self.remember_context_candidate();
            self.reset_candidate();
        }
    }

    fn remember_previous(&mut self, target: FocusTarget, delimiter: Delimiter, generation: u32) {
        if self.candidate.is_empty() || self.strokes.is_empty() {
            self.previous = None;
            return;
        }
        self.previous = Some(PreviousToken {
            focus: target.hwnd as isize,
            process_id: target.process_id,
            generation,
            source_hkl: target.hkl,
            source_language: target.language,
            text: self.candidate.clone(),
            strokes: self.strokes.clone(),
            delimiter,
        });
    }

    fn remember_context_candidate(&mut self) {
        if self.candidate.is_empty()
            || is_code_safe_token(&self.candidate)
            || infer_language(&self.candidate).is_none()
        {
            return;
        }
        self.push_context(self.candidate.clone());
    }

    fn push_context(&mut self, token: String) {
        if infer_language(&token).is_none() || is_code_safe_token(&token) {
            return;
        }
        if self.context_tokens.len() >= MAX_CONTEXT_WORDS {
            self.context_tokens.remove(0);
        }
        self.context_tokens.push(token);
    }

    fn try_correct(
        &mut self,
        source: FocusTarget,
        delimiter: Delimiter,
        at_boundary: bool,
        generation: u32,
    ) -> bool {
        if self.candidate.is_empty()
            || self.strokes.is_empty()
            || self.pending_correction.is_some()
            || is_code_safe_token(&self.candidate)
        {
            return false;
        }

        let runtime_settings = settings::runtime_settings();
        if !runtime_settings.auto_correct {
            return false;
        }
        let detection = if at_boundary {
            correction_at_boundary_with_context(
                &self.candidate,
                &runtime_settings.user_words,
                runtime_settings.sensitivity.confidence_threshold(),
                &self.context_tokens,
            )
        } else {
            correction_with_context(
                &self.candidate,
                &runtime_settings.user_words,
                runtime_settings.sensitivity.confidence_threshold(),
                &self.context_tokens,
            )
        };
        let Some(detection) = detection else {
            return false;
        };
        if detection.source != source.language {
            return false;
        }

        self.queue_correction_parts(
            source,
            detection.target,
            self.candidate.clone(),
            detection.corrected,
            self.candidate.chars().count() + 1,
            self.strokes.clone(),
            Some(delimiter),
            Modifiers::default(),
            generation,
        )
    }

    fn queue_selected_conversion(&mut self, target: FocusTarget, generation: u32) -> bool {
        if self.pending_selection.is_some() || self.pending_correction.is_some() {
            return false;
        }
        self.reset_candidate();
        self.previous = None;
        self.context_tokens.clear();
        self.undo = None;
        self.selection_undo = None;
        self.pending_selection = Some(PendingSelection {
            focus: target.hwnd as isize,
            process_id: target.process_id,
            generation,
        });
        if !post_runtime(WM_RUNTIME_SELECTION, 0, 0) {
            self.pending_selection = None;
            return false;
        }
        true
    }

    fn execute_pending_selection(&mut self) {
        let Some(pending) = self.pending_selection.take() else {
            return;
        };
        if settings::paused() || current_generation() != pending.generation {
            return;
        }
        let Some(target) = focused_target() else {
            return;
        };
        if target.hwnd as isize != pending.focus || target.process_id != pending.process_id {
            return;
        }
        self.refresh_process_name(target.process_id);
        let runtime_settings = settings::runtime_settings();
        if runtime_settings.app_mode(&self.process_name) == AppMode::Disabled
            || secure_input::is_secure_input(target.hwnd, &self.process_name)
        {
            return;
        }

        let Some(selected) = selection::read_selected_text(target.hwnd) else {
            return;
        };
        let Some(source_language) = infer_language(&selected.text) else {
            return;
        };
        let target_language = opposite_language(source_language);
        let corrected = opposite_layout_text(&selected.text, source_language);
        if corrected == selected.text {
            return;
        }
        let Some(target_hkl) = select_layout(target_language) else {
            return;
        };
        if !switch_layout(target.hwnd, target.thread_id, target_hkl) {
            return;
        }
        if current_generation() != pending.generation
            || focused_target().is_none_or(|now| {
                now.hwnd as isize != pending.focus || now.process_id != pending.process_id
            })
        {
            let _ = switch_layout(target.hwnd, target.thread_id, target.hkl);
            return;
        }
        if !selection::replace_range(target.hwnd, selected.start, selected.end, &corrected) {
            let _ = switch_layout(target.hwnd, target.thread_id, target.hkl);
            return;
        }

        self.selection_undo = Some(SelectionUndo {
            focus: target.hwnd as isize,
            process_id: target.process_id,
            generation: pending.generation,
            source_hkl: target.hkl,
            source_language: target.language,
            target_hkl,
            corrected: corrected.clone(),
            original: selected.text,
        });
        self.undo = None;
        self.reset_candidate();
        self.previous = None;
        self.context_tokens.clear();
        tray_status::note_correction(target_language);
        sound::play_correction(&runtime_settings);
    }

    fn try_manual_convert(
        &mut self,
        source: FocusTarget,
        modifiers: Modifiers,
        generation: u32,
    ) -> bool {
        if self.candidate.is_empty() || self.strokes.is_empty() || self.pending_correction.is_some()
        {
            return false;
        }
        let target = opposite_language(source.language);
        let corrected = opposite_layout_text(&self.candidate, source.language);
        self.previous = None;
        self.selection_undo = None;
        self.queue_correction_parts(
            source,
            target,
            self.candidate.clone(),
            corrected,
            self.candidate.chars().count(),
            self.strokes.clone(),
            None,
            modifiers,
            generation,
        )
    }

    fn try_convert_previous(
        &mut self,
        target: FocusTarget,
        modifiers: Modifiers,
        generation: u32,
    ) -> bool {
        if self.pending_correction.is_some() || !self.candidate.is_empty() {
            return false;
        }
        let Some(previous) = self.previous.clone() else {
            return false;
        };
        if previous.focus != target.hwnd as isize
            || previous.process_id != target.process_id
            || previous.generation != generation
        {
            self.previous = None;
            return false;
        }

        let previous_text = previous.text.clone();
        let corrected = opposite_layout_text(&previous.text, previous.source_language);
        let source = FocusTarget {
            hkl: previous.source_hkl,
            language: previous.source_language,
            ..target
        };
        self.selection_undo = None;
        let queued = self.queue_correction_parts(
            source,
            opposite_language(previous.source_language),
            previous.text.clone(),
            corrected,
            previous.text.chars().count() + 1,
            previous.strokes,
            Some(previous.delimiter),
            modifiers,
            generation,
        );
        if queued {
            self.previous = None;
            if self.context_tokens.last() == Some(&previous_text) {
                self.context_tokens.pop();
            }
        }
        queued
    }

    #[allow(clippy::too_many_arguments)]
    fn queue_correction_parts(
        &mut self,
        source: FocusTarget,
        target_language: Language,
        original: String,
        corrected: String,
        erase_len: usize,
        original_strokes: Vec<Stroke>,
        delimiter: Option<Delimiter>,
        held_modifiers: Modifiers,
        generation: u32,
    ) -> bool {
        let Some(target_hkl) = select_layout(target_language) else {
            return false;
        };

        let mut preflight = Vec::new();
        append_backspaces(&mut preflight, erase_len);
        if !append_text_for_layout(&mut preflight, &corrected, target_hkl)
            || !append_optional_delimiter(&mut preflight, delimiter, target_hkl)
        {
            return false;
        }

        let delimiter_text = delimiter.map(Delimiter::text).unwrap_or_default();
        let original_text = format!("{original}{delimiter_text}");
        let replacement_text = format!("{corrected}{delimiter_text}");
        self.pending_correction = Some(PendingCorrection {
            focus: source.hwnd as isize,
            thread_id: source.thread_id,
            process_id: source.process_id,
            generation,
            source_hkl: source.hkl,
            source_language: source.language,
            target_hkl,
            original_text,
            corrected,
            replacement_text,
            erase_len,
            original_strokes,
            delimiter,
            held_modifiers,
        });

        if !post_runtime(WM_RUNTIME_CORRECTION, 0, 0) {
            self.pending_correction = None;
            return false;
        }

        self.reset_candidate();
        true
    }

    fn execute_pending_correction(&mut self) {
        let Some(pending) = self.pending_correction.take() else {
            return;
        };
        if settings::paused() || current_generation() != pending.generation {
            return;
        }
        let hwnd = pending.focus as HWND;
        let Some(now) = focused_target() else {
            return;
        };
        if now.hwnd as isize != pending.focus
            || now.process_id != pending.process_id
            || now.thread_id != pending.thread_id
            || now.hkl != pending.source_hkl
        {
            return;
        }
        self.refresh_process_name(now.process_id);
        if secure_input::is_secure_input(hwnd, &self.process_name) {
            return;
        }

        if selection::is_standard_edit(hwnd) {
            if !wait_for_edit_suffix(hwnd, &pending.original_text, pending.generation) {
                return;
            }
            if !switch_layout(hwnd, pending.thread_id, pending.target_hkl) {
                return;
            }
            if current_generation() != pending.generation
                || !selection::replace_suffix_at_caret(
                    hwnd,
                    &pending.original_text,
                    &pending.replacement_text,
                )
            {
                let _ = switch_layout(hwnd, pending.thread_id, pending.source_hkl);
                return;
            }
        } else {
            if !switch_layout(hwnd, pending.thread_id, pending.target_hkl) {
                return;
            }
            let active_modifiers = Modifiers {
                ctrl: pending.held_modifiers.ctrl && is_control_down(),
                shift: pending.held_modifiers.shift && is_shift_down(),
                alt: pending.held_modifiers.alt && is_alt_down(),
            };
            let mut inputs = Vec::new();
            append_modifier_releases(&mut inputs, active_modifiers);
            append_backspaces(&mut inputs, pending.erase_len);
            if !append_text_for_layout(&mut inputs, &pending.corrected, pending.target_hkl)
                || !append_optional_delimiter(&mut inputs, pending.delimiter, pending.target_hkl)
            {
                let _ = switch_layout(hwnd, pending.thread_id, pending.source_hkl);
                return;
            }
            append_modifier_presses(&mut inputs, active_modifiers);
            if !send_inputs_in_layout(&inputs, pending.target_hkl) {
                let _ = switch_layout(hwnd, pending.thread_id, pending.source_hkl);
                self.reset_transient();
                return;
            }
        }

        self.undo = Some(RuntimeUndo {
            focus: pending.focus,
            process_id: pending.process_id,
            generation: pending.generation,
            source_hkl: pending.source_hkl,
            source_language: pending.source_language,
            target_hkl: pending.target_hkl,
            original_text: pending.original_text,
            corrected_text: pending.replacement_text,
            original_strokes: pending.original_strokes,
            corrected_len: pending.corrected.chars().count(),
            delimiter: pending.delimiter,
        });
        self.selection_undo = None;

        if pending.delimiter.is_some() {
            self.push_context(pending.corrected.clone());
        }
        tray_status::note_correction(opposite_language(pending.source_language));
        sound::play_correction(&settings::runtime_settings());
    }

    fn try_undo(
        &mut self,
        target: FocusTarget,
        modifiers: Modifiers,
        generation: u32,
    ) -> bool {
        if let Some(undo) = self.selection_undo.take() {
            if undo.focus != target.hwnd as isize
                || undo.process_id != target.process_id
                || undo.generation != generation
                || current_generation() != generation
                || secure_input::is_secure_input(target.hwnd, &self.process_name)
            {
                return false;
            }
            if !switch_layout(target.hwnd, target.thread_id, undo.source_hkl) {
                return false;
            }
            if selection::replace_suffix_at_caret(target.hwnd, &undo.corrected, &undo.original) {
                self.context_tokens.clear();
                self.previous = None;
                tray_status::note_undo(undo.source_language);
                return true;
            }
            let _ = switch_layout(target.hwnd, target.thread_id, undo.target_hkl);
            return false;
        }

        let Some(undo) = self.undo.take() else {
            return false;
        };
        if undo.focus != target.hwnd as isize
            || undo.process_id != target.process_id
            || undo.generation != generation
            || current_generation() != generation
        {
            return false;
        }
        if !switch_layout(target.hwnd, target.thread_id, undo.source_hkl) {
            return false;
        }

        if selection::is_standard_edit(target.hwnd) {
            if selection::replace_suffix_at_caret(
                target.hwnd,
                &undo.corrected_text,
                &undo.original_text,
            ) {
                self.candidate_focus = target.hwnd as isize;
                self.previous = None;
                self.context_tokens.clear();
                tray_status::note_undo(undo.source_language);
                return true;
            }
            let _ = switch_layout(target.hwnd, target.thread_id, undo.target_hkl);
            return false;
        }

        let mut inputs = Vec::new();
        append_modifier_releases(&mut inputs, modifiers);
        append_backspaces(
            &mut inputs,
            undo.corrected_len + usize::from(undo.delimiter.is_some()),
        );
        for stroke in &undo.original_strokes {
            append_stroke(&mut inputs, *stroke);
        }
        if !append_optional_delimiter(&mut inputs, undo.delimiter, undo.source_hkl) {
            return false;
        }
        append_modifier_presses(&mut inputs, modifiers);

        let result = send_inputs_in_layout(&inputs, undo.source_hkl);
        if result {
            self.candidate_focus = target.hwnd as isize;
            self.previous = None;
            self.context_tokens.clear();
            tray_status::note_undo(undo.source_language);
        }
        result
    }

    fn reset_candidate(&mut self) {
        self.candidate.clear();
        self.strokes.clear();
        self.candidate_focus = 0;
    }

    fn reset_transient(&mut self) {
        self.reset_candidate();
        self.previous = None;
        self.context_tokens.clear();
        self.undo = None;
        self.selection_undo = None;
        self.pending_correction = None;
        self.pending_selection = None;
    }
}

fn current_generation() -> u32 {
    CONTEXT_GENERATION.load(Ordering::SeqCst)
}

fn wait_for_edit_suffix(hwnd: HWND, expected: &str, generation: u32) -> bool {
    for _ in 0..50 {
        if current_generation() != generation || focused_hwnd_fast() != hwnd {
            return false;
        }
        if selection::suffix_matches_at_caret(hwnd, expected) {
            return true;
        }
        unsafe { Sleep(1) };
    }
    false
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
        let mut process_id = 0u32;
        let thread_id = GetWindowThreadProcessId(hwnd, &mut process_id);
        if thread_id == 0 || process_id == 0 {
            return None;
        }
        let hkl = GetKeyboardLayout(thread_id) as isize;
        let language = language_from_hkl(hkl)?;
        Some(FocusTarget {
            hwnd,
            thread_id,
            process_id,
            hkl,
            language,
        })
    }
}

fn process_name_for_pid(process_id: u32) -> Option<String> {
    unsafe {
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, process_id);
        if process.is_null() {
            return None;
        }
        let mut buffer = vec![0u16; 32_768];
        let mut length = buffer.len() as u32;
        let result = QueryFullProcessImageNameW(process, 0, buffer.as_mut_ptr(), &mut length);
        CloseHandle(process);
        if result == 0 || length == 0 {
            return None;
        }
        let path = String::from_utf16_lossy(&buffer[..length as usize]);
        path.rsplit(['\\', '/'])
            .next()
            .filter(|name| !name.is_empty())
            .map(|name| name.to_ascii_lowercase())
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

fn opposite_language(language: Language) -> Language {
    match language {
        Language::Russian => Language::English,
        Language::English => Language::Russian,
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

fn visible_char(vk: u16, language: Language, shifted: bool, caps: bool) -> Option<char> {
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

    if (b'0' as u16..=b'9' as u16).contains(&vk) {
        let index = (vk - b'0' as u16) as usize;
        if !shifted {
            return char::from_digit(index as u32, 10);
        }
        let symbols = match language {
            Language::English => ")!@#$%^&*(",
            Language::Russian => ")!\"№;%:?*(",
        };
        return symbols.chars().nth(index);
    }

    match (language, vk, shifted) {
        (_, VK_OEM_MINUS, false) => Some('-'),
        (_, VK_OEM_MINUS, true) => Some('_'),
        (_, VK_OEM_PLUS, false) => Some('='),
        (_, VK_OEM_PLUS, true) => Some('+'),
        (Language::English, VK_OEM_5, false) => Some('\\'),
        (Language::English, VK_OEM_5, true) => Some('|'),
        (Language::Russian, VK_OEM_5, false) => Some('\\'),
        (Language::Russian, VK_OEM_5, true) => Some('/'),
        (Language::English, VK_OEM_3, false) => Some('`'),
        (Language::English, VK_OEM_3, true) => Some('~'),
        (Language::English, VK_OEM_4, false) => Some('['),
        (Language::English, VK_OEM_4, true) => Some('{'),
        (Language::English, VK_OEM_6, false) => Some(']'),
        (Language::English, VK_OEM_6, true) => Some('}'),
        (Language::English, VK_OEM_1, false) => Some(';'),
        (Language::English, VK_OEM_1, true) => Some(':'),
        (Language::English, VK_OEM_7, false) => Some('\''),
        (Language::English, VK_OEM_7, true) => Some('"'),
        (Language::English, VK_OEM_COMMA, false) => Some(','),
        (Language::English, VK_OEM_COMMA, true) => Some('<'),
        (Language::English, VK_OEM_PERIOD, false) => Some('.'),
        (Language::English, VK_OEM_PERIOD, true) => Some('>'),
        (Language::English, VK_OEM_2, false) => Some('/'),
        (Language::English, VK_OEM_2, true) => Some('?'),
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
        0x10 | 0x11 | 0x12 | 0x14 | 0xA0 | 0xA1 | 0xA2 | 0xA3 | 0xA4 | 0xA5
    )
}

fn is_shift_down() -> bool {
    unsafe { GetAsyncKeyState(VK_SHIFT as i32) < 0 }
}

fn is_control_down() -> bool {
    unsafe { GetAsyncKeyState(VK_CONTROL as i32) < 0 }
}

fn is_alt_down() -> bool {
    unsafe { GetAsyncKeyState(VK_MENU as i32) < 0 }
}

fn append_modifier_releases(inputs: &mut Vec<INPUT>, modifiers: Modifiers) {
    if modifiers.ctrl {
        inputs.push(key_input(VK_CONTROL, KEYEVENTF_KEYUP));
    }
    if modifiers.shift {
        inputs.push(key_input(VK_SHIFT, KEYEVENTF_KEYUP));
    }
    if modifiers.alt {
        inputs.push(key_input(VK_MENU, KEYEVENTF_KEYUP));
    }
}

fn append_modifier_presses(inputs: &mut Vec<INPUT>, modifiers: Modifiers) {
    if modifiers.alt {
        inputs.push(key_input(VK_MENU, 0));
    }
    if modifiers.shift {
        inputs.push(key_input(VK_SHIFT, 0));
    }
    if modifiers.ctrl {
        inputs.push(key_input(VK_CONTROL, 0));
    }
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

fn append_text_for_layout(inputs: &mut Vec<INPUT>, text: &str, hkl: isize) -> bool {
    for ch in text.chars() {
        let encoded = unsafe { VkKeyScanExW(ch as u16, hkl as *mut core::ffi::c_void) };
        if encoded == -1 {
            return false;
        }
        let encoded = encoded as u16;
        let vk = encoded & 0xff;
        let modifiers = (encoded >> 8) & 0xff;
        if modifiers & !1 != 0 {
            return false;
        }
        append_stroke(
            inputs,
            Stroke {
                vk,
                shift: modifiers & 1 != 0,
            },
        );
    }
    true
}

fn append_optional_delimiter(
    inputs: &mut Vec<INPUT>,
    delimiter: Option<Delimiter>,
    hkl: isize,
) -> bool {
    delimiter
        .map(|delimiter| append_delimiter(inputs, delimiter, hkl))
        .unwrap_or(true)
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

    if let Some(scan) = physical_oem_scan_code(stroke.vk) {
        inputs.push(scan_input(scan, 0));
        inputs.push(scan_input(scan, KEYEVENTF_KEYUP));
    } else {
        inputs.push(key_input(stroke.vk, 0));
        inputs.push(key_input(stroke.vk, KEYEVENTF_KEYUP));
    }

    if stroke.shift {
        inputs.push(key_input(VK_SHIFT, KEYEVENTF_KEYUP));
    }
}

fn physical_oem_scan_code(vk: u16) -> Option<u16> {
    match vk {
        VK_OEM_4 => Some(0x1A),
        VK_OEM_6 => Some(0x1B),
        VK_OEM_1 => Some(0x27),
        VK_OEM_7 => Some(0x28),
        VK_OEM_3 => Some(0x29),
        VK_OEM_COMMA => Some(0x33),
        VK_OEM_PERIOD => Some(0x34),
        VK_OEM_2 => Some(0x35),
        _ => None,
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

fn scan_input(scan: u16, flags: u32) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: 0,
                wScan: scan,
                dwFlags: flags | KEYEVENTF_SCANCODE,
                time: 0,
                dwExtraInfo: MAGIC_EXTRA_INFO,
            },
        },
    }
}

fn send_inputs_in_layout(inputs: &[INPUT], hkl: isize) -> bool {
    unsafe {
        if ActivateKeyboardLayout(hkl as *mut core::ffi::c_void, 0).is_null() {
            return false;
        }
    }
    send_inputs(inputs)
}

const SEND_INPUT_STALL_RETRY_LIMIT: usize = 32;

fn send_inputs(inputs: &[INPUT]) -> bool {
    deliver_inputs_with_retry(inputs.len(), |offset, remaining| unsafe {
        SendInput(
            remaining as u32,
            inputs[offset..].as_ptr(),
            size_of::<INPUT>() as i32,
        ) as usize
    })
}

fn deliver_inputs_with_retry(total: usize, mut send: impl FnMut(usize, usize) -> usize) -> bool {
    if total == 0 {
        return true;
    }

    let mut offset = 0usize;
    let mut stalled = 0usize;
    while offset < total {
        let remaining = total - offset;
        let sent = send(offset, remaining).min(remaining);
        if sent == 0 {
            if offset == 0 {
                return false;
            }
            stalled += 1;
            if stalled >= SEND_INPUT_STALL_RETRY_LIMIT {
                return false;
            }
            unsafe { Sleep(1) };
            continue;
        }

        offset += sent;
        stalled = 0;
    }
    true
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
#[path = "windows_runtime/e2e_tests.rs"]
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
    fn hook_event_roundtrip_preserves_generation_and_decision() {
        let modifiers = Modifiers {
            ctrl: true,
            shift: false,
            alt: true,
        };
        let packed = encode_hook_event(b'Q' as u16, modifiers, true, 0x1234_5678, true);
        let event = decode_hook_event(packed, 42);
        assert_eq!(event.vk, b'Q' as u16);
        assert!(event.modifiers.ctrl);
        assert!(!event.modifiers.shift);
        assert!(event.modifiers.alt);
        assert!(event.caps);
        assert!(event.suppressed);
        assert_eq!(event.focus, 42);
        assert_eq!(event.generation, 0x1234_5678);
    }

    #[test]
    fn navigation_invalidates_context() {
        assert!(invalidates_context(VK_LEFT, Modifiers::default()));
        assert!(invalidates_context(VK_HOME, Modifiers::default()));
        assert!(!invalidates_context(b'A' as u16, Modifiers::default()));
    }

    #[test]
    fn code_safe_characters_are_kept_in_one_runtime_candidate() {
        let mut candidate = String::new();
        for ch in "user_ghbdtn".chars() {
            candidate.push(ch);
        }
        assert!(is_code_safe_token(&candidate));
        assert!(is_code_safe_token("HOST-ghbdtn-01"));
        assert!(is_code_safe_token("user@ghbdtn.test"));
        assert!(is_code_safe_token("C:\\ghbdtn\\file"));
        assert!(is_code_safe_token("--ghbdtn"));
        assert!(!is_code_safe_token("ghbdtn"));
    }

    #[test]
    fn visible_char_includes_technical_sequence_keys() {
        assert_eq!(visible_char(b'1' as u16, Language::English, false, false), Some('1'));
        assert_eq!(visible_char(b'2' as u16, Language::English, true, false), Some('@'));
        assert_eq!(visible_char(VK_OEM_MINUS, Language::English, true, false), Some('_'));
        assert_eq!(visible_char(VK_OEM_5, Language::English, false, false), Some('\\'));
        assert_eq!(visible_char(VK_OEM_1, Language::English, true, false), Some(':'));
    }

    #[test]
    fn partial_sendinput_delivery_resumes_from_unsent_tail() {
        let mut calls = Vec::new();
        let mut attempt = 0usize;
        let delivered = deliver_inputs_with_retry(10, |offset, remaining| {
            calls.push((offset, remaining));
            attempt += 1;
            match attempt {
                1 => 4,
                2 => 0,
                _ => remaining,
            }
        });
        assert!(delivered);
        assert_eq!(calls, vec![(0, 10), (4, 6), (4, 6)]);
    }

    #[test]
    fn zero_progress_sendinput_fails_without_deleting_any_tail() {
        let mut calls = 0usize;
        let delivered = deliver_inputs_with_retry(10, |offset, remaining| {
            calls += 1;
            assert_eq!((offset, remaining), (0, 10));
            0
        });
        assert!(!delivered);
        assert_eq!(calls, 1);
    }
}
