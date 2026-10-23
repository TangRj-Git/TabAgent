"""可复制的目录快照；不包含连接、锁、配置凭据或可执行对象。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from mcp_types import (
    Implementation,
    Prompt,
    Resource,
    ResourceTemplate,
    ServerCapabilities,
    Tool,
)

# DiscoveryStatus 表示某一类目录的查询状态
# 工具、资源、Prompt、资源模板各自有独立的状态
DiscoveryStatus = Literal[
    "unloaded",  # 尚未完成查询，可能还没开始，也可能正在查询
    "ready",  # 查询成功，已获得完整目录；即使结果为空也属于成功
    "unsupported",  # 服务端没有声明支持这一类能力，因此不进行查询
    "failed",  # 服务端声明支持，但查询过程中发生错误，例如超时、分页异常
]

# ConnectionStatus 表示整个服务连接的状态
ConnectionStatus = Literal[
    "disabled",  # 配置中设置了 enabled=False，服务被禁用
    "disconnected",  # 尚未连接，或者已经正常关闭连接
    "connecting",  # 正在建立连接、协商协议或进行认证
    "connected",  # 连接已经建立，可以进行请求
    "closing",  # 正在关闭连接、取消任务并清理资源
    "failed",  # 连接建立失败、检测到断线，或者关闭清理发生问题
]


# @dataclass 自动生成 __init__、__repr__、__eq__ 等方法，
# 但不会像 Pydantic BaseModel 那样自动进行字段类型校验。
# 这里的 field 来自 dataclasses；default_factory 会为每个实例创建独立的默认对象。


# MCPErrorInfo 保存结构化的错误信息，便于查询、展示和定位问题。
@dataclass
class MCPErrorInfo:
    server_id: str  # 发生错误的服务标识，对应配置中 mcpServers 下的键
    operation: str  # 发生错误的操作，如 connect、call_tool、close
    message: str  # 用于描述错误的可读信息
    exception_type: str  # 异常类型名称，如 TimeoutError
    category: str = "unknown"  # 错误分类，如超时、认证失败；无法识别时为 unknown
    cause_type: str | None = None  # 底层原因的异常类型名称；未识别到时为 None
    status_code: int | None = None  # HTTP 状态码，如 401、500；没有时为 None
    error_code: int | None = None  # MCP/JSON-RPC 协议错误码；没有时为 None


# MCPCollection 表示某一类能力的目录，包含定义列表及其查询状态。
# T 是泛型参数，表示列表元素的类型，例如 Tool、Resource、Prompt。
@dataclass
class MCPCollection[T]:
    status: DiscoveryStatus = "unloaded"  # 目录发现状态：未加载、成功、不支持或失败
    items: list[T] = field(default_factory=list)  # 目录中的定义列表，每个实例默认获得独立的空列表
    error: MCPErrorInfo | None = None  # 当前目录发现失败的错误信息；没有错误时为 None
    stale: bool = False  # 已缓存的目录是否可能过期，如刷新失败、连接关闭或断线后
    updated_at: datetime | None = None  # 目录的更新时间；尚未记录时为 None


# MCPServerInfo 保存单个服务的连接状态、服务端信息及运行错误。
@dataclass
class MCPServerInfo:
    server_id: str  # 当前服务在客户端侧的标识
    transport: Literal["stdio", "http", "sse"]  # 使用的传输方式
    state: ConnectionStatus = "disconnected"  # 当前连接状态，初始为未连接
    server_info: Implementation | None = None  # 服务端返回的实现信息，如服务名称、版本
    protocol_version: str | None = None  # 连接协商后使用的 MCP 协议版本
    capabilities: ServerCapabilities | None = None  # 服务端声明支持的能力，如工具、资源、Prompt
    instructions: str | None = None  # 服务端提供的使用说明，供上层应用参考
    error: MCPErrorInfo | None = None  # 最近一次连接、工具调用等操作的错误信息
    cleanup_error: MCPErrorInfo | None = None  # 关闭或清理失败的信息，与正常操作错误分开保存
    cleanup_pending: bool = False  # 是否仍有未完成的清理；可能正在执行，也可能需要重试


# MCPServerCatalog 汇总单个服务的四类能力目录，各分类独立保存状态和错误。
@dataclass
class MCPServerCatalog:
    server_id: str  # 这些目录所属的服务标识
    tools: MCPCollection[Tool] = field(default_factory=MCPCollection)  # 工具定义目录，如名称、描述、输入 Schema
    resources: MCPCollection[Resource] = field(default_factory=MCPCollection)  # 资源定义目录，保存资源描述而非实际内容
    prompts: MCPCollection[Prompt] = field(default_factory=MCPCollection)  # Prompt 定义目录，保存描述和参数等信息
    resource_templates: MCPCollection[ResourceTemplate] = field(default_factory=MCPCollection)  # 资源模板目录，如带参数的 URI 模板


# MCPCatalog 汇总所有服务的能力目录，通过 server_id 查找对应服务。
@dataclass
class MCPCatalog:
    servers: dict[str, MCPServerCatalog] = field(default_factory=dict)  # 服务标识 → 该服务的四类目录；默认独立空字典


# MCPToolDefinition 表示聚合工具列表中的一个条目，同时保留工具来源。
@dataclass
class MCPToolDefinition:
    """聚合查询结果；保留来源和原始工具定义，不改名、不转换 Schema。"""

    server_id: str  # 工具所属的服务标识，用于路由调用、区分不同服务的同名工具
    tool: Tool  # 原始 MCP 工具定义，包含名称、描述、输入 Schema 等信息
