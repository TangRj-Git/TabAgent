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
    """
    构造不连接；管理启动、目录查询、显式重连及统一关闭。
    这个 MCPClientManager 是统一管理多个 MCP 服务连接的入口。
    一个 MCPServerClient 负责一个服务；管理器持有多个客户端，协调它们一起工作。比如你同时配置了文件服务、搜索服务和数据库服务，上层代码就可以通过同一个管理器使用它们。
    """

    def __init__(
            self,
            *,
            config_path: str | Path,  # MCP 配置文件路径，必填，可以是字符串或 Path。
            startup_concurrency: int = 4,  # 最多同时启动多少个服务，默认 4。这是启动并发上限，并不限制总共可以连接多少个服务。
    ) -> None:
        """
        初始化管理器的配置与状态；此时不连接 MCP 服务。

        以下属性保存的是 asyncio.Task 对象，而不是裸协程对象：

        1. self._work：保存管理器持有的任务，方便关闭时统一取消和等待。
           - 整个MCPClientManager管理器的启动任务：执行 self._open(wait_for_optional)。
           - 管理器为各个MCP客户端创建的启动任务：执行 open_one(client)。
           - 后续创建的重连任务等。
           它不是客户端内部所有任务的集合；客户端内部的连接、目录查询等任务，由各客户端自己的 client._work 跟踪，与管理器的 self._work 是不同集合。

        2. self._starts：保存 server_id 到对应客户端初次启动任务的映射。
           例如：
               "time" -> 执行 open_one(time_client) 的 Task
               "fetch" -> 执行 open_one(fetch_client) 的 Task
           字典中的任务，与 self._work 中对应的任务是同一个对象，只是多保存一处引用，便于按 server_id 查找，不会导致任务重复执行。

        3. self._connect_task：保存整个管理器的启动任务，即执行 self._open(wait_for_optional) 的 Task，负责协调各服务的启动。
           这个任务也会加入 self._work；它只负责启动流程，并不是在管理器整个使用期间一直运行的任务。

        初始时，self._work 是空集合 set()，self._starts 是空字典 {}，self._connect_task 才是 None；空集合不等于 None，可以直接添加任务。
        任务结束后，完成回调会将其从 self._work 自动移除，但 self._starts 和 self._connect_task 仍可以保留对已结束任务的引用。
        启动任务结束不代表已经建立的 MCP 连接关闭。
        """
        if (
                isinstance(startup_concurrency, bool)
                or not isinstance(startup_concurrency, int)
                or startup_concurrency < 1
        ):
            raise MCPConfigError("startup_concurrency must be a positive integer.")
        self._config_path = resolve_config_path(config_path)  # 配置文件的绝对路径

        # startup_concurrency 表示：最多允许多少个 MCP 服务同时执行“启动流程”。
        # 默认值是 4。假如你配置了 10 个 MCP 服务，它们最终都可以连接并保持可用，但同一时间最多有 4 个处于启动过程中。
        # 可以把它理解为“有几个启动名额”：某个服务完成启动后，就把名额让给下一个服务，已经建立的连接继续保留。
        self._startup_concurrency = startup_concurrency  # 保存启动并发上限

        self._clients: dict[str, MCPServerClient] = {}  # 保存每个服务的客户端

        # 保存管理器启动、各服务启动、重连等任务，方便关闭时统一取消和等待。
        # 在 MCPClientManager 里面，self._work 表示的是 管理器持有的异步任务集合，可以把它理解为“管理器需要跟踪和清理的任务清单”。
        # 保存管理器持有的任务，方便关闭时统一取消和等待。
        self._work: set[asyncio.Task[Any]] = set()  # 跟踪管理器拥有的异步任务

        # 用于等待服务启动完成，以及判断某个服务是否还在启动。这里的启动包括连接及等待工具目录查询结束。
        # 保存 server_id 到对应客户端初次启动任务的映射
        self._starts: dict[str, asyncio.Task[None]] = {}  # 按服务保存初次启动任务

        # 如果多个调用同时要求重连同一个服务，就共享正在进行的任务，避免重复重连。任务成功后返回该服务的 MCPServerCatalog。
        self._reconnects: dict[str, asyncio.Task[MCPServerCatalog]] = {}  # 按服务保存重连任务

        # 整个MCPClientManager管理器的启动任务
        self._connect_task: asyncio.Task[None] | None = None  # 整个管理器的启动任务
        self._close_task: asyncio.Task[None] | None = None  # 整个管理器的关闭任务

        self._opened = False  # 管理器是否已经打开
        self._closing = False  # 管理器是否正在关闭或仍有清理未完成

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def is_open(self) -> bool:
        return self._opened and not self._closing

    def _get_client(
            self,
            server_id: str
    ) -> MCPServerClient:
        try:
            return self._clients[server_id]
        except (KeyError, TypeError):
            raise MCPRequestError(f"Unknown MCP server ID: {server_id!r}.") from None

    def _require_open(self) -> None:
        if not self.is_open:
            raise MCPNotConnectedError("The MCP client manager is not open.")

    async def connect(
            self,
            *,
            wait_for_optional: bool = True
    ) -> None:
        """
        管理器与各个 MCP 客户端之间的启动任务关系。

        整体上，是一个管理器启动任务创建并协调多个客户端启动任务，每个客户端再管理自己的连接任务，而不是所有连接都在同一个 Task 中执行。

        一、三个任务层次

        1. 管理器的整体启动任务：
           connect() 通过 start_task() 创建执行 self._open(wait_for_optional) 的 Task。
           这个任务由 self._connect_task 引用，同时加入管理器的 self._work。
           它负责创建各客户端的启动任务，并根据 wait_for_optional 决定等待范围。

        2. 管理器为各客户端创建的启动任务：
           _open() 运行时，为每个客户端分别创建执行 open_one(client) 的独立 Task。
           每个 open_one(client) 在取得启动并发名额后，调用 await client.connect()。
           这些任务也加入管理器的 self._work，并保存在 self._starts[server_id] 中。

        3. 客户端内部的连接任务：
           client.connect() 内部会创建或复用客户端自己的连接 Task，由这个任务执行客户端的 _open()，完成实际连接流程。
           这个任务由 client._connect_task 引用，并加入该客户端自己的 client._work。
           client._work 和管理器的 self._work 是不同对象的不同集合。

        二、为什么前两层任务会进入同一个 self._work

        connect() 和管理器的 _open() 创建任务时，都传入 owner=self._work。
        这里的 self 都指向同一个 MCPClientManager，因此使用的是同一个任务集合。

        假设配置了 time 和 fetch 两个服务，在以下任务均已创建且尚未结束时，管理器的任务集合可以表示为：

            self._work = {
                T_manager,  # 执行 self._open(wait_for_optional)
                T_time,     # 执行 open_one(time_client)
                T_fetch,    # 执行 open_one(fetch_client)
            }

        其中，T_manager 在执行过程中创建了 T_time 和 T_fetch，但它们仍然是三个独立的 Task，由事件循环分别调度，并通过等待建立协作关系。
        客户端内部的实际连接 Task 则由各自的 client._work 跟踪，不在上述集合中。

        因此，“管理器启动任务运行时，又创建了各客户端的启动任务，并将它们一起记录到管理器的 self._work 中”是准确的理解。

        self._work 本身只是保存 Task 引用的集合，不是协程，也不是一个大 Task。
        任务结束后，完成回调会将其从所属的 _work 集合中移除。
        """
        if not isinstance(wait_for_optional, bool):
            raise MCPConfigError("wait_for_optional must be a boolean.")

        if self._closing:
            raise MCPConnectionError("MCP manager cleanup is unfinished; call aclose() before reopening.")

        if self.is_open:
            raise MCPConnectionError("The MCP client manager is already open.")

        # Task 封装并管理协程的一次执行。
        # task.done() 用来判断这个任务是否已经结束，返回 True 或 False。
        task = self._connect_task
        if task is None or task.done():
            task = start_task(
                self._open(wait_for_optional),
                name="mcp:manager:connect",
                owner=self._work,
            )
            # 保存的是负责执行 self._open(wait_for_optional) 的任务对象，不是协程的返回值。
            self._connect_task = task
        try:
            # shield 保护内部启动任务：等待者被取消时，等待者仍会收到 CancelledError，
            # 但取消不会通过这次 await 自动传给 task；任务的正常结果和异常仍会传播。
            # 它不阻止显式 task.cancel()，也不保证后续清理流程不会取消任务。
            await asyncio.shield(task)
            # 如果任务尚未完成：当前 connect() 挂起，等待任务完成。
            # 事件循环可以调度新任务，让它执行 _open()。
            # shield 额外阻止等待者的取消通过这次 await 自动传播给 task。
        except BaseException as exc:
            if self._connect_task is task:
                try:
                    # 本管理器选择在启动失败或连接等待被取消后统一关闭；
                    # aclose() 的清理流程会显式取消后台任务，即使上面使用了 shield。
                    await self.aclose()
                except BaseException as cleanup_exc:
                    if isinstance(cleanup_exc, asyncio.CancelledError):
                        raise
                    exc.add_note("MCP manager cleanup also failed; inspect server statuses and retry aclose().")
            raise

    async def _open(
            self,
            wait_for_optional: bool
    ) -> None:
        if self._closing:
            raise asyncio.CancelledError

        config = await asyncio.to_thread(
            load_mcp_config,
            self.config_path
        )

        self._clients = {
            server_id: MCPServerClient(server_id=server_id, config=entry)
            for server_id, entry in config.servers.items()
        }

        # 必需服务优先进入启动队列，避免可选慢服务先占满启动名额。
        # sorted() 返回新列表，不修改 self._clients 字典或其中的客户端对象。
        # 排序是稳定的：同为必需或同为可选的服务，保持原有的配置顺序。
        # 这里只决定排队顺序；实际并发数由 semaphore 控制，
        # 不要求等所有必需服务都启动完成后，才开始启动可选服务。
        ordered = sorted(
            self._clients.values(),  # 取出所有 MCPServerClient 对象，不包含 server_id 键。
            # lambda 为每个客户端计算排序依据，相当于 return not client.required。
            # 必需服务：required=True -> False；可选服务：required=False -> True。
            # 默认升序排列，False < True，因此必需服务排在前面。
            key=lambda client: not client.required
        )

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

        self._starts = {
            client.server_id: start_task(
                open_one(client),
                name=f"mcp:manager:start:{client.server_id}",
                owner=self._work,
            )
            for client in ordered
        }

        waiting = [
            task for server_id, task in self._starts.items()
            if wait_for_optional or self._clients[server_id].required
        ]

        if waiting:
            # gather 并发等待启动结果；shield 防止 gather 的取消自动传给各个启动任务。
            # 若需要停止这些任务，由管理器的关闭流程统一显式取消。
            await asyncio.gather(*(asyncio.shield(task) for task in waiting))
        if self._closing:
            raise asyncio.CancelledError
        self._opened = True

    async def wait_ready(
            self,
            *,
            include_metadata: bool = False
    ) -> None:
        """等待可选服务启动；按需再等待资源、Prompt 和资源模板目录。"""
        self._require_open()
        if self._starts:
            # 取消本次就绪等待不会连带取消服务的启动任务，其他等待者仍可继续等待它们。
            await asyncio.gather(*(asyncio.shield(task) for task in self._starts.values()))
        self._require_open()
        if include_metadata:
            await asyncio.gather(*(
                client.wait_for_discovery()
                for client in self._clients.values()
                if client.get_server_info().state == "connected"
            ))
        self._require_open()

    def get_server_info(
            self,
            server_id: str
    ) -> MCPServerInfo:
        return self._get_client(server_id).get_server_info()

    def get_server_infos(self) -> dict[str, MCPServerInfo]:
        return {
            name: client.get_server_info()
            for name, client in self._clients.items()
        }

    def get_catalog(self) -> MCPCatalog:
        return MCPCatalog(servers={
            name: client.get_catalog()
            for name, client in self._clients.items()
        })

    def get_tools(self) -> list[MCPToolDefinition]:
        """只聚合已连接、工具目录查询成功且未过期的定义。"""
        tools: list[MCPToolDefinition] = []
        for server_id, client in self._clients.items():
            if client.get_server_info().state != "connected":
                continue
            collection = client.get_tools()
            if collection.status == "ready" and not collection.stale:
                tools.extend(
                    MCPToolDefinition(server_id, tool)
                    for tool in collection.items
                )
        return tools

    async def refresh(
            self,
            *,
            server_id: str | None = None
    ) -> MCPCatalog:
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

    async def _reconnect(
            self,
            client: MCPServerClient
    ) -> MCPServerCatalog:
        await client.aclose()
        self._require_open()
        await client.connect()
        if client.get_tools().status == "failed":
            raise MCPDiscoveryError(
                f"Tool discovery failed for MCP server {client.server_id!r}.",
                info=client.get_tools().error,
            )
        return client.get_catalog()

    async def reconnect(
            self,
            *,
            server_id: str
    ) -> MCPServerCatalog:
        """只重连指定服务；同一服务并发重连共享一个任务，不重放工具调用。"""
        self._require_open()
        client = self._get_client(server_id)
        starting = self._starts.get(server_id)
        if starting is not None and not starting.done():
            raise MCPConnectionError("Server startup is still in progress; await wait_ready() first.")
        task = self._reconnects.get(server_id)
        if task is None or task.done():
            task = start_task(
                self._reconnect(client),
                name=f"mcp:manager:reconnect:{server_id}",
                owner=self._work,
            )
            self._reconnects[server_id] = task
        # 同一服务的并发重连共享 task；shield 避免某个等待者取消时连带取消共享重连。
        # 重连任务仍由管理器持有，关闭管理器时可以显式取消它。
        return deepcopy(await asyncio.shield(task))

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
            name=name,
            arguments=arguments,
            timeout=timeout,
        )

    async def _shutdown(self) -> None:
        pending = tuple(task for task in self._work if not task.done())
        for task in pending:
            # 直接向任务发送取消请求；shield 只阻止等待者取消的自动传播，不阻止此操作。
            task.cancel()
        clients: tuple = tuple(self._clients.values())
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
