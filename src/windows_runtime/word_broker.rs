//! One authenticated broker transaction; only value messages cross the process boundary.
#[path = "word_dispatch.rs"]
mod dispatch;
#[path = "word_broker_os.rs"]
mod os;
use super::settings::{AppMode, RuntimeSettings};
use crate::word_wire::u64_value;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::HWND;
const QUIET: Duration = Duration::from_millis(120);
const MAX_WORD_UNITS: usize = 32768;
// Bounded authority for starting stages, not a bound on COM calls already entered.
const SECURITY_LIFETIME: Duration = Duration::from_secs(5);
static CLIENT: OnceLock<Option<Client>> = OnceLock::new();
static NEXT: AtomicU64 = AtomicU64::new(1);
static LIVE: OnceLock<Mutex<Option<Live>>> = OnceLock::new();
struct Live {
    connection: Arc<os::Connection>,
    peer: os::Peer,
    mapping: Arc<os::Mapping>,
    request: Request,
    allowed_hkl: i64,
    deadline: Instant,
}
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
pub(super) enum Kind {
    Auto,
    Boundary,
    Manual,
    Previous,
    Selected,
    Undo,
}
#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Undo {
    pub(super) original: String,
    pub(super) corrected: String,
    pub(super) start: u32,
    pub(super) end: u32,
    pub(super) selected: bool,
    pub(super) source_hkl: i64,
    pub(super) target_hkl: i64,
}
#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Request {
    #[serde(with = "u64_value")]
    operation: u64,
    #[serde(with = "u64_value")]
    epoch: u64,
    #[serde(with = "u64_value")]
    input: u64,
    #[serde(with = "u64_value")]
    policy: u64,
    generation: u32,
    hwnd: i64,
    pid: u32,
    #[serde(with = "u64_value")]
    birth: u64,
    thread: u32,
    hkl: i64,
    kind: Kind,
    threshold: u8,
    user_words: Vec<String>,
    auto_enabled: bool,
    mode: u8,
    undo: Option<Undo>,
}
#[derive(Serialize, Deserialize)]
struct Hello {
    version: u32,
    pid: u32,
    #[serde(with = "u64_value")]
    birth: u64,
    mapping: String,
    #[serde(with = "u64_value")]
    epoch: u64,
    build: String,
    #[serde(with = "u64_value")]
    nonce: u64,
}
#[derive(Serialize, Deserialize)]
struct Ack {
    version: u32,
    pid: u32,
    #[serde(with = "u64_value")]
    birth: u64,
    #[serde(with = "u64_value")]
    epoch: u64,
    build: String,
    #[serde(with = "u64_value")]
    nonce: u64,
    #[serde(with = "u64_value")]
    session: u64,
}
#[derive(Serialize, Deserialize)]
pub(super) struct Response {
    #[serde(with = "u64_value")]
    pub(super) operation: u64,
    #[serde(with = "u64_value")]
    pub(super) epoch: u64,
    pub(super) generation: u32,
    #[serde(with = "u64_value")]
    pub(super) input: u64,
    pub(super) success: bool,
    pub(super) uncertain: bool,
    pub(super) hwnd: i64,
    pub(super) pid: u32,
    #[serde(with = "u64_value")]
    pub(super) birth: u64,
    pub(super) target_language: u8,
    pub(super) undo: Option<Undo>,
    pub(super) undone: bool,
}
struct Pending {
    request: Request,
    due: Instant,
}
struct Client {
    mapping: Arc<os::Mapping>,
    dispatcher: dispatch::Dispatcher<Request, Option<Response>>,
    pending: Mutex<Option<Pending>>,
}
pub(super) fn initialize() {
    CLIENT.get_or_init(|| {
        let mapping = os::Mapping::create().ok()?;
        let owned = mapping.clone();
        let dispatcher = dispatch::Dispatcher::start_notified(
            move |request| transact(&owned, request).ok(),
            || {
                super::post_runtime(super::WM_RUNTIME_WORD_RESULT, 0, 0);
            },
        )
        .ok()?;
        Some(Client {
            mapping,
            dispatcher,
            pending: Mutex::new(None),
        })
    });
}
pub(super) fn input_activity(generation: u32) {
    if let Some(Some(client)) = CLIENT.get() {
        os::bump_input(&client.mapping, generation);
    }
}
pub(super) fn policy_changed() {
    if let Some(Some(client)) = CLIENT.get() {
        client.mapping.state().policy.fetch_add(1, Ordering::SeqCst);
        client
            .mapping
            .state()
            .paused
            .store(u32::from(super::settings::paused()), Ordering::SeqCst);
    }
}
// Unknown hotkeys remain pass-through, including default Ctrl+Backspace: Word
// may consume/edit first, so stored-original Undo is supported only if all fresh
// checks still match. Never suppress based on a cached successful correction.
pub(super) fn submit(
    target: super::FocusTarget,
    generation: u32,
    kind: Kind,
    settings: &RuntimeSettings,
    undo: Option<Undo>,
) -> bool {
    let Some(Some(client)) = CLIENT.get() else {
        return false;
    };
    if settings.app_mode("winword.exe") == AppMode::Disabled || super::settings::paused() {
        return false;
    }
    if kind == Kind::Auto
        && (settings.app_mode("winword.exe") != AppMode::Auto || !settings.auto_correct)
    {
        return false;
    }
    let (_, birth) = match super::selection::word_admission::identity(target.hwnd as isize) {
        Some(identity) => identity,
        None => return false,
    };
    let state = client.mapping.state();
    let request = Request {
        operation: NEXT.fetch_add(1, Ordering::SeqCst),
        epoch: state.epoch.load(Ordering::SeqCst),
        input: state.input.load(Ordering::SeqCst),
        policy: state.policy.load(Ordering::SeqCst),
        generation,
        hwnd: target.hwnd as i64,
        pid: target.process_id,
        birth,
        thread: target.thread_id,
        hkl: target.hkl as i64,
        kind: kind.clone(),
        threshold: settings.sensitivity.confidence_threshold(),
        user_words: settings.user_words.clone(),
        auto_enabled: settings.auto_correct,
        mode: match settings.app_mode("winword.exe") {
            AppMode::Disabled => 0,
            AppMode::ManualOnly => 1,
            AppMode::Auto => 2,
        },
        undo,
    };
    let Ok(mut slot) = client.pending.try_lock() else {
        return false;
    };
    // Coalesce only not-yet-admitted preparation. Busy provider submission will be refused.
    *slot = Some(Pending {
        request,
        due: Instant::now()
            + if kind == Kind::Auto {
                QUIET
            } else {
                Duration::from_millis(20)
            },
    });
    true
}
pub(super) fn tick() {
    let Some(Some(client)) = CLIENT.get() else {
        return;
    };
    dispatch_pending(client, super::current_generation());
}
fn dispatch_pending(client: &Client, generation: u32) {
    let Ok(mut slot) = client.pending.try_lock() else {
        return;
    };
    if slot.as_ref().is_some_and(|p| Instant::now() >= p.due)
        && os::quiet(&client.mapping, QUIET.as_millis() as u64)
    {
        let mut pending = slot.take().unwrap();
        let state = client.mapping.state();
        if state.policy.load(Ordering::SeqCst) == pending.request.policy
            && generation == pending.request.generation
        {
            // Capture latest settled key-up epoch before admission; never refresh after provider starts.
            pending.request.input = state.input.load(Ordering::SeqCst);
            // Only not-yet-admitted value preparation is retained. Once submitted, this
            // request is never retried even if its provider fails or becomes uncertain.
            if !client.dispatcher.submit(
                pending.request.operation,
                pending.request.epoch,
                pending.request.clone(),
            ) {
                *slot = Some(pending);
            }
        }
    }
}
pub(super) fn poll() -> Option<Response> {
    let client = CLIENT.get()?.as_ref()?;
    let epoch = client.mapping.state().epoch.load(Ordering::SeqCst);
    client.dispatcher.poll(epoch)?.1
}
pub(super) fn current_input() -> Option<u64> {
    Some(
        CLIENT
            .get()?
            .as_ref()?
            .mapping
            .state()
            .input
            .load(Ordering::SeqCst),
    )
}
fn transact(mapping: &Arc<os::Mapping>, request: Request) -> std::io::Result<Response> {
    let name = os::pipe_name()?;
    let mut connection = os::connect(&name);
    let mut spawned = None;
    if connection
        .as_ref()
        .err()
        .is_some_and(|e| e.raw_os_error() == Some(2))
    {
        // A second role process cannot acquire an existing/abandoned broker mutex. Never kills/replaces an owner.
        spawned = Some(
            std::process::Command::new(std::env::current_exe()?)
                .arg("--word-broker")
                .spawn()?
                .id(),
        );
        let deadline = Instant::now() + Duration::from_secs(3);
        while connection.is_err() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(30));
            connection = os::connect(&name);
        }
    }
    let (mut stream, peer) = connection?;
    if spawned.is_some_and(|pid| pid != peer.pid) {
        return Err(std::io::Error::other("spawned broker PID mismatch"));
    }
    let own = os::Peer::authenticate(std::process::id())?;
    let nonce = os::random()?;
    os::send(
        &mut stream,
        &Hello {
            version: 1,
            pid: own.pid,
            birth: own.birth,
            mapping: mapping.name.clone(),
            epoch: request.epoch,
            build: env!("GSWITCHER_BROKER_BUILD_ID").into(),
            nonce,
        },
    )?;
    let ack: Ack = os::receive(&mut stream)?;
    if ack.build != env!("GSWITCHER_BROKER_BUILD_ID")
        || ack.nonce != nonce
        || ack.session == 0
        || ack.version != 1
        || ack.pid != peer.pid
        || ack.birth != peer.birth
        || ack.epoch != request.epoch
        || !peer.alive()
    {
        return Err(std::io::Error::other(
            "broker identity acknowledgement mismatch",
        ));
    }
    os::send(&mut stream, &request)?;
    let result: Response = os::receive(&mut stream)?;
    if result.operation != request.operation
        || result.epoch != request.epoch
        || result.hwnd != request.hwnd
        || result.pid != request.pid
    {
        return Err(std::io::Error::other("foreign broker reply"));
    }
    Ok(result)
}
pub(super) fn run_role() -> anyhow::Result<()> {
    super::selection::configure_broker_runtime(authenticated_client_birth, security_valid);
    let _owner = os::Owner::acquire()?;
    let session = os::random()?;
    super::selection::configure_runtime_policy(live_generation, live_paused);
    let mut server = os::Server::create(&os::pipe_name()?)?;
    loop {
        let result = (|| -> std::io::Result<()> {
            let peer = server.accept()?;
            let hello: Hello = os::receive(server.stream())?;
            if hello.build != env!("GSWITCHER_BROKER_BUILD_ID")
                || hello.nonce == 0
                || hello.version != 1
                || hello.pid != peer.pid
                || hello.birth != peer.birth
                || !peer.alive()
            {
                return Err(std::io::Error::other("foreign client"));
            }
            let mapping = os::Mapping::open(hello.mapping)?;
            if mapping.state().creator_pid.load(Ordering::SeqCst) != peer.pid
                || mapping.state().creator_birth.load(Ordering::SeqCst) != peer.birth
                || mapping.state().protocol.load(Ordering::SeqCst) != 1
                || mapping.state().build.as_slice() != env!("GSWITCHER_BROKER_BUILD_ID").as_bytes()
                || mapping.state().epoch.load(Ordering::SeqCst) != hello.epoch
            {
                return Err(std::io::Error::other("foreign client epoch"));
            }
            let own = os::Peer::authenticate(std::process::id())?;
            os::send(
                server.stream(),
                &Ack {
                    version: 1,
                    pid: own.pid,
                    birth: own.birth,
                    epoch: hello.epoch,
                    build: env!("GSWITCHER_BROKER_BUILD_ID").into(),
                    nonce: hello.nonce,
                    session,
                },
            )?;
            let request: Request = os::receive(server.stream())?;
            if request.epoch != hello.epoch
                || request.generation == 0
                || request.mode > 2
                || request.user_words.iter().map(String::len).sum::<usize>() > MAX_WORD_UNITS
            {
                return Err(std::io::Error::other("invalid operation"));
            }
            let live = LIVE.get_or_init(|| Mutex::new(None));
            *live
                .lock()
                .map_err(|_| std::io::Error::other("poisoned authority"))? = Some(Live {
                connection: server.connection()?,
                peer,
                mapping,
                request: request.clone(),
                allowed_hkl: request.hkl,
                deadline: Instant::now() + SECURITY_LIFETIME,
            });
            let result = execute(request.clone());
            // No next request is accepted until all synchronous native operation cleanup has returned.
            os::send(server.stream(), &result)?;
            Ok(())
        })();
        if let Some(live) = LIVE.get() {
            if let Ok(mut slot) = live.lock() {
                *slot = None;
            }
        }
        if result.is_err() {
            super::selection::word_admission::trace(6, "broker-transport-or-authority-refused");
        }
        server.disconnect();
    }
}
fn live_valid(live: &Live, include_input: bool) -> bool {
    let state = live.mapping.state();
    live.connection.stage_current(live.deadline)
        && super::selection::word_admission::identity(live.request.hwnd as isize)
            == Some((live.request.pid, live.request.birth))
        && live.mapping.belongs_to(&live.peer, live.request.epoch)
        && state.epoch.load(Ordering::SeqCst) == live.request.epoch
        && state.policy.load(Ordering::SeqCst) == live.request.policy
        && state.generation.load(Ordering::SeqCst) == live.request.generation
        && state.paused.load(Ordering::SeqCst) == 0
        && (!include_input || state.input.load(Ordering::SeqCst) == live.request.input)
        && super::focused_target().is_some_and(|t| {
            t.hwnd as i64 == live.request.hwnd
                && t.process_id == live.request.pid
                && t.thread_id == live.request.thread
                && t.hkl as i64 == live.allowed_hkl
        })
}
fn live_generation() -> u32 {
    LIVE.get()
        .and_then(|s| s.lock().ok())
        .and_then(|s| {
            s.as_ref()
                .filter(|l| live_valid(l, true))
                .map(|l| l.request.generation)
        })
        .unwrap_or(0)
}
fn live_paused() -> bool {
    live_generation() == 0
}
fn security_valid() -> bool {
    LIVE.get()
        .and_then(|s| s.lock().ok())
        .and_then(|s| s.as_ref().map(|l| live_valid(l, false)))
        .unwrap_or(false)
}
fn execute(request: Request) -> Response {
    let mut response = Response {
        operation: request.operation,
        epoch: request.epoch,
        generation: request.generation,
        input: request.input,
        success: false,
        uncertain: false,
        hwnd: request.hwnd,
        pid: request.pid,
        birth: request.birth,
        target_language: 0,
        undo: None,
        undone: false,
    };
    let hwnd = request.hwnd as HWND;
    if request.mode == 0
        || super::selection::word_admission::identity(hwnd as isize)
            != Some((request.pid, request.birth))
        || !security_valid()
        || !super::selection::is_word_target(hwnd)
    {
        return response;
    }
    let Some(parent) = super::selection::word_admission::begin(hwnd as isize) else {
        return response;
    };
    super::selection::word_admission::with_parent(parent.clone(), || {
        if super::secure_input::is_secure_input(hwnd, "winword.exe")
            || super::uia_secure::probe_target(request.pid, hwnd).is_none_or(|p| p.is_password)
            || !security_valid()
        {
            return;
        }
        // Successful security is op-local. New keys alone do not invalidate its response,
        // but this particular candidate remains exact-input-bound and is refused without retry.
        if live_generation() != request.generation {
            return;
        }
        let result = prepare_and_replace(&request, hwnd);
        if let Some((undo, language, undone)) = result {
            response.success = true;
            response.undo = Some(undo);
            response.target_language = language;
            response.undone = undone;
        }
    });
    response.uncertain = super::selection::word_native::uncertain() || !security_valid();
    if !parent.complete(response.uncertain) {
        response.success = false;
        response.uncertain = true;
    }
    response
}
fn prepare_and_replace(request: &Request, hwnd: HWND) -> Option<(Undo, u8, bool)> {
    use super::selection::word_native as native;
    use crate::model::Language;
    if request.kind == Kind::Undo {
        let undo = request.undo.clone()?;
        if !commit_range(
            request,
            hwnd,
            undo.start,
            undo.end,
            &undo.corrected,
            &undo.original,
            undo.source_hkl,
        ) {
            return None;
        }
        return Some((undo, 0, true));
    }
    if request.kind == Kind::Selected {
        let selected = native::read_selected_text(hwnd)?;
        let source = crate::detector::infer_language(&selected.text)?;
        let replacement = crate::layout::opposite_layout_text(&selected.text, source);
        let target_hkl = super::select_layout(super::opposite_language(source))? as i64;
        if !commit_range(
            request,
            hwnd,
            selected.start,
            selected.end,
            &selected.text,
            &replacement,
            target_hkl,
        ) {
            return None;
        }
        return Some((
            Undo {
                original: selected.text,
                corrected: replacement,
                start: selected.start,
                end: selected.end,
                selected: true,
                source_hkl: request.hkl,
                target_hkl,
            },
            if source == Language::English { 1 } else { 2 },
            false,
        ));
    }
    let snapshot = native::snapshot_caret(hwnd)?;
    let mode = match request.mode {
        0 => crate::word_candidate::Mode::Disabled,
        1 => crate::word_candidate::Mode::Manual,
        2 => crate::word_candidate::Mode::Auto,
        _ => return None,
    };
    let trigger = match request.kind {
        Kind::Auto => crate::word_candidate::Trigger::Auto,
        Kind::Boundary => crate::word_candidate::Trigger::Boundary,
        Kind::Previous => crate::word_candidate::Trigger::Previous,
        _ => crate::word_candidate::Trigger::Manual,
    };
    let candidate = crate::word_candidate::prepare(
        &snapshot.text_before_caret,
        mode,
        trigger,
        request.auto_enabled,
        super::language_from_hkl(request.hkl as isize)?,
        &request.user_words,
        request.threshold,
    )?;
    if live_generation() != request.generation {
        return None;
    }
    let end = candidate.start + candidate.original.encode_utf16().count() as u32;
    let target_hkl = super::select_layout(candidate.target)? as i64;
    if !commit_range(
        request,
        hwnd,
        candidate.start,
        end,
        &candidate.original,
        &candidate.replacement,
        target_hkl,
    ) {
        return None;
    }
    Some((
        Undo {
            original: candidate.original,
            corrected: candidate.replacement,
            start: candidate.start,
            end,
            selected: false,
            source_hkl: request.hkl,
            target_hkl,
        },
        if candidate.source == Language::English {
            1
        } else {
            2
        },
        false,
    ))
}

