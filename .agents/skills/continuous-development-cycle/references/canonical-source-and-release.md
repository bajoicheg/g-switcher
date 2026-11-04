# Canonical source, independent release and consumer locks

CDC 2.7 separates development authority, release evidence and consumer adoption.

## Canonical source

Exactly one canonical source repository owns the CDC release line. Product repositories may vendor released packages, but they are consumers rather than alternative CDC source repositories. Product-specific AGENTS, adapters, checkpoints and coordination records remain outside the core package.

CDC N is developed under stable CDC N-1. The candidate runtime must never become its only validator. Run an independent, standard-library-only bootstrap contract before candidate runtime imports. Keep bootstrap, package, compatibility, fault-injection and consumer evidence as separate release classes.

## Release identity

A release binds semantic version, immutable versioned release ref, exact release commit, exact package Git tree, independent bootstrap evidence, candidate package/test evidence, compatibility and fault-injection evidence, and validations from at least three distinct consumers when required by canonical release policy. Version strings or source-tree similarity alone are not release identity.

## Consumer lock

Consumers persist `cdc-consumer-lock/v1`. The lock binds canonical repository + version + release ref + release commit + package tree and requires checkpoint v4, a safe ownership boundary and an immutable vendored core. Validate with `scripts/consumer_lock.py`.

A consumer is drifted when its vendored core tree differs from the lock even if VERSION matches. Repair drift by materializing the exact canonical released package, not by editing the consumer copy.

## Safe convergence

Never advance a consumer lock across an active owner or unreconciled external guard. Require explicit release or independently verified quiescence, reconcile/clear guards, and preserve budget, validation and append-only audit history. Release/convergence recommendations do not grant product writes, takeover, external starts, merge or scheduler mutation.

## Self-hosting

The canonical repository may migrate its own development policy from N-1 to N only after N has independently reached released state. The released N policy can then drive development of N+1.
