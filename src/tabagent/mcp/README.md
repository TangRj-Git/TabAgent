# MCP 客户端

本模块使用 **FastMCP 4.1.1**。一个 `MCPServerClient` 对应一个配置的服务，
`MCPClientManager` 负责加载 JSON、持有这些客户端并聚合目录。

当前实现发现工具、资源、Prompt 和资源模板的定义，业务调用只提供工具执行。
资源内容读取、Prompt 渲染、Agent/ToolRegistry 适配、MCP 中间件接入留在后续层处理。
`tests/stdio_server.py` 仅为集成测试的服务端夹具。

## 依赖

实现和测试对应 `fastmcp==4.1.1`，使用该版本的 `mcp_types` 协议模型。
当前项目已声明 FastMCP 依赖；本模块按已安装的 4.1.1 版本验证。
独立复用此模块时，可自行安装对应依赖，例如：

```powershell
uv add "fastmcp==4.1.1"
```

只需要客户端时，也可选择官方客户端发行包 `fastmcp-slim[client]==4.1.1`；
Python 导入仍然是 `fastmcp`。模块测试使用完整 FastMCP 包创建本地测试服务。

## 最小使用方式

```python
import asyncio

from tabagent.mcp import MCPClientManager


async def main() -> None:
    async with MCPClientManager(
        config_path="E:/OpenProject/TabAgent/resources/mcp_config.json",
    ) as manager:
        # 全部已配置的服务都有状态，包括禁用或连接失败的服务。
        for server_id, info in manager.get_server_infos().items():
            print(server_id, info.state, info.error)

        # 工具目录已完成；如果这次需要查看全部元数据，再等待其余分类。
        await manager.wait_ready(include_metadata=True)

        # 每个服务分别保存四类目录，包括查询状态、错误和旧数据标记。
        catalog = manager.get_catalog()
        for server_id, server in catalog.servers.items():
            print(server_id, server.tools.status, server.resources.status)
            print(server.prompts.status, server.resource_templates.status)

        # 聚合当前连接正常、工具目录查询成功且未过期的定义。
        for entry in manager.get_tools():
            print(entry.server_id, entry.tool.name, entry.tool.input_schema)

        # 示例调用：将这两个名称换成实际发现的 server_id 和工具名。
        # result = await manager.call_tool(
        #     server_id="documents",
        #     name="search",
        #     arguments={"query": "MCP"},
        # )
        # print(result.is_error, result.content, result.structured_content)


asyncio.run(main())
```

`config_path` 是必填参数，没有默认值。构造管理器时将它固定为绝对路径，
进入 `async with` 时才读取文件、启动本地服务或建立网络连接。
也可配对使用 `await manager.connect()` 和 `await manager.aclose()`。
上下文不可嵌套使用同一个实例；关闭后可以再次打开，届时重新加载配置。
同一个实例应在同一个事件循环内使用。

## 启动与目录就绪

管理器按 `startup_concurrency` 限制启动并发数，默认是 `4`，必需服务优先进入队列。
`async with` / `connect()` 默认等待所有启用服务的连接和工具目录查询结束，
可选服务的失败保存在状态中，不使整个管理器启动失败。
资源、Prompt、资源模板独立查询、独立发布，慢元数据不再挡住工具使用。
因此刚进入上下文时，其他三类目录可能仍是 `unloaded`。

如果希望可选慢服务在后台启动：

```python
manager = MCPClientManager(config_path=config_path, startup_concurrency=4)
try:
    await manager.connect(wait_for_optional=False)
    # 必需服务已就绪；get_tools() 随可选服务完成启动逐步增加。
    available = manager.get_tools()

    # 需要所有可选服务的启动结果时再等待。
    await manager.wait_ready()
    # 需要全部四类目录时再等待；失败分类仍通过 error 查看。
    await manager.wait_ready(include_metadata=True)
finally:
    await manager.aclose()
```

