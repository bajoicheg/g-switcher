# CDC 2.9.2 — Continuous Autonomy & Learning

## Progress-Is-Not-Terminal
A progress update, commit, test subset, validation stage, PR, artifact or migration batch is informational. After a milestone, evaluate Terminal-State v2 and immediately continue observe → reconcile → choose-next → act whenever the terminal gate does not permit a final response.

## Per-report timestamps in every CDC-managed chat
Every substantive owner-facing Russian progress, blocker, continuation and final report in every CDC-managed chat receives a fresh runtime-clock observation converted to Europe/Moscow. The exact prefix is `[HH:MM DD.MM]`, for example `[19:31 26.09]`, without seconds or a timezone/MSK suffix. A long or resumed command may produce several substantive reports; its initial command timestamp does not satisfy later reports. Read a fresh clock for each report, never extrapolate or manually increment a prior timestamp. Only an exact idempotent retry of the same `(command_id, report_id)` report may suppress a duplicate. Legacy v1 per-command timestamp behavior remains compatibility only, not evidence of per-report adoption. Timestamp evidence creates no authority.

## RCA-to-roadmap feedback closure
Every material anomaly gets one deduplicated systemic disposition. Sensitive operational context must be sanitized before it can become roadmap payload.

## Fleet Watcher improvement harvesting
Every Fleet Watcher run returns exactly one evidence-based result: one new proposal or one reinforcement of an existing fix. Empty harvests are invalid; novelty is not forced. Harvesting grants no mutation authority.
