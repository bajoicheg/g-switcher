#[cfg(test)] mod authority_tests {
 use super::*;
 #[test] fn disconnected_stage_does_not_enter_provider() {
  let calls=std::cell::Cell::new(0);
  assert_eq!(provider_stage(||true,||{calls.set(calls.get()+1);7}),Some(7));
  assert_eq!(provider_stage(||false,||{calls.set(calls.get()+1);8}),None);
  assert_eq!(calls.get(),1,"revoked transport must prevent the NEXT provider stage");
 }
 #[test] fn expired_stage_does_not_enter_provider() {
  let expired=std::time::Instant::now()-std::time::Duration::from_secs(1);
  let calls=std::cell::Cell::new(0);
  assert_eq!(provider_stage(||deadline_current(expired),||{calls.set(1);7}),None);
  assert_eq!(calls.get(),0);
 }
}
