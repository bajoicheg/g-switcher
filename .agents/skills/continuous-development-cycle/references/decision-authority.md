# CDC 2.8.1 decision authority

CDC should not ask the user to make routine mechanical engineering choices that are already within authorized scope.

Automatic execution is allowed only when all of the following are true:

- scope remains existing;
- risk is low or medium;
- the action is reversible or compensatable;
- it is not destructive;
- it does not require a missing secret;
- it does not cross a protected approval/environment gate;
- project policy pre-approves the action;
- a durable authorization reference exists.

Any high-risk, irreversible, destructive, scope-expanding, secret-dependent or protected-gate action is a human boundary. Missing authority is BLOCKED rather than guessed. The decision classifier never creates authority.
