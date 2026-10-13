# CDC 2.12.0 managed process-only adoption

Canonical release: `refs/heads/release/v2.12.0`
Release commit: `540d42b5a8b06b11d7aeae78585cffbff99da231`
Exact package tree: `247facf39eadf073883c5f1fe3b4a291278da7f8`
Source base: `e2159a7856ea12b4c6237820965263f5d6f92a4b`

Prior UI/Word prepared attempt 19599cc1-2f55-556c-852f-ea8c5a9316c9 never launched a runtime or acquired a lease; artifact 11492088368 retains the exact request. Its base-specific preparation is superseded by this atomic adoption and the authorized repair resumes on the new base.

This adoption is assembled detached from the shared source ref and published once by the released 2.12.0 conditional fast-forward/readback path. Project product behavior, product acceptance/release gates, and owner-paused scheduler state are preserved. Live coordination ownership is authoritative over checkpoint projections.
