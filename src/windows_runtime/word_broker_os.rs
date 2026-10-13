//! Local user/session IPC and retained OS process identities; no COM ownership.
use super::super::selection;
use std::ffi::c_void;
use std::io::{self, Read, Write};
use std::os::windows::io::{AsRawHandle, FromRawHandle};
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;
type Handle = *mut c_void;
#[repr(C)]
#[derive(Default)]
struct FileTime {
    low: u32,
    high: u32,
}
#[repr(C)]
struct SecurityAttributes {
    length: u32,
    descriptor: *mut c_void,
    inherit: i32,
}
#[repr(C)]
struct SidAttributes {
    sid: *mut c_void,
    attributes: u32,
}
#[link(name = "kernel32")]
extern "system" {
    fn GetTickCount64() -> u64;
    fn GetCurrentProcess() -> Handle;
    fn CloseHandle(h: Handle) -> i32;
    fn GetCurrentProcessId() -> u32;
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
    fn GetProcessTimes(
        h: Handle,
        birth: *mut FileTime,
        exit: *mut FileTime,
        kernel: *mut FileTime,
        user: *mut FileTime,
    ) -> i32;
    fn QueryFullProcessImageNameW(h: Handle, flags: u32, path: *mut u16, len: *mut u32) -> i32;
    fn WaitForSingleObject(h: Handle, millis: u32) -> u32;
    fn ProcessIdToSessionId(pid: u32, session: *mut u32) -> i32;
    fn CreateNamedPipeW(
        name: *const u16,
        mode: u32,
        kind: u32,
        instances: u32,
        out: u32,
        input: u32,
        timeout: u32,
        security: *const SecurityAttributes,
    ) -> Handle;
    fn ConnectNamedPipe(h: Handle, overlapped: *mut c_void) -> i32;
    fn DisconnectNamedPipe(h: Handle) -> i32;
    fn PeekNamedPipe(
        h: Handle,
        buffer: *mut c_void,
        size: u32,
        read: *mut u32,
        available: *mut u32,
        left: *mut u32,
    ) -> i32;
    fn GetNamedPipeClientProcessId(h: Handle, pid: *mut u32) -> i32;
    fn GetNamedPipeServerProcessId(h: Handle, pid: *mut u32) -> i32;
    fn CreateFileW(
        name: *const u16,
        access: u32,
        share: u32,
        security: *const SecurityAttributes,
        creation: u32,
        flags: u32,
        template: Handle,
    ) -> Handle;
    fn GetLastError() -> u32;
    fn LocalFree(h: Handle) -> Handle;
    fn CreateMutexW(security: *const c_void, owner: i32, name: *const u16) -> Handle;
    fn ReleaseMutex(h: Handle) -> i32;
    fn CreateFileMappingW(
        file: Handle,
        security: *const SecurityAttributes,
        protect: u32,
        high: u32,
        low: u32,
        name: *const u16,
    ) -> Handle;
    fn OpenFileMappingW(access: u32, inherit: i32, name: *const u16) -> Handle;
    fn MapViewOfFile(h: Handle, access: u32, high: u32, low: u32, size: usize) -> *mut c_void;
    fn UnmapViewOfFile(p: *const c_void) -> i32;
}
#[link(name = "advapi32")]
extern "system" {
    fn OpenProcessToken(process: Handle, access: u32, token: *mut Handle) -> i32;
    fn GetTokenInformation(
        token: Handle,
        kind: u32,
        buffer: *mut c_void,
        size: u32,
        needed: *mut u32,
    ) -> i32;
    fn ConvertSidToStringSidW(sid: *const c_void, result: *mut *mut u16) -> i32;
    fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
        text: *const u16,
        revision: u32,
        result: *mut *mut c_void,
        size: *mut u32,
    ) -> i32;
}
#[link(name = "bcrypt")]
extern "system" {
    fn BCryptGenRandom(algorithm: Handle, buffer: *mut u8, size: u32, flags: u32) -> i32;
}
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}
fn error() -> io::Error {
    io::Error::last_os_error()
}
fn valid(h: Handle) -> bool {
    !h.is_null() && h as isize != -1
}
struct Owned(Handle);
unsafe impl Send for Owned {}
unsafe impl Sync for Owned {}
impl Drop for Owned {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}
struct Security {
    descriptor: Handle,
    attributes: SecurityAttributes,
}
impl Security {
    fn new() -> io::Result<Self> {
        let text = wide("D:P(A;;GA;;;OW)");
        let mut descriptor = std::ptr::null_mut();
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                text.as_ptr(),
                1,
                &mut descriptor,
                std::ptr::null_mut(),
            )
        } == 0
        {
            return Err(error());
        }
        Ok(Self {
            descriptor,
            attributes: SecurityAttributes {
                length: std::mem::size_of::<SecurityAttributes>() as u32,
                descriptor,
                inherit: 0,
            },
        })
    }
}
impl Drop for Security {
    fn drop(&mut self) {
        unsafe {
            LocalFree(self.descriptor);
        }
    }
}
pub(super) fn random() -> io::Result<u64> {
    let mut value = 0u64;
    if unsafe { BCryptGenRandom(std::ptr::null_mut(), (&mut value as *mut u64).cast(), 8, 2) } != 0
        || value == 0
    {
        return Err(io::Error::other("broker randomness unavailable"));
    }
    Ok(value)
}
pub(super) fn namespace() -> io::Result<String> {
    unsafe {
        let mut token = std::ptr::null_mut();
        if OpenProcessToken(GetCurrentProcess(), 8, &mut token) == 0 {
            return Err(error());
        }
        let token = Owned(token);
        let mut needed = 0;
        GetTokenInformation(token.0, 1, std::ptr::null_mut(), 0, &mut needed);
        if needed == 0 || needed > 4096 {
            return Err(error());
        }
        let mut buffer = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
        if GetTokenInformation(token.0, 1, buffer.as_mut_ptr().cast(), needed, &mut needed) == 0 {
            return Err(error());
        }
        let user = &*buffer.as_ptr().cast::<SidAttributes>();
        let mut text = std::ptr::null_mut();
        if ConvertSidToStringSidW(user.sid, &mut text) == 0 {
            return Err(error());
        }
        let mut length = 0;
        while *text.add(length) != 0 && length < 256 {
            length += 1;
        }
        let sid = String::from_utf16(std::slice::from_raw_parts(text, length))
            .map_err(|_| io::Error::other("invalid SID"))?;
        LocalFree(text.cast());
        let mut session = 0;
        if ProcessIdToSessionId(GetCurrentProcessId(), &mut session) == 0 {
            return Err(error());
        }
        Ok(format!("GSwitcher.WordBroker.v1.{sid}.{session}"))
    }
}
pub(super) struct Owner {
    handle: Owned,
}
impl Owner {
    pub(super) fn acquire() -> io::Result<Self> {
        let security = Security::new()?;
        let name = wide(&format!("Local\\{}", namespace()?));
        let h = unsafe {
            CreateMutexW(
                (&security.attributes as *const SecurityAttributes).cast(),
                0,
                name.as_ptr(),
            )
        };
        if !valid(h) {
            return Err(error());
        }
        let handle = Owned(h);
        if unsafe { WaitForSingleObject(h, 0) } != 0 {
            return Err(io::Error::other("existing or abandoned broker ownership"));
        }
        Ok(Self { handle })
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        unsafe {
            ReleaseMutex(self.handle.0);
        }
    }
}
pub(super) struct Peer {
    handle: Owned,
    pub(super) pid: u32,
    pub(super) birth: u64,
}
impl Peer {
    pub(super) fn authenticate(pid: u32) -> io::Result<Self> {
        unsafe {
            let h = OpenProcess(0x0010_0000 | 0x1000, 0, pid);
            if !valid(h) {
                return Err(error());
            }
            let handle = Owned(h);
            let mut birth = FileTime::default();
            let (mut exit, mut kernel, mut user) = (
                FileTime::default(),
                FileTime::default(),
                FileTime::default(),
            );
            if GetProcessTimes(h, &mut birth, &mut exit, &mut kernel, &mut user) == 0 {
                return Err(error());
            }
            let mut path = [0u16; 32768];
            let mut n = path.len() as u32;
            if QueryFullProcessImageNameW(h, 0, path.as_mut_ptr(), &mut n) == 0 {
                return Err(error());
            }
            let image = std::path::PathBuf::from(
                String::from_utf16(&path[..n as usize])
                    .map_err(|_| io::Error::other("invalid image"))?,
            );
            if image != std::env::current_exe()? {
                return Err(io::Error::other("foreign executable"));
            }
            let (mut remote, mut local) = (0, 0);
            if ProcessIdToSessionId(pid, &mut remote) == 0
                || ProcessIdToSessionId(GetCurrentProcessId(), &mut local) == 0
                || remote != local
            {
                return Err(io::Error::other("foreign session"));
            }
            let peer = Self {
                handle,
                pid,
                birth: (u64::from(birth.high) << 32) | u64::from(birth.low),
            };
            if !peer.alive() {
                return Err(io::Error::other("exited peer"));
            }
            Ok(peer)
        }
    }
    pub(super) fn alive(&self) -> bool {
        unsafe { WaitForSingleObject(self.handle.0, 0) == 258 }
    }
}
// Retains the exact transaction endpoint; probes only on the broker, never Engine.
pub(super) struct Connection {
    file: std::fs::File,
}
impl Connection {
    pub(super) fn stage_current(&self, deadline: std::time::Instant) -> bool {
        selection::word_admission::deadline_current(deadline) && self.connected()
    }
    pub(super) fn connected(&self) -> bool {
        unsafe {
            PeekNamedPipe(
                self.file.as_raw_handle(),
                std::ptr::null_mut(),
                0,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            ) != 0
        }
    }
}
pub(super) struct Server {
    file: std::fs::File,
}
impl Server {
    pub(super) fn create(name: &str) -> io::Result<Self> {
        let security = Security::new()?;
        let name = wide(name);
        let h = unsafe {
            CreateNamedPipeW(
                name.as_ptr(),
                3 | 0x0008_0000,
                8,
                1,
                65536,
                65536,
                0,
                &security.attributes,
            )
        };
        if !valid(h) {
            return Err(error());
        }
        Ok(Self {
            file: unsafe { std::fs::File::from_raw_handle(h) },
        })
    }
    pub(super) fn accept(&mut self) -> io::Result<Peer> {
        let h = self.file.as_raw_handle();
        if unsafe { ConnectNamedPipe(h, std::ptr::null_mut()) } == 0
            && unsafe { GetLastError() } != 535
        {
            return Err(error());
        }
        let mut pid = 0;
        if unsafe { GetNamedPipeClientProcessId(h, &mut pid) } == 0 {
            return Err(error());
        }
        Peer::authenticate(pid)
    }
    pub(super) fn connection(&self) -> io::Result<Arc<Connection>> {
        Ok(Arc::new(Connection {
            file: self.file.try_clone()?,
        }))
    }
    pub(super) fn stream(&mut self) -> &mut std::fs::File {
        &mut self.file
    }
    pub(super) fn disconnect(&mut self) {
        unsafe {
            DisconnectNamedPipe(self.file.as_raw_handle());
        }
    }
}
pub(super) fn pipe_name() -> io::Result<String> {
    Ok(format!("\\\\.\\pipe\\{}", namespace()?))
}
pub(super) fn connect(name: &str) -> io::Result<(std::fs::File, Peer)> {
    let name = wide(name);
    let h = unsafe {
        CreateFileW(
            name.as_ptr(),
            0xc000_0000,
            0,
            std::ptr::null(),
            3,
            0,
            std::ptr::null_mut(),
        )
    };
    if !valid(h) {
        return Err(error());
    }
    let file = unsafe { std::fs::File::from_raw_handle(h) };
    let mut pid = 0;
    if unsafe { GetNamedPipeServerProcessId(h, &mut pid) } == 0 {
        return Err(error());
    }
    let peer = Peer::authenticate(pid)?;
    Ok((file, peer))
}
pub(super) fn send(stream: &mut std::fs::File, value: &impl serde::Serialize) -> io::Result<()> {
    let text = toml::to_string(value).map_err(io::Error::other)?;
    if text.len() > 65536 {
        return Err(io::Error::other("oversized broker message"));
    }
    stream.write_all(&(text.len() as u32).to_le_bytes())?;
    stream.write_all(text.as_bytes())?;
    stream.flush()
}
pub(super) fn receive<T: serde::de::DeserializeOwned>(stream: &mut std::fs::File) -> io::Result<T> {
    let mut size = [0; 4];
    stream.read_exact(&mut size)?;
    let size = u32::from_le_bytes(size) as usize;
    if size == 0 || size > 65536 {
        return Err(io::Error::other("invalid broker message length"));
    }
    let mut bytes = vec![0; size];
    stream.read_exact(&mut bytes)?;
    toml::from_str(std::str::from_utf8(&bytes).map_err(io::Error::other)?).map_err(io::Error::other)
}
#[repr(C)]
pub(super) struct Authority {
    pub(super) creator_pid: AtomicU32,
    pub(super) creator_birth: AtomicU64,
    pub(super) protocol: AtomicU32,
    pub(super) build: [u8; 40],
    pub(super) epoch: AtomicU64,
    pub(super) input: AtomicU64,
    pub(super) policy: AtomicU64,
    pub(super) generation: AtomicU32,
    pub(super) paused: AtomicU32,
    pub(super) last_input: AtomicU64,
}
pub(super) struct Mapping {
    handle: Owned,
    view: *mut Authority,
    pub(super) name: String,
}
unsafe impl Send for Mapping {}
unsafe impl Sync for Mapping {}
impl Mapping {
    pub(super) fn create() -> io::Result<Arc<Self>> {
        let name = format!("Local\\{}.{}", namespace()?, random()?);
        let security = Security::new()?;
        let h = unsafe {
            CreateFileMappingW(
                -1isize as Handle,
                &security.attributes,
                4,
                0,
                std::mem::size_of::<Authority>() as u32,
                wide(&name).as_ptr(),
            )
        };
        if !valid(h) {
            return Err(error());
        }
        if unsafe { GetLastError() } == 183 {
            unsafe {
                CloseHandle(h);
            }
            return Err(io::Error::other("authority name collision"));
        }
        let mapping = Self::map(h, 0x000f_001f, name)?;
        unsafe {
            mapping.view.write(Authority {
                creator_pid: AtomicU32::new(std::process::id()),
                creator_birth: AtomicU64::new(Peer::authenticate(std::process::id())?.birth),
                protocol: AtomicU32::new(1),
                build: env!("GSWITCHER_BROKER_BUILD_ID")
                    .as_bytes()
                    .try_into()
                    .map_err(|_| io::Error::other("invalid build identity"))?,
                epoch: AtomicU64::new(random()?),
                input: AtomicU64::new(0),
                policy: AtomicU64::new(1),
                generation: AtomicU32::new(1),
                paused: AtomicU32::new(0),
                last_input: AtomicU64::new(0),
            });
        }
        Ok(Arc::new(mapping))
    }
    pub(super) fn open(name: String) -> io::Result<Arc<Self>> {
        if !name.starts_with(&format!("Local\\{}.", namespace()?)) {
            return Err(io::Error::other("foreign authority mapping"));
        }
        let h = unsafe { OpenFileMappingW(4, 0, wide(&name).as_ptr()) };
        if !valid(h) {
            return Err(error());
        }
        Ok(Arc::new(Self::map(h, 4, name)?))
    }
    fn map(h: Handle, access: u32, name: String) -> io::Result<Self> {
        let handle = Owned(h);
        let view = unsafe { MapViewOfFile(h, access, 0, 0, std::mem::size_of::<Authority>()) };
        if view.is_null() {
            return Err(error());
        }
        Ok(Self {
            handle,
            view: view.cast(),
            name,
        })
    }
    pub(super) fn state(&self) -> &Authority {
        unsafe { &*self.view }
    }
    pub(super) fn belongs_to(&self, peer: &Peer, epoch: u64) -> bool {
        let state = self.state();
        peer.alive()
            && state.creator_pid.load(Ordering::SeqCst) == peer.pid
            && state.creator_birth.load(Ordering::SeqCst) == peer.birth
            && state.protocol.load(Ordering::SeqCst) == 1
            && state.build.as_slice() == env!("GSWITCHER_BROKER_BUILD_ID").as_bytes()
            && state.epoch.load(Ordering::SeqCst) == epoch
    }
}
impl Drop for Mapping {
    fn drop(&mut self) {
        unsafe {
            UnmapViewOfFile(self.view.cast());
        }
        let _ = &self.handle;
    }
}
pub(super) fn bump_input(mapping: &Mapping, generation: u32) {
    mapping
        .state()
        .last_input
        .store(unsafe { GetTickCount64() }, Ordering::SeqCst);
    mapping.state().input.fetch_add(1, Ordering::SeqCst);
    mapping
        .state()
        .generation
        .store(generation, Ordering::SeqCst);
}

