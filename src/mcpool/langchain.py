# Author: gadwant
"""
LangChain integration — expose MCP tools as LangChain Tool objects.

Requires the ``mcpool[langchain]`` extra
(``pip install "mcpool[langchain]"``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .pool import MCPPool

logger = logging.getLogger("mcpool.langchain")


def _ensure_langchain() -> Any:
    """Lazy-import ``langchain_core`` and return the ``Tool`` class."""
    try:
        from langchain_core.tools import Tool
    except ImportError as exc:
        raise ImportError(
            "langchain-core is required for langchain_tools().  "
            "Install it with: pip install 'mcpool[langchain]'"
        ) from exc
    return Tool


def langchain_tools(pool: MCPPool) -> list[Any]:
    """
    Build a list of LangChain ``Tool`` objects from the pool's cached
    tool definitions.

    Each tool wraps ``pool.call_tool()`` so it borrows a session
    transparently.

    Usage::

        tools = pool.langchain_tools()
        agent = create_react_agent(llm, tools)

    Args:
        pool: An already-started :class:`MCPPool` instance.

    Returns:
        A list of ``langchain_core.tools.Tool`` objects.
    """
    LCTool = _ensure_langchain()

    # Use already-cached tool definitions if available.
    cached = pool.cache.get()
    if cached is None:
        # Synchronous context — run in the current event loop if possible.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            raise RuntimeError(
                "Cannot fetch tools synchronously from a running event loop.  "
                "Call `await pool.list_tools()` first to warm the cache, "
                "then call `pool.langchain_tools()`."
            )
        cached = asyncio.run(pool.list_tools())

    tools_list: list[Any] = []

    raw_tools: list[Any] = cached.tools if hasattr(cached, "tools") else cached

    for tool_def in raw_tools:
        name: str = (
            tool_def["name"]
            if isinstance(tool_def, dict)
            else getattr(tool_def, "name", str(tool_def))
        )
        description: str = (
            tool_def.get("description", name)
            if isinstance(tool_def, dict)
            else getattr(tool_def, "description", name)
        )

        # Create a closure that captures the tool name.
        def _make_runner(tool_name: str):  # type: ignore[no-untyped-def]
            def run_tool(input_str: str) -> str:
                try:
                    args = json.loads(input_str) if input_str else {}
                except json.JSONDecodeError:
                    args = {"input": input_str}

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop is not None and loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            asyncio.run, pool.call_tool(tool_name, arguments=args)
                        )
                        result = future.result()
                else:
                    result = asyncio.run(pool.call_tool(tool_name, arguments=args))

                return str(result)

            return run_tool

        lc_tool = LCTool(
            name=name,
            description=description,
            func=_make_runner(name),
        )
        tools_list.append(lc_tool)

    logger.debug("Created %d LangChain tools from pool", len(tools_list))
    return tools_list
