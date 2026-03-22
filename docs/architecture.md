# Architecture

`mcpool` has three core responsibilities:

- manage warm session capacity
- keep idle sessions healthy and fresh
- protect upstream MCP endpoints from retry storms

## Runtime Flow

```mermaid
flowchart TD
    A["Caller"] --> B["MCPPool.session()"]
    B --> C{"Capacity Available?"}
    C -->|No| D["Wait up to borrow_timeout_s"]
    C -->|Yes| E["Borrow idle session or create new one"]
    D --> E
    E --> F["Circuit breaker + retry policy"]
    F --> G["ClientSession"]
    G --> H["Tool calls"]
    H --> I["Return to idle pool"]
    I --> J["Health checker / recycle window"]
```

## `list_tools()` Path

`list_tools()` uses a single-flight refresh path:

1. Check the TTL cache.
2. If valid, return immediately.
3. If stale, one caller refreshes while other callers wait for the result.
4. Store the fresh tool list and update cache metrics.

## Shutdown Model

Shutdown marks the pool as draining, waits for in-flight borrows to complete up to `drain_timeout_s`, then closes all sessions and clears the pool state.
