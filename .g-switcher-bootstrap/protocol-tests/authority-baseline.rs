// Review snapshot's missing stage predicate/deadline represented only for staged RED.
fn provider_stage<R>(_:impl FnOnce()->bool,provider:impl FnOnce()->R)->Option<R>{Some(provider())}
fn deadline_current(_:std::time::Instant)->bool{true}
include!("authority-regression-tests.rs");
