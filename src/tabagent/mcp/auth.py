"""将本项目的认证配置转换为 FastMCP 认证对象。"""

import httpx2
from fastmcp.client.auth import BearerAuth, ClientCredentialsOAuthProvider, OAuth

from .config import (
    AuthConfig,
    BearerAuthConfig,
    ClientCredentialsConfig,
    NoAuthConfig,
    OAuthConfig,
)
from .exceptions import MCPConfigError


def create_auth(config: AuthConfig | None) -> httpx2.Auth | None:
    if config is None or isinstance(config, NoAuthConfig):
        return None
    if isinstance(config, BearerAuthConfig):
        return BearerAuth(config.token.get_secret_value())
    if isinstance(config, OAuthConfig):
        return OAuth(
            scopes=list(config.scopes),
            client_id=config.client_id,
            client_secret=(
                config.client_secret.get_secret_value()
                if config.client_secret is not None else None
            ),
            callback_port=config.callback_port,
        )
    if isinstance(config, ClientCredentialsConfig):
        return ClientCredentialsOAuthProvider(
            client_id=config.client_id,
            client_secret=config.client_secret.get_secret_value(),
            scopes=list(config.scopes),
            token_endpoint_auth_method=config.token_endpoint_auth_method,
        )
    raise MCPConfigError("Unsupported MCP authentication configuration.")
