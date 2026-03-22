# Quickstart

## Install

```bash
pip install mcp-pool
```

For OpenTelemetry support:

```bash
pip install "mcp-pool[otel]"
```

## Basic Usage

```python
import asyncio
from mcpool import MCPPool, PoolConfig


async def main() -> None:
    config = PoolConfig(
        endpoint="http://gateway.example.com/mcp",
        min_sessions=2,
        max_sessions=8,
        borrow_timeout_s=2.0,
        retry_count=2,
        failure_threshold=5,
    )

    async with MCPPool(config=config) as pool:
        async with pool.session() as session:
            result = await session.call_tool("search", arguments={"q": "pooling"})
            print(result)

        tools = await pool.list_tools()
        print(len(tools.tools))


asyncio.run(main())
```

## Best-effort Borrow

Use `try_session()` when the caller should not wait for capacity:

```python
async with pool.try_session() as session:
    if session is None:
        return
    await session.call_tool("optional_work")
```

## Development Commands

```bash
pytest -v
pytest tests/benchmarks tests/fuzz -v --no-cov
mkdocs build --strict
```