fn set_expected_layout(hkl: i64) -> Option<()> {
    LIVE.get()?.lock().ok()?.as_mut()?.allowed_hkl = hkl;
    Some(())
}
fn commit_range(
    request: &Request,
    hwnd: HWND,
    start: u32,
    end: u32,
    original: &str,
    replacement: &str,
    target_hkl: i64,
) -> bool {
    use super::selection::word_native as native;
    if live_generation() != request.generation {
        return false;
    }
    if set_expected_layout(target_hkl).is_none() {
        return false;
    }
    if !super::switch_layout(hwnd, request.thread, target_hkl as isize) {
        native::quarantine();
        return false;
    }
    if live_generation() != request.generation {
        return false;
    }
    if native::replace_range_if_matches(hwnd, start, end, original, replacement, request.generation)
    {
        return true;
    }
    // No blind or late restoration into changed focus/input. Unknown provider retains latch.
    if !native::uncertain()
        && live_generation() == request.generation
        && set_expected_layout(request.hkl).is_some()
        && !super::switch_layout(hwnd, request.thread, request.hkl as isize)
    {
        native::quarantine();
    }
    false
}

// Lazy broker birth is not the installing client's enrollment epoch. Only the
// retained, OS-authenticated current peer supplies this authority.
pub(super) fn authenticated_client_birth() -> Option<u64> {
    let live = LIVE.get()?.lock().ok()?;
    let live = live.as_ref()?;
    security_valid_without_lock(live).then_some(live.peer.birth)
}
fn security_valid_without_lock(live: &Live) -> bool {
    live_valid(live, false)
        && live.mapping.state().creator_pid.load(Ordering::SeqCst) == live.peer.pid
        && live.mapping.state().creator_birth.load(Ordering::SeqCst) == live.peer.birth
}

