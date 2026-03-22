# Performance Tuning

## Pool Sizing

- Increase `min_sessions` when startup latency matters more than memory.
- Increase `max_sessions` only when you expect true concurrent tool calls.
- Keep `borrow_timeout_s` lower than user-facing request deadlines.

## Cache Behavior

- Use a longer `tool_cache_ttl_s` when tool schemas rarely change.
- Invalidate the cache manually if your MCP server updates tool schemas out of band.

## Retry and Circuit Breaker

- Use small retry counts for interactive traffic.
- Use a higher `failure_threshold` for endpoints with occasional transient failures.
- Lower `recovery_timeout_s` only if your endpoint recovers quickly and reliably.

## Benchmark and Fuzz Commands

```bash
pytest tests/benchmarks -v --no-cov
pytest tests/fuzz -v --no-cov
```

The benchmark suite is written as regression guards, so failures indicate a meaningful change in relative behavior rather than a noisy absolute latency target.
