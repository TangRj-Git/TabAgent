import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mcp_types import Tool

from tabagent.mcp import MCPCollection, StdioConfig
from tabagent.mcp.discovery import discover_collection


def test_complete_pagination_and_unsupported():
    async def scenario():
        cursors = []

        async def fetch(*, cursor, cache_mode):
            assert cache_mode == "bypass"
            cursors.append(cursor)
            return SimpleNamespace(
                tools=[Tool(name="first" if cursor is None else "second", input_schema={})],
                next_cursor="next" if cursor is None else None,
            )

        kwargs = dict(
            server_id="test", operation="tools", previous=MCPCollection(),
            fetch=fetch, attribute="tools", config=StdioConfig(command="unused"),
        )
        result = await discover_collection(supported=True, **kwargs)
        assert result.status == "ready"
        assert [tool.name for tool in result.items] == ["first", "second"]
        assert cursors == [None, "next"]
        result = await discover_collection(supported=False, **kwargs)
        assert result.status == "unsupported"
        assert cursors == [None, "next"]

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["items", "cursor", "repeated", "pages", "timeout"])
def test_incomplete_listing_preserves_previous_snapshot(case):
    async def scenario():
        old = Tool(name="previous", input_schema={})
        previous = MCPCollection(status="ready", items=[old], updated_at=datetime.now(UTC))
        config = StdioConfig(
            command="unused", max_discovery_items=2, max_cursor_bytes=4,
            max_discovery_pages=1 if case == "pages" else 3, discovery_timeout=0.02,
        )

        async def fetch(**kwargs):
            if case == "timeout":
                await asyncio.Event().wait()
            return SimpleNamespace(
                tools=[Tool(name=f"item{i}", input_schema={}) for i in range(3 if case == "items" else 0)],
                next_cursor="x" * 5 if case == "cursor" else "next",
            )

        result = await discover_collection(
            server_id="test", operation="tools", supported=True, previous=previous,
            fetch=fetch, attribute="tools", config=config,
        )
        assert result.status == "failed"
        assert result.stale
        assert result.items == [old]
        assert result.updated_at == previous.updated_at
        assert result.error.category == ("timeout" if case == "timeout" else "validation")

    asyncio.run(scenario())
