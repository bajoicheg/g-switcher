//! Standalone staged bounded Flat OPC text transformer. No COM/IPC/file/network I/O.
//! Caller-supplied evidence is a typed integration seam, NOT authenticated by XML.
//! This proposal is not enabled for Word dispatch or proven Word formatting fidelity.
use std::collections::BTreeMap;
pub const MAX_XML_BYTES:usize=65_536;
pub const MAX_TEXT_UNITS:usize=128;
pub const MAX_RUNS:usize=64;
const MAX_NODES:usize=512;
const MAX_DEPTH:usize=12;
const MAX_ATTRS:usize=16;
const MAX_ATTRIBUTE_BYTES:usize=256;
const PACKAGE_NS:&str="http://schemas.microsoft.com/office/2006/xmlPackage";
const WORD_NS:&str="http://schemas.openxmlformats.org/wordprocessingml/2006/main";
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct FreshBinding {
 pub operation:u128,pub word_pid:u32,pub word_birth:u64,pub document:[u8;32],
 pub range_start:u32,pub range_end:u32,pub input_epoch:u64,pub policy_epoch:u64,
}
#[derive(Clone,Debug,PartialEq,Eq)]
pub enum DependencyAssessment {Unknown,NoImplicitOrImportedDependencies}
#[derive(Clone,PartialEq,Eq)]
pub struct EffectiveDependencyEvidence {
 pub binding:FreshBinding,pub source_xml:String,pub source_context:[u8;32],pub destination_context:[u8;32],
 pub effective_per_utf16:Vec<[u8;32]>,pub dependencies:DependencyAssessment,
}
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct RunMapping {pub utf16_start:usize,pub utf16_len:usize,pub source_text_bytes:(usize,usize)}
#[derive(Clone,PartialEq,Eq)]
pub struct XmlPlan {
 xml:String,original:String,replacement:String,mapping:Vec<RunMapping>,
 effective_per_utf16:Vec<[u8;32]>,binding:FreshBinding,
}
impl XmlPlan {
 pub fn xml(&self)->&str{&self.xml}
 pub fn original(&self)->&str{&self.original}
 pub fn replacement(&self)->&str{&self.replacement}
 pub fn mapping(&self)->&[RunMapping]{&self.mapping}
 pub fn effective_per_utf16(&self)->&[[u8;32]]{&self.effective_per_utf16}
 pub fn binding(&self)->&FreshBinding{&self.binding}
}
impl std::fmt::Debug for XmlPlan {
 fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{f.debug_struct("XmlPlan").field("run_count",&self.mapping.len()).field("utf16_units",&self.effective_per_utf16.len()).finish_non_exhaustive()}
}
impl std::fmt::Debug for EffectiveDependencyEvidence {
 fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{f.debug_struct("EffectiveDependencyEvidence").field("dependencies",&self.dependencies).finish_non_exhaustive()}
}
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub enum Refusal {Bounds,MalformedXml,UnsupportedXml,UnsupportedText,OriginalMismatch,
 EvidenceRequired,EvidenceMismatch,DependencyUnproven,NoChange}
