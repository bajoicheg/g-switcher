//! RED harness only: intentionally models current process-local restart reset.
//! Not a proposed implementation and not an exact-source product baseline.
use std::path::PathBuf;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Host { pid: u32, birth: u64 }
#[derive(Clone, Debug)]
struct Operation { host: Host, id: u64 }
#[derive(Clone, Debug)]
struct Child { operation: Operation, id: u64 }
struct Gate { root: PathBuf, busy: bool, next: u64 }
impl Gate {
    fn open(root: PathBuf) -> Self { Self {root,busy:false,next:0} }
    fn begin(&mut self, host: Host) -> Option<Operation> {
        if self.busy {return None;} self.busy=true; self.next+=1;
        // Harness writes an unverified marker but ignores it after restart.
        let _=std::fs::write(self.root.join(format!("{}-{}.pending",host.pid,host.birth)),b"pending");
        Some(Operation {host,id:self.next})
    }
    fn child(&mut self, op:&Operation)->Option<Child>{Some(Child{operation:op.clone(),id:1})}
    fn quarantine(&mut self,_op:&Operation)->Result<(),&'static str>{Ok(())}
    fn parent_complete(&mut self,_op:&Operation,_uncertain:bool)->Result<(),&'static str>{self.busy=false;Ok(())}
    fn child_complete(&mut self,_child:Child)->Result<(),&'static str>{self.busy=false;Ok(())}
}
include!("requirements_tests.rs");
