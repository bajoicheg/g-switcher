//! One bounded, read-only provider worker. No mutation is allowed here.
//! After a timeout, refuse new work until the exact old call completed.
//! Discard its late reply; resume only with a new request on the same thread.
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, SyncSender, TryRecvError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

struct Read<Q, R> {
    input: Q,
    result: SyncSender<R>,
    completed: Arc<AtomicBool>,
}

#[derive(Default)]
struct ReaderState {
    in_flight: Option<Arc<AtomicBool>>,
    caller_active: bool,
    timed_out: bool,
    disconnected: bool,
}

pub struct BoundedReader<Q, R> {
    requests: SyncSender<Read<Q, R>>,
    state: Mutex<ReaderState>,
}

impl<Q: Send + 'static, R: Send + 'static> BoundedReader<Q, R> {
    pub fn start(mut process: impl FnMut(Q) -> R + Send + 'static) -> std::io::Result<Self> {
        let (requests, queue) = mpsc::sync_channel::<Read<Q, R>>(1);
        std::thread::Builder::new()
            .name("g-switcher-uia-reader".into())
            .spawn(move || {
                while let Ok(request) = queue.recv() {
                    let result = process(request.input);
                    // Completion acknowledges provider quiescence only. It
                    // never grants writable/security authority to the caller.
                    request.completed.store(true, Ordering::Release);
                    let _ = request.result.try_send(result);
                }
            })?;
        Ok(Self {
            requests,
            state: Mutex::new(ReaderState::default()),
        })
    }

    pub fn request(&self, input: Q, timeout: Duration) -> Option<R> {
        let deadline = Instant::now().checked_add(timeout)?;
        let completed = Arc::new(AtomicBool::new(false));
        let recovered = {
            let mut state = self.state.try_lock().ok()?;
            if state.disconnected || state.caller_active {
                return None;
            }
            if state
                .in_flight
                .as_ref()
                .is_some_and(|old| !old.load(Ordering::Acquire))
            {
                return None;
            }
            let recovered = state.timed_out;
            state.timed_out = false;
            state.in_flight = Some(completed.clone());
            state.caller_active = true;
            recovered
        };
        struct Caller<'a>(&'a Mutex<ReaderState>);
        impl Drop for Caller<'_> {
            fn drop(&mut self) {
                if let Ok(mut state) = self.0.lock() {
                    state.caller_active = false;
                }
            }
        }
        let _caller = Caller(&self.state);
        if recovered {
            trace_reader("reader-recovered-fresh-request");
        }
        let (result, response) = mpsc::sync_channel(1);
        if self
            .requests
            .try_send(Read {
                input,
                result,
                completed,
            })
            .is_err()
        {
            self.state.lock().ok()?.disconnected = true;
            trace_reader("reader-disconnected");
            return None;
        }
        loop {
            pump_sent_messages();
            if Instant::now() >= deadline {
                self.state.lock().ok()?.timed_out = true;
                trace_reader("reader-timeout-awaiting-old-completion");
                return None;
            }
            match response.try_recv() {
                Ok(value) => return Some(value),
                Err(TryRecvError::Disconnected) => {
                    self.state.lock().ok()?.disconnected = true;
                    trace_reader("reader-disconnected");
                    return None;
                }
                Err(TryRecvError::Empty) => std::thread::sleep(Duration::from_millis(1)),
            }
        }
    }
}

fn trace_reader(stage: &str) {
    use std::io::Write;
    let path = std::env::temp_dir().join("GSwitcher-Word-Runtime.log");
    let oversized = std::fs::metadata(&path).is_ok_and(|meta| meta.len() > 1_048_576);
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(!oversized)
        .truncate(oversized)
        .open(path)
    {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let _ = writeln!(file, "{now} pid={} stage={stage}", std::process::id());
    }
}

