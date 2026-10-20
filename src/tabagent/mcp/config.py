"""配置数据类型。JSON 的读取、环境变量展开和路径解析见 config_loader。"""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class _Config(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class NoAuthConfig(_Config):
    type: Literal["none"] = "none"


class BearerAuthConfig(_Config):
    type: Literal["bearer"] = "bearer"
    token: SecretStr = Field(min_length=1, repr=False)

    @model_validator(mode="after")
    def validate_token(self) -> Self:
        token = self.token.get_secret_value()
        if token != token.strip() or token.lower().startswith("bearer "):
            raise ValueError("Use the token only, without a Bearer prefix or whitespace.")
        return self


class OAuthConfig(_Config):
    """交互式 OAuth；凭据和 token 默认只保存在 FastMCP 的内存存储中。"""

    type: Literal["oauth"] = "oauth"
    scopes: list[str] = Field(default_factory=list)
    client_id: str | None = None
    client_secret: SecretStr | None = Field(default=None, repr=False)
    callback_port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_credentials(self) -> Self:
        if self.client_secret is not None and not self.client_id:
            raise ValueError("client_id is required when client_secret is set.")
        return self


class ClientCredentialsConfig(_Config):
    """服务账户 OAuth；由 FastMCP 发现 token endpoint。"""

    type: Literal["client_credentials"] = "client_credentials"
    client_id: str = Field(min_length=1)
    client_secret: SecretStr = Field(min_length=1, repr=False)
    scopes: list[str] = Field(default_factory=list)
    token_endpoint_auth_method: Literal[
        "client_secret_basic", "client_secret_post"
    ] = "client_secret_basic"


AuthConfig = Annotated[
    NoAuthConfig | BearerAuthConfig | OAuthConfig | ClientCredentialsConfig,
    Field(discriminator="type"),
]


class MCPServerConfig(_Config):
    """所有连接共有的策略。required 由多服务管理器在启动时检查。"""

    enabled: bool = True
    required: bool = False
    connect_timeout: float = Field(default=30.0, gt=0)
    request_timeout: float | None = Field(default=60.0, gt=0)
    discovery_timeout: float = Field(default=60.0, gt=0)
    close_timeout: float = Field(default=5.0, gt=0)
    max_discovery_pages: int = Field(default=250, ge=1)
    max_discovery_items: int = Field(default=10000, ge=1)
    max_cursor_bytes: int = Field(default=65536, ge=1)


class StdioConfig(MCPServerConfig):
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list, repr=False)
    env: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    # load_mcp_config() 会将 cwd 转换成绝对路径。
    cwd: str | None = None

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


ServerConfig = Annotated[StdioConfig | RemoteConfig, Field(discriminator="transport")]


class MCPClientConfig(_Config):
    """配置文件根对象；字典键就是稳定的 server_id。"""

    servers: dict[str, ServerConfig] = Field(alias="mcpServers")

    @model_validator(mode="after")
    def validate_server_ids(self) -> Self:
        if any(not key or key != key.strip() for key in self.servers):
            raise ValueError("Server IDs must be nonempty and have no surrounding whitespace.")
        return self
