#!/usr/bin/env python3
"""CDC 2.8.1 deterministic compact evidence projection."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
RESULTS={"PASS","FAIL","EXPECTED_RED","NOT_RUN"}
def compact(s):
    if not isinstance(s,dict) or set(s)!={"schema","scope_id","events"} or s.get("schema")!="evidence-stream/v1":raise ValueError("evidence stream invalid")
    if not isinstance(s["scope_id"],str) or not s["scope_id"].strip():raise ValueError("scope_id invalid")
    if not isinstance(s["events"],list):raise ValueError("events invalid")
    ids=set();rows=[];refs=[];counts={x:0 for x in sorted(RESULTS)}
    fields={"id","kind","result","ref","digest","terminal","detail"}
    for e in s["events"]:
        if not isinstance(e,dict) or set(e)!=fields:raise ValueError("event fields mismatch")
        if e["id"] in ids:raise ValueError("duplicate event id")
        ids.add(e["id"])
        if e["result"] not in RESULTS:raise ValueError("event result invalid")
        if type(e["terminal"]) is not bool:raise ValueError("terminal invalid")
        counts[e["result"]]+=1
        if e["ref"] not in refs:refs.append(e["ref"])
        rows.append({"id":e["id"],"kind":e["kind"],"result":e["result"],"ref":e["ref"],"digest":e["digest"],"terminal":e["terminal"]})
    raw=json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return {"schema":"canonical-evidence/v1","scope_id":s["scope_id"],"source_event_count":len(rows),"result_counts":counts,"terminal_event_count":sum(1 for x in rows if x["terminal"]),"evidence_refs":refs,"source_digest":"sha256:"+hashlib.sha256(raw).hexdigest(),"details_retained":False}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("stream");a=p.parse_args(argv)
    try:r=compact(json.loads(Path(a.stream).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
