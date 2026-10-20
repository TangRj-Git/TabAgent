"""只负责创建 FastMCP 对象；不在此处连接或启动进程。"""

from fastmcp import Client
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)

from .auth import create_auth
from .config import ServerConfig, StdioConfig


def create_client(
        server_id: str,
        config: ServerConfig
) -> Client:
    if isinstance(config, StdioConfig):
        transport = StdioTransport(
            command=config.command,
            args=list(config.args),
            env={name: value.get_secret_value() for name, value in config.env.items()},
            cwd=config.cwd,
            keep_alive=False,
        )
        auth = None
    else:
        transport_type = StreamableHttpTransport if config.transport == "http" else SSETransport
        transport = transport_type(
            url=config.url,
            headers={name: value.get_secret_value() for name, value in config.headers.items()},
        )
        auth = create_auth(config.auth)
    return Client(
        transport,
        name=f"TabAgent/{server_id}",
        auth=auth,
        timeout=config.request_timeout,
        init_timeout=config.connect_timeout,
        mode="auto",
        cache=False,
    )
