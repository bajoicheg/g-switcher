# Managed diagnostic recovery a4 independent quality review

**FINAL PASS for current a4 source/pipeline after persisted SPEC PASS; no concrete blocker found.** Supersedes earlier route bindings. No launch or remote action by this reviewer.

| Artifact | SHA-256 |
| --- | --- |
| `admission.py` | `6babb162a627edd05e064476cea5ee1a67fa4113b08d55a6553ef5110be20eb8` |
| `runtime_factory.py` | `a894e91261575f6bebf5d19ae66d7476cd58f73cd22cd19cc0fa47ff920c8058` |
| `github_api.py` | `fc6633fa9fec5c9f54a27e6bd16ad1f11b520a8e34fb13491bc7e474068eeac0` |
| `controller.py` | `c2642f1de56dd9f62e83684a73ad8f251a50ab6e690d9f12f5b94a634517905b` |
| `worker.py` | `2f1e33d3d28e4de972b795f1cd8681db5b00422b10ca4e45a7d68063409f74a7` |
| `windows_bundle_gate.py` | `13a486b7bdbef99e6bf70d0d2f98c4f2ab1021409dc7652eaa7b50cf8041aa58` |
| `host_step.py` | `a0f52fc41dd4ed07ea01adf70ed3604e317aa25502aa9a6a5da359b6f64e7912` |
| `preflight.py` | `bee6d63bc4141d73f818a5110b2ddc2ee52e19f3bb8bbb37c1fba4914a2c31a6` |
| `original-worker.py` | `04a9e38ec5ed9f4e3ccec1425a41303b06639b0280340c2bdef7eae987e70ee5` |
| `checks.json` | `ac2e93b0bd2d87265713dc92d071673f04f04fdc68de0aace2700ccbfb7549b9` |
| `result.json` | `17511970d1c9e3ad68e656e88c08884112b95dbdf0f36467d031735f38205950` |
| `windows-ci.yml` | `52f433e73683b47a53b27d2fba4de4664bb4ce5f8c2800dc74966b6402d37d5f` |
| `word-bootstrap.yml` | `c83fe6ddc19c5cf26e8f4946119262c8cd790594b0b266838d6376ff86acfa7b` |
| `bundle_worker.py` | `2530bc7979d8341dd28adc9809184534892c676088be2468da8939b9bcf89e75` |
| `stable_reader.py` | `560e878636d84f3f1307e0537a6807baf91d53f91c5e535215656eab2147fe3f` |
| `reconcile_prior.py` | `2f57840dc3683862245fc71f7935067512bf55c5b0340f68674134fbb072613f` |
| `host-launch-intent.json` | `a9105dce3551139c3ce4043b5d44ee737cc5b9a34ffcc6c23266e56661d4909a` |

The bounded stable snapshot reader restarts the entire ref→immutable-content→ref read on legitimate CAS drift, with a maximum12 attempts. Consumers still validate exact owner/generation/invocation/source/expiry/guard/claim and child admission on the resulting immutable snapshot; retry does not soften any security predicate or reuse earlier successful values. New tests exercise full-snapshot restart and bounded failure rather than accepting mixed-revision data.

Fresh canonical generation34 acquisition binds exact released33 revision/last_release and preserved external guard. The new read-only worker waits behind an additional controller reconciliation marker before bundle work. reconcile_prior authenticates the precise old terminal attempt1/run/job/head/title, original intent/claim/child admission, audited gate hash, exact snapshot-race traceback and all26 product steps skipped. It records requested-binding-only setup failure, not candidate admission/validation success. The old operation update uses normal CAS/readback, then current34 ownership resolves the inherited guard with canonical clear_guard/CAS/readback and verifies the old33 grant resolution before opening the secondary worker gate. No manual lease rewrite, fake old success or ownership transfer shortcut appears.

For future pre-admission failure, parent reconciliation requires the exact REQUEST marker, terminal failure of the gate step and all26 product steps skipped. REQUEST is never treated as PASS; successful validation still requires the full authenticated candidate/operation/grant/run/attempt PASS marker and terminal success. Actual child run/attempt/job/head and one-use admission remain checked. Unknown/missing proof continues to preserve the effect/guard rather than resubmit.

The immutable prior bundle remains authenticated and reused without reconstruction or repetition of prior successful checks. Prepared Windows head `ff2aeaf76a98df223905b865f39c274c7a12da2e` pins generation34 and the new snapshot helper; all26 product contract steps remain exact. Source stays10b and frozen candidate3407 is loaded only in the governed child. Existing TTL2700, genuine gated supervisor, source-bound intent/claim, read-only finish and no product publication remain. Credentials/output capture retain prior reviewed handling.

All25 budget events are preserved, including real child reservation and setup failure/remedy history. Disclosed cap6→8 adjustment retains old/new policy digests, explicit continue authorization, concrete bounded repair/mandatory validation rationale and unknown provider quota. It does not refund, restore quota, create a fake wake or alter package budget decisions. Final durable bootstrap must preserve the reviewed policy/intent/actual-head/new-admission binding.

Verification here: complete changed source/pipeline review, all16 payload hashes and final intent `a9105dce3551139c3ce4043b5d44ee737cc5b9a34ffcc6c23266e56661d4909a`, Python ASTs/YAML and exact26 contract comparison. Parent reports snapshot-race RED and two GREEN tests; the inherited-guard canonical integration is still reported running at this review boundary, so no result is claimed for it. No tests, CI, Word/browser operation or remote mutation performed by this reviewer. Actual a4 admission, inherited-guard resolution/release, real Windows terminal outcome, EXE build and installed application acceptance remain runtime evidence requirements.
