use super::*;
use std::sync::{mpsc, Arc, atomic::{AtomicUsize, Ordering}};
use std::time::Duration;

#[test]
fn main_dispatch_continues_while_exact_provider_is_stalled() {
    let (entered_tx, entered_rx)=mpsc::sync_channel(1);
    let (release_tx, release_rx)=mpsc::sync_channel(1);
    let calls=Arc::new(AtomicUsize::new(0));let observed=calls.clone();
    let dispatcher=Dispatcher::start(move |input:u64|{observed.fetch_add(1,Ordering::SeqCst);entered_tx.send(()).unwrap();release_rx.recv().unwrap();input}).unwrap();
    let (other_tx,other_rx)=mpsc::sync_channel(1);
    let main=std::thread::spawn(move ||{assert!(dispatcher.submit(1,1,7));other_tx.send(()).unwrap();dispatcher});
    entered_rx.recv_timeout(Duration::from_secs(2)).expect("provider must actually enter");
    let progressed=other_rx.recv_timeout(Duration::from_millis(100)).is_ok();
    assert_eq!(calls.load(Ordering::SeqCst),1);
    release_tx.send(()).unwrap();let _dispatcher=main.join().unwrap();
    assert!(progressed,"main dispatcher was blocked by the exact pending Word provider");
}

#[test]
fn busy_dispatch_never_starts_second_provider() {
    let (entered_tx,entered_rx)=mpsc::sync_channel(1);let (release_tx,release_rx)=mpsc::sync_channel(1);
    let calls=Arc::new(AtomicUsize::new(0));let observed=calls.clone();
    let dispatcher=Dispatcher::start(move |input:u64|{observed.fetch_add(1,Ordering::SeqCst);entered_tx.send(()).unwrap();release_rx.recv().unwrap();input}).unwrap();
    assert!(dispatcher.submit(11,4,7));entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(!dispatcher.submit(12,4,8));assert_eq!(calls.load(Ordering::SeqCst),1);
    release_tx.send(()).unwrap();
    let end=std::time::Instant::now()+Duration::from_secs(2);
    loop {if dispatcher.poll(4).is_some(){break;}assert!(std::time::Instant::now()<end);std::thread::yield_now();}
    assert_eq!(calls.load(Ordering::SeqCst),1);
}

#[test]
fn old_epoch_reply_cannot_install_current_undo() {
    let (done_tx,done_rx)=mpsc::sync_channel(1);
    let dispatcher=Dispatcher::start(move |input:u64|{done_tx.send(()).unwrap();input}).unwrap();
    assert!(dispatcher.submit(21,5,9));done_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    let end=std::time::Instant::now()+Duration::from_secs(2);
    while dispatcher.busy(){assert!(std::time::Instant::now()<end);std::thread::yield_now();}
    assert!(dispatcher.poll(6).is_none());
    assert!(dispatcher.poll(5).is_none(),"discarded stale result cannot be recovered");
}
