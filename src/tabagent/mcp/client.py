"""一个 MCPServerClient 拥有一个服务的连接、目录及后台任务。"""

import asyncio
import math
from collections.abc import Awaitable, Callable
from copy import deepcopy
from types import TracebackType
from typing import Any, Self

from fastmcp import Client
from mcp_types import CallToolResult, Tool

from ._arguments import copy_arguments
from ._lifecycle import finish_cleanup, start_task
from .config import RemoteConfig, ServerConfig, StdioConfig
from .diagnostics import error_info
from .discovery import discover_collection, discovery_queries
from .exceptions import (
    MCPConfigError,
    MCPConnectionError,
    MCPNotConnectedError,
    MCPRequestError,
)
from .models import MCPCollection, MCPErrorInfo, MCPServerCatalog, MCPServerInfo
from .transport import create_client


class MCPServerClient:
    """一个实例只在一个事件循环中使用；目录读取返回独立快照。"""

    def __init__(self, *, server_id: str, config: ServerConfig) -> None:
        if not isinstance(server_id, str) or not server_id or server_id != server_id.strip():
            raise MCPConfigError("server_id must be nonempty and have no surrounding whitespace.")
        if not isinstance(config, (StdioConfig, RemoteConfig)):
            raise MCPConfigError("config must be a StdioConfig or RemoteConfig instance.")
        self._server_id = server_id
        self._config = config.model_copy(deep=True)
        self._client: Client | None = None
        self._work: set[asyncio.Task[Any]] = set()
        self._connect_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._discoveries: dict[str, asyncio.Task[None]] = {}
        self._closing = False
        self._catalog = MCPServerCatalog(server_id=server_id)
        self._info = MCPServerInfo(
            server_id=server_id,
            transport=config.transport,
            state="disconnected" if config.enabled else "disabled",
        )

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def required(self) -> bool:
        return self._config.required and self._config.enabled

    @property
    def close_timeout(self) -> float:
        return self._config.close_timeout

    def _mark_stale(self) -> None:
        for name in ("tools", "resources", "prompts", "resource_templates"):
            collection = getattr(self._catalog, name)
            if collection.updated_at is not None:
                collection.stale = True

    def _check_connection(self) -> None:
        if self._info.state == "connected" and (
            self._client is None or not self._client.is_connected()
        ):
            self._info.state = "failed"
            self._info.error = MCPErrorInfo(
                self.server_id, "connection", "The MCP connection is no longer active.",
                "MCPNotConnectedError", category="connection",
            )
            self._mark_stale()

    def get_server_info(self) -> MCPServerInfo:
        self._check_connection()
        return deepcopy(self._info)

    def get_catalog(self) -> MCPServerCatalog:
        self._check_connection()
        return deepcopy(self._catalog)

    def get_tools(self) -> MCPCollection[Tool]:
        """只复制工具分类，聚合工具时不复制资源和 Prompt。"""
        self._check_connection()
        return deepcopy(self._catalog.tools)

    def _require_client(self) -> Client:
        self._check_connection()
        if self._closing or self._client is None or self._info.state != "connected":
            raise MCPNotConnectedError(f"MCP server {self.server_id!r} is not connected.")
        return self._client

    async def connect(self) -> None:
        """等待连接和工具目录；其他分类在后台继续发现。并发打开共享同一次尝试。"""
        if self._closing:
            raise MCPConnectionError("MCP cleanup is unfinished; call aclose() before reopening.")
        if not self._config.enabled:
            return
        task = self._connect_task
        if task is None or task.done():
            if self._client is not None:
                raise MCPConnectionError(f"MCP server {self.server_id!r} must be closed before reopening.")
            task = start_task(self._open(), name=f"mcp:{self.server_id}:connect", owner=self._work)
            self._connect_task = task
        try:
            await asyncio.shield(task)
        except BaseException as exc:
            # 取消连接的等待者会结束本次打开；关闭不依赖连接持有的锁。
            if self._connect_task is task:
                try:
                    await self.aclose()
                except BaseException as cleanup_exc:
                    if isinstance(cleanup_exc, asyncio.CancelledError):
                        raise
                    exc.add_note("MCP connection cleanup also failed; inspect cleanup_error and retry aclose().")
                if isinstance(exc, Exception) and self._client is None:
                    self._info.state = "failed"
            raise

    async def _open(self) -> None:
        if self._closing:
            raise asyncio.CancelledError
        self._info.state = "connecting"
        self._info.error = None
        try:
            self._client = create_client(self.server_id, self._config)
            async with asyncio.timeout(self._config.connect_timeout):
                await self._client.__aenter__()
            if self._closing:
                raise asyncio.CancelledError
            self._info.server_info = deepcopy(self._client.server_info)
            self._info.protocol_version = self._client.protocol_version
            self._info.capabilities = deepcopy(self._client.server_capabilities)
            self._info.instructions = self._client.instructions
            if self._info.capabilities is None:
                raise MCPConnectionError("The server did not provide its capabilities.")
            self._info.state = "connected"
            self._start_discovery()
            await asyncio.shield(self._discoveries["tools"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            info = error_info(server_id=self.server_id, operation="connect", exc=exc)
            self._info.error = info
            if not self._closing:
                self._info.state = "failed"
            raise MCPConnectionError(info.message, info=deepcopy(info)) from None

    def _start_discovery(self) -> None:
        client = self._require_client()
        capabilities = self._info.capabilities
        if capabilities is None:
            raise MCPConnectionError("Server capabilities are unavailable.")

        async def query(
            name: str, supported: bool, fetch: Callable[..., Awaitable[Any]],
        ) -> None:
            collection = await discover_collection(
                server_id=self.server_id,
                operation=name,
                supported=supported,
                previous=getattr(self._catalog, name),
                fetch=fetch,
                attribute=name,
                config=self._config,
            )
            # 即使第三方请求忽略取消，也不能在关闭后发布为最新目录。
            if not self._closing and self._client is client:
                setattr(self._catalog, name, collection)

        self._discoveries = {
            name: start_task(
                query(name, supported, fetch),
                name=f"mcp:{self.server_id}:discover:{name}",
                owner=self._work,
            )
            for name, supported, fetch in discovery_queries(client, capabilities)
        }

    async def wait_for_discovery(self) -> MCPServerCatalog:
        """等待当前四类目录查询完成；某类失败保存在该分类的 error 中。"""
        self._require_client()
        tasks = tuple(self._discoveries.values())
        if tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tasks))
        self._require_client()
        return self.get_catalog()

    async def refresh(self) -> MCPServerCatalog:
        """合并正在进行的发现；空闲时开始新一轮，并等待全部分类。"""
        self._require_client()
        if not any(not task.done() for task in self._discoveries.values()):
            self._start_discovery()
        return await self.wait_for_discovery()

    async def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> CallToolResult:
        """保留原始协议结果；超时、取消或断线都不会自动重试工具。"""
        client = self._require_client()
        if not isinstance(name, str) or not any(tool.name == name for tool in self._catalog.tools.items):
            raise MCPRequestError(f"The tool is not in the catalog for MCP server {self.server_id!r}.")
        arguments = copy_arguments(arguments)
        limit = self._config.request_timeout if timeout is None else timeout
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, (float, int))
            or not math.isfinite(limit) or limit <= 0
        ):
            raise MCPRequestError("Tool timeout must be a positive finite number.")

        async def execute() -> CallToolResult:
            try:
                async with asyncio.timeout(limit):
                    result = await client.call_tool_mcp(name=name, arguments=arguments, timeout=limit)
                if not self._closing:
                    self._info.error = None
                return result
            except Exception as exc:
                self._check_connection()
                info = error_info(server_id=self.server_id, operation="call_tool", exc=exc)
                info.message += " The remote execution outcome may be unknown."
                self._info.error = info
                raise MCPRequestError(info.message, info=deepcopy(info)) from None

        task = start_task(execute(), name=f"mcp:{self.server_id}:call_tool", owner=self._work)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            # 不等待不配合取消的第三方任务；仍由 _work 持有并在关闭时清理。
            raise

    async def _shutdown(self) -> None:
        pending = tuple(task for task in self._work if not task.done())
        for task in pending:
            task.cancel()
        client = self._client
        transport_close = None
        try:
            # 同时关闭传输，帮助唤醒正在等待网络或 stdio 的任务。
            if client is not None:
                transport_close = start_task(
                    client.close(), name=f"mcp:{self.server_id}:transport-close",
                )
            await asyncio.gather(
                *pending, *([transport_close] if transport_close else []),
                return_exceptions=True,
            )
            if transport_close is not None:
                transport_close.result()
                if pending:
                    # 上面的 close 可能与尚未退出的 __aenter__ 交错。
                    # 等所有旧任务退出后再关闭一次，避免迟到的连接遗留。
                    await client.close()
        except BaseException as exc:
            self._info.state = "failed"
            self._info.cleanup_pending = True
            info = error_info(server_id=self.server_id, operation="close", exc=exc)
            self._info.cleanup_error = info
            if not isinstance(exc, Exception):
                raise
            raise MCPConnectionError(info.message, info=deepcopy(info)) from None
        else:
            self._client = None
            self._closing = False
            self._info.state = "disconnected" if self._config.enabled else "disabled"
            self._info.cleanup_error = None
            self._info.cleanup_pending = False
        finally:
            self._mark_stale()

    async def aclose(self) -> None:
        """立即停止接收请求；最多等待 close_timeout，未完成清理仍由本实例持有。"""
        task = self._close_task
        if task is None or task.done():
            self._closing = True
            self._info.state = "closing"
            self._info.cleanup_pending = True
            self._mark_stale()
            task = start_task(self._shutdown(), name=f"mcp:{self.server_id}:close")
            self._close_task = task
        try:
            await finish_cleanup(task, timeout=self.close_timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            if not task.done():
                info = error_info(
                    server_id=self.server_id, operation="close",
                    exc=TimeoutError("Cleanup is still pending."),
                )
                info.message += " Cleanup is still running; call aclose() again to wait for it."
                self._info.state = "failed"
                self._info.cleanup_error = info
                self._info.cleanup_pending = True
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise MCPConnectionError(
                self._info.cleanup_error.message, info=deepcopy(self._info.cleanup_error),
            ) from None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self.aclose()
        except Exception:
            if exc is None:
                raise
            exc.add_note("MCP client cleanup also failed; inspect cleanup_error.")
