# mcpool

[![PyPI version](https://img.shields.io/pypi/v/mcp-pool.svg)](https://pypi.org/project/mcp-pool/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/adwantg/mcp-pool/actions/workflows/ci.yml/badge.svg)](https://github.com/adwantg/mcp-pool/actions)

> ⚡ Async connection pool for Model Context Protocol (MCP) client sessions — keep sessions warm, reuse across requests, auto-reconnect on failure, cache tools/list. Drop-in replacement saving ~195ms per agent request.

## The Problem

Every agent request creates a new MCP session:

```
Request → TCP connect → TLS handshake → MCP initialize → tools/list → tools/call → close
                                    ~200ms overhead per request
```

With 1000+ requests/day, this wastes hours purely on session setup. The `tools/list` response is identical every time, yet it's fetched fresh on every invocation.

## The Solution

**mcpool** keeps sessions warm, reuses them, and caches tool lists:

```
App startup → pool.start() → N warm sessions ready
Request → pool.session() → tools/call → return session    ~5ms ⚡
Request → pool.session() → tools/call → return session    ~5ms ⚡
Shutdown → pool.shutdown() → drain + close all sessions
```

## Installation

```bash
pip install mcp-pool
```

## Quickstart

```python
import asyncio
from mcpool import MCPPool, PoolConfig

async def main():
    config = PoolConfig(
        endpoint="http://gateway.example.com/mcp",
        transport="streamable_http",
        min_sessions=2,
        max_sessions=10,
        tool_cache_ttl_s=300,        # Cache tools/list for 5 minutes
        health_check_interval_s=30,  # Ping idle sessions every 30s
        auth="your-api-key",         # Optional auth token
    )

    async with MCPPool(config=config) as pool:
        # Borrow a warm session
        async with pool.session() as session:
            result = await session.call_tool("my_tool", arguments={"key": "value"})
            print(result)

        # Tools are cached automatically
        tools = await pool.list_tools()
        print(f"Available tools: {[t.name for t in tools.tools]}")

        # Check pool health
        print(pool.metrics.snapshot())

asyncio.run(main())
```

## Features

### v1.0 — Core
| Feature | Description |
|---------|-------------|
| **Async session pool** | Borrow/return warm `ClientSession` instances with configurable `min_sessions` / `max_sessions` |
| **Session health check** | Background ping on idle sessions. Auto-detect and replace dead sessions |
| **Tool caching** | Cache `tools/list` with configurable TTL. Explicit invalidation support |
| **Graceful drain** | On shutdown, wait for in-flight calls to complete before closing |
| **Per-request headers** | Inject headers (e.g., `X-Access-Token`) per-call without creating a new session |
| **Metrics** | Live counters: active/idle sessions, borrow wait time, cache hit rate, error count |
| **Session lifetime** | Auto-recycle sessions after max lifetime (prevents credential expiry) |

### Transport Support
- ✅ `streamable_http` — production HTTP transport
- ✅ `stdio` — subprocess-based transport

## API Reference

### `MCPPool`

```python
# Via config object
pool = MCPPool(config=PoolConfig(endpoint="http://..."))

# Or via keyword arguments
pool = MCPPool(endpoint="http://...", min_sessions=2, max_sessions=10)
```

| Method | Description |
|--------|-------------|
| `await pool.start()` | Pre-warm sessions and start health checker |
| `await pool.shutdown()` | Drain in-flight calls and close all sessions |
| `async with pool.session(headers=...) as s:` | Borrow a session |
| `await pool.list_tools()` | Get cached tools (fetches if stale) |
| `pool.invalidate_tools_cache()` | Force tool cache refresh |
| `pool.metrics.snapshot()` | Get metrics dictionary |

### `PoolConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `endpoint` | `str` | `""` | MCP server URL or stdio command |
| `transport` | `str` | `"streamable_http"` | `"streamable_http"` or `"stdio"` |
| `min_sessions` | `int` | `2` | Sessions to pre-warm on start |
| `max_sessions` | `int` | `10` | Hard cap on concurrent sessions |
| `health_check_interval_s` | `float` | `30.0` | Seconds between health pings (0 = disabled) |
| `tool_cache_ttl_s` | `float` | `300.0` | Tool cache TTL in seconds (0 = disabled) |
| `max_session_lifetime_s` | `float` | `3600.0` | Force-recycle after N seconds (0 = disabled) |
| `connect_timeout_s` | `float` | `10.0` | Timeout for new sessions |
| `drain_timeout_s` | `float` | `30.0` | Max wait during shutdown drain |
| `auth` | `str?` | `None` | Bearer token for Authorization header |
| `mcp_headers` | `dict` | `{}` | Extra headers on every request |

## Metrics

```python
>>> pool.metrics.snapshot()
{
    "active": 1,
    "idle": 4,
    "total": 5,
    "borrow_count": 42,
    "avg_borrow_wait_s": 0.003,
    "cache_hits": 38,
    "cache_misses": 4,
    "cache_hit_rate": 0.905,
    "reconnect_count": 1,
    "sessions_created": 6,
    "sessions_destroyed": 1,
    "errors": 0,
    "uptime_s": 3600.5
}
```

## Why mcpool?

| Library | Session Pooling | Tool Caching | Health Check | Auth | Transport |
|---------|:-:|:-:|:-:|:-:|:-:|
| **mcpool** | ✅ | ✅ | ✅ | ✅ | HTTP + stdio |
| `mcp` SDK | ❌ | ❌ | ❌ | ❌ | HTTP + stdio |
| `langchain-mcp-adapters` | ❌ | ❌ | ❌ | ❌ | HTTP + stdio |
| `mcp-proxy-for-aws` | ❌ | ❌ | ❌ | ✅ | HTTP |
| `mcp-bridgekit` | ⚠️ Gateway | ❌ | ❌ | ❌ | HTTP |

## Development

```bash
git clone https://github.com/adwantg/mcp-pool.git
cd mcp-pool
pip install -e ".[dev]"
pytest -v
ruff check src/ tests/
mypy src/
```

## License

MIT — see [LICENSE](LICENSE).

## Citation

If you use mcpool in research, please cite:

```bibtex
@software{adwant_mcpool_2025,
  author = {Goutam Adwant},
  title = {mcpool: Async Connection Pool for MCP Sessions},
  year = {2025},
  url = {https://github.com/adwantg/mcp-pool}
}
```
