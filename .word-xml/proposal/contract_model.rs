//! Test-only single-destination call-sequence model. No Word authority or integration.
#[derive(Debug,PartialEq,Eq)]pub enum Outcome{Refused,Unknown,Complete}
pub trait DestinationModel{fn put_character(&mut self,offset:usize,value:char)->Result<(),()>;fn insert_xml(&mut self,xml:&str)->Result<(),()>;}
pub fn submit_model(original:&str,replacement:&str,xml:&str,destination:&mut impl DestinationModel)->Outcome{
 if xml.is_empty()||original.chars().count()!=replacement.chars().count(){return Outcome::Refused;}
 match destination.insert_xml(xml){Ok(())=>Outcome::Complete,Err(())=>Outcome::Unknown}
}
