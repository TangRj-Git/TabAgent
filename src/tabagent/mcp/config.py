"""配置数据类型。JSON 的读取、环境变量展开和路径解析见 config_loader。"""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class _Config(BaseModel):
    """
    BaseModel 提供数据校验能力
    BaseModel 提供校验机制，你在类中声明具体规则，它负责自动执行。
    model_config 是 Pydantic 约定的配置属性，ConfigDict 用来声明它支持的配置选项
    """
    model_config = ConfigDict(
        extra="forbid",  # 禁止未声明的字段
        strict=True,  # 启用严格类型校验
        frozen=True,  # 创建后禁止重新给属性赋值
        validate_default=True,  # 默认值也要校验
        hide_input_in_errors=True,  # 错误文本中隐藏输入值
        allow_inf_nan=False,  # 数值字段不接受无穷大和 NaN
    )


class NoAuthConfig(_Config):
    # 字面量类型，这里同时声明了允许的值和默认值
    type: Literal["none"] = "none"


class BearerAuthConfig(_Config):
    type: Literal["bearer"] = "bearer"
    # SecretStr 是 Pydantic 提供的敏感字符串类型。它在常规展示时会掩盖内容，例如显示成 **********，但这并不是加密。
    # min_length=1 要求至少有一个字符，空字符串 "" 不合法。
    # repr=False 表示打印整个配置对象时，不展示这个字段。由于没有设置默认值，token 是必填字段。
    token: SecretStr = Field(min_length=1, repr=False)

    # 这个装饰器告诉 Pydantic：创建模型时，自动执行 validate_token()。
    # mode="after" 表示在各个字段完成校验之后执行。因此进入这个方法时，self.token 已经是一个通过字段校验的 SecretStr 对象。
    # Self 是返回值的类型注解，表示返回当前类的实例，这里就是 BearerAuthConfig。
    @model_validator(mode="after")
    def validate_token(self) -> Self:
        token = self.token.get_secret_value()
        if token != token.strip() or token.lower().startswith("bearer "):
            raise ValueError("Use the token only, without a Bearer prefix or whitespace.")
        return self


class OAuthConfig(_Config):
    """
    交互式 OAuth；凭据和 token 默认只保存在 FastMCP 的内存存储中。
    这个类用来配置交互式 OAuth 认证：通常由认证组件打开浏览器，让用户登录并授权。
    """

    type: Literal["oauth"] = "oauth"
    scopes: list[str] = Field(default_factory=list)  # scopes 是字符串列表，表示客户端希望申请哪些权限
    client_id: str | None = None  # client_id 是应用在 OAuth 服务中的标识
    # client_secret 同样可以不传。提供时使用 SecretStr 包装，repr=False 则让它不出现在整个模型的常规打印结果中。
    client_secret: SecretStr | None = Field(default=None, repr=False)  # client_secret 是应用的客户端密钥
    callback_port: int | None = Field(default=None, ge=1, le=65535)  # 浏览器完成授权后，认证流程通常需要回调到本机监听的地址，这个字段指定其端口。

    @model_validator(mode="after")
    def validate_credentials(self) -> Self:
        if self.client_secret is not None and not self.client_id:
            # 如果提供了 client_secret，就必须同时提供非空的 client_id。
            raise ValueError("client_id is required when client_secret is set.")
        return self


class ClientCredentialsConfig(_Config):
    """
    服务账户 OAuth；由 FastMCP 发现 token endpoint。
    OAuth 的客户端凭据模式（Client Credentials）：后台程序使用自己的 client_id 和 client_secret 获取访问令牌，不需要用户通过浏览器登录。
    """

    type: Literal["client_credentials"] = "client_credentials"  # 只能取字符串 "client_credentials"，默认也是这个值
    scopes: list[str] = Field(default_factory=list)  # 指定需要申请的权限，例如 ["read", "write"]，具体名称由服务端定义
    client_id: str = Field(min_length=1)  # client_id 是应用的标识
    client_secret: SecretStr = Field(min_length=1, repr=False)  # client_secret 是应用的密钥
    # token endpoint 是 OAuth 服务用来签发访问令牌的接口。
    # 这个字段决定：向该接口申请令牌时，怎样发送 client_id 和 client_secret。
    # "client_secret_basic"	HTTP 的 Authorization 请求头，使用 Basic 认证
    # "client_secret_post"	HTTP POST 请求的表单正文
    token_endpoint_auth_method: Literal[
        "client_secret_basic", "client_secret_post"
    ] = "client_secret_basic"