#[cfg(test)]
pub(super) fn fixture_dispatcher(
    provider: impl FnMut(Kind) -> Kind + Send + 'static,
) -> dispatch::Dispatcher<Kind, Kind> {
    dispatch::Dispatcher::start(provider).unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn actual_broker_wire_round_trips_unsigned_message_fields() {
        fn round_trip<T: serde::Serialize + serde::de::DeserializeOwned>(value: &T) -> T {
            toml::from_str(&toml::to_string(value).unwrap()).unwrap()
        }
        let hello = round_trip(&Hello {
            version: 1,
            pid: 1,
            birth: u64::MAX,
            mapping: "fixture".into(),
            epoch: u64::MAX,
            build: "fixture".into(),
            nonce: u64::MAX,
        });
        assert_eq!(
            (hello.birth, hello.epoch, hello.nonce),
            (u64::MAX, u64::MAX, u64::MAX)
        );
        let ack = round_trip(&Ack {
            version: 1,
            pid: 1,
            birth: u64::MAX,
            epoch: u64::MAX,
            build: "fixture".into(),
            nonce: u64::MAX,
            session: u64::MAX,
        });
        assert_eq!(
            (ack.birth, ack.epoch, ack.nonce, ack.session),
            (u64::MAX, u64::MAX, u64::MAX, u64::MAX)
        );
        let request = round_trip(&Request {
            operation: u64::MAX,
            epoch: u64::MAX,
            input: u64::MAX,
            policy: u64::MAX,
            generation: 1,
            hwnd: -1,
            pid: 1,
            birth: u64::MAX,
            thread: 1,
            hkl: -1,
            kind: Kind::Auto,
            threshold: 80,
            user_words: vec![],
            auto_enabled: true,
            mode: 2,
            undo: None,
        });
        assert_eq!(
            (
                request.operation,
                request.epoch,
                request.input,
                request.policy,
                request.birth
            ),
            (u64::MAX, u64::MAX, u64::MAX, u64::MAX, u64::MAX)
        );
        assert_eq!((request.hwnd, request.hkl), (-1, -1));
        let response = round_trip(&Response {
            operation: u64::MAX,
            epoch: u64::MAX,
            generation: 1,
            input: u64::MAX,
            success: false,
            uncertain: false,
            hwnd: -1,
            pid: 1,
            birth: u64::MAX,
            target_language: 0,
            undo: None,
            undone: false,
        });
        assert_eq!(
            (
                response.operation,
                response.epoch,
                response.input,
                response.birth
            ),
            (u64::MAX, u64::MAX, u64::MAX, u64::MAX)
        );
        assert_eq!(response.hwnd, -1);
    }
    struct RoleFixture(std::process::Child);
    impl Drop for RoleFixture {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    #[test]
    #[ignore = "exact subprocess role fixture invoked by handshake regression; never a Word operation"]
    fn fixture_actual_broker_role() {
        if std::env::var("GSWITCHER_FIXTURE_ROLE").as_deref() != Ok("broker") {
            return;
        }
        run_role().unwrap();
    }
    #[test]
    fn actual_latest_pending_survives_busy_and_completed_unpolled_result() {
        // Actual client mailbox and Dispatcher; synthetic value requests never enter
        // the transport/provider authority path or Word. Every fixture call counted.
        let _fixture_serial = os::fixture_lock();
        let mapping = os::Mapping::create().unwrap();
        let epoch = mapping.state().epoch.load(Ordering::SeqCst);
        let (entered, entries) = std::sync::mpsc::sync_channel(1);
        let (release, wait) = std::sync::mpsc::sync_channel(1);
        let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let observed = calls.clone();
        let dispatcher = dispatch::Dispatcher::start(move |request: Request| -> Option<Response> {
            observed.fetch_add(1, Ordering::SeqCst);
            entered.send((request.operation, request.input)).unwrap();
            wait.recv().unwrap();
            None
        })
        .unwrap();
        let request = |operation| Request {
            operation,
            epoch,
            input: 0,
            policy: 1,
            generation: 1,
            hwnd: 0,
            pid: 0,
            birth: 0,
            thread: 0,
            hkl: 0,
            kind: Kind::Auto,
            threshold: 80,
            user_words: vec![],
            auto_enabled: true,
            mode: 2,
            undo: None,
        };
        let client = Client {
            mapping,
            dispatcher,
            pending: Mutex::new(None),
        };
        assert!(client.dispatcher.submit(1, epoch, request(1)));
        assert_eq!(
            entries.recv_timeout(Duration::from_secs(5)).unwrap(),
            (1, 0)
        );
        *client.pending.lock().unwrap() = Some(Pending {
            request: request(2),
            due: Instant::now(),
        });
        client.mapping.state().input.store(7, Ordering::SeqCst);
        assert!(os::quiet(&client.mapping, QUIET.as_millis() as u64));
        dispatch_pending(&client, 1);
        assert!(client.pending.lock().unwrap().is_some());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        release.send(()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while client.dispatcher.busy() {
            assert!(Instant::now() < deadline);
            std::thread::yield_now();
        }
        dispatch_pending(&client, 1);
        assert!(
            client.pending.lock().unwrap().is_some(),
            "completed result still blocks admission, latest preparation must remain"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(client.dispatcher.poll(epoch).is_some());
        dispatch_pending(&client, 1);
        assert_eq!(
            entries.recv_timeout(Duration::from_secs(5)).unwrap(),
            (2, 7)
        );
        assert!(client.pending.lock().unwrap().is_none());
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        release.send(()).unwrap();
    }
    #[test]
    fn actual_same_executable_role_authenticates_build_nonce_and_mapping() {
        let _fixture_serial = os::fixture_lock();
        let path =
            module_path!().split_once("::").unwrap().1.to_string() + "::fixture_actual_broker_role";
        let child = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", &path, "--ignored", "--nocapture"])
            .env("GSWITCHER_FIXTURE_ROLE", "broker")
            .stdout(std::process::Stdio::null())
            .spawn()
            .unwrap();
        let mut role = RoleFixture(child);
        let mapping = os::Mapping::create().unwrap();
        let own = os::Peer::authenticate(std::process::id()).unwrap();
        let name = os::pipe_name().unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        let (mut stream, peer) = loop {
            match os::connect(&name) {
                Ok(value) => break value,
                Err(e) => {
                    assert!(
                        Instant::now() < deadline,
                        "actual role must become available: {e}"
                    );
                    assert!(
                        role.0.try_wait().unwrap().is_none(),
                        "role exited before admission"
                    );
                    std::thread::sleep(Duration::from_millis(10));
                }
            }
        };
        assert_eq!(peer.pid, role.0.id());
        mapping.state().epoch.store(u64::MAX, Ordering::SeqCst);
        let epoch = mapping.state().epoch.load(Ordering::SeqCst);
        let nonce = u64::MAX;
        os::send(
            &mut stream,
            &Hello {
                version: 1,
                pid: own.pid,
                birth: own.birth,
                mapping: mapping.name.clone(),
                epoch,
                build: env!("GSWITCHER_BROKER_BUILD_ID").into(),
                nonce,
            },
        )
        .unwrap();
        let ack: Ack = os::receive(&mut stream).unwrap();
        assert_eq!(ack.pid, peer.pid);
        assert_eq!(ack.birth, peer.birth);
        assert_eq!(ack.nonce, nonce);
        assert_eq!(ack.epoch, epoch);
        assert_eq!(ack.build, env!("GSWITCHER_BROKER_BUILD_ID"));
        assert_ne!(ack.session, 0);
        // gen0 is rejected before LIVE/execute; this role fixture never grants Word authority.
        let invalid = Request {
            operation: 1,
            epoch,
            input: 0,
            policy: 1,
            generation: 0,
            hwnd: 0,
            pid: 0,
            birth: 0,
            thread: 0,
            hkl: 0,
            kind: Kind::Auto,
            threshold: 80,
            user_words: vec![],
            auto_enabled: true,
            mode: 2,
            undo: None,
        };
        os::send(&mut stream, &invalid).unwrap();
        assert!(os::receive::<Response>(&mut stream).is_err());
        drop(stream);
        let deadline = Instant::now() + Duration::from_secs(5);
        let (mut stream, peer2) = loop {
            match os::connect(&name) {
                Ok(value) => break value,
                Err(e) => {
                    assert!(
                        Instant::now() < deadline,
                        "role must reaccept after refused operation: {e}"
                    );
                    std::thread::yield_now();
                }
            }
        };
        assert_eq!(peer2.pid, peer.pid);
        os::send(
            &mut stream,
            &Hello {
                version: 1,
                pid: own.pid,
                birth: own.birth,
                mapping: mapping.name.clone(),
                epoch,
                build: "foreign-build".into(),
                nonce: os::random().unwrap(),
            },
        )
        .unwrap();
        assert!(os::receive::<Ack>(&mut stream).is_err());
    }
}
