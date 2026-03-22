# Configuration Reference

## Core Sizing

| Setting | Default | Meaning |
|---------|---------|---------|
| `min_sessions` | `2` | Sessions created during `start()` |
| `max_sessions` | `10` | Maximum concurrently borrowed sessions |
| `borrow_timeout_s` | `connect_timeout_s` | Wait time for pool capacity |
| `connect_timeout_s` | `10.0` | Timeout for one session creation attempt |

## Cache and Health

| Setting | Default | Meaning |
|---------|---------|---------|
| `tool_cache_ttl_s` | `300.0` | TTL for cached `tools/list` responses |
| `health_check_interval_s` | `30.0` | Time between idle-session sweeps |
| `max_session_lifetime_s` | `3600.0` | Hard session lifetime |
| `recycle_window_s` | `30.0` | Recycle idle sessions before they expire |

## Retry and Circuit Breaker

| Setting | Default | Meaning |
|---------|---------|---------|
| `retry_count` | `2` | Retries after the first failure |
| `retry_base_delay_s` | `0.1` | Exponential backoff base |
| `retry_max_delay_s` | `2.0` | Backoff cap |
| `failure_threshold` | `5` | Consecutive failures before opening the circuit |
| `recovery_timeout_s` | `30.0` | Open-circuit wait before a half-open probe |

## Observability

| Setting | Default | Meaning |
|---------|---------|---------|
| `enable_opentelemetry` | `False` | Emit OTel spans and metrics when available |
| `event_hooks` | `EventHooks()` | Lifecycle callbacks for borrow, return, circuit, and health events |

## Auth and Headers

| Setting | Default | Meaning |
|---------|---------|---------|
| `auth` | `None` | Bearer token for `Authorization` |
| `mcp_headers` | `{}` | Static headers sent on every request |

## Transports

- `streamable_http`: remote MCP servers over HTTP
- `stdio`: subprocess-backed MCP servers
