# Author: gadwant
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpool.config import PoolConfig
from mcpool.langchain import _ensure_langchain, langchain_tools
from mcpool.pool import MCPPool


class TestLangChainTools:
    def test_import_error_when_no_langchain(self):
        """Should raise ImportError if langchain_core is missing."""
        with patch.dict("sys.modules", {"langchain_core.tools": None}):
            with pytest.raises(ImportError, match="langchain-core is required"):
                _ensure_langchain()

    @pytest.mark.asyncio
    async def test_langchain_tools_conversion(self):
        """Should convert cached tools to LangChain Tool objects."""
        # Mock Tool class
        mock_tool_class = MagicMock()
        mock_tool_class.side_effect = lambda **kwargs: kwargs

        pool = MCPPool(config=PoolConfig(endpoint="http://dummy"))
        pool.cache.set([
            {"name": "tool1", "description": "desc1"},
            {"name": "tool2"}, # No description 
        ])

        with patch("mcpool.langchain._ensure_langchain", return_value=mock_tool_class):
            tools = langchain_tools(pool)

        assert len(tools) == 2
        
        # Verify converted tool1
        t1 = tools[0]
        assert t1["name"] == "tool1"
        assert t1["description"] == "desc1"
        assert callable(t1["func"])

        # Verify converted tool2 fallback
        t2 = tools[1]
        assert t2["name"] == "tool2"
        assert t2["description"] == "tool2"

    @pytest.mark.asyncio
    async def test_langchain_tools_sync_warning_in_loop(self):
        """Should raise RuntimeError if cache empty and running inside async loop."""
        pool = MCPPool(config=PoolConfig(endpoint="http://dummy"))
        pool.cache.invalidate()

        mock_tool_class = MagicMock()
        
        with patch("mcpool.langchain._ensure_langchain", return_value=mock_tool_class):
            with pytest.raises(RuntimeError, match="Cannot fetch tools synchronously"):
                langchain_tools(pool)

    def test_langchain_tools_runner_closure(self):
        """The generated func closure should call pool.call_tool."""
        mock_tool_class = MagicMock()
        mock_tool_class.side_effect = lambda **kwargs: kwargs

        pool = MCPPool(config=PoolConfig(endpoint="http://dummy"))
        pool.cache.set([{"name": "my_tool"}])
        
        # Mock pool.call_tool
        mock_call = AsyncMock(return_value={"result": "success"})
        pool.call_tool = mock_call

        with patch("mcpool.langchain._ensure_langchain", return_value=mock_tool_class):
            tools = langchain_tools(pool)

        runner = tools[0]["func"]
        
        # Since we are outside of an event loop here, runner uses asyncio.run()
        # Ensure we are not inside an async loop for this test
        result = runner('{"arg1": "val1"}')
        
        assert result == "{'result': 'success'}"
        mock_call.assert_called_once_with("my_tool", arguments={"arg1": "val1"})
