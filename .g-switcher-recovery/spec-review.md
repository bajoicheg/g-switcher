# Exact diagnostic result recovery preflight: independent SPEC review

## Verdict

**PASS for this information-gathering preflight implementation; no blocking source finding.** This verdict does not cover takeover implementation, quiescence admission, publication or artifact delivery. Existing user-authorized continuation covers this bounded recovery inquiry; no additional approval is needed for the reviewed scope.

| Inspected file | SHA-256 |
| --- | --- |
| `preflight.py` | `b68d84f81adaf0a7d9145f263e426d6b9d915464db33bc87cd1a65e90f8d12d1` |
| `plan.md` | `c06bd133a76956eb71985cbe61770a1432dbb611d152794aafd067f012a0e308` |
| `original-worker.py` | `04a9e38ec5ed9f4e3ccec1425a41303b06639b0280340c2bdef7eae987e70ee5` |
| `checks.json` | `ac2e93b0bd2d87265713dc92d071673f04f04fdc68de0aace2700ccbfb7549b9` |
| `result.json` | `17511970d1c9e3ad68e656e88c08884112b95dbdf0f36467d031735f38205950` |

Read source and plan directly against the earlier blocked handoff and canonical API review. Did not run preflight, launch work, acquire ownership, write remote/product refs or rerun tests. Only this report was written.

## Required behavior verified in source

- Enforces exact local source HEAD/clean checkout and canonical package tree, original worker bytes/hash, original evidence raw hashes and matching five successful checks/result identity. Live GitHub API reads bind artifact11552529665 to exact artifact digest, original run37783419838 and orchestration head8f548515; original job113331980853 must be completed/failure. Raw evidence hashes originate from the parent's previously authenticated artifact; this script checks those pinned inputs rather than downloading/re-deriving the archive itself.
- Reconstructs in a detached local worktree from exact base10b7e90, verifies original/payload bytes, formats with Rustfmt1.98.1, reproduces validation record bytes and requires exactly the original prepared paths. Bounded timestamp search uses a fixed parent/tree/identity/message and accepts only full exact commit SHA3407a2d0570b88864fd265de61a8761999995380. Any tree/record/formatter difference prevents reuse through hash mismatch. Past checks are associated with that same commit only; no product suite is rerun.
- Writes the recovered commit and ref only in the local checkout, then creates/verifies result.bundle and preserves formatted path bytes before touching the remote dry-run. These local artifact operations are consistent with a remote-read-only preflight.
- Reads authoritative source ref before and after the dry-run and requires exact unchanged base. Remote command includes explicit dry-run, isolated canonical remote arguments, no followTags and exact source-head lease. No lease APIs or remote update command without dry-run exists. Reconstructed commit has direct exact-base parent; the probe does not imply force-rewrite authority.
- Retains numeric/static report fields and allow-listed rejection classes only, never raw captured Git stdout/stderr. Final sanitized report records bundle digest and lack of Windows CI/new EXE. If probe fails, the already-created bundle and report remain available for workflow artifact capture.

## Evidence interpretation boundaries

1. **Completed job is not full executor-stopped evidence.** Current script checks terminal job metadata, but does not read/validate cleanup2943 log lines, supervisor/worker birth identities, descendant quiescence or exact prior lease binding. The plan's phrase “authenticate cleanup2943” must be interpreted as a later recovery requirement, not a fact proven by this implementation. It is acceptable here because preflight performs no ownership attempt. Do not use preflight.json alone as takeover quiescence.
2. **Dry-run success is transport/preflight success, not publication acceptance.** Git dry-run does not prove server receive hooks/rules would accept a real update. The report's `dry_run_reason: accepted` is scoped by its dry_run field; it must not be promoted into conditional_update/publication evidence or proof that the original rejection has a remedy. Unknown rejection remains unclassified; no replay or lease acquisition follows from this script.
3. **Exact object recovery preserves prior result, not old ownership.** Reconstruction does not release generation31 or authorize generation32. Later takeover requires separate authenticated quiescence review, fresh source/coordination observations, package-managed terminal capability and normal final release. Preflight failure blocks that dependent action.
4. **Preservation still depends on host artifact capture.** This script saves local bundle/formatted bytes/report; the enclosing recovery CI must upload them even on dry-run failure. No restored remote candidate is claimed here.

All original product gates remain mandatory. A recovery dry-run cannot stand in for Windows exact-candidate acceptance, actual Word diagnostics, an EXE build or delivery. No such success is claimed by this review.
