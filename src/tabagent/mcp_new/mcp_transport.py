from typing import Literal, Annotated

from pydantic import BaseModel, ConfigDict, SecretStr, Field

from tabagent.mcp_new.mcp_auth import AuthConfig


class TransportBaseConfig(BaseModel):
    """公共校验规则。"""

    model_config = ConfigDict(
        extra="allow",
        strict=True,
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class ServerBaseConfig(TransportBaseConfig):
    """每个 MCP 服务共有的配置。"""


class StdioConfig(ServerBaseConfig):
    """启动本地子进程，通过标准输入、标准输出通信。"""

    transport: Literal["stdio"] = "stdio"

    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict, repr=False)
    cwd: str | None = None
    keep_alive: bool = False
    log_file: str | None = None


class SSEConfig(ServerBaseConfig):
    """通过旧版 SSE 连接服务，支持 HTTP/HTTPS 地址。"""

    transport: Literal["sse"] = "sse"

    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    auth: AuthConfig | None = Field(default=None, repr=False)
    sse_read_timeout: float | None = Field(default=None, gt=0)


class HttpConfig(ServerBaseConfig):
    """通过 Streamable HTTP 连接服务，支持 HTTP/HTTPS 地址。"""

    transport: Literal["http", "streamable-http"] = "http"

    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    auth: AuthConfig | None = Field(default=None, repr=False)


ServerConfig = Annotated[
    StdioConfig | SSEConfig | HttpConfig,
    Field(discriminator="transport"),
]


class MCPClientConfig(TransportBaseConfig):
    """整个 MCP 配置文件；字典的键就是服务标识。"""

    servers: dict[str, ServerConfig] = Field(alias="mcpServers")