没有必需服务且使用 `wait_for_optional=False` 时，启动可以很快返回，工具列表最初可能为空。
直接使用单服务客户端时，`connect()` 同样只等待工具目录；
`await client.wait_for_discovery()` 用于等待四类目录全部结束。
同一实例的并发 `connect()` 共享一次启动，取消连接等待者会取消这一轮启动并清理。
这不是为同一客户端创建多个独立所有者；上下文嵌套仍不支持。

## JSON 格式

下面展示支持的连接形式；将包名、URL 和环境变量换成真实值后使用。

```json
{
  "mcpServers": {
    "node_service": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "<mcp-server-package>"],
      "cwd": "..",
      "env": {"SERVICE_API_KEY": "${LOCAL_SERVICE_API_KEY}"}
    },
    "python_service": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["<mcp-server-package>"],
      "cwd": ".."
    },
    "documents": {
      "transport": "http",
      "url": "https://documents.example.com/mcp",
      "required": true,
      "auth": {"type": "bearer", "token": "${DOCUMENTS_TOKEN}"}
    },
    "interactive_account": {
      "transport": "http",
      "url": "https://account.example.com/mcp",
      "connect_timeout": 180,
      "auth": {"type": "oauth", "scopes": ["read"]}
    },
    "machine_account": {
      "transport": "http",
      "url": "https://machine.example.com/mcp",
      "auth": {
        "type": "client_credentials",
        "client_id": "${MCP_CLIENT_ID}",
        "client_secret": "${MCP_CLIENT_SECRET}",
        "scopes": ["read"],
        "token_endpoint_auth_method": "client_secret_basic"
      }
    },
    "legacy_service": {
      "transport": "sse",
      "url": "https://legacy.example.com/sse",
      "headers": {"X-API-Key": "${LEGACY_API_KEY}"},
      "enabled": false
    }
  }
}
```

配置规则：

- 根对象必须有 `mcpServers`。字典键是稳定的 `server_id`，不能只包含空白。
- 只包含 `command` 时可省略 `transport`，推断为 `stdio`；只包含 `url` 时推断为 `http`。
  同时指定二者、拼错字段或重复 JSON 键会报错。`streamable-http` 可作为 `http` 的别名。
- `stdio` 使用 `command`、`args`、`cwd`、`env`，直接交给 FastMCP 启动。
  `npx`、`uvx` 必须已安装且能通过 PATH 找到，也可以配置可执行文件的绝对路径。
  这里不使用 Shell 工具或其进程管理器来接管 MCP 的 stdin/stdout。
- `http` 是 Streamable HTTP；`sse` 用于旧服务。即使 URL 指向本机，仍属于网络连接。
- `auth` 可省略，或使用 `{"type": "none"}`。Bearer 的 `token` 不带 `Bearer ` 前缀。
  HTTP 自定义 API key 放在 `headers` 中。配置了认证对象后不能再手写 `Authorization` header。
- 交互式 OAuth 支持 `scopes`、可选 `client_id`、`client_secret`、`callback_port`；
  可能打开浏览器等待登录。机器账户使用 `client_credentials`，认证方法支持
  `client_secret_basic` 和 `client_secret_post`。token 缓存使用 FastMCP 的默认内存存储。
- `${NAME}` 从进程环境变量展开一次，缺失会报错；不会自动读取 `.env`。
  如需 `.env`，由应用先调用 `load_dotenv()`。禁用服务不展开占位符、不检查其目录是否存在，
  但仍检查配置结构和字段类型。
- 相对 `cwd` 从 JSON 所在目录解析，省略时使用 JSON 所在目录。对于
  `resources/mcp_config.json`，`"cwd": ".."` 指向项目目录，`"cwd": "."` 指向 `resources`。
  `args` 保持原样，相对脚本参数通常由子进程按照 `cwd` 解释。
- stdio 环境使用 SDK 的基本变量白名单再叠加 `env`，不会转发整个父进程环境。
- 配置对象会隐藏凭据的常规 `repr`，本模块的错误信息也不拼接原始凭据或远端异常全文。
  配置文件和工具原始结果本身仍需由应用合理处理。