#[derive(Debug)]
struct Node {name:String,attrs:BTreeMap<String,String>,children:Vec<Node>,body_start:usize,body_end:usize,raw_text:String}
struct Parser<'a>{source:&'a str,at:usize,nodes:usize}
impl<'a> Parser<'a> {
 fn fail<T>(&self)->Result<T,Refusal>{Err(Refusal::MalformedXml)}
 fn whitespace(&mut self){while self.source.as_bytes().get(self.at).is_some_and(|b|b.is_ascii_whitespace()){self.at+=1;}}
 fn name(&mut self)->Result<String,Refusal>{
  let start=self.at;
  while self.source.as_bytes().get(self.at).is_some_and(|b|b.is_ascii_alphanumeric()||matches!(*b,b'_'|b':'|b'-')){self.at+=1;}
  if self.at==start||self.at-start>64{return self.fail();}Ok(self.source[start..self.at].to_owned())
 }
 fn node(&mut self,depth:usize)->Result<Node,Refusal>{
  self.nodes+=1;if depth>MAX_DEPTH||self.nodes>MAX_NODES{return Err(Refusal::Bounds);}
  if !self.source[self.at..].starts_with('<')||self.source[self.at..].starts_with("</"){return self.fail();}
  self.at+=1;let name=self.name()?;let mut attrs=BTreeMap::new();
  let empty;
  loop{
   let before=self.at;self.whitespace();
   if self.source[self.at..].starts_with("/>"){self.at+=2;empty=true;break;}
   if self.source[self.at..].starts_with('>'){self.at+=1;empty=false;break;}
   if before==self.at{return self.fail();}
   let key=self.name()?;self.whitespace();if self.source.as_bytes().get(self.at)!=Some(&b'='){return self.fail();}
   self.at+=1;self.whitespace();let quote=*self.source.as_bytes().get(self.at).ok_or(Refusal::MalformedXml)?;
   if !matches!(quote,b'\''|b'"'){return self.fail();}self.at+=1;let start=self.at;
   while self.source.as_bytes().get(self.at).is_some_and(|b|*b!=quote){self.at+=1;}
   if self.at>=self.source.len()||self.at-start>MAX_ATTRIBUTE_BYTES{return Err(Refusal::Bounds);}
   let value=decode(&self.source[start..self.at])?;self.at+=1;
   if attrs.insert(key,value).is_some(){return self.fail();}if attrs.len()>MAX_ATTRS{return Err(Refusal::Bounds);}
  }
  let body_start=self.at;let mut children=Vec::new();let mut raw_text=String::new();
  if empty{return Ok(Node{name,attrs,children,body_start,body_end:body_start,raw_text});}
  loop{
   if self.at>=self.source.len(){return self.fail();}
   if self.source[self.at..].starts_with("</"){
    let body_end=self.at;self.at+=2;let ending=self.name()?;self.whitespace();
    if ending!=name||self.source.as_bytes().get(self.at)!=Some(&b'>'){return self.fail();}self.at+=1;
    return Ok(Node{name,attrs,children,body_start,body_end,raw_text});
   }
   if self.source[self.at..].starts_with('<'){children.push(self.node(depth+1)?);}
   else{
    let start=self.at;while self.source.as_bytes().get(self.at).is_some_and(|b|*b!=b'<'){self.at+=1;}
    raw_text.push_str(&self.source[start..self.at]);
   }
  }
 }
}
fn decode(raw:&str)->Result<String,Refusal>{
 let mut result=String::new();let mut remaining=raw;
 while let Some(index)=remaining.find('&'){
  result.push_str(&remaining[..index]);remaining=&remaining[index+1..];let end=remaining.find(';').ok_or(Refusal::MalformedXml)?;
  if end>16{return Err(Refusal::MalformedXml);}let entity=&remaining[..end];
  let ch=match entity{
   "amp"=>'&',"lt"=>'<',"gt"=>'>',"quot"=>'"',"apos"=>'\'',
   _=>{let value=if let Some(hex)=entity.strip_prefix("#x"){if hex.is_empty()||!hex.bytes().all(|b|b.is_ascii_hexdigit()){return Err(Refusal::MalformedXml);}u32::from_str_radix(hex,16)}
    else if let Some(decimal)=entity.strip_prefix('#'){if decimal.is_empty()||!decimal.bytes().all(|b|b.is_ascii_digit()){return Err(Refusal::MalformedXml);}decimal.parse()}
    else{return Err(Refusal::UnsupportedXml);};char::from_u32(value.map_err(|_|Refusal::MalformedXml)?).ok_or(Refusal::MalformedXml)?}
  };
  if !graphic_bmp(ch){return Err(Refusal::UnsupportedText);}result.push(ch);remaining=&remaining[end+1..];
 }
 result.push_str(remaining);
 if result.contains('<')&&raw.contains('<'){return Err(Refusal::MalformedXml);}
 if result.chars().any(|ch|ch=='\0'||ch=='\r'||ch=='\n'||ch=='\t'||(ch as u32>=0xd800&&ch as u32<=0xdfff)){return Err(Refusal::UnsupportedText);}
 Ok(result)
}
fn graphic_bmp(ch:char)->bool{let value=ch as u32;value<=0xffff&&!ch.is_whitespace()&&!ch.is_control()&&!(0xfdd0..=0xfdef).contains(&value)&&!matches!(value,0xfffe|0xffff)}
fn token(value:&str)->Result<usize,Refusal>{
 let length=value.encode_utf16().count();if length==0||length>MAX_TEXT_UNITS{return Err(Refusal::Bounds);}
 if !value.chars().all(|c|graphic_bmp(c)&&matches!(c,'A'..='Z'|'a'..='z'|'А'..='я'|'Ё'|'ё')){return Err(Refusal::UnsupportedText);}Ok(length)
}
fn attrs(node:&Node,expected:&[(&str,&str)])->Result<(),Refusal>{
 if node.attrs.len()!=expected.len()||expected.iter().any(|(key,value)|node.attrs.get(*key).map(String::as_str)!=Some(*value)){return Err(Refusal::UnsupportedXml);}Ok(())
}
fn container<'a>(node:&'a Node,name:&str)->Result<&'a [Node],Refusal>{
 if node.name!=name||!node.raw_text.bytes().all(|b|matches!(b,b' '|b'\t'|b'\r'|b'\n')){return Err(Refusal::UnsupportedXml);}Ok(&node.children)
}
fn only<'a>(node:&'a Node,name:&str,child:&str)->Result<&'a Node,Refusal>{
 let children=container(node,name)?;if children.len()!=1||children[0].name!=child{return Err(Refusal::UnsupportedXml);}Ok(&children[0])
}
fn run_properties(node:&Node)->Result<(),Refusal>{
 attrs(node,&[])?;let mut seen=std::collections::BTreeSet::new();
 for property in container(node,"w:rPr")?{
  if !seen.insert(property.name.as_str())||!property.children.is_empty()||!property.raw_text.is_empty(){return Err(Refusal::UnsupportedXml);}
  let allowed:&[&str]=match property.name.as_str(){
   "w:b"|"w:i"|"w:bCs"|"w:iCs"=>&["w:val"],
   "w:sz"|"w:szCs"|"w:color"|"w:highlight"|"w:u"=>&["w:val"],
   "w:rFonts"=>&["w:ascii","w:hAnsi","w:eastAsia","w:cs"],
   "w:lang"=>&["w:val","w:eastAsia","w:bidi"],
   _=>return Err(Refusal::DependencyUnproven),
  };
  if property.attrs.keys().any(|k|!allowed.contains(&k.as_str())){return Err(Refusal::DependencyUnproven);}
  for value in property.attrs.values(){if value.is_empty(){return Err(Refusal::UnsupportedXml);}}
  match property.name.as_str(){
   "w:b"|"w:i"|"w:bCs"|"w:iCs"=>{if property.attrs.get("w:val").is_some_and(|v|!matches!(v.as_str(),"0"|"1"|"true"|"false"|"on"|"off")){return Err(Refusal::UnsupportedXml);}}
   "w:sz"|"w:szCs"=>{let value=property.attrs.get("w:val").ok_or(Refusal::UnsupportedXml)?;if !value.bytes().all(|b|b.is_ascii_digit())||!value.parse::<u32>().is_ok_and(|v|(1..=3276).contains(&v)){return Err(Refusal::UnsupportedXml);}}
   "w:color"=>{if !property.attrs.get("w:val").is_some_and(|v|v.len()==6&&v.bytes().all(|b|b.is_ascii_hexdigit())){return Err(Refusal::UnsupportedXml);}}
   "w:highlight"=>{if !property.attrs.get("w:val").is_some_and(|v|matches!(v.as_str(),"black"|"blue"|"cyan"|"green"|"magenta"|"red"|"yellow"|"white"|"darkBlue"|"darkCyan"|"darkGreen"|"darkMagenta"|"darkRed"|"darkYellow"|"darkGray"|"lightGray"|"none")){return Err(Refusal::UnsupportedXml);}}
   "w:u"=>{if !property.attrs.get("w:val").is_some_and(|v|matches!(v.as_str(),"single"|"double"|"none"|"words")){return Err(Refusal::UnsupportedXml);}}
   _=>{}
  }
 }
 Ok(())
}
fn escape_text(value:&str)->String{value.replace('&',"&amp;").replace('<',"&lt;").replace('>',"&gt;")}
pub fn prepare(xml:&str,original:&str,replacement:&str,binding:&FreshBinding,evidence:Option<&EffectiveDependencyEvidence>)->Result<XmlPlan,Refusal>{
 if xml.is_empty()||xml.len()>MAX_XML_BYTES{return Err(Refusal::Bounds);}
 let units=token(original)?;if token(replacement)?!=units{return Err(Refusal::UnsupportedText);}if original==replacement{return Err(Refusal::NoChange);}
 // Lexically reject XML features before parsing; no resolver or external resources exist.
 if xml.contains("<!")||xml.contains("<?")||xml.contains("]]>")||xml.chars().any(|c|((c as u32)<32&&!matches!(c,'\t'|'\n'|'\r'))||(0xfdd0..=0xfdef).contains(&(c as u32))||matches!(c as u32,0xfffe|0xffff))||xml.contains('\0'){return Err(Refusal::UnsupportedXml);}
 let mut parser=Parser{source:xml,at:0,nodes:0};parser.whitespace();let package=parser.node(0)?;parser.whitespace();if parser.at!=xml.len(){return Err(Refusal::MalformedXml);}
 attrs(&package,&[("xmlns:pkg",PACKAGE_NS)])?;
 let part=only(&package,"pkg:package","pkg:part")?;
 attrs(part,&[("pkg:name","/word/document.xml"),("pkg:contentType","application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")])?;
 let data=only(part,"pkg:part","pkg:xmlData")?;attrs(data,&[])?;
 let document=only(data,"pkg:xmlData","w:document")?;attrs(document,&[("xmlns:w",WORD_NS)])?;
 let body=only(document,"w:document","w:body")?;attrs(body,&[])?;
 let paragraph=only(body,"w:body","w:p")?;attrs(paragraph,&[])?;
 let runs=container(paragraph,"w:p")?;if runs.is_empty()||runs.len()>MAX_RUNS{return Err(Refusal::Bounds);}
 let mut flattened=String::new();let mut mapping=Vec::new();
 for run in runs{
  attrs(run,&[])?;let children=container(run,"w:r")?;
  let text=match children { [text]=>text,[props,text]=>{run_properties(props)?;text},_=>return Err(Refusal::UnsupportedXml)};
  if text.name!="w:t"||!text.children.is_empty(){return Err(Refusal::UnsupportedXml);}
  if text.attrs.is_empty(){attrs(text,&[])?;}else{attrs(text,&[("xml:space","preserve")])?;}
  let decoded=decode(&text.raw_text)?;let length=token(&decoded)?;let start=flattened.encode_utf16().count();flattened.push_str(&decoded);
  if flattened.encode_utf16().count()>MAX_TEXT_UNITS{return Err(Refusal::Bounds);}
  mapping.push(RunMapping{utf16_start:start,utf16_len:length,source_text_bytes:(text.body_start,text.body_end)});
 }
 if flattened!=original{return Err(Refusal::OriginalMismatch);}
 let proof=evidence.ok_or(Refusal::EvidenceRequired)?;
 if proof.dependencies!=DependencyAssessment::NoImplicitOrImportedDependencies{return Err(Refusal::DependencyUnproven);}
 if &proof.binding!=binding||proof.source_xml!=xml||binding.operation==0||binding.word_pid==0||binding.word_birth==0||binding.document==[0;32]
  ||binding.range_end.checked_sub(binding.range_start)!=Some(units as u32)||proof.source_context==[0;32]
  ||proof.source_context!=proof.destination_context||proof.effective_per_utf16.len()!=units||proof.effective_per_utf16.iter().any(|f|*f==[0;32]){return Err(Refusal::EvidenceMismatch);}
 let replacement_chars:Vec<char>=replacement.chars().collect();let mut transformed=xml.to_owned();
 for slice in mapping.iter().rev(){
  let content:String=replacement_chars[slice.utf16_start..slice.utf16_start+slice.utf16_len].iter().collect();
  let original_content:String=original.chars().skip(slice.utf16_start).take(slice.utf16_len).collect();
  if content!=original_content{transformed.replace_range(slice.source_text_bytes.0..slice.source_text_bytes.1,&escape_text(&content));}
 }
 if transformed.len()>MAX_XML_BYTES{return Err(Refusal::Bounds);}
 Ok(XmlPlan{xml:transformed,original:original.to_owned(),replacement:replacement.to_owned(),mapping,effective_per_utf16:proof.effective_per_utf16.clone(),binding:binding.clone()})
}

#[cfg(test)]
#[path="transform_tests.rs"]
mod tests;
