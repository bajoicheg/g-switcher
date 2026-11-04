# CDC 2.11.2 adoption

Verified base: `bajoicheg/g-switcher@938a98957e44e0d4a8ebce735486e140ca1922fc` on `release/2.0.1`.
Canonical release: `48e637b230e7640d0dcd13da60d712f38f59a2b6` at `refs/heads/release/v2.11.2`.
Exact package tree: `7a7a7faa75b7fc9160d912d8fb507c6b9573d17f`.
Adapter policy revision: `2026-09-30-cdc-2.11.2-fleet-adoption`.
Adapter semantic digest: `43fb931928738c33b7b20e500bb31a90be3b9e49536f58498735720dd4070b1f`.
Recovery lease generation: 9; invocation: `chat-20261001-cdc2112-recovery-g-switcher`.

This is a process-only adoption from an exact released 2.11.1 base. The stopped prior chat made no shared source writes and no external submissions. The 2.11.2 package is assembled on a detached Git tree and exact subtree identity is verified before the shared source ref moves. Product runtime, Windows evidence, manual compatibility/final-review release gates, budget history and the owner's scheduler pause remain unchanged.

The canonical fault-injection fixture blob `907e50ecccf5bb56ff206394351966b502947eea` is mirrored at `.agents/fault-injection/scenarios.json` for retained package-suite portability without changing the immutable package subtree.

Final authoritative adoption evidence and lease release are written on `cdc/coordination`.
