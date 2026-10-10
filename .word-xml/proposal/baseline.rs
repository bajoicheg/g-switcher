//! Honest per-character contract model, not original Word runtime/executable.
mod contract {
 #[derive(Debug,PartialEq,Eq)] pub enum Outcome{Refused,Unknown,Complete}
 pub trait DestinationModel{fn put_character(&mut self,offset:usize,value:char)->Result<(),()>;fn insert_xml(&mut self,xml:&str)->Result<(),()>;}
 pub fn submit_model(original:&str,replacement:&str,xml:&str,destination:&mut impl DestinationModel)->Outcome{
  if xml.is_empty()||original.chars().count()!=replacement.chars().count(){return Outcome::Refused;}
  for (offset,(old,new)) in original.chars().zip(replacement.chars()).enumerate(){
   if old!=new&&destination.put_character(offset,new).is_err(){return Outcome::Unknown;}
  }
  Outcome::Complete
 }
}
#[path="shared_contract_tests.rs"]mod tests;
#[test]
fn baseline_model_exposes_two_completed_prefix_before_failure() {
 use contract::*;
 struct Partial {attempts:usize,text:String}
 impl DestinationModel for Partial {
  fn put_character(&mut self,_offset:usize,value:char)->Result<(),()>{self.attempts+=1;if self.attempts==3{return Err(());}self.text.push(value);Ok(())}
  fn insert_xml(&mut self,_xml:&str)->Result<(),()>{panic!("baseline does not submit XML")}
 }
 let mut state=Partial{attempts:0,text:String::new()};
 assert_eq!(submit_model("ghbdtn","привет","<synthetic-xml/>",&mut state),Outcome::Unknown);
 assert_eq!(state.text,"пр");assert_eq!(state.attempts,3);
}
