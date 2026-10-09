//! Isolated model of the existing synchronous Engine→native wait, not full original source.
use std::sync::Mutex;
struct Dispatcher<Q,R>{provider:Mutex<Box<dyn FnMut(Q)->R+Send>>,result:Mutex<Option<(u64,u64,R)>>}
impl<Q:Send+'static,R:Send+'static> Dispatcher<Q,R>{
 fn start(provider:impl FnMut(Q)->R+Send+'static)->std::io::Result<Self>{Ok(Self{provider:Mutex::new(Box::new(provider)),result:Mutex::new(None)})}
 fn submit(&self,operation:u64,epoch:u64,input:Q)->bool{let result=(self.provider.lock().unwrap())(input);*self.result.lock().unwrap()=Some((operation,epoch,result));true}
 fn poll(&self,epoch:u64)->Option<(u64,R)>{self.result.lock().unwrap().take().filter(|r|r.1==epoch).map(|r|(r.0,r.2))}
 fn busy(&self)->bool{false}
}
#[cfg(test)] mod tests {include!("requirements.rs");}
