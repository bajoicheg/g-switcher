"""Read-only child admission check using the actual controller reservation AST."""
import ast
import copy
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
repo = os.environ.get('CDC_REPO_ROOT')
scripts = (Path(repo) / '.agents/skills/continuous-development-cycle/scripts'
           if repo else root.parent / 'word-hang-task/cdc2121/scripts')
sys.path.insert(0, str(scripts.resolve()))
import budget
import operation_intent as operation

pinned = json.loads((root / 'host-launch-intent.json').read_text())
tree = ast.parse((root / 'controller.py').read_text())
reservations = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'reservation' for t in n.targets)
                and isinstance(n.value, ast.Dict)]
assert len(reservations) == 1, 'Controller child reservation expression changed'
expression = compile(ast.Expression(reservations[0]), 'actual-controller-reservation', 'eval')
now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
contract = pinned['windows_contract']
binding = {'repository': 'bajoicheg/g-switcher',
           'candidate_sha': 'd272ae9cbb455b82a42a1d16ae0fa511287361b7',
           'backend': 'github_actions', 'mode': 'CI_ONLY',
           'check_suite_fingerprint': operation._hash(contract['steps']),
           'environment_fingerprint': operation._hash(contract['environment']),
           'check_plan_digest': operation._hash(contract),
           'environment_id': 'windows-latest/rust1.98.1'}
intent = operation.prepare(binding, 'read-only-child-budget-preflight',
                           'refs/heads/release/2.0.1', now)

def decide(configuration):
    namespace = {'pinned': configuration, 'intent': intent,
                 'ledger': pinned['budget_ledger'], 'key': 'read-only-child-budget-preflight',
                 'utc': lambda: now}
    reservation = eval(expression, {'__builtins__': {}}, namespace)
    return budget.decide(pinned['budget_ledger'], reservation)

baseline = copy.deepcopy(pinned)
baseline['windows_recovery_ref'] = None
red = decide(baseline)
assert not red['allow_reservation']
assert 'failure circuit open: fresh concrete correction/recovery evidence required' in red['reasons']
assert pinned['windows_recovery_ref'] == 'report:word-stalled-reader-fixture-corrected-windows-a5'
green = decide(pinned)
assert green['allow_reservation'], green
print('CHILD_BUDGET_PREFLIGHT_PASS actual-controller-AST; uncorrected-retry-denied; corrected-child-allowed; no reservation or launch performed')
