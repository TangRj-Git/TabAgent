from typing import Literal, Annotated

import httpx2
from fastmcp.client import BearerAuth, OAuth, ClientCredentialsOAuthProvider
from pydantic import BaseModel, ConfigDict, SecretStr, Field


class AuthBaseConfig(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class NoAuthConfig(AuthBaseConfig):
    """不额外配置认证。"""

    type: Literal["none"] = "none"


class BearerAuthConfig(AuthBaseConfig):
    """使用已有的访问令牌。"""

    type: Literal["bearer"] = "bearer"

    token: SecretStr = Field(min_length=1, repr=False)


class OAuthConfig(AuthBaseConfig):
    """通过浏览器登录、授权。"""

    type: Literal["oauth"] = "oauth"

    scopes: str | list[str] | None = None
    callback_port: int | None = Field(default=None, ge=1, le=65535)
    client_id: str | None = Field(default=None, min_length=1)
    client_secret: SecretStr | None = Field(default=None, min_length=1, repr=False)


class ClientCredentialsConfig(AuthBaseConfig):
    """程序通过客户端 ID 和密钥申请访问令牌。"""

    type: Literal["client_credentials"] = "client_credentials"

    client_id: str = Field(min_length=1)
    client_secret: SecretStr = Field(min_length=1, repr=False)
    scopes: str | list[str] | None = None
    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic"


AuthConfig = Annotated[
    NoAuthConfig | BearerAuthConfig | OAuthConfig | ClientCredentialsConfig,
    Field(discriminator="type"),
]


def create_auth(config: AuthConfig | None) -> httpx2.Auth | None:
    if config is None or isinstance(config, NoAuthConfig):
        return None

    if isinstance(config, BearerAuthConfig):
        return BearerAuth(
            token=config.token.get_secret_value(),
        )

    if isinstance(config, OAuthConfig):
        return OAuth(
            scopes=config.scopes,
            callback_port=config.callback_port,
            client_id=config.client_id,
            client_secret=(
                config.client_secret.get_secret_value()
                if config.client_secret is not None
                else None
            ),
        )

    if isinstance(config, ClientCredentialsConfig):
        return ClientCredentialsOAuthProvider(
            client_id=config.client_id,
            client_secret=(
                config.client_secret.get_secret_value()
                if config.client_secret is not None
                else None
            ),
            scopes=config.scopes,
            token_endpoint_auth_method=config.token_endpoint_auth_method,
        )

    raise TypeError(f"Unsupported authentication configuration type: {type(config).__name__}.")
