# Deployment Patterns

## Web Applications

- Create one pool per process during app startup.
- Reuse that pool across requests.
- Call `shutdown()` from the framework lifespan hook.

## Worker Processes

- Use `min_sessions=0` for cold-start-sensitive workers.
- Set `borrow_timeout_s` low for fail-fast workloads.
- Tune `retry_count` to tolerate short endpoint blips without stalling the worker.

## Credential Rotation

- Set `max_session_lifetime_s` below token lifetime.
- Set `recycle_window_s` so idle sessions are replaced before expiry.

## Unstable MCP Endpoints

- Leave the circuit breaker enabled.
- Use the event hooks to emit alerts on `on_circuit_open` and `on_health_check_failed`.
- Enable OpenTelemetry if you want traces on retry storms or repeated failures.
