//! Word NativeOM adapter. Native interfaces never leave the one-operation STA.
//! UIA metadata is isolated on a bounded, windowless MTA reader.
//! A synchronous join deliberately has no mutation timeout: returning while a
//! Word call can still write would permit a second correction against unknown
//! state. Any uncertain mutation disables this adapter until process restart.

#[path = "word_native_plan.rs"]
mod plan;

#[path = "word_auto_correct.rs"]
mod auto_correct;

#[path = "word_call_gate.rs"]
mod call_gate;

use std::cell::RefCell;
use std::collections::HashMap;
use std::mem::zeroed;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, Once};
use std::time::{Duration, Instant};
use windows::core::{IUnknown, Interface, BSTR, GUID, PCWSTR};
use windows::Win32::System::Com::{
    CoInitializeEx, CoUninitialize, IDispatch, COINIT_APARTMENTTHREADED, DISPATCH_FLAGS,
    DISPATCH_METHOD, DISPATCH_PROPERTYGET, DISPATCH_PROPERTYPUT, DISPPARAMS,
};
use windows::Win32::System::Variant::VARIANT;
use windows::Win32::UI::Accessibility::AccessibleObjectFromWindow;
use windows_sys::Win32::Foundation::{CloseHandle, HWND};
use windows_sys::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetClassNameW, GetWindowThreadProcessId, PeekMessageW, TranslateMessage, MSG,
    PM_REMOVE,
};
#[path = "word_focus.rs"]
mod word_focus;
use word_focus::{focused, Focus};

const OBJID_NATIVEOM: u32 = 0xffff_fff0;
const LOCALE_USER_DEFAULT: u32 = 0x0400;
const DISPID_PROPERTYPUT: i32 = -3;
const VT_DISPATCH: u16 = 9;
static SERIAL: Mutex<()> = Mutex::new(());
static UNCERTAIN_MUTATION: AtomicBool = AtomicBool::new(false);
// Stage-only diagnostics contain no text, document names, paths or values.
// They identify the last external boundary if real Word remains unresponsive.
fn trace(stage: &str) {
    use std::io::Write;
    let path = std::env::temp_dir().join("GSwitcher-Word-Runtime.log");
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        if file
            .metadata()
            .map(|metadata| metadata.len() > 1_048_576)
            .unwrap_or(false)
        {
            let _ = file.set_len(0);
        }
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let _ = writeln!(file, "{now} pid={} stage={stage}", std::process::id());
    }
}

// Plain diagnostic state only. This observer owns no COM interfaces and
// cannot cancel calls, clear the mutation latch or authorize another writer.
static DIAGNOSTICS: Once = Once::new();
static ACTIVE_CALL: Mutex<Option<ActiveCall>> = Mutex::new(None);
struct ActiveCall {
    name: String,
    kind: &'static str,
    phase: &'static str,
    started: Instant,
}
struct NativeCallTrace;
impl NativeCallTrace {
    fn start(name: &str, kind: &'static str) -> Self {
        DIAGNOSTICS.call_once(|| {
            trace("word-diagnostics-v1");
            let _ = std::thread::Builder::new()
                .name("g-switcher-word-diagnostic".into())
                .spawn(|| {
                    let mut last_report = None;
                    loop {
                        std::thread::sleep(Duration::from_secs(1));
                        let now = Instant::now();
                        let pending = ACTIVE_CALL.try_lock().ok().and_then(|state| {
                            state
                                .as_ref()
                                .filter(|call| {
                                    now.duration_since(call.started) >= Duration::from_secs(1)
                                        && last_report.is_none_or(|last: Instant| {
                                            now.duration_since(last) >= Duration::from_secs(5)
                                        })
                                })
                                .map(|call| {
                                    format!(
                                        "native-pending-{}-{}-{}",
                                        call.kind, call.name, call.phase
                                    )
                                })
                        });
                        if let Some(stage) = pending {
                            last_report = Some(now);
                            trace(&stage);
                        }
                    }
                });
        });
        if let Ok(mut state) = ACTIVE_CALL.lock() {
            *state = Some(ActiveCall {
                name: name.into(),
                kind,
                phase: "pump",
                started: Instant::now(),
            });
        }
        Self
    }
    fn phase(&self, phase: &'static str) {
        if let Ok(mut state) = ACTIVE_CALL.lock() {
            if let Some(call) = state.as_mut() {
                call.phase = phase;
            }
        }
    }
}
impl Drop for NativeCallTrace {
    fn drop(&mut self) {
        if let Ok(mut state) = ACTIVE_CALL.lock() {
            *state = None;
        }
    }
}
fn checked<T>(stage: &str, value: Option<T>) -> Option<T> {
    if value.is_none() {
        trace(stage);
    }
    value
}
struct CachedDispatch {
    object: IDispatch,
    ids: HashMap<String, i32>,
}
thread_local! {
    // Retaining the exact dispatch object prevents address reuse while an ID
    // is cached. Clear on this STA before CoUninitialize, including unwinding.
    static DISPATCH_IDS: RefCell<Vec<CachedDispatch>> = const { RefCell::new(Vec::new()) };
}