pub fn pump_sent_messages() {
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::UI::WindowsAndMessaging::{PeekMessageW, MSG, PM_NOREMOVE};
        let mut message: MSG = std::mem::zeroed();
        // PeekMessage dispatches pending nonqueued sent messages even when no
        // posted message is removed. Do not Translate/Dispatch posted messages.
        PeekMessageW(&mut message, std::ptr::null_mut(), 0, 0, PM_NOREMOVE);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Condvar, Mutex};
    use std::time::{Duration, Instant};

    #[test]
    fn provider_runs_off_the_requesting_thread() {
        let caller = std::thread::current().id();
        let reader = BoundedReader::start(|()| std::thread::current().id()).unwrap();
        let observed = reader
            .request((), Duration::from_secs(1))
            .expect("metadata worker must respond");
        assert_ne!(observed, caller);
    }

    #[test]
    fn stalled_metadata_returns_none_and_never_queues_a_replacement() {
        let gate = Arc::new((Mutex::new(false), Condvar::new()));
        let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let worker_gate = gate.clone();
        let worker_calls = calls.clone();
        let reader = BoundedReader::start(move |value| {
            worker_calls.fetch_add(1, Ordering::SeqCst);
            let (lock, wake) = &*worker_gate;
            let _guard = wake
                .wait_while(lock.lock().unwrap(), |ready| !*ready)
                .unwrap();
            value
        })
        .unwrap();
        // Baseline synchronous behavior is released eventually, so RED cannot hang.
        let release = gate.clone();
        let releaser = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(250));
            *release.0.lock().unwrap() = true;
            release.1.notify_all();
        });
        let started = Instant::now();
        let result = reader.request(42, Duration::from_millis(20));
        let elapsed = started.elapsed();
        let second = reader.request(43, Duration::from_millis(20));
        releaser.join().unwrap();
        assert_eq!(
            result, None,
            "late metadata must not become writable authority"
        );
        assert!(
            elapsed < Duration::from_millis(200),
            "caller blocked {elapsed:?}"
        );
        assert_eq!(second, None, "a timed-out reader remains quarantined");
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let deadline = Instant::now() + Duration::from_secs(1);
        loop {
            if let Some(value) = reader.request(44, Duration::from_millis(100)) {
                assert_eq!(value, 44);
                break;
            }
            assert!(Instant::now() < deadline);
            std::thread::sleep(Duration::from_millis(1));
        }
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn each_successful_request_reads_fresh_state() {
        let mut revision = 0;
        let reader = BoundedReader::start(move |()| {
            revision += 1;
            revision
        })
        .unwrap();
        assert_eq!(reader.request((), Duration::from_secs(1)), Some(1));
        assert_eq!(reader.request((), Duration::from_secs(1)), Some(2));
    }

    #[test]
    fn provider_failure_returns_none_without_panicking_the_caller() {
        let reader = BoundedReader::<(), ()>::start(|()| panic!("provider failed")).unwrap();
        assert_eq!(reader.request((), Duration::from_secs(1)), None);
        assert_eq!(reader.request((), Duration::from_secs(1)), None);
    }
}

#[cfg(all(test, windows))]
mod windows_tests {
    use super::*;
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
    use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DefWindowProcW, DestroyWindow, GetWindowLongPtrW, PeekMessageW,
        PostMessageW, RegisterClassW, SendMessageTimeoutW, GWLP_USERDATA, HWND_MESSAGE, MSG,
        PM_REMOVE, SMTO_ABORTIFHUNG, WM_APP, WNDCLASSW,
    };
    const QUERY: u32 = WM_APP + 77;
    const POSTED: u32 = WM_APP + 78;
    unsafe extern "system" fn window_proc(
        hwnd: HWND,
        message: u32,
        w: WPARAM,
        l: LPARAM,
    ) -> LRESULT {
        if message == QUERY {
            return 123;
        }
        if message == POSTED {
            // A posted callback must remain queued while the reader waits.
            return GetWindowLongPtrW(hwnd, GWLP_USERDATA);
        }
        DefWindowProcW(hwnd, message, w, l)
    }
    #[test]
    fn sent_message_callbacks_remain_live_but_posted_work_is_not_reentered() {
        unsafe {
            let class: Vec<u16> = format!(
                "GSwitcher.Reader.Test.{}",
                GetModuleHandleW(null()) as usize
            )
            .encode_utf16()
            .chain(Some(0))
            .collect();
            let module = GetModuleHandleW(null());
            let definition = WNDCLASSW {
                lpfnWndProc: Some(window_proc),
                hInstance: module,
                lpszClassName: class.as_ptr(),
                ..std::mem::zeroed()
            };
            // The same source module can occur in more than one adapter namespace.
            let _ = RegisterClassW(&definition);
            let hwnd = CreateWindowExW(
                0,
                class.as_ptr(),
                class.as_ptr(),
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                null_mut(),
                module,
                null(),
            );
            assert!(!hwnd.is_null());
            assert_ne!(PostMessageW(hwnd, POSTED, 0, 0), 0);
            let reader = BoundedReader::start(|handle: isize| {
                let mut value = 0;
                let ok = SendMessageTimeoutW(
                    handle as HWND,
                    QUERY,
                    0,
                    0,
                    SMTO_ABORTIFHUNG,
                    400,
                    &mut value,
                );
                (ok != 0, value)
            })
            .unwrap();
            let result = reader.request(hwnd as isize, Duration::from_secs(1));
            let mut posted: MSG = std::mem::zeroed();
            let still_queued = PeekMessageW(&mut posted, hwnd, POSTED, POSTED, PM_REMOVE);
            DestroyWindow(hwnd);
            assert_eq!(result, Some((true, 123)));
            assert_ne!(
                still_queued, 0,
                "wait must not dispatch posted runtime work"
            );
        }
    }
}

