import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn
from fastmcp import Client, FastMCP
from mcp_types import CallToolResult, TextContent

from tabagent.mcp import MCPClientManager, MCPServerClient, RemoteConfig, StdioConfig

from .stdio_server import server


def assert_four_catalogs(catalog):
    for name in ("tools", "resources", "prompts", "resource_templates"):
        collection = getattr(catalog, name)
        assert collection.status == "ready"
        assert collection.items


def test_real_in_memory_definitions_results_and_error_results():
    async def scenario():
        service = FastMCP("result-test")

        @service.tool
        def business_error() -> CallToolResult:
            return CallToolResult(
                content=[TextContent(type="text", text="The requested item is unavailable.")],
                structured_content={"found": False}, is_error=True,
            )

        raw = Client(service)
        with patch("tabagent.mcp.client.create_client", return_value=raw):
            async with MCPServerClient(server_id="real", config=StdioConfig(command="unused")) as client:
                result = await client.call_tool(name="business_error")
                assert result.is_error
                assert result.structured_content == {"found": False}
                assert result.content[0].text == "The requested item is unavailable."
        assert not raw.is_connected()

    asyncio.run(scenario())


def process_is_alive(pid):
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_real_stdio_lifecycle_and_config_routing(tmp_path):
    async def scenario():
        config_path = tmp_path / "mcp.json"
        config_path.write_text(json.dumps({"mcpServers": {"fixture": {
            "command": sys.executable,
            "args": ["-B", str(Path(__file__).with_name("stdio_server.py"))],
            "env": {"PYTHONDONTWRITEBYTECODE": "1"},
            "required": True,
        }}}), encoding="utf-8")
        async with MCPClientManager(config_path=config_path) as manager:
            await manager.wait_ready(include_metadata=True)
            assert_four_catalogs(manager.get_catalog().servers["fixture"])
            response = await manager.call_tool(server_id="fixture", name="echo", arguments={"value": "verified"})
            assert response.structured_content == {"value": "verified"}
            response = await manager.call_tool(server_id="fixture", name="process_id")
            pid = response.structured_content["result"]
            assert process_is_alive(pid)
        assert not process_is_alive(pid)
        assert manager.get_server_info("fixture").state == "disconnected"

    asyncio.run(scenario())


@pytest.mark.parametrize("transport", ["http", "sse"])
def test_real_loopback_transports_and_auth_headers(transport):
    async def scenario():
        received = []
        app = server.http_app(transport=transport)

        async def record_headers(scope, receive, send):
            if scope["type"] == "http":
                received.append(dict(scope["headers"]))
            await app(scope, receive, send)

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        host = uvicorn.Server(uvicorn.Config(record_headers, log_level="critical", lifespan="on"))
        serving = asyncio.create_task(host.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not host.started:
                    if serving.done():
                        serving.result()
                    await asyncio.sleep(0.01)
            route = "/mcp" if transport == "http" else "/sse"
            config = RemoteConfig(
                transport=transport, url=f"http://127.0.0.1:{port}{route}",
                headers={"X-Test-Key": "test-key"}, auth={"type": "bearer", "token": "test-token"},
            )
            async with MCPServerClient(server_id="loopback", config=config) as client:
                assert_four_catalogs(await client.wait_for_discovery())
                response = await client.call_tool(name="echo", arguments={"value": transport})
                assert response.structured_content == {"value": transport}
            assert any(headers.get(b"authorization") == b"Bearer test-token" for headers in received)
            assert any(headers.get(b"x-test-key") == b"test-key" for headers in received)
        finally:
            host.should_exit = True
            await asyncio.wait_for(serving, 5)
            listener.close()

    asyncio.run(scenario())