pub(super) fn quiet(mapping: &Mapping, millis: u64) -> bool {
    unsafe { GetTickCount64() }.saturating_sub(mapping.state().last_input.load(Ordering::SeqCst))
        >= millis
}

// One lock for endpoint/owner fixture users in each test binary. The ordinary
// Windows gate may run tests in parallel; no workflow flag is required.
#[cfg(test)]
pub(super) fn fixture_lock() -> std::sync::MutexGuard<'static, ()> {
    static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
    LOCK.lock().unwrap()
}

#[cfg(test)]
pub(super) struct FixtureProcess {
    child: std::process::Child,
    pub(super) peer: Peer,
    pub(super) mapping: Arc<Mapping>,
    pub(super) epoch: u64,
}
#[cfg(test)]
impl Drop for FixtureProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
#[cfg(test)]
pub(super) fn fixture_process() -> FixtureProcess {
    use std::io::BufRead;
    let path = module_path!().split_once("::").unwrap().1.to_string()
        + "::tests::fixture_authority_publisher";
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", &path, "--ignored", "--nocapture"])
        .env("GSWITCHER_FIXTURE_ROLE", "authority")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let stdout = child.stdout.take().unwrap();
    let (tx, rx) = std::sync::mpsc::sync_channel(1);
    std::thread::spawn(move || {
        for line in std::io::BufReader::new(stdout).lines() {
            let Ok(line) = line else {
                break;
            };
            if let Some(value) = line.strip_prefix("BROKER_FIXTURE_MAPPING=") {
                let _ = tx.send(value.to_owned());
                break;
            }
        }
    });
    let information = rx.recv_timeout(std::time::Duration::from_secs(5));
    if information.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    let information = information.expect("actual subprocess must publish authority");
    let (name, epoch) = information.rsplit_once('|').unwrap();
    let peer = Peer::authenticate(child.id()).unwrap();
    let mapping = Mapping::open(name.to_string()).unwrap();
    FixtureProcess {
        child,
        peer,
        mapping,
        epoch: epoch.parse().unwrap(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[derive(serde::Serialize, serde::Deserialize)]
    struct Message {
        #[serde(with = "crate::word_wire::u64_value")]
        nonce: u64,
    }
    #[test]
    #[ignore = "subprocess fixture explicitly executed by parent regressions"]
    fn fixture_authority_publisher() {
        if std::env::var("GSWITCHER_FIXTURE_ROLE").as_deref() != Ok("authority") {
            return;
        }
        let mapping = Mapping::create().unwrap();
        println!(
            "BROKER_FIXTURE_MAPPING={}|{}",
            mapping.name,
            mapping.state().epoch.load(Ordering::SeqCst)
        );
        std::io::stdout().flush().unwrap();
        let mut byte = [0u8; 1];
        let _ = std::io::stdin().read(&mut byte); // parent closes/terminates only this no-provider fixture
    }
    #[test]
    fn actual_parent_exit_invalidates_retained_shared_authority() {
        let _fixture_serial = fixture_lock();
        let mut fixture = fixture_process();
        assert!(fixture.mapping.belongs_to(&fixture.peer, fixture.epoch));
        let foreign = Mapping::create().unwrap();
        assert!(!foreign.belongs_to(&fixture.peer, fixture.epoch));
        fixture.child.kill().unwrap();
        fixture.child.wait().unwrap();
        assert!(!fixture.peer.alive());
        assert!(
            !fixture.mapping.belongs_to(&fixture.peer, fixture.epoch),
            "retained mapping must never authorize effects after exact creator exits"
        );
    }
    #[test]
    fn real_local_pipe_authenticates_endpoint_process_and_session() {
        let _fixture_serial = fixture_lock();
        let nonce = random().unwrap();
        let name = format!("{}-fixture-{nonce}", pipe_name().unwrap());
        let mut server = Server::create(&name).unwrap();
        let copy = name.clone();
        let thread = std::thread::spawn(move || {
            let (mut stream, peer) = connect(&copy).unwrap();
            assert_eq!(peer.pid, std::process::id());
            assert!(peer.alive());
            send(&mut stream, &Message { nonce }).unwrap();
            let result: Message = receive(&mut stream).unwrap();
            assert_eq!(result.nonce, nonce);
        });
        let peer = server.accept().unwrap();
        assert_eq!(peer.pid, std::process::id());
        assert!(peer.alive());
        let value: Message = receive(server.stream()).unwrap();
        assert_eq!(value.nonce, nonce);
        send(server.stream(), &value).unwrap();
        thread.join().unwrap();
        server.disconnect();
    }
    #[test]
    fn actual_pipe_disconnect_revokes_authority_while_parent_remains_alive() {
        // Run alone: configuring OnceLock authority must not affect other tests.
        if std::env::var("GSWITCHER_STAGE_FIXTURE").as_deref() != Ok("configured") {
            let path = module_path!().split_once("::").unwrap().1.to_string()
                + "::actual_pipe_disconnect_revokes_authority_while_parent_remains_alive";
            let result = std::process::Command::new(std::env::current_exe().unwrap())
                .args(["--exact", &path, "--nocapture"])
                .env("GSWITCHER_STAGE_FIXTURE", "configured")
                .status()
                .unwrap();
            assert!(result.success());
            return;
        }
        let _fixture_serial = fixture_lock();
        let name = format!("{}-disconnect-{}", pipe_name().unwrap(), random().unwrap());
        let mut server = Server::create(&name).unwrap();
        let copy = name.clone();
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        let (release, wait) = std::sync::mpsc::sync_channel(1);
        let client = std::thread::spawn(move || {
            let (stream, peer) = connect(&copy).unwrap();
            tx.send(peer.pid).unwrap();
            wait.recv().unwrap();
            drop(stream);
        });
        let peer = server.accept().unwrap();
        assert_eq!(
            rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap(),
            std::process::id()
        );
        let connection = server.connection().unwrap();
        assert!(connection.connected());
        assert!(peer.alive());
        static STAGE: std::sync::Mutex<Option<(Arc<Connection>, std::time::Instant)>> =
            std::sync::Mutex::new(None);
        fn configured_authority() -> bool {
            STAGE
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|(connection, deadline)| connection.stage_current(*deadline))
        }
        super::selection::configure_broker_runtime(|| None, configured_authority);
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(60);
        *STAGE.lock().unwrap() = Some((connection.clone(), deadline));
        let calls = std::cell::Cell::new(0);
        // Synthetic parent predicate: no installed Word/COM claim. The configured
        // security callback and OS transport/deadline gate are production paths.
        assert_eq!(
            super::selection::word_security_stage_for_parent(
                || true,
                || {
                    calls.set(calls.get() + 1);
                    7
                }
            ),
            Some(7)
        );
        *STAGE.lock().unwrap() = Some((
            connection.clone(),
            std::time::Instant::now() - std::time::Duration::from_secs(1),
        ));
        assert_eq!(
            super::selection::word_security_stage_for_parent(
                || true,
                || {
                    calls.set(calls.get() + 1);
                    9
                }
            ),
            None
        );
        assert_eq!(
            calls.get(),
            1,
            "expired production authority must stop the next provider entry"
        );
        *STAGE.lock().unwrap() = Some((connection.clone(), deadline));
        release.send(()).unwrap();
        client.join().unwrap();
        let until = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while connection.connected() && std::time::Instant::now() < until {
            std::thread::yield_now();
        }
        assert!(peer.alive());
        assert!(
            !connection.connected(),
            "closed transaction cannot borrow live process/map authority"
        );
        assert_eq!(
            super::selection::word_security_stage_for_parent(
                || true,
                || {
                    calls.set(calls.get() + 1);
                    8
                }
            ),
            None
        );
        assert_eq!(
            calls.get(),
            1,
            "actual closed pipe must prevent the next provider entry, even with live parent"
        );
        server.disconnect();
    }
    #[test]
    fn real_read_only_mapping_observes_exact_owner_epoch_changes() {
        let _fixture_serial = fixture_lock();
        let owner = Mapping::create().unwrap();
        let reader = Mapping::open(owner.name.clone()).unwrap();
        let initial = reader.state().epoch.load(Ordering::SeqCst);
        assert_ne!(initial, 0);
        owner.state().epoch.fetch_add(1, Ordering::SeqCst);
        assert_ne!(reader.state().epoch.load(Ordering::SeqCst), initial);
        bump_input(&owner, 17);
        assert_eq!(reader.state().generation.load(Ordering::SeqCst), 17);
        assert_eq!(reader.state().input.load(Ordering::SeqCst), 1);
    }
}
