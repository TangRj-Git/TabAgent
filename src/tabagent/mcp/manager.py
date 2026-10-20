"""通过必填 JSON 路径管理多个独立 MCP 客户端。"""

import asyncio
from copy import deepcopy
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from mcp_types import CallToolResult

from ._lifecycle import finish_cleanup, start_task
from .client import MCPServerClient
from .config_loader import load_mcp_config, resolve_config_path
from .exceptions import (
    MCPConfigError,
    MCPConnectionError,
    MCPDiscoveryError,
    MCPNotConnectedError,
    MCPRequestError,
)
from .models import MCPCatalog, MCPServerCatalog, MCPServerInfo, MCPToolDefinition


class MCPClientManager:
    """构造不连接；管理启动、目录查询、显式重连及统一关闭。"""

    def __init__(
        self,
        *,
        config_path: str | Path,
        startup_concurrency: int = 4,
    ) -> None:
        if (
            isinstance(startup_concurrency, bool)
            or not isinstance(startup_concurrency, int)
            or startup_concurrency < 1
        ):
            raise MCPConfigError("startup_concurrency must be a positive integer.")
        self._config_path = resolve_config_path(config_path)
        self._startup_concurrency = startup_concurrency
        self._clients: dict[str, MCPServerClient] = {}
        self._work: set[asyncio.Task[Any]] = set()
        self._starts: dict[str, asyncio.Task[None]] = {}
        self._reconnects: dict[str, asyncio.Task[MCPServerCatalog]] = {}
        self._connect_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._opened = False
        self._closing = False

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def is_open(self) -> bool:
        return self._opened and not self._closing

    def _get_client(self, server_id: str) -> MCPServerClient:
        try:
            return self._clients[server_id]
        except (KeyError, TypeError):
            raise MCPRequestError(f"Unknown MCP server ID: {server_id!r}.") from None

    def _require_open(self) -> None:
        if not self.is_open:
            raise MCPNotConnectedError("The MCP client manager is not open.")

    async def connect(self, *, wait_for_optional: bool = True) -> None:
        """并发启动。默认等待所有工具目录；False 时仅等待必需服务。"""
        if not isinstance(wait_for_optional, bool):
            raise MCPConfigError("wait_for_optional must be a boolean.")
        if self._closing:
            raise MCPConnectionError("MCP manager cleanup is unfinished; call aclose() before reopening.")
        if self.is_open:
            raise MCPConnectionError("The MCP client manager is already open.")
        task = self._connect_task
        if task is None or task.done():
            task = start_task(
                self._open(wait_for_optional), name="mcp:manager:connect", owner=self._work,
            )
            self._connect_task = task
        try:
            await asyncio.shield(task)
        except BaseException as exc:
            if self._connect_task is task:
                try:
                    await self.aclose()
                except BaseException as cleanup_exc:
                    if isinstance(cleanup_exc, asyncio.CancelledError):
                        raise
                    exc.add_note("MCP manager cleanup also failed; inspect server statuses and retry aclose().")
            raise

    async def _open(self, wait_for_optional: bool) -> None:
        config = await asyncio.to_thread(load_mcp_config, self.config_path)
        if self._closing:
            raise asyncio.CancelledError
        self._clients = {
            server_id: MCPServerClient(server_id=server_id, config=entry)
            for server_id, entry in config.servers.items()
        }
        self._reconnects = {}
        semaphore = asyncio.Semaphore(self._startup_concurrency)

        async def open_one(client: MCPServerClient) -> None:
            async with semaphore:
                try:
                    await client.connect()
                except MCPConnectionError:
                    if client.required:
                        raise
                    return
                if client.required and client.get_tools().status == "failed":
                    raise MCPDiscoveryError(
                        f"Tool discovery failed for required MCP server {client.server_id!r}.",
                        info=client.get_tools().error,
                    )

        # 必需服务先进入队列，避免可选慢服务占满启动名额。
        ordered = sorted(self._clients.values(), key=lambda client: not client.required)
        self._starts = {
            client.server_id: start_task(
                open_one(client), name=f"mcp:manager:start:{client.server_id}", owner=self._work,
            )
            for client in ordered
        }
        waiting = [
            task for server_id, task in self._starts.items()
            if wait_for_optional or self._clients[server_id].required
        ]
        if waiting:
            await asyncio.gather(*(asyncio.shield(task) for task in waiting))
        if self._closing:
            raise asyncio.CancelledError
        self._opened = True

    async def wait_ready(self, *, include_metadata: bool = False) -> None:
        """等待可选服务启动；按需再等待资源、Prompt 和资源模板目录。"""
        self._require_open()
        if self._starts:
            await asyncio.gather(*(asyncio.shield(task) for task in self._starts.values()))
        self._require_open()
        if include_metadata:
            await asyncio.gather(*(
                client.wait_for_discovery()
                for client in self._clients.values()
                if client.get_server_info().state == "connected"
            ))
        self._require_open()

    def get_catalog(self) -> MCPCatalog:
        return MCPCatalog(servers={
            name: client.get_catalog() for name, client in self._clients.items()
        })

    def get_server_info(self, server_id: str) -> MCPServerInfo:
        return self._get_client(server_id).get_server_info()

    def get_server_infos(self) -> dict[str, MCPServerInfo]:
        return {name: client.get_server_info() for name, client in self._clients.items()}

    def get_tools(self) -> list[MCPToolDefinition]:
        """只聚合已连接、工具目录查询成功且未过期的定义。"""
        tools: list[MCPToolDefinition] = []
        for server_id, client in self._clients.items():
            if client.get_server_info().state != "connected":
                continue
            collection = client.get_tools()
            if collection.status == "ready" and not collection.stale:
                tools.extend(MCPToolDefinition(server_id, tool) for tool in collection.items)
        return tools

    async def refresh(self, *, server_id: str | None = None) -> MCPCatalog:
        """刷新远程定义；不重读配置、不自动重连；各分类单独发布结果。"""
        self._require_open()
        clients = (
            [self._get_client(server_id)] if server_id is not None else
            [client for client in self._clients.values() if client.get_server_info().state == "connected"]
        )
        if clients:
            await asyncio.gather(*(client.refresh() for client in clients))
        self._require_open()
        return self.get_catalog()

    async def reconnect(self, *, server_id: str) -> MCPServerCatalog:
        """只重连指定服务；同一服务并发重连共享一个任务，不重放工具调用。"""
        self._require_open()
        client = self._get_client(server_id)
        starting = self._starts.get(server_id)
        if starting is not None and not starting.done():
            raise MCPConnectionError("Server startup is still in progress; await wait_ready() first.")
        task = self._reconnects.get(server_id)
        if task is None or task.done():
            task = start_task(
                self._reconnect(client), name=f"mcp:manager:reconnect:{server_id}", owner=self._work,
            )
            self._reconnects[server_id] = task
        return deepcopy(await asyncio.shield(task))

    async def _reconnect(self, client: MCPServerClient) -> MCPServerCatalog:
        await client.aclose()
        self._require_open()
        await client.connect()
        if client.get_tools().status == "failed":
            raise MCPDiscoveryError(
                f"Tool discovery failed for MCP server {client.server_id!r}.",
                info=client.get_tools().error,
            )
        return client.get_catalog()

    async def call_tool(
        self,
        *,
        server_id: str,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> CallToolResult:
        self._require_open()
        return await self._get_client(server_id).call_tool(
            name=name, arguments=arguments, timeout=timeout,
        )

    async def _shutdown(self) -> None:
        pending = tuple(task for task in self._work if not task.done())
        for task in pending:
            task.cancel()
        clients = tuple(self._clients.values())
        # 独立关闭所有服务，某一服务的超时/异常不会阻止尝试关闭其余服务。
        closing = [
            start_task(client.aclose(), name=f"mcp:manager:close:{client.server_id}")
            for client in clients
        ]
        results = await asyncio.gather(*closing, *pending, return_exceptions=True)
        failures = [
            client.server_id
            for client, result in zip(clients, results[:len(clients)])
            if isinstance(result, BaseException)
        ]
        if failures:
            raise MCPConnectionError(
                f"Cannot finish closing MCP servers: {', '.join(failures)}. "
                "Inspect cleanup_error and retry aclose()."
            )
        self._closing = False

    async def aclose(self) -> None:
        """停止启动和请求，并发关闭服务；保留未完成清理的客户端供查询或重试。"""
        self._opened = False
        task = self._close_task
        if task is None or task.done():
            self._closing = True
            task = start_task(self._shutdown(), name="mcp:manager:close")
            self._close_task = task
        # 各客户端自己限时；额外一秒用于调度和收集取消后的结果。
        limit = max((client.close_timeout for client in self._clients.values()), default=5.0) + 1.0
        try:
            await finish_cleanup(task, timeout=limit)
        except TimeoutError:
            raise MCPConnectionError(
                "MCP manager cleanup is still pending; call aclose() again to wait for it."
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
        except MCPConnectionError:
            if exc is None:
                raise
            exc.add_note("MCP manager cleanup also failed; inspect the server statuses.")