公共选项：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `enabled` | `true` | 是否连接此服务 |
| `required` | `false` | 启动时连接或工具目录查询失败，是否回滚并抛出异常 |
| `connect_timeout` | `30.0` | 连接、协商和认证的最大等待秒数 |
| `request_timeout` | `60.0` | 请求超时秒数；`null` 不设置本模块的工具调用总时限 |
| `discovery_timeout` | `60.0` | 单个分类全部分页的总时限 |
| `close_timeout` | `5.0` | 单服务每次关闭最多等待的秒数；超时后保留清理任务 |
| `max_discovery_pages` | `250` | 单个分类允许查询的最大页数 |
| `max_discovery_items` | `10000` | 单个分类全部分页累计的最大条目数 |
| `max_cursor_bytes` | `65536` | 单个分页游标的最大 UTF-8 字节数 |

`request_timeout` 不保证服务端会停止执行；服务器和底层传输还可能有自己的时限。
单次 `call_tool(timeout=...)` 可以覆盖工具请求的时限。

## 目录、状态与结果

| 类 | 保存的内容 |
| --- | --- |
| `MCPServerInfo` | 连接状态、服务信息、capabilities、最近操作错误，以及独立的 cleanup_error / cleanup_pending |
| `MCPServerCatalog` | 一个服务的 tools、resources、prompts、resource_templates |
| `MCPCollection` | 一个分类的状态、完整定义、更新时间、错误和 stale 标记 |
| `MCPCatalog` | 按 server_id 汇总所有服务的目录 |
| `MCPToolDefinition` | 聚合工具查询中的 server_id 和原始 Tool 定义 |
| `MCPErrorInfo` | 英文说明、操作名、错误分类、异常类型、底层原因类型、HTTP / 协议错误码 |

定义使用 `mcp_types` 原始模型，保留 Schema、注解、图标等字段。
读取目录和服务信息返回副本，外部修改不会改变内部缓存。
资源模板属于 resources capability，不存在单独的模板 capability 开关。

分类状态分别为：

- `unloaded`：尚未完成查询。
- `ready`：完整查询成功；空列表也属于成功。
- `unsupported`：服务没有声明该类 capability。
- `failed`：声明支持但查询失败；错误详情在这个分类的 `error` 中。

查询会遍历分页。重复游标、游标过大、页数/条目数超限或中途失败均不会把部分结果冒充完整目录。
这些上限约束目录聚合；不是传输层的响应字节限制，SDK 仍需先解析收到的单页响应。
刷新失败时保留上次完整结果并设置 `stale=True`，关闭或检测到断线也会将已有目录标旧。
`get_catalog()` 可查看旧定义；`get_tools()` 只提供当前连接正常且最新查询成功的工具。
`call_tool()` 可以显式调用缓存中仍保留的旧工具名，服务端是否仍提供它由本次调用确认。

`await manager.refresh()` 刷新所有已连接服务，也可传 `server_id` 刷新一个。
同一服务已有目录查询进行时会合并等待该轮；空闲时才开始新一轮查询。
刷新或目录等待者取消后，客户端仍持有后台发现任务；关闭客户端才会取消这些任务。
它不重读 JSON、不自动重连。若修改了配置，需要关闭并重新打开管理器。
本版不订阅目录变更通知，远端增删工具后由调用方主动刷新。

`await manager.reconnect(server_id="documents")` 关闭并重建一个服务的连接，
等待新的工具目录，不影响其他服务，也不重读 JSON。
同一服务的并发重连共享一次操作；取消某个重连等待者不会取消共享重连。
服务初次启动尚未完成时应先等待 `wait_ready()`，再发起重连。
关闭尚未完成的服务不能创建第二条连接；重连会先尝试完成旧连接的清理。

可选服务连接失败时，其他服务继续可用。资源、Prompt 或模板目录失败不会阻止工具使用。
必需服务连接失败或工具目录查询失败时，管理器关闭本轮已打开的客户端再抛出异常。
未声明 tools capability 是 `unsupported`，并不等价于查询失败。

