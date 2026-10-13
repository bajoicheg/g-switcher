# CDC 2.6 control-plane audit

`scripts/control_plane_audit.py` validates an append-only `control-plane-audit-log/v1`. Each entry has a monotonic sequence, previous hash, canonical event hash and a digest of detailed evidence stored elsewhere. The chain detects deletion, reordering and mutation of already recorded control-plane decisions.

Audit events cover lease acquire/release, guard changes, policy adoption, scheduler drift, recovery, fleet assessment, SLO state change, version convergence and continuation delivery. Audit data is evidence, never authority.