#[derive(Debug)]
pub struct SelectedText {
    pub start: u32,
    pub end: u32,
    pub text: String,
}
#[derive(Debug)]
pub struct EditSnapshot {
    pub caret: u32,
    pub text_before_caret: String,
}

/// Cheap identity classification only; NativeOM availability is separate.
pub fn is_word_window(hwnd: HWND) -> bool {
    unsafe {
        let mut class = [0u16; 256];
        let length = GetClassNameW(hwnd, class.as_mut_ptr(), class.len() as i32);
        if length <= 0 || String::from_utf16_lossy(&class[..length as usize]) != "_WwG" {
            return false;
        }
        let mut pid = 0;
        if GetWindowThreadProcessId(hwnd, &mut pid) == 0 || pid == 0 {
            return false;
        }
        let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if process.is_null() {
            return false;
        }
        let mut path = [0u16; 32768];
        let mut size = path.len() as u32;
        let ok = QueryFullProcessImageNameW(process, 0, path.as_mut_ptr(), &mut size);
        CloseHandle(process);
        ok != 0 && plan::is_word_target("_WwG", &String::from_utf16_lossy(&path[..size as usize]))
    }
}

pub fn has_adapter(hwnd: HWND) -> bool {
    run(hwnd, |context| {
        let (_, document_start, document_end, document) = context.content()?;
        let (_, start, end) = context.selection()?;
        if !plan::available_selection(&document, document_start, document_end, start, end) {
            return None;
        }
        context.stable()?;
        Some(true)
    })
    .unwrap_or(false)
}

pub fn normalize_newlines(value: &str) -> String {
    plan::normalize_newlines(value)
}

fn run<R: Send + 'static>(
    hwnd: HWND,
    operation: impl FnOnce(&Context) -> Option<R> + Send + 'static,
) -> Option<R> {
    run_at_generation(hwnd, super::runtime_generation()?, operation)
}

