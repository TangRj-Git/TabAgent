"""本地集成测试专用服务，不读取配置、文件或外部网络。"""

import os

from fastmcp import FastMCP

server = FastMCP("TabAgent MCP test fixture")


@server.tool
def echo(value: str) -> dict[str, str]:
    return {"value": value}


@server.tool
def process_id() -> int:
    return os.getpid()


@server.resource("data://info")
def info() -> str:
    raise AssertionError("Discovery must not read resource content.")


@server.resource("data://items/{name}")
def item(name: str) -> str:
    raise AssertionError("Discovery must not expand resource templates.")


@server.prompt
def greet(name: str) -> str:
    raise AssertionError("Discovery must not render prompts.")


if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