"""
none	            不配置认证
bearer	            已有 token，直接携带它访问服务
oauth	            用户通过浏览器登录并授权，程序随后获取 token
client_credentials	程序使用应用凭据自动申请 token，不需要用户参与登录
"""

AuthConfig = Annotated[
    NoAuthConfig | BearerAuthConfig | OAuthConfig | ClientCredentialsConfig,
    Field(discriminator="type"),  # discriminator --> 鉴别器
]

"""
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
"""


class MCPServerConfig(_Config):
    """所有连接共有的策略。required 由多服务管理器在启动时检查。"""

    enabled: bool = True  # 是否启用这个服务；为 False 时不建立连接
    required: bool = False  # 是否属于必需服务；连接或工具目录查询失败时，管理器是否让本轮启动失败并回滚
    connect_timeout: float = Field(default=30.0, gt=0)  # 建立连接、协议协商及认证的等待时限
    request_timeout: float | None = Field(default=60.0, gt=0)  # 工具调用的默认时限；None 表示不设置本模块的工具调用总时限
    discovery_timeout: float = Field(default=60.0, gt=0)  # 发现一个目录分类的总时限，包括这个分类的全部分页
    close_timeout: float = Field(default=5.0, gt=0)  # 单服务每次关闭操作最多等待的时间
    max_discovery_pages: int = Field(default=250, ge=1)  # 一个目录分类最多允许查询多少页
    max_discovery_items: int = Field(default=10000, ge=1)  # 一个目录分类全部分页累计最多允许多少条定义
    max_cursor_bytes: int = Field(default=65536, ge=1)  # 分页游标最多允许多少个 UTF-8 字节，即 64 KiB


class StdioConfig(MCPServerConfig):
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list, repr=False)
    # load_mcp_config() 会将 cwd 转换成绝对路径。
    cwd: str | None = None
    env: dict[str, SecretStr] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        if self.enabled and not self.command.strip():
            raise ValueError("command must not be blank.")
        return self


class RemoteConfig(MCPServerConfig):
    transport: Literal["http", "sse"] = "http"
    url: str = Field(min_length=1, repr=False)
    headers: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    auth: AuthConfig | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_remote(self) -> Self:
        # 禁用的配置可以保留尚未展开的环境变量占位符。
        if not self.enabled:
            return self
        try:
            parts = urlsplit(self.url)
            port = parts.port
        except ValueError:
            raise ValueError("url must be a valid HTTP or HTTPS URL.") from None
        if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.fragment
                or any(char.isspace() for char in self.url)
                or port == 0
        ):
            raise ValueError("url must be HTTP or HTTPS without user info or a fragment.")
        names = [name.lower() for name in self.headers]
        if len(names) != len(set(names)):
            raise ValueError("HTTP header names must be unique ignoring case.")
        if "authorization" in names and self.auth is not None and self.auth.type != "none":
            raise ValueError("Configure auth or an Authorization header, not both.")
        return self


ServerConfig = Annotated[
    StdioConfig | RemoteConfig,
    Field(discriminator="transport")
]


class MCPClientConfig(_Config):
    """配置文件根对象；字典键就是稳定的 server_id。"""

    # alias="mcpServers" 表示：外部数据里的字段名叫 mcpServers，Python 代码里的属性名叫 servers。
    servers: dict[str, ServerConfig] = Field(alias="mcpServers")

    @model_validator(mode="after")
    def validate_server_ids(self) -> Self:
        if any(not key or key != key.strip() for key in self.servers):
            raise ValueError("Server IDs must be nonempty and have no surrounding whitespace.")
        return self