#[cfg(test)]
mod concurrency_tests {
    use super::*;
    use std::sync::{Arc, Condvar, Mutex};
    #[test]
    fn concurrent_requests_cannot_replace_a_stalled_or_quarantined_reader() {
        let gate = Arc::new((Mutex::new(false), Condvar::new()));
        let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let worker_gate = gate.clone();
        let worker_calls = calls.clone();
        let (started_tx, started_rx) = mpsc::sync_channel(1);
        let (ended_tx, ended_rx) = mpsc::sync_channel(1);
        let reader = Arc::new(
            BoundedReader::start(move |value| {
                worker_calls.fetch_add(1, Ordering::SeqCst);
                started_tx.send(()).unwrap();
                let _guard = worker_gate
                    .1
                    .wait_while(worker_gate.0.lock().unwrap(), |ready| !*ready)
                    .unwrap();
                ended_tx.send(()).unwrap();
                value
            })
            .unwrap(),
        );
        let first_reader = reader.clone();
        let first = std::thread::spawn(move || first_reader.request(1, Duration::from_millis(80)));
        started_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        let other_readers: Vec<_> = (0..16)
            .map(|_| {
                let reader = reader.clone();
                std::thread::spawn(move || reader.request(2, Duration::from_secs(1)))
            })
            .collect();
        for other in other_readers {
            assert_eq!(other.join().unwrap(), None);
        }
        assert_eq!(first.join().unwrap(), None);
        let after_timeout: Vec<_> = (0..16)
            .map(|_| {
                let reader = reader.clone();
                std::thread::spawn(move || reader.request(3, Duration::from_secs(1)))
            })
            .collect();
        for other in after_timeout {
            assert_eq!(other.join().unwrap(), None);
        }
        *gate.0.lock().unwrap() = true;
        gate.1.notify_all();
        ended_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        let deadline = Instant::now() + Duration::from_secs(1);
        loop {
            if let Some(value) = reader.request(4, Duration::from_millis(100)) {
                assert_eq!(value, 4);
                break;
            }
            assert!(Instant::now() < deadline);
            std::thread::sleep(Duration::from_millis(1));
        }
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }
}

#[cfg(test)]
mod recovery_regression {
    use super::*;
    use std::sync::{Arc, Condvar, Mutex};
    #[test]
    fn transient_stall_recovers_same_worker_with_fresh_result_only() {
        let gate = Arc::new((Mutex::new(false), Condvar::new()));
        let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let worker_gate = gate.clone();
        let worker_calls = calls.clone();
        let (started_tx, started_rx) = mpsc::sync_channel(1);
        let reader = Arc::new(
            BoundedReader::start(move |value| {
                if worker_calls.fetch_add(1, Ordering::SeqCst) == 0 {
                    started_tx.send(std::thread::current().id()).unwrap();
                    let _guard = worker_gate
                        .1
                        .wait_while(worker_gate.0.lock().unwrap(), |ready| !*ready)
                        .unwrap();
                }
                (value, std::thread::current().id())
            })
            .unwrap(),
        );
        let first_reader = reader.clone();
        let first = std::thread::spawn(move || first_reader.request(42, Duration::from_millis(30)));
        let worker_id = started_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(first.join().unwrap(), None);
        let contenders: Vec<_> = (0..32)
            .map(|_| {
                let reader = reader.clone();
                std::thread::spawn(move || reader.request(77, Duration::from_millis(20)))
            })
            .collect();
        for contender in contenders {
            assert_eq!(contender.join().unwrap(), None);
        }
        assert_eq!(
            calls.load(Ordering::SeqCst),
            1,
            "no request or replacement while provider is stalled"
        );
        *gate.0.lock().unwrap() = true;
        gate.1.notify_all();
        let deadline = Instant::now() + Duration::from_secs(1);
        let fresh = loop {
            if let Some(value) = reader.request(99, Duration::from_millis(100)) {
                break value;
            }
            assert!(
                Instant::now() < deadline,
                "transient delay permanently disabled reader"
            );
            std::thread::sleep(Duration::from_millis(1));
        };
        assert_eq!(
            fresh,
            (99, worker_id),
            "never accept old42, and never create a replacement thread"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }
}
