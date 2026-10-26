"""完整分页发现四类定义；不读取资源内容，也不渲染 Prompt。"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastmcp import Client
from mcp_types import ServerCapabilities

from .config import ServerConfig
from .diagnostics import error_info
from .exceptions import MCPDiscoveryError
from .models import MCPCollection


async def _read_pages(
        fetch: Callable[..., Awaitable[Any]],
        attribute: str,
        config: ServerConfig,
) -> list[Any]:
    items: list[Any] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(config.max_discovery_pages):
        page = await fetch(cursor=cursor, cache_mode="bypass")
        batch = getattr(page, attribute)
        if len(items) + len(batch) > config.max_discovery_items:
            raise MCPDiscoveryError("The discovery item limit was exceeded.")
        items.extend(batch)
        cursor = page.next_cursor
        if cursor is None:
            return items
        if not isinstance(cursor, str):
            raise MCPDiscoveryError("The server returned a non-string pagination cursor.")
        if len(cursor.encode("utf-8")) > config.max_cursor_bytes:
            raise MCPDiscoveryError("The pagination cursor exceeds the configured byte limit.")
        if cursor in seen:
            raise MCPDiscoveryError("The server returned a repeated pagination cursor.")
        seen.add(cursor)
    raise MCPDiscoveryError("The discovery page limit was reached before the listing ended.")


async def discover_collection[T](
        *,
        server_id: str,
        operation: str,
        supported: bool,
        previous: MCPCollection[T],
        fetch: Callable[..., Awaitable[Any]],
        attribute: str,
        config: ServerConfig,
) -> MCPCollection[T]:
    if not supported:
        return MCPCollection(status="unsupported", updated_at=datetime.now(UTC))
    try:
        # 限制整个目录查询的时间，而不只是其中一页的时间。
        async with asyncio.timeout(config.discovery_timeout):
            items = await _read_pages(fetch, attribute, config)
        return MCPCollection(status="ready", items=items, updated_at=datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001 -- 各分类独立保存查询失败，取消仍直接向上传播。
        return MCPCollection(
            status="failed",
            items=list(previous.items),
            stale=previous.updated_at is not None,
            updated_at=previous.updated_at,
            error=error_info(
                server_id=server_id,
                operation=operation,
                exc=exc,
            ),
        )


def discovery_queries(
        client: Client,
        capabilities: ServerCapabilities,
) -> tuple[tuple[str, bool, Callable[..., Awaitable[Any]]], ...]:
    """查询描述由客户端分别调度，便于独立发布和取消每个分类。"""
    return (
        ("tools", capabilities.tools is not None, client.list_tools_mcp),
        ("resources", capabilities.resources is not None, client.list_resources_mcp),
        ("prompts", capabilities.prompts is not None, client.list_prompts_mcp),
        # Resource templates 同样受 resources capability 控制。
        ("resource_templates", capabilities.resources is not None, client.list_resource_templates_mcp),
    )
