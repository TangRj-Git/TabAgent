from pathlib import Path

from fastmcp.client import StdioTransport, SSETransport, StreamableHttpTransport, ClientTransport

from tabagent.mcp.auth import create_auth
from tabagent.mcp.transport import StdioConfig, SSEConfig, HttpConfig, ServerConfig


def create_stdio_transport(config: StdioConfig) -> StdioTransport:
    return StdioTransport(
        command=config.command,
        args=config.args,
        env=config.env,
        cwd=config.cwd,
        keep_alive=config.keep_alive,
        log_file=Path(config.log_file) if config.log_file is not None else None,
    )


def create_sse_transport(config: SSEConfig) -> SSETransport:
    return SSETransport(
        url=config.url,
        headers=config.headers,
        auth=create_auth(config.auth),
        sse_read_timeout=config.sse_read_timeout,
    )


def create_http_transport(config: HttpConfig) -> StreamableHttpTransport:
    return StreamableHttpTransport(
        url=config.url,
        headers=config.headers,
        auth=create_auth(config.auth),
    )


def create_transport(config: ServerConfig) -> ClientTransport:
    if isinstance(config, StdioConfig):
        return create_stdio_transport(config)

    if isinstance(config, HttpConfig):
        return create_http_transport(config)

    if isinstance(config, SSEConfig):
        return create_sse_transport(config)

    raise TypeError(f"Unsupported transport configuration type: {type(config).__name__}.")
