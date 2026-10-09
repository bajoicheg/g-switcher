// Compile this with baseline.rs for RED, then with proposed guard_core.rs for GREEN.
// No Word/COM calls: these test admission/pending ownership, not Word recovery.
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(1);
    fn directory() -> PathBuf {
        let p = std::env::temp_dir().join(format!("word-guard-spec-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::SeqCst)));
        fs::create_dir(&p).unwrap();
        p
    }
    fn host(birth: u64) -> Host { Host { pid: 42, birth } }
    fn begin(g: &mut Gate) -> Operation { g.begin(host(100)).expect("new authenticated host should admit") }

    #[test]
    fn restart_refuses_previous_pending_before_any_provider_call() {
        let dir = directory();
        let mut first = Gate::open(dir.clone());
        let _pending = begin(&mut first);
        drop(first); // caller exit is not provider completion
        let mut restarted = Gate::open(dir.clone());
        assert!(restarted.begin(host(100)).is_none(), "restart must preserve pending provider ownership");
        drop(restarted);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn caller_timeout_does_not_complete_worker_owned_read() {
        let dir = directory(); let mut gate = Gate::open(dir.clone());
        let op = begin(&mut gate); let child = gate.child(&op).expect("delegated reader");
        gate.parent_complete(&op, false).unwrap(); // STA finished after focus read timed out
        assert!(gate.begin(host(100)).is_none(), "old child provider still running");
        gate.child_complete(child).unwrap(); // actual old provider returned, no result reused
        assert!(gate.begin(host(100)).is_some(), "new fresh request after all actual calls complete");
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn late_child_does_not_clear_uncertain_native_mutation() {
        let dir=directory(); let mut gate=Gate::open(dir.clone());
        let op=begin(&mut gate); let child=gate.child(&op).unwrap();
        gate.parent_complete(&op, true).unwrap();
        gate.child_complete(child).unwrap();
        assert!(gate.begin(host(100)).is_none(), "read completion cannot resolve native uncertainty");
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn foreign_completion_cannot_clear_current_operation() {
        let dir=directory(); let mut gate=Gate::open(dir.clone()); let op=begin(&mut gate);
        let foreign=Operation { host: op.host, id: op.id.wrapping_add(1) };
        assert!(gate.parent_complete(&foreign, false).is_err());
        assert!(gate.begin(host(100)).is_none());
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn duplicate_child_completion_cannot_consume_another_child() {
        let dir=directory(); let mut gate=Gate::open(dir.clone()); let op=begin(&mut gate);
        let a=gate.child(&op).unwrap(); let b=gate.child(&op).unwrap();
        gate.parent_complete(&op, false).unwrap();
        gate.child_complete(a.clone()).unwrap();
        assert!(gate.child_complete(a).is_err());
        assert!(gate.begin(host(100)).is_none());
        gate.child_complete(b).unwrap();
        assert!(gate.begin(host(100)).is_some());
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn missing_identity_never_admits() {
        let dir=directory(); let mut gate=Gate::open(dir.clone());
        assert!(gate.begin(Host {pid:0,birth:0}).is_none());
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn persistence_failure_refuses_before_provider_admission() {
        let dir=directory(); let not_directory=dir.join("not-directory"); fs::write(&not_directory,b"occupied").unwrap();
        let mut gate=Gate::open(not_directory);
        assert!(gate.begin(host(100)).is_none());
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn corrupt_prior_marker_never_becomes_idle() {
        let dir=directory(); fs::write(dir.join("42-100.pending"), b"truncated").unwrap();
        let mut gate=Gate::open(dir.clone()); assert!(gate.begin(host(100)).is_none());
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    #[cfg(not(windows))]
    fn missing_marker_at_completion_is_not_success() {
        let dir=directory(); let mut gate=Gate::open(dir.clone()); let op=begin(&mut gate);
        fs::remove_file(dir.join("42-100.pending")).unwrap();
        assert!(gate.parent_complete(&op,false).is_err());
        assert!(gate.begin(host(100)).is_none(), "persistence anomaly poisons process admission");
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn actual_host_birth_change_does_not_reuse_old_host_authority() {
        let dir=directory(); let mut gate=Gate::open(dir.clone()); let _pending=begin(&mut gate);
        let mut restarted=Gate::open(dir.clone());
        assert!(restarted.begin(host(101)).is_some(), "Win32-authenticated different process incarnation");
        drop(restarted);
        let mut old = Gate::open(dir.clone());
        assert!(old.begin(host(100)).is_none(), "old incarnation remains pending");
        drop(old);
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn normal_exact_completion_allows_fresh_admission() {
        let dir=directory(); let mut gate=Gate::open(dir.clone()); let op=begin(&mut gate);
        gate.parent_complete(&op,false).unwrap();
        assert!(gate.begin(host(100)).is_some());
        drop(gate);
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn timed_out_window_message_quarantine_is_sticky_after_parent_completion() {
        let dir=directory();let mut gate=Gate::open(dir.clone());let op=begin(&mut gate);
        gate.quarantine(&op).unwrap();gate.parent_complete(&op,false).unwrap();
        assert!(gate.begin(host(100)).is_none());drop(gate);fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn actual_pending_worker_owns_ticket_beyond_caller_timeout() {
        use std::sync::{Arc,Mutex,Condvar,mpsc};
        let dir=directory();let mut initial=Gate::open(dir.clone());let op=begin(&mut initial);
        let child=initial.child(&op).unwrap();let gate=Arc::new(Mutex::new(initial));
        let barrier=Arc::new((Mutex::new(false),Condvar::new()));let worker_gate=gate.clone();let worker_barrier=barrier.clone();
        let (finished,completion)=mpsc::channel();
        let worker=std::thread::spawn(move||{
            let (state,ready)=&*worker_barrier;
            let lock=ready.wait_while(state.lock().unwrap(),|released|!*released).unwrap();drop(lock);
            worker_gate.lock().unwrap().child_complete(child).unwrap();finished.send(()).unwrap();
        });
        gate.lock().unwrap().parent_complete(&op,false).unwrap();
        assert!(completion.recv_timeout(std::time::Duration::from_millis(20)).is_err());
        assert!(gate.lock().unwrap().begin(host(100)).is_none());
        *barrier.0.lock().unwrap()=true;barrier.1.notify_all();
        completion.recv_timeout(std::time::Duration::from_secs(2)).unwrap();worker.join().unwrap();
        assert!(gate.lock().unwrap().begin(host(100)).is_some());drop(gate);fs::remove_dir_all(dir).unwrap();
    }

}

#[cfg(all(test,windows))]
mod windows_marker_tests {
    use super::*;
    #[test]
    fn active_marker_denies_external_deletion_until_verified_completion() {
        let dir=std::env::temp_dir().join(format!("word-guard-live-marker-{}",std::process::id()));
        std::fs::create_dir(&dir).unwrap();
        let mut gate=Gate::open(dir.clone());let host=Host{pid:43,birth:100};
        let op=gate.begin(host).unwrap();
        assert!(std::fs::remove_file(dir.join("43-100.pending")).is_err());
        gate.parent_complete(&op,false).unwrap();
        assert!(gate.begin(host).is_some());
        drop(gate);std::fs::remove_dir_all(dir).unwrap();
    }
}
