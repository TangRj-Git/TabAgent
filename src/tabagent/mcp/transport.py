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
        # 工具调用单独传入 request_timeout，不将它用作全局会话超时。
        # 否则较短的工具超时也会中断握手和目录发现；这两阶段已有各自的时限。
        timeout=None,
        init_timeout=config.connect_timeout,
        mode="auto",
        cache=False,
    )