调用使用 `(server_id, name)` 明确路由，不拼接或拆分工具名。
不同服务可以提供同名工具。返回值是完整 `mcp_types.CallToolResult`，保留
`content`、`structured_content`、`meta`、`is_error` 等；工具返回 `is_error=True`
仍然是正常返回的业务结果。协议或传输失败才包装为本模块异常。
超时/断线不自动重试工具，避免有副作用的操作重复执行。

工具参数递归检查 JSON 类型：所有层级的对象键必须为字符串，不接受循环引用、
NaN / Infinity、tuple / set / 自定义对象，嵌套深度最多为 64。
合法参数复制后交给 SDK；是否符合工具的输入 Schema 仍由服务端验证。

错误中的 `category` 区分超时、认证、HTTP、操作系统、连接、协议等原因；
SDK 包装过的异常会继续查找底层类型与数字错误码。
例如命令不存在可以看到 `not_found`，HTTP 401 可看到 `authentication` 和 `status_code=401`。
不会直接返回第三方异常全文或请求 URL，无法安全识别的原因保留类型并使用通用英文说明。
抛出的模块异常也可通过 `exc.info` 取得诊断数据。
连接失败后清理也失败时，`error` 和 `cleanup_error` 分别保留，异常附加清理失败说明。

多个工具调用可用 `asyncio.gather()` 并发等待。关闭立即停止接收新请求，
取消本客户端持有的启动、发现、工具请求，并关闭传输；管理器并发清理所有服务，
一个服务清理失败不会阻止尝试清理其他服务。本地 stdio 子进程仍由 FastMCP 负责清理。
若关闭传输与尚未退出的启动任务交错，待旧任务退出后会再确认关闭，避免迟到的连接遗留。

外部取消会延迟到清理结束或 `close_timeout` 到期后继续传播，不会无限等待。
单服务超时会抛出 `MCPConnectionError`，状态保存 `cleanup_pending=True`；
已有清理任务仍被持有并继续运行，后续 `aclose()` 会等待同一任务，已失败的清理则重新尝试。
清理成功后才移除连接引用、清除清理错误并允许重新打开。
管理器总等待上限为各服务最大 `close_timeout` 加 1 秒调度余量。

Python 无法强制终止忽略取消的协程，因此“关闭调用已返回”不必然代表“清理已经成功”。
遇到 `cleanup_pending` 时应保留实例、检查状态并再次等待清理；直接结束事件循环不能替代清理。
超时、取消或关闭也不能保证远程服务已停止已经收到的业务操作。

## 文件分工与流程

```text
显式 config_path
    -> config_loader.py 读取并规范化
    -> config.py 验证配置类型
    -> manager.py 为各服务创建 MCPServerClient
    -> client.py 管理单个连接
       -> auth.py + transport.py 创建 FastMCP Client
       -> discovery.py 查询四类目录
       -> models.py 保存可读取的快照
    -> manager.call_tool(server_id, name, arguments)
       -> 对应 client.call_tool_mcp(...)
       -> 完整 CallToolResult
```

`exceptions.py` 定义模块异常，`diagnostics.py` 提取安全诊断信息；
`_lifecycle.py` 管理任务引用和关闭期间的有限等待，`_arguments.py` 校验并复制 JSON 参数。
`__init__.py` 汇总公共导入。

## 独立测试

Windows / PowerShell，从项目根目录使用现有虚拟环境运行：

```powershell
$env:PYTHONPATH = "$PWD/src"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\.venv\Scripts\python.exe -B -m pytest src/tabagent/mcp/tests -q -p no:cacheprovider
```

测试包括真实内存 MCP 服务、本地 stdio 启停与子进程退出、回环 HTTP/SSE 连接、
Bearer/header 传递、配置校验、四类目录、分页边界、JSON 参数、错误结果、
必需服务失败回滚、刷新取消、有限并发启动、慢元数据、单服务重连、清理超时及重复取消。
测试临时配置放在本模块的 tests 目录下，完成后移除；不调用项目中的交互式 Agent 测试。
真实 OAuth 登录、远程服务兼容性需要实际服务和凭据，在接入具体服务时验证。

目录变更通知、独立登录流程/持久 token 存储、工具检索和 Agent 适配不属于当前实现。
