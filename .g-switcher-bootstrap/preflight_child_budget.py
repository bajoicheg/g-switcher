"""Read-only admission probe of the actual child expression and preserved ledger."""
import ast
import copy
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
scripts = Path(os.environ['CDC_REPO_ROOT']) / '.agents/skills/continuous-development-cycle/scripts'
sys.path.insert(0, str(scripts))
import budget
import operation_intent as operation

pinned = json.loads((root / 'host-launch-intent.json').read_text())
ledger = pinned['budget_ledger']
budget.validate_ledger(ledger)
tree = ast.parse((root / 'controller.py').read_text())
reservations = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'reservation' for t in n.targets)
                and isinstance(n.value, ast.Dict)]
assert len(reservations) == 1, 'Controller child reservation expression changed'
expression = compile(ast.Expression(reservations[0]), 'actual-controller-reservation', 'eval')
now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
contract = pinned['windows_contract']
binding = {'repository': 'bajoicheg/g-switcher',
           'candidate_sha': pinned.get('base', '436003d9287937d10606c74ae942b5518495d62a'),
           'backend': 'github_actions', 'mode': 'CI_ONLY',
           'check_suite_fingerprint': operation._hash(contract['steps']),
           'environment_fingerprint': operation._hash(contract['environment']),
           'check_plan_digest': operation._hash(contract),
           'environment_id': 'windows-latest/rust1.98.1'}
intent = operation.prepare(binding, 'read-only-child-budget-preflight',
                           'refs/heads/release/2.0.1', now)
namespace = {'pinned': pinned, 'intent': intent, 'ledger': ledger,
             'key': 'read-only-child-budget-preflight', 'utc': lambda: now}
reservation = eval(expression, {'__builtins__': {}}, namespace)
decision = budget.decide(ledger, reservation)
assert decision['allow_reservation'], decision
assert not decision['already_recorded'], 'A probe cannot replay a real submission'
assert decision['allow_launch'] is False

# Disposable cap fixtures cannot change the actual preserved ledger.
full = copy.deepcopy(ledger)
full['policy']['wake_limits']['ci_starts'] = budget.summarize(ledger)['wake']['ci_starts']
full['policy_digest'] = budget._digest(full['policy'])
denied = budget.decide(full, reservation)
assert not denied['allow_reservation']
assert 'wake ci_starts limit/reserve exceeded' in denied['reasons']
print('CHILD_BUDGET_PREFLIGHT_PASS actual-controller-AST; current-child-allowed; full-cycle-denied; no reservation or launch performed')
