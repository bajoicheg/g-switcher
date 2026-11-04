#!/usr/bin/env python3
"""Qualify immutable supported Fleet control projections; never adopt or repair policy."""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from contracts import ContractError,load_yaml,require_supported_runtime
from validate_adapter import validate_adapter
from validate_checkpoint_24 import validate_checkpoint_24
ROOT=Path(__file__).resolve().parents[1]
PROVENANCE_SHA256='c06ebcfcfeab52883a5a1443d524192a86a1ca326d32e228fa923f0bada0b9e7'

def qualify(adapter,checkpoint,*,installed_version):
    require_supported_runtime(installed_version)
    candidate=(ROOT/'VERSION').read_text().strip()
    require_supported_runtime(candidate)
    for version in (installed_version,candidate):
        binding=validate_adapter(adapter,skill_version=version)
        if (checkpoint.get('policy_revision')!=binding['policy_revision'] or
                checkpoint.get('policy_digest')!=binding['policy_digest']):
            raise ContractError('supported snapshot policy binding mismatch')
        validate_checkpoint_24(checkpoint,adapter,skill_version=version)
    return dict(candidate_version=candidate,installed_version=installed_version,
                installation_compatible=True,qualification='supported_projection_compatible',
                migration_changes=[],authorizes_adoption=False,authorizes_policy_write=False)

def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON field: '+key)
        result[key]=value
    return result

def qualify_snapshots(snapshot_root,*,consumers,package_tree):
    if not isinstance(package_tree,str) or not re.fullmatch('[0-9a-f]{40}',package_tree):
        raise ValueError('package_tree must be exact Git tree SHA')
    if (not isinstance(consumers,(list,tuple)) or len(consumers)!=3 or len(set(consumers))!=3 or
            any(not isinstance(n,str) or not re.fullmatch('[A-Za-z0-9_-]+',n) for n in consumers)):
        raise ValueError('exactly three distinct consumer directory names required')
    pinned_raw=(ROOT/'templates/supported-consumer-provenance.json').read_bytes()
    if hashlib.sha256(pinned_raw).hexdigest()!=PROVENANCE_SHA256:
        raise ValueError('supported authenticated provenance binding changed')
    pinned=json.loads(pinned_raw.decode('utf-8'),object_pairs_hook=_unique)
    if pinned.get('schema')!='cdc-supported-consumer-pins/v1':
        raise ValueError('supported authenticated provenance schema invalid')
    pins=pinned['consumers']
    if set(consumers)!=set(pins):
        raise ValueError('supported authenticated consumer set binding mismatch')
    results=[]
    for name in consumers:
        root=Path(snapshot_root)/name
        paths=[root/'source.json',root/'development-cycle.yaml',root/'work-status.md']
        before=[p.read_bytes() for p in paths]
        source=json.loads(before[0].decode('utf-8'),object_pairs_hook=_unique)
        if (source.get('schema')!='cdc-supported-consumer-projection/v1' or source.get('projection') is not True or
                source.get('candidate_version')!=(ROOT/'VERSION').read_text().strip() or
                source.get('candidate_package_tree')!=package_tree or
                not re.fullmatch('[0-9a-f]{40}',source.get('source_commit',''))):
            raise ValueError(name+' supported source binding mismatch')
        for key in ('original_adapter_sha256','original_checkpoint_sha256'):
            if not re.fullmatch('[0-9a-f]{64}',source.get(key,'')):
                raise ValueError(name+' original provenance hash invalid')
        for key,raw in zip(('adapter_sha256','checkpoint_sha256'),before[1:]):
            if source.get(key)!=hashlib.sha256(raw).hexdigest():
                raise ValueError(name+' supported control hash mismatch')
        for key,expected in pins[name].items():
            if source.get(key)!=expected:
                raise ValueError(name+' authenticated provenance binding mismatch: '+key)
        adapter=load_yaml(paths[1]);checkpoint=load_yaml(paths[2],frontmatter=True)
        if source.get('repository')!=adapter['repository']['remote']:
            raise ValueError(name+' supported repository identity mismatch')
        result=qualify(adapter,checkpoint,installed_version=source.get('installed_version'))
        if [p.read_bytes() for p in paths]!=before:
            raise ValueError(name+' snapshot changed during qualification')
        results.append(dict(result,consumer=name,source_commit=source['source_commit'],projection=True))
    return dict(schema='supported-consumer-qualification/v1',consumers=results,package_tree=package_tree,
                snapshots_unchanged=True,authorizes_adoption=False,authorizes_policy_write=False)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot-root',required=True)
    p.add_argument('--consumers',nargs=3,required=True);p.add_argument('--package-tree',required=True);a=p.parse_args(argv)
    try:value=qualify_snapshots(a.snapshot_root,consumers=a.consumers,package_tree=a.package_tree)
    except (OSError,ValueError,TypeError,KeyError) as e:
        print('SUPPORTED_CONSUMERS_RED:',e);return 1
    print(json.dumps(value,sort_keys=True));print('THREE_SUPPORTED_CONSUMERS_QUALIFIED package_tree='+a.package_tree);return 0
if __name__=='__main__':raise SystemExit(main())
