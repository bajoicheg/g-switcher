use crate::contract::*;
struct FailingDestination { attempts:usize, prefix:String }
impl DestinationModel for FailingDestination {
 fn put_character(&mut self,_offset:usize,value:char)->Result<(),()> {self.attempts+=1;if self.attempts>2{return Err(());}self.prefix.push(value);Ok(())}
 fn insert_xml(&mut self,_xml:&str)->Result<(),()> {self.attempts+=1;Err(())}
}
#[test]
fn one_destination_attempt_even_when_destination_outcome_unknown() {
 let mut destination=FailingDestination{attempts:0,prefix:String::new()};
 assert_eq!(submit_model("ghbdtn","привет","<synthetic-xml/>",&mut destination),Outcome::Unknown);
 assert_eq!(destination.attempts,1,"per-character baseline makes several submissions and leaves prefix");
}
#[test]
fn missing_prepared_model_payload_has_zero_destination_calls() {
 let mut destination=FailingDestination{attempts:0,prefix:String::new()};
 assert_eq!(submit_model("abc","ab","",&mut destination),Outcome::Refused);
 assert_eq!(destination.attempts,0);
}
#[test]
fn successful_single_call_receives_exact_prepared_xml_without_plaintext_put() {
 struct Successful {xml:Option<String>,puts:usize}
 impl DestinationModel for Successful {
  fn put_character(&mut self,_offset:usize,_value:char)->Result<(),()>{self.puts+=1;Err(())}
  fn insert_xml(&mut self,xml:&str)->Result<(),()>{assert!(self.xml.is_none());self.xml=Some(xml.to_owned());Ok(())}
 }
 let mut destination=Successful{xml:None,puts:0};
 assert_eq!(submit_model("abc","xyz","<prepared-xml/>",&mut destination),Outcome::Complete);
 assert_eq!(destination.xml.as_deref(),Some("<prepared-xml/>"));assert_eq!(destination.puts,0);
}
