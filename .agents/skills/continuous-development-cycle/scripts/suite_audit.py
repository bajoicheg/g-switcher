"""Read-only exact-body test duplicate candidates; never deletion authority."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path


def audit(root):
    root=Path(root)
    groups={};count=0;uncertain=[]
    for path in sorted(root.glob('test_*.py')):
        if path.is_symlink():raise ValueError('symlink test file rejected')
        module=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(module):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                count+=1
                body=ast.dump(ast.Module(body=node.body,type_ignores=[]),include_attributes=False)
                key=hashlib.sha256(body.encode()).hexdigest()
                groups.setdefault(key,[]).append(path.name+':'+node.name)
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ('exec','eval','__import__'):
                uncertain.append(path.name)
    candidates=[{'body_sha256':key,'tests':items,'risk_mapping_required':True}
                for key,items in groups.items() if len(items)>1]
    return {'schema':'test-risk-audit/v1','test_methods':count,'duplicate_candidates':candidates,
            'dynamic_dependency_files':sorted(set(uncertain)),
            'automatic_deletion_allowed':False,'distinct_risk_coverage_proven':False}
