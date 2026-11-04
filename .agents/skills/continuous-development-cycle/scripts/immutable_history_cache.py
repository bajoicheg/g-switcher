"""Bounded process-local JSON reuse. Entries are data, never permissions/proofs.

Callers must authenticate the endpoint, current ref and complete parent chain on
EVERY read. Cache lineage may save decoding an immutable verified prefix; it
cannot stand in for current head, policy, lease, PID or authority observations.
"""
from __future__ import annotations
from collections import OrderedDict
import json
import threading
import zlib

class _HistoryCache:
    def __init__(self, *, max_bytes=16*1024*1024, max_entries=32, max_decoded_bytes=128*1024*1024):
        self._max_bytes=max_bytes;self._max_entries=max_entries
        self._max_decoded_bytes=max_decoded_bytes
        self._entries=OrderedDict();self._bytes=0;self._lock=threading.RLock()
    @staticmethod
    def _encode(value):
        return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    def _decode(self, raw):
        try:
            decoder=zlib.decompressobj()
            decoded=decoder.decompress(raw,self._max_decoded_bytes+1)
            if (len(decoded)>self._max_decoded_bytes or decoder.unconsumed_tail
                    or not decoder.eof or decoder.unused_data):
                raise ValueError('compact history exceeds its decoding bound or is incomplete')
            return json.loads(decoded)
        except (zlib.error,UnicodeError,json.JSONDecodeError) as error:
            raise ValueError('compact history encoding changed') from error
    def get(self, context):
        key=self._encode(context)
        with self._lock:
            raw=self._entries.get(key)
            if raw is None:return None
            self._entries.move_to_end(key)
        # Detached decoding prevents any caller from changing a shared prefix.
        return self._decode(raw)
    def put(self, context, snapshot):
        key=self._encode(context);decoded=self._encode(snapshot)
        if len(decoded)>self._max_decoded_bytes:return
        raw=zlib.compress(decoded,level=1);size=len(key)+len(raw)
        if size>self._max_bytes:return
        with self._lock:
            previous=self._entries.get(key)
            if previous is not None:
                old=self._decode(previous)['chain'];new=snapshot['chain']
                if new[:len(old)]!=old:
                    # A concurrent older reader may finish after a newer one.
                    # Keep the newer observation; never downgrade stored lineage.
                    if old[:len(new)]==new:return
                    raise ValueError('authenticated cached history diverged')
                self._bytes-=len(key)+len(previous)
            self._entries[key]=raw;self._entries.move_to_end(key);self._bytes+=size
            while self._bytes>self._max_bytes or len(self._entries)>self._max_entries:
                discarded,value=self._entries.popitem(last=False);self._bytes-=len(discarded)+len(value)

_cache=_HistoryCache()

def _context(store, kind, binding=None):
    return {'kind':kind,'repo':str(store.repo.resolve()),'remote':store.remote,'ref':store.ref,
            'endpoint':store.store_id,'binding':binding}

def _linear_chain(rows, *, anchor=None):
    """Authenticate the fresh complete ordered graph, including cached parents."""
    import re
    revision=re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
    chain=[];previous=anchor;seen=set()
    for row in rows:
        parts=row.split()
        if (not parts or any(not revision.fullmatch(value) for value in parts)
                or parts[0] in seen or parts[1:]!=([previous] if previous else [])):
            raise ValueError('native coordination history must preserve one complete parent chain')
        seen.add(parts[0]);chain.append(parts);previous=parts[0]
    return chain
