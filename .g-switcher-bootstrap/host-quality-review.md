# Restart-guard host transport: independent QUALITY review

Verdict: **PASS for the staged host transport source after targeted correction.** This is not launch acceptance. Review was source-only; no tests, workflows, remote writes, or product edits performed.

## Targeted correction verified

`word-bootstrap.yml` now sets job-level `RUSTUP_TOOLCHAIN: 1.98.1`. It is inherited by the host/controller and managed worker's bare Rust commands, matching the installed compiler, rustfmt, Clippy and GNU target. `prepare_host.py` now reproduces that setting. This resolves the prior toolchain-selection blocker. No test execution or measured compiler/CI success is claimed.

The worker's RED invocation uses the exact `tests::restart_refuses_previous_pending_before_any_provider_call` filter with `--exact`, expected exit 101 and required FAILED output. Zero selected tests exit successfully and cannot pass this gate. GREEN now compiles an external wrapper whose #[path] imports the installed production guard core as a module, preserving pub(super) context. The worker also requires each payload-declared regression name to appear as passed in the GREEN log, rejecting zero GREEN tests when that required list is nonempty. Completeness and fidelity of that list and baseline remain pending the completed product payload; no previous portable prototype is accepted as final.

## Reviewed behavior

The worker binds clean BASE and original file hashes before edits, waits for generation admission, compiles RED before installing product files, requires the exact named test to exit 101 with FAILED output, then compiles/tests GREEN and runs library tests, GNU typed compilation, Clippy, format and scope checks. It commits an isolated candidate and exports a hash-bound bundle. Terminal Windows evidence must name that candidate, mark guard reconciliation, and conclude succeeded before worker success. A Windows failure makes the worker fail; the controller's success finish requires pending succeeded, so the reviewed path cannot intentionally publish a failed Windows candidate. Product-test fidelity itself awaits the complete product payload/baseline.

The controller retains canonical exact-type ownership, source-ref guard binding, one-use host CAS, authenticated prior released generation, isolated writer scope, dynamic candidate binding, authentic artifact digest/bundle verification, durable validation intent and budget reservation, fresh canonical submission claim, actual child-run admission and exact run/attempt/head/job/log binding. Guard clearing requires authenticated terminal observation; unresolved provider outcomes remain unreconciled rather than being classified as success. Bundle gate rechecks canonical ownership/source/claim before product checks. Token headers are not forwarded to storage redirects; child gate has read-only GitHub permissions. No added forced pushes, scheduler, merge, or release publication was found in these staged files.

## Outstanding acceptance boundary

Host-launch intent, product payload, baseline tests, budget ledger, durable bootstrap document/readbacks and exact Windows/control heads are absent or pending. Their completeness/hash consistency, source scope and canonical released34/nullguard admission must be reviewed before launch acceptance. Full Windows CI and actual installed Word acceptance are not yet evidence; this review makes no Word hang-fix or provider recovery claim. `prepare_host.py` regenerates staged files from the prior transport, and the generator now preserves the selected host toolchain.

## Exact staged binding

| File | SHA-256 |
| --- | --- |
| `controller.py` | `99c97acde0905cde48ab92cc3536c2f73401382138ddea3c9bb43d14983e2bd2` |
| `worker.py` | `67243a48bd7a3f8873600663de3969a02c1c90a2d9c8888ac689291fb3b0a261` |
| `word-bootstrap.yml` | `9303251a6bbb687c07435385f3aa302ee5119c59f8e53abc480371e3231bbaee` |
| `windows-ci.yml` | `a5312c06586dc420ca2c585ecc7c6d28152a8a6857ed34742295c597848710e9` |
| `windows_bundle_gate.py` | `faf862a3b6e4233db9f7ec7048be0388cf9e3754a582e203393e44c59b34dc3d` |
| `host_step.py` | `a0f52fc41dd4ed07ea01adf70ed3604e317aa25502aa9a6a5da359b6f64e7912` |
| `runtime_factory.py` | `a894e91261575f6bebf5d19ae66d7476cd58f73cd22cd19cc0fa47ff920c8058` |
| `github_api.py` | `fc6633fa9fec5c9f54a27e6bd16ad1f11b520a8e34fb13491bc7e474068eeac0` |
| `stable_reader.py` | `560e878636d84f3f1307e0537a6807baf91d53f91c5e535215656eab2147fe3f` |
| `constants.py` | `627c8c41c799c69c6903fae4dbfc1887ae14a09e892b1d516245df83722c3dd7` |
| `prepare_host.py` | `604d8baaf9eed6ac1946ace91dc77a06dc5336ae975ac39e217d34eb59160a63` |
