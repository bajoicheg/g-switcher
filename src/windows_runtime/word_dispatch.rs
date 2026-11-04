//! Bounded client dispatcher: provider/IPC waits never run on the caller.
//! Busy requests are refused; a caller timeout never replaces a provider worker.
use std::sync::{
    mpsc::{self, SyncSender},
    Arc, Mutex,
};

struct Request<Q> {
    operation: u64,
    epoch: u64,
    input: Q,
}
struct State<R> {
    active: bool,
    result: Option<(u64, u64, R)>,
    disconnected: bool,
}
pub(crate) struct Dispatcher<Q, R> {
    queue: SyncSender<Request<Q>>,
    state: Arc<Mutex<State<R>>>,
}
impl<Q: Send + 'static, R: Send + 'static> Dispatcher<Q, R> {
    #[cfg(test)]
    pub(crate) fn start(provider: impl FnMut(Q) -> R + Send + 'static) -> std::io::Result<Self> {
        Self::start_notified(provider, || {})
    }
    pub(crate) fn start_notified(
        mut provider: impl FnMut(Q) -> R + Send + 'static,
        notify: impl Fn() + Send + 'static,
    ) -> std::io::Result<Self> {
        let (queue, requests) = mpsc::sync_channel::<Request<Q>>(1);
        let state = Arc::new(Mutex::new(State {
            active: false,
            result: None,
            disconnected: false,
        }));
        let worker_state = state.clone();
        std::thread::Builder::new()
            .name("g-switcher-word-client".into())
            .spawn(move || {
                while let Ok(request) = requests.recv() {
                    let result = provider(request.input); // No client state or Engine lock across provider/IPC.
                    let Ok(mut state) = worker_state.lock() else {
                        return;
                    };
                    state.result = Some((request.operation, request.epoch, result));
                    state.active = false;
                    drop(state);
                    notify();
                }
            })?;
        Ok(Self { queue, state })
    }
    pub(crate) fn submit(&self, operation: u64, epoch: u64, input: Q) -> bool {
        let Ok(mut state) = self.state.try_lock() else {
            return false;
        };
        if state.active || state.result.is_some() || state.disconnected {
            return false;
        }
        state.active = true;
        if self
            .queue
            .try_send(Request {
                operation,
                epoch,
                input,
            })
            .is_err()
        {
            state.active = false;
            state.disconnected = true;
            return false;
        }
        true
    }
    pub(crate) fn poll(&self, epoch: u64) -> Option<(u64, R)> {
        self.state
            .try_lock()
            .ok()?
            .result
            .take()
            .filter(|r| r.1 == epoch)
            .map(|r| (r.0, r.2))
    }
    #[cfg(test)]
    pub(crate) fn busy(&self) -> bool {
        self.state.lock().unwrap().active
    }
}
#[cfg(test)]
mod tests {
    include!("word_dispatch_requirements.rs");
}
