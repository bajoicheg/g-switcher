"""Bounded evidence projection and actual installed runtime identity."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess

from active_package import _inventory, _version_errors
from package_transport import _tree_oid

MAX_BYTES = 8192


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def project(path, pointers, max_bytes=MAX_BYTES):
    if type(max_bytes) is not int or not 512 <= max_bytes <= MAX_BYTES:
        raise ValueError('projection byte limit must be 512..8192')
    path = Path(path)
    if not path.is_file() or path.is_symlink():raise ValueError('regular evidence file required')
    if not isinstance(pointers, list) or len(pointers) > 32 or len(set(pointers)) != len(pointers):
        raise ValueError('at most32 distinct JSON pointers required')
    raw = path.read_bytes()
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('duplicate JSON key')
            result[k]=v
        return result
    data = json.loads(raw, object_pairs_hook=unique)
    out={'schema':'compact-evidence/v1','source_sha256':hashlib.sha256(raw).hexdigest(),
         'source_bytes':len(raw),'values':{},'omitted':[],
         'authorizes_external_start':False,'authorizes_product_write':False}
    for pointer in pointers:
        if not isinstance(pointer,str) or not pointer.startswith('/'):
            raise ValueError('explicit nonroot JSON pointer required')
        value = data
        for part in pointer[1:].split('/'):
            if re.search(r'~(?![01])',part):raise ValueError('invalid JSON pointer escape')
            key=part.replace('~1','/').replace('~0','~')
            try:value=value[int(key)] if isinstance(value,list) and key.isdigit() else value[key]
            except (KeyError,IndexError,TypeError):raise ValueError('JSON pointer missing: '+pointer) from None
        if len(encode(value)) > max_bytes//2:
            value={'omitted':True,'sha256':hashlib.sha256(encode(value)).hexdigest(),
                   'bytes':len(encode(value))}
        proposed=dict(out, values={**out['values'],pointer:value})
        if len(encode(proposed))+1 <= max_bytes:
            out=proposed
        else:
            out['omitted'].append(hashlib.sha256(pointer.encode()).hexdigest())
            if len(encode(out))+1 > max_bytes:
                out['omitted']= ['remaining_selection_exceeds_limit']
                break
    if len(encode(out))+1 > max_bytes:raise ValueError('projection metadata exceeds byte limit')
    return out


def runtime_identity(request):
    required={'schema','runtime_root','version','package_tree','saved_commit',
              'loader_path','saved_loader_sha256','interface_loader_sha256','acceptance_ref'}
    if not isinstance(request,dict) or set(request)!=required or request['schema']!='runtime-identity/v1':
        raise ValueError('runtime identity request invalid')
    for k in ('package_tree','saved_commit'):
        if not re.fullmatch('[0-9a-f]{40}',request[k]):raise ValueError(k+' invalid')
    for k in ('saved_loader_sha256','interface_loader_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',request[k]):raise ValueError(k+' invalid')
    if not isinstance(request['acceptance_ref'],str) or not request['acceptance_ref'].strip():
        raise ValueError('saved acceptance provenance required')
    root=Path(request['runtime_root']);loader=Path(request['loader_path'])
    if not loader.is_file() or loader.is_symlink():raise ValueError('actual saved loader required')
    actual_loader=hashlib.sha256(loader.read_bytes()).hexdigest()
    files,_=_inventory(root)
    actual_tree=_tree_oid(files.values())
    errors=_version_errors(root,request['version'])
    if actual_tree!=request['package_tree']:errors.append('installed_tree_changed')
    if actual_loader!=request['saved_loader_sha256']:errors.append('saved_loader_changed')
    actual_commit=None
    try:
        def git(*args):
            return subprocess.check_output(['git','-C',str(loader.resolve().parent),*args],
                                           stderr=subprocess.DEVNULL,timeout=10)
        repository=Path(git('rev-parse','--show-toplevel').decode().strip())
        actual_commit=git('rev-parse','HEAD').decode().strip()
        relative=loader.resolve().relative_to(repository.resolve()).as_posix()
        saved_bytes=git('show',actual_commit+':'+relative)
        if actual_commit!=request['saved_commit']:errors.append('saved_commit_changed')
        if saved_bytes!=loader.read_bytes():errors.append('saved_loader_uncommitted')
    except (OSError,ValueError,subprocess.SubprocessError):
        errors.append('saved_revision_unavailable')
    stale=request['interface_loader_sha256']!=actual_loader
    return {'schema':'runtime-identity-result/v1','verified':not errors,'errors':errors,
            'actual_package_tree':actual_tree,'files':len(files),'saved_commit':actual_commit,
            'acceptance_provenance_verified':False,
            'acceptance_ref':request['acceptance_ref'],'stale_interface_snapshot':stale,
            'load_actual_saved_loader':stale and not errors,
            'requires_archive_extraction':False,'requires_FULL':False,
            'proves_agent_behavior':False,'authorizes_external_start':False}
