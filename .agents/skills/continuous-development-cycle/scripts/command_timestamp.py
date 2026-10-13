#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path

SCHEMA="command-timestamp-request/v1"
ALLOWED={"runtime_clock","authoritative_time_source"}
MSK=timezone(timedelta(hours=3))
MAX_AGE_SECONDS=90
MAX_FUTURE_SKEW_SECONDS=5

def _aware(value,name):
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)

def validate(d):
    if not isinstance(d,dict) or set(d)!={"schema","command_id","observed_at","time_source","already_timestamped_command_ids"} or d.get("schema")!=SCHEMA:
        raise ValueError("invalid command timestamp request")
    if not isinstance(d["command_id"],str) or not d["command_id"].strip() or d["time_source"] not in ALLOWED:
        raise ValueError("fresh observed time source required")
    ids=d["already_timestamped_command_ids"]
    if not isinstance(ids,list) or len(ids)!=len(set(ids)) or any(not isinstance(x,str) or not x.strip() for x in ids):
        raise ValueError("timestamp ledger invalid")
    try:
        dt=datetime.fromisoformat(d["observed_at"].replace("Z","+00:00"))
    except (AttributeError,ValueError) as e:
        raise ValueError("observed_at must be ISO-8601") from e
    if dt.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return dt.astimezone(timezone.utc)

def render(d,*,now=None):
    observed=validate(d)
    current=_aware(now if now is not None else datetime.now(timezone.utc),"now")
    skew=(observed-current).total_seconds()
    age=(current-observed).total_seconds()
    if skew>MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("observed_at is ahead of fresh wall clock")
    if age>MAX_AGE_SECONDS:
        raise ValueError("observed_at is stale; acquire fresh wall clock")
    if d["command_id"] in d["already_timestamped_command_ids"]:
        return {"schema":"command-timestamp-evidence/v1","action":"SUPPRESS_DUPLICATE","command_id":d["command_id"],"display":None,"timezone":"Europe/Moscow","source":d["time_source"],"authorizes_anything":False}
    return {"schema":"command-timestamp-evidence/v1","action":"EMIT_ONCE","command_id":d["command_id"],"display":observed.astimezone(MSK).strftime("[%H:%M %d.%m]"),"timezone":"Europe/Moscow","source":d["time_source"],"authorizes_anything":False}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("input");a=p.parse_args(argv)
    try:r=render(json.loads(Path(a.input).read_text()))
    except (OSError,ValueError,json.JSONDecodeError) as e:
        print(f"FAIL: {e}",file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True,ensure_ascii=False));return 0

if __name__=="__main__":
    raise SystemExit(main())
