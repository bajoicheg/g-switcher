# Independent host launch SPEC review

Verdict: PASS for current host launch source and bindings; product source review is separate.

Inspected intent SHA256: `e1669d1f394074cd29dc0c323fc0d18794d031aad9c4e90d1364c726df7a84bf`. Normalized product payload SHA256: `b55d7e55c8517e145d776f59299bdde43651d052df23b260196493b7c3f4b1d9`. All 16 intent payload bindings match current bytes; all 12 proposed Rust source strings equal the independently authored frozen proposal. Baseline and shared requirements copies match.

## Corrected targeted finding

Previous intent `afb9738055484c1e2c0ef7493b02f496975fdf2fb33fc52a4d6fb650bb94a48c` was blocked because worker Git `.strip()` corrupted leading porcelain status bytes. Current `worker.py:23` uses `.rstrip('\n')`, preserving fixed-column parsing at line87. This resolves the concrete blocker. Root reports the actual Python leading-space regression and syntax checks passed; this reviewer inspected corrected bytes and bindings, without running product/Rust tests. Prior intent was not launched or durably published; replacement retains all28 carried events plus one prepared host reservation, rather than refunding an actual start.

## Other route findings

- Pinned prior lease is released generation34, revision `658f63bd8b7580becfceec329ee5adf22e0d8abf`, exact last_release, null owner/invocation/finalization/guard. Authentication callback rechecks source10b and exact readback before ordinary canonical generation35 acquisition; it supplies no stale quiescence evidence. Runtime factory keeps exact original canonical class/store/backend/capability and delegates public acquisition with TTL2700 seconds.
- Bootstrap prepared→claimed CAS binds actual host SHA, attempt1, intent digest and full ledger before bridge.start. The bridge owns the one-use pool and genuine worker gate. Product worker verifies base, originals and payload, waits for actual admission, compiles and executes named baseline RED before applying source; then checks actual applied core GREEN, formatting, portable tests, Windows typed compile and Clippy before commit/bundle. No product compute starts from a mere routing result.
- Windows dispatch consumes fresh canonical guard claim after durable intent, budget and readbacks. Child admission CAS binds exact run/attempt1/job/grant/operation; gate checks actual workflow SHA against durable Windows head, live owned generation35/expiry/source/claim, authenticated artifact digest and exact bundle candidate, then rechecks admission/lease before mandatory checks. Contract equals every workflow step after the gate (26 entries), preserving all mandatory gates.
- Worker refuses terminal Windows non-success. Controller cannot publish a failed candidate: its normal finish path demands pending succeeded; failures signal real worker failure and use canonical failed finish, retaining unresolved guard where applicable. Source publication remains canonical conditional writer finish; no merge/release/scheduler mutation is introduced.
- Ledger preserves all28 carried events byte-for-value and appends one host reservation (29 total). Child reservation is decided/applied before dispatch with concrete recovery reference, no refunded history or known-provider-quota claim. Bounds: controller35min, worker/pool40min, TTL45min, host job48min and Windows job45min; timeout is fail-closed rather than promised validation completion.

No remote mutation, host launch, Rust/product test execution or installed Word acceptance was performed by this review. Current worker and all16 intent payload hashes have been rebound and verified. This PASS authorizes no claim of successful host execution, Windows validation or installed Word behavior.

## Inspected payload hashes

- `constants.py`: `627c8c41c799c69c6903fae4dbfc1887ae14a09e892b1d516245df83722c3dd7`
- `controller.py`: `99c97acde0905cde48ab92cc3536c2f73401382138ddea3c9bb43d14983e2bd2`
- `github_api.py`: `fc6633fa9fec5c9f54a27e6bd16ad1f11b520a8e34fb13491bc7e474068eeac0`
- `host-quality-review.md`: `844443fb265d682ae13c160c63a8fd0c5abb4bbb38bd49ec9692d323bd0fa87e`
- `host_step.py`: `a0f52fc41dd4ed07ea01adf70ed3604e317aa25502aa9a6a5da359b6f64e7912`
- `product-payload.json`: `b55d7e55c8517e145d776f59299bdde43651d052df23b260196493b7c3f4b1d9`
- `product-quality-review.md`: `ade9d1868b051907cb63705c751384ef8f1cbf4ae179fc67f6b34d36934c6db3`
- `protocol-tests/baseline.rs`: `ba30f71c4332baffb78c7f99c9a3cecad658984fa887144a95a72a7090fc8cf7`
- `protocol-tests/requirements_tests.rs`: `b75587213f09b8766e5b87873f3967cafd90b42387357d97eb26b8bc0f2a90c8`
- `runtime_factory.py`: `a894e91261575f6bebf5d19ae66d7476cd58f73cd22cd19cc0fa47ff920c8058`
- `spec-review.md`: `886cbeb3205dcc2eb317c07bcda68226887f0277710f5ef78f34034ce8820a35`
- `stable_reader.py`: `560e878636d84f3f1307e0537a6807baf91d53f91c5e535215656eab2147fe3f`
- `windows-ci.yml`: `a5312c06586dc420ca2c585ecc7c6d28152a8a6857ed34742295c597848710e9`
- `windows_bundle_gate.py`: `faf862a3b6e4233db9f7ec7048be0388cf9e3754a582e203393e44c59b34dc3d`
- `word-bootstrap.yml`: `9303251a6bbb687c07435385f3aa302ee5119c59f8e53abc480371e3231bbaee`
- `worker.py`: `c9c904661f71c2c2e407e62c431938d489f9dc5719a4b7f4fa0a1e25d0f01501`