fn run_at_generation<R: Send + 'static>(
    hwnd: HWND,
    generation: u32,
    operation: impl FnOnce(&Context) -> Option<R> + Send + 'static,
) -> Option<R> {
    if !super::broker_role() {
        return None;
    }
    if UNCERTAIN_MUTATION.load(Ordering::Acquire) {
        trace("refuse-uncertain-mutation");
        return None;
    }
    if !is_word_window(hwnd) {
        return None;
    }
    let _serial = SERIAL.lock().ok()?;
    if UNCERTAIN_MUTATION.load(Ordering::Acquire) {
        trace("refuse-uncertain-mutation");
        return None;
    }
    let inherited = super::word_admission::current();
    let parent = match inherited.as_ref() {
        Some(p) => p.clone(),
        None => super::word_admission::begin(hwnd as isize)?,
    };
    if !parent.matches(hwnd as isize) {
        parent.quarantine();
        return None;
    }
    let worker_parent = parent.clone();
    let handle = hwnd as isize;
    // The thread owns every interface, VARIANT and BSTR. COM pumps incoming
    // apartment messages during outgoing calls; drain queued messages between
    // calls. There is no persistent STA blocked on a non-pumping receiver.
    let worker = std::thread::Builder::new()
        .name("g-switcher-word-sta".into())
        .spawn(move || {
            super::word_admission::with_parent(worker_parent, || {
                unsafe {
                    CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok().ok()?;
                }
                struct Apartment;
                impl Drop for Apartment {
                    fn drop(&mut self) {
                        let diagnostic = NativeCallTrace::start("CoUninitialize", "release");
                        diagnostic.phase("release");
                        unsafe {
                            CoUninitialize();
                        }
                    }
                }
                let _apartment = Apartment;
                struct DispatchCache;
                impl Drop for DispatchCache {
                    fn drop(&mut self) {
                        let diagnostic = NativeCallTrace::start("DispatchCache", "release");
                        diagnostic.phase("release");
                        DISPATCH_IDS.with(|cache| cache.borrow_mut().clear());
                    }
                }
                let _cache = DispatchCache;
                pump();
                trace("context-open");
                let context = Context::open(handle as HWND, generation)?;
                trace("context-ready");
                let result = operation(&context);
                trace(if result.is_some() {
                    "operation-complete"
                } else {
                    "operation-refused"
                });
                {
                    let diagnostic = NativeCallTrace::start("Context", "release");
                    diagnostic.phase("release");
                    drop(context);
                }
                {
                    let diagnostic = NativeCallTrace::start("STA", "pump");
                    diagnostic.phase("pump");
                    pump();
                }
                result
            })
        })
        .ok()?;
    // Keep synchronous ownership of the one native writer. Pump only sent
    // messages so cross-process accessibility callbacks cannot block on our UI.
    // Posted runtime events remain queued, preventing Engine-lock reentrancy.
    while !worker.is_finished() {
        super::read_worker::pump_sent_messages();
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
    let result = worker.join().ok()?;
    if inherited.is_none() && !parent.complete(UNCERTAIN_MUTATION.load(Ordering::Acquire)) {
        return None;
    }
    result
}

pub fn read_selected_text(hwnd: HWND) -> Option<SelectedText> {
    run(hwnd, |context| {
        let (content, document_start, document_end, text) = context.content()?;
        let (_, start, end) = context.selection()?;
        let (end, text) = plan::selection_text(&text, document_start, document_end, start, end)?;
        let range = duplicate_range(&content, start, end)?;
        if get_text(&range)? != text {
            return None;
        }
        context.stable()?;
        let (_, current_start, current_end) = context.selection()?;
        if current_start != start || (current_end != end && current_end != document_end) {
            return None;
        }
        Some(SelectedText { start, end, text })
    })
}

pub fn prepare_correction_suffix(
    hwnd: HWND,
    expected: &str,
    replacement: &str,
) -> Option<(String, String)> {
    let expected = plan::normalize_newlines(expected);
    let replacement = plan::normalize_newlines(replacement);
    auto_correct::prepare_once(
        || snapshot_caret(hwnd).map(|snapshot| snapshot.text_before_caret),
        &expected,
        &replacement,
    )
}

pub fn snapshot_caret(hwnd: HWND) -> Option<EditSnapshot> {
    run(hwnd, |context| {
        let (content, start, end, text) = context.content()?;
        let (_, caret, selected_end) = context.selection()?;
        if caret != selected_end || caret >= end {
            return None;
        }
        // Use native range endpoints, and prove their mapping to UTF16 before
        // exposing offsets through the existing selection interface.
        let _ = plan::selection_text(&text, start, end, 0, end)?;
        let prefix = duplicate_range(&content, 0, caret)?;
        let text_before_caret = get_text(&prefix)?;
        if text_before_caret.encode_utf16().count() != caret as usize {
            return None;
        }
        context.stable()?;
        let (_, current_start, current_end) = context.selection()?;
        if (current_start, current_end) != (caret, caret) {
            return None;
        }
        Some(EditSnapshot {
            caret,
            text_before_caret,
        })
    })
}

#[cfg(test)]
pub fn read_document_text(hwnd: HWND) -> Option<String> {
    run(hwnd, |context| {
        context.stable()?;
        Some(context.content()?.3)
    })
}

pub fn replace_suffix_if_matches(
    hwnd: HWND,
    expected: &str,
    replacement: &str,
    generation: u32,
) -> bool {
    let expected = plan::normalize_newlines(expected);
    let replacement = plan::normalize_newlines(replacement);
    run_at_generation(hwnd, generation, move |context| {
        let (_, caret, selected_end) = context.selection()?;
        if caret != selected_end {
            return None;
        }
        let units = u32::try_from(expected.encode_utf16().count()).ok()?;
        let start = caret.checked_sub(units)?;
        context.replace(start, caret, &expected, &replacement)
    })
    .unwrap_or(false)
}

pub fn replace_range_if_matches(
    hwnd: HWND,
    start: u32,
    end: u32,
    expected: &str,
    replacement: &str,
    generation: u32,
) -> bool {
    let expected = plan::normalize_newlines(expected);
    let replacement = plan::normalize_newlines(replacement);
    run_at_generation(hwnd, generation, move |context| {
        context.replace(start, end, &expected, &replacement)
    })
    .unwrap_or(false)
}

struct Context {
    hwnd: HWND,
    focus: Focus,
    window: IDispatch,
    document: IDispatch,
    document_identity: IUnknown,
    generation: u32,
}

impl Context {
    fn open(hwnd: HWND, generation: u32) -> Option<Self> {
        trace("fresh-uia-focus");
        let focus = focused(hwnd)?;
        trace("native-window-acquire");
        let window = native_window(hwnd)?;
        if get_i32(&window, "Hwnd")? as isize != focus.root {
            return None;
        }
        let selection = get_dispatch(&window, "Selection")?;
        let document = get_dispatch(&get_dispatch(&selection, "Range")?, "Document")?;
        let document_identity = document.cast::<IUnknown>().ok()?;
        let context = Self {
            hwnd,
            focus,
            window,
            document,
            document_identity,
            generation,
        };
        context.stable()?;
        Some(context)
    }

    fn stable(&self) -> Option<()> {
        self.bound()?;
        let window = native_window(self.hwnd)?;
        if get_i32(&window, "Hwnd")? as isize != self.focus.root {
            return None;
        }
        // Initial scope refuses structural containers anywhere in the document.
        // This also refuses a range inside a field/control whose local Count
        // can be zero, without relying on ambiguous provider boundary queries.
        for collection in ["Fields", "Tables", "ContentControls", "Revisions"] {
            if get_i32(&get_dispatch(&self.document, collection)?, "Count")? != 0 {
                trace(&format!("binding-structural-{collection}-refused"));
                return None;
            }
        }
        if focused(self.hwnd)? != self.focus {
            trace("binding-focus-changed");
            return None;
        }
        Some(())
    }

    fn bound(&self) -> Option<(IDispatch, u32, u32)> {
        if super::runtime_generation() != Some(self.generation) {
            trace("binding-generation-changed");
            return None;
        }
        if focused(self.hwnd)? != self.focus {
            trace("binding-focus-changed");
            return None;
        }
        let selection = self.selection()?;
        if get_bool(&self.document, "ReadOnly")?
            || get_i32(&self.document, "ProtectionType")? != -1
            || get_bool(&self.document, "TrackRevisions")?
            || ![1, 2].contains(&get_i32(&selection.0, "Type")?)
        {
            trace("binding-protection-or-selection-refused");
            return None;
        }
        if focused(self.hwnd)? != self.focus {
            trace("binding-focus-changed");
            return None;
        }
        if super::runtime_generation() != Some(self.generation) {
            trace("binding-generation-changed");
            return None;
        }
        Some(selection)
    }

    fn content(&self) -> Option<(IDispatch, u32, u32, String)> {
        let content = get_dispatch(&self.document, "Content")?;
        if get_i32(&content, "StoryType")? != 1 {
            return None;
        }
        let start = u32::try_from(get_i32(&content, "Start")?).ok()?;
        let end = u32::try_from(get_i32(&content, "End")?).ok()?;
        if end as usize > plan::MAX_DOCUMENT_UNITS {
            return None;
        }
        let text = get_text(&content)?;
        if start != 0 || text.encode_utf16().count() != end as usize {
            return None;
        }
        Some((content, start, end, text))
    }

    fn selection(&self) -> Option<(IDispatch, u32, u32)> {
        let selection = get_dispatch(&self.window, "Selection")?;
        let range = get_dispatch(&selection, "Range")?;
        if get_i32(&range, "StoryType")? != 1
            || get_dispatch(&range, "Document")?
                .cast::<IUnknown>()
                .ok()?
                .as_raw()
                != self.document_identity.as_raw()
        {
            trace("selection-story-or-document-mismatch");
            return None;
        }
        let start = u32::try_from(get_i32(&range, "Start")?).ok()?;
        let end = u32::try_from(get_i32(&range, "End")?).ok()?;
        Some((selection, start, end))
    }

    fn replace(&self, start: u32, end: u32, expected: &str, replacement: &str) -> Option<bool> {
        checked("replace-runtime-policy-refused", self.mutation_allowed())?;
        checked("replace-stability-refused", self.stable())?;
        let (content, document_start, document_end, before) =
            checked("replace-content-read-failed", self.content())?;
        let plan = plan::Plan::new(
            &before,
            document_start,
            document_end,
            start,
            end,
            expected,
            replacement,
        )?;
        let (start, end) = (plan.start, plan.end);
        let (_, selected_start, selected_end) =
            checked("replace-selection-read-failed", self.selection())?;
        if !plan::selection_matches(selected_start, selected_end, start, end, document_end) {
            trace("replace-initial-selection-mismatch");
            return None;
        }
        let range = duplicate_range(&content, start, end)?;
        if checked("replace-range-read-failed", get_text(&range))? != expected {
            trace("replace-initial-range-mismatch");
            return None;
        }
        let application = get_dispatch(&self.window, "Application")?;
        let undo = get_dispatch(&application, "UndoRecord")?;
        if get_bool(&undo, "IsRecordingCustomRecord")? {
            trace("replace-foreign-undo-record");
            return None;
        }
        checked("replace-stability-refused", self.stable())?;
        let (_, current_start, current_end) =
            checked("replace-selection-read-failed", self.selection())?;
        if checked("replace-content-read-failed", self.content())?.3 != before
            || (current_start, current_end) != (selected_start, selected_end)
        {
            trace("replace-pre-write-state-changed");
            return None;
        }
        checked("replace-runtime-policy-refused", self.mutation_allowed())?;

        // Set the latch before submitting a COM operation with side effects.
        // A failed HRESULT or panic cannot prove that Word made no change.
        UNCERTAIN_MUTATION.store(true, Ordering::Release);
        call(
            &undo,
            "StartCustomRecord",
            vec![VARIANT::from("G-switcher correction")],
        )?;
        trace("custom-undo-started");
        let mut record = UndoRecord {
            dispatch: undo,
            active: true,
        };
        let result = (|| {
            let one = duplicate_range(&content, start, start.checked_add(1)?)?;
            for (offset, character) in plan.replacement.iter().enumerate() {
                checked("replace-runtime-policy-refused", self.mutation_allowed())?;
                let (_, current_start, current_end) =
                    checked("replace-binding-refused", self.bound())?;
                if checked("replace-range-read-failed", get_text(&range))?
                    != plan.range_progress(offset)
                {
                    trace("replace-evolving-range-mismatch");
                    return None;
                }
                if (current_start, current_end) != (selected_start, selected_end) {
                    trace("replace-selection-moved");
                    return None;
                }
                let position = start.checked_add(offset as u32)?;
                set_range(&one, position, position.checked_add(1)?)?;
                let previous = plan.original[offset].to_string();
                if previous == character.to_string() {
                    continue;
                }
                if checked("replace-focus-read-failed", focused(self.hwnd))? != self.focus {
                    trace("replace-focus-changed");
                    return None;
                }
                checked("replace-runtime-policy-refused", self.mutation_allowed())?;
                // Independent one-character range; never writes Font, global
                // flags, Selection.Text, a full document, or the clipboard.
                trace("character-write");
                checked(
                    "replace-character-put-failed",
                    put(&one, "Text", VARIANT::from(character.to_string().as_str())),
                )?;
                // The next iteration verifies the entire evolving range;
                // the last character is verified by the final full-state check.
            }
            checked("replace-stability-refused", self.stable())?;
            if checked("replace-content-read-failed", self.content())?.3 != plan.after
                || checked("replace-range-read-failed", get_text(&range))? != replacement
            {
                trace("replace-after-write-text-mismatch");
                return None;
            }
            let (selection, current_start, current_end) =
                checked("replace-selection-read-failed", self.selection())?;
            if (current_start, current_end) != (selected_start, selected_end) {
                trace("replace-selection-moved");
                return None;
            }
            checked("replace-runtime-policy-refused", self.mutation_allowed())?;
            call(
                &selection,
                "SetRange",
                vec![VARIANT::from(end as i32), VARIANT::from(end as i32)],
            )?;
            checked("replace-stability-refused", self.stable())?;
            let (_, caret_start, caret_end) =
                checked("replace-selection-read-failed", self.selection())?;
            if (caret_start, caret_end) != (end, end)
                || checked("replace-content-read-failed", self.content())?.3 != plan.after
            {
                trace("replace-post-caret-state-mismatch");
                return None;
            }
            Some(())
        })();
        // End only our successfully started record, including partial failure.
        // Never blindly Undo an unknown outcome or retry another writer.
        trace("custom-undo-end");
        let ended = checked("replace-undo-end-failed", record.end()).is_some();
        if result.is_none() || !ended {
            trace("replace-uncertain-latch-retained");
            return None;
        }
        checked("replace-runtime-policy-refused", self.mutation_allowed())?;
        checked("replace-stability-refused", self.stable())?;
        let (_, current_start, current_end) =
            checked("replace-selection-read-failed", self.selection())?;
        if checked("replace-content-read-failed", self.content())?.3 != plan.after
            || (current_start, current_end) != (end, end)
        {
            trace("replace-post-undo-state-mismatch");
            return None;
        }
        UNCERTAIN_MUTATION.store(false, Ordering::Release);
        Some(true)
    }

    fn mutation_allowed(&self) -> Option<()> {
        if !super::runtime_allows_mutation(self.generation) {
            trace("mutation-runtime-policy-refused");
            return None;
        }
        Some(())
    }
}

struct UndoRecord {
    dispatch: IDispatch,
    active: bool,
}
impl UndoRecord {
    fn end(&mut self) -> Option<()> {
        call_gate::finish_once(&mut self.active, || {
            invoke_undo_completion(&self.dispatch).map(|_| ())
        })
    }
}
impl Drop for UndoRecord {
    fn drop(&mut self) {
        if self.active {
            let _ = self.end();
        }
    }
}

fn duplicate_range(content: &IDispatch, start: u32, end: u32) -> Option<IDispatch> {
    let range = get_dispatch(content, "Duplicate")?;
    set_range(&range, start, end)?;
    Some(range)
}
fn set_range(range: &IDispatch, start: u32, end: u32) -> Option<()> {
    call(
        range,
        "SetRange",
        vec![VARIANT::from(start as i32), VARIANT::from(end as i32)],
    )?;
    if get_i32(range, "Start")? != start as i32
        || get_i32(range, "End")? != end as i32
        || get_i32(range, "StoryType")? != 1
    {
        trace("native-range-bounds-or-story-mismatch");
        return None;
    }
    Some(())
}

fn native_window(hwnd: HWND) -> Option<IDispatch> {
    super::word_security_stage(hwnd as isize, || ())?;
    let diagnostic = NativeCallTrace::start("AccessibleObjectFromWindow", "acquire");
    diagnostic.phase("acquire");
    let mut raw = std::ptr::null_mut();
    unsafe {
        AccessibleObjectFromWindow(
            windows::Win32::Foundation::HWND(hwnd),
            OBJID_NATIVEOM,
            &IDispatch::IID,
            &mut raw,
        )
        .ok()?;
        if raw.is_null() {
            return None;
        }
        Some(IDispatch::from_raw(raw))
    }
}

fn invoke(
    object: &IDispatch,
    name: &str,
    flags: DISPATCH_FLAGS,
    args: Vec<VARIANT>,
) -> Option<VARIANT> {
    invoke_with_gate(object, name, flags, args, call_gate::CallGate::provider())
}
// Only the retained UndoRecord::end call reaches this nonserialized obligation.
// It cannot name another member, read text, mutate a range or grant a new stage.
fn invoke_undo_completion(object: &IDispatch) -> Option<VARIANT> {
    invoke_with_gate(
        object,
        "EndCustomRecord",
        DISPATCH_METHOD,
        vec![],
        call_gate::CallGate::undo_completion(),
    )
}
fn invoke_with_gate(
    object: &IDispatch,
    name: &str,
    flags: DISPATCH_FLAGS,
    mut args: Vec<VARIANT>,
    gate: call_gate::CallGate,
) -> Option<VARIANT> {
    let kind = if flags == DISPATCH_PROPERTYGET {
        "get"
    } else if flags == DISPATCH_PROPERTYPUT {
        "put"
    } else {
        "method"
    };
    let diagnostic = NativeCallTrace::start(name, kind);
    pump();
    diagnostic.phase("lookup");
    let id = DISPATCH_IDS.with(|cache| {
        let mut cache = cache.borrow_mut();
        let index = match cache
            .iter()
            .position(|dispatch| dispatch.object.as_raw() == object.as_raw())
        {
            Some(index) => index,
            None => {
                cache.push(CachedDispatch {
                    object: object.clone(),
                    ids: HashMap::new(),
                });
                cache.len() - 1
            }
        };
        if let Some(id) = cache[index].ids.get(name) {
            return Some(*id);
        }
        if !gate.allows(super::security_authorized) {
            return None;
        }
        let wide: Vec<u16> = name.encode_utf16().chain(std::iter::once(0)).collect();
        let name_pointer = PCWSTR(wide.as_ptr());
        let mut id = 0i32;
        unsafe {
            object
                .GetIDsOfNames(
                    &GUID::zeroed(),
                    &name_pointer,
                    1,
                    LOCALE_USER_DEFAULT,
                    &mut id,
                )
                .map_err(|error| {
                    trace(&format!(
                        "native-lookup-failed-{name}-hr-{:08x}",
                        error.code().0 as u32
                    ))
                })
                .ok()?;
        }
        cache[index].ids.insert(name.to_owned(), id);
        Some(id)
    })?;
    let mut named = DISPID_PROPERTYPUT;
    args.reverse(); // COM DISPPARAMS arguments are in reverse order.
    let parameters = DISPPARAMS {
        rgvarg: args.as_mut_ptr(),
        cArgs: args.len() as u32,
        rgdispidNamedArgs: if flags == DISPATCH_PROPERTYPUT {
            &mut named
        } else {
            std::ptr::null_mut()
        },
        cNamedArgs: u32::from(flags == DISPATCH_PROPERTYPUT),
    };
    let mut result = VARIANT::default();
    diagnostic.phase("invoke");
    if !gate.allows(super::security_authorized) {
        return None;
    }
    unsafe {
        // No EXCEPINFO allocation or diagnostic text is retained/logged.
        object
            .Invoke(
                id,
                &GUID::zeroed(),
                LOCALE_USER_DEFAULT,
                flags,
                &parameters,
                Some(&mut result),
                None,
                None,
            )
            .map_err(|error| {
                trace(&format!(
                    "native-invoke-failed-{kind}-{name}-hr-{:08x}",
                    error.code().0 as u32
                ))
            })
            .ok()?;
    }
    Some(result)
}
fn get(object: &IDispatch, name: &str) -> Option<VARIANT> {
    invoke(object, name, DISPATCH_PROPERTYGET, vec![])
}
fn call(object: &IDispatch, name: &str, args: Vec<VARIANT>) -> Option<VARIANT> {
    invoke(object, name, DISPATCH_METHOD, args)
}
fn put(object: &IDispatch, name: &str, value: VARIANT) -> Option<()> {
    invoke(object, name, DISPATCH_PROPERTYPUT, vec![value]).map(|_| ())
}
fn get_i32(object: &IDispatch, name: &str) -> Option<i32> {
    let value = get(object, name)?;
    if value.vt().0 != 3 {
        trace(&format!("native-return-type-{name}-i32-mismatch"));
        return None;
    }
    i32::try_from(&value).ok()
}
fn get_bool(object: &IDispatch, name: &str) -> Option<bool> {
    let value = get(object, name)?;
    if value.vt().0 != 11 {
        trace(&format!("native-return-type-{name}-bool-mismatch"));
        return None;
    }
    bool::try_from(&value).ok()
}
fn get_text(object: &IDispatch) -> Option<String> {
    let value = get(object, "Text")?;
    if value.vt().0 != 8 {
        trace("native-return-type-Text-bstr-mismatch");
        return None;
    }
    let text = BSTR::try_from(&value).ok()?;
    if text.len() > plan::MAX_DOCUMENT_UNITS {
        return None;
    }
    String::from_utf16(&text).ok()
}
fn get_dispatch(object: &IDispatch, name: &str) -> Option<IDispatch> {
    let variant = get(object, name)?;
    unsafe {
        if variant.vt().0 != VT_DISPATCH {
            trace(&format!("native-return-type-{name}-dispatch-mismatch"));
            return None;
        }
        variant
            .Anonymous
            .Anonymous
            .Anonymous
            .pdispVal
            .as_ref()
            .cloned()
    }
}

fn pump() {
    unsafe {
        let mut message: MSG = zeroed();
        while PeekMessageW(&mut message, std::ptr::null_mut(), 0, 0, PM_REMOVE) != 0 {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
}

pub(crate) fn uncertain() -> bool {
    UNCERTAIN_MUTATION.load(Ordering::Acquire)
}
pub(crate) fn quarantine() {
    UNCERTAIN_MUTATION.store(true, Ordering::Release);
}
