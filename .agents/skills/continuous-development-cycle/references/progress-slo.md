# CDC 2.6 meaningful-progress SLO

Heartbeat, lease renewal, status reads, health checks, unchanged polling and reports are activity, not progress. `scripts/progress_slo.py` measures age from the last **meaningful durable progress** reference.

Default template thresholds are 20 minutes to DEGRADED and 60 minutes to STALLED. A real durable blocker or waiting_external pauses the stall clock and classifies BLOCKED instead of blaming the executor. Missing progress time is RECOVERY_REQUIRED. SLO output is diagnostic/recovery input only and grants no authority.
