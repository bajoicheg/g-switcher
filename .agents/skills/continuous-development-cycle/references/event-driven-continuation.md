# CDC 2.5 event-driven continuation

Polling and the recurring watchdog are fallback mechanisms, not the preferred latency path. Terminal CI/compute, backend recovery, policy change, scheduler recovery or explicit manual-kick observations may be serialized as `continuation-event/v1` and ingested into durable `continuation-queue/v1`.

Events bind repository/source ref and, when relevant, candidate SHA, operation key and task/run ID. Canonical dedupe makes repeated delivery idempotent. Queue claims are invocation-bound and expire so a lost wake can be retried; the claim coordinates delivery only and grants no execution authority. The claimed invocation still passes normal resume, lease, guard, budget and completion gates.

If the platform supports immediate event wakes, newly inserted events should request one. Otherwise the hourly watchdog drains the same durable queue on its next wake: **scheduler fallback remains mandatory**.
