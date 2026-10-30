import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from mcp_types import Tool

from tabagent.mcp import client as client_module
from tabagent.mcp import manager as manager_module
from tabagent.mcp.client import MCPServerClient
from tabagent.mcp.manager import MCPServerClientManager
from tabagent.mcp.transport import MCPClientConfig


@dataclass
class FakeTransport:
    fail_connect: bool = False
    fail_close: bool = False
    gate: asyncio.Event | None = None
    started: asyncio.Event | None = None
    opens: int = 0
    closes: int = 0


class FakeClient:
    def __init__(self, *, name, transport, init_timeout):
        self.name = name
        self.transport = transport
        self.connected = False
        self.instructions = None
        self.protocol_version = None
        self.server_info = None
        self.server_capabilities = SimpleNamespace(
            tools=object(), prompts=None, resources=None,
        )

    def is_connected(self):
        return self.connected

    async def __aenter__(self):
        self.transport.opens += 1
        if self.transport.started is not None:
            self.transport.started.set()
        if self.transport.gate is not None:
            await self.transport.gate.wait()
        if self.transport.fail_connect:
            raise ConnectionError("Simulated startup failure.")
        self.connected = True
        return self

    async def __aexit__(self, *exc):
        self.connected = False

    async def close(self):
        self.transport.closes += 1
        self.connected = False
        if self.transport.fail_close:
            self.transport.fail_close = False
            raise RuntimeError("Simulated cleanup failure.")

    async def list_tools(self):
        if not self.connected:
            raise RuntimeError("Not connected.")
        return [Tool(name=f"{self.name}_echo", input_schema={"type": "object"})]

    async def call_tool(self, *, name, arguments):
        if not self.connected:
            raise RuntimeError("Not connected.")
        return self.name, name, arguments


def make_config(*names):
    return MCPClientConfig.model_validate({
        "mcpServers": {
            name: {"transport": "stdio", "command": name}
            for name in names
        },
    })


@pytest.fixture
def fake_clients(monkeypatch):
    monkeypatch.setattr(client_module, "Client", FakeClient)

    def build(transports, **kwargs):
        monkeypatch.setattr(
            manager_module, "create_transport",
            lambda config: transports[config.command],
        )
        return MCPServerClientManager(make_config(*transports), **kwargs)

    return build


def run(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, timeout=10))


def test_client_reuses_connection_and_reopens_after_disconnect(fake_clients):
    async def scenario():
        transport = FakeTransport()
        manager = fake_clients({"time": transport})
        try:
            await asyncio.gather(
                manager.connect_server("time"), manager.connect_server("time"),
            )
            client = manager.get_client("time")
            assert transport.opens == 1
            snapshot = client.get_status()

            await manager.disconnect_server("time")
            assert snapshot.state == "connected"
            assert manager.get_status("time").state == "disconnected"
            with pytest.raises(RuntimeError, match="not connected"):
                await client.call_tool("echo")

            await manager.connect_server("time")
            await manager.reconnect_server("time")
            assert manager.get_client("time") is client
            assert transport.opens == 3
        finally:
            await manager.aclose()

        assert manager.get_status("time").state == "closed"
        with pytest.raises(RuntimeError, match="closed"):
            await manager.connect()
        with pytest.raises(RuntimeError, match="closed"):
            await client.connect()

    run(scenario())


def test_optional_failure_preserves_other_services_and_aggregations(fake_clients):
    async def scenario():
        good, bad = FakeTransport(), FakeTransport(fail_connect=True)
        manager = fake_clients({"good": good, "bad": bad})
        try:
            results = await manager.connect()
            assert results["good"] is None
            assert "ConnectionError" in results["bad"]
            assert manager.get_status("bad").state == "failed"
            assert bad.closes == 1
            assert manager.get_all_server_infos().servers.keys() == {"good"}
            assert (await manager.get_all_catalogs()).servers.keys() == {"good"}
            assert [tool.name for tool in await manager.get_all_tools()] == ["good_echo"]
            assert [f["name"] for f in await manager.get_all_functions()] == ["good_echo"]

            assert await manager.call_tool("good", "echo", {"text": "ok"}) == (
                "good", "echo", {"text": "ok"},
            )
            with pytest.raises(RuntimeError, match="not connected"):
                manager.get_client("bad")
            with pytest.raises(KeyError, match="Unknown MCP server"):
                await manager.connect_server("missing")

            bad.fail_connect = False
            await manager.reconnect_server("bad")
            assert manager.get_status("bad").error is None
            await manager.disconnect_server("bad")
            assert good.opens == 1
            assert manager.get_client("good").is_connected()
        finally:
            await manager.aclose()

    run(scenario())


def test_required_failure_is_reported_after_other_servers_start(fake_clients):
    async def scenario():
        manager = fake_clients(
            {"bad": FakeTransport(fail_connect=True), "good": FakeTransport()},
            required_servers={"bad"},
        )
        try:
            with pytest.raises(RuntimeError, match="Required MCP servers failed"):
                await manager.connect()
            assert manager.get_client("good").is_connected()
        finally:
            await manager.aclose()

    run(scenario())


def test_unknown_required_server_is_rejected(fake_clients):
    with pytest.raises(ValueError, match="Unknown required MCP servers"):
        fake_clients({"time": FakeTransport()}, required_servers={"missing"})


def test_slow_server_does_not_lock_other_servers(fake_clients):
    async def scenario():
        gate, started = asyncio.Event(), asyncio.Event()
        manager = fake_clients({
            "slow": FakeTransport(gate=gate, started=started),
            "fast": FakeTransport(),
        })
        opening = asyncio.create_task(manager.connect_server("slow"))
        try:
            await started.wait()
            await asyncio.wait_for(manager.connect_server("fast"), timeout=1)
            await manager.reconnect_server("fast")
            assert not opening.done()
            assert manager.get_client("fast").is_connected()
        finally:
            gate.set()
            await opening
            await manager.aclose()

    run(scenario())


def test_connection_timeout_cleans_partial_connection(fake_clients):
    async def scenario():
        transport = FakeTransport(gate=asyncio.Event())
        manager = fake_clients({"slow": transport}, connect_timeout=0.02)
        try:
            result = await manager.connect()
            assert "TimeoutError" in result["slow"]
            assert manager.get_status("slow").state == "failed"
            assert transport.closes == 1
        finally:
            await manager.aclose()

    run(scenario())


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_startup_cancellation_is_not_swallowed(fake_clients, cleanup_fails):
    async def scenario():
        started = asyncio.Event()
        pending = FakeTransport(
            gate=asyncio.Event(), started=started, fail_close=cleanup_fails,
        )
        manager = fake_clients({"good": FakeTransport(), "pending": pending})
        opening = asyncio.create_task(manager.connect())
        try:
            await started.wait()
            opening.cancel()
            with pytest.raises(asyncio.CancelledError):
                await opening
            assert manager.get_client("good").is_connected()
            assert pending.closes == 1
        finally:
            await manager.aclose()
        assert all(s.state == "closed" for s in manager.get_all_statuses().values())

    run(scenario())


def test_shutdown_attempts_all_clients_and_allows_cleanup_retry(fake_clients):
    async def scenario():
        first, second = FakeTransport(), FakeTransport()
        manager = fake_clients({"first": first, "second": second})
        await manager.connect()
        first.fail_close = True

        with pytest.raises(ExceptionGroup, match="Failed to close MCP clients") as exc:
            await manager.aclose()
        assert "MCP server: first" in exc.value.exceptions[0].__notes__
        assert manager.get_status("first").state == "failed"
        assert manager.get_status("second").state == "closed"
        assert second.closes == 1

        await manager.aclose()
        assert manager.get_status("first").state == "closed"

    run(scenario())


def test_shutdown_during_startup_rejects_new_connections(fake_clients):
    async def scenario():
        gate, started = asyncio.Event(), asyncio.Event()
        late = FakeTransport()
        manager = fake_clients({
            "slow": FakeTransport(gate=gate, started=started), "late": late,
        })
        opening = asyncio.create_task(manager.connect_server("slow"))
        await started.wait()
        closing = asyncio.create_task(manager.aclose())
        await asyncio.sleep(0)
        try:
            with pytest.raises(RuntimeError, match="closed"):
                await manager.connect_server("late")
        finally:
            gate.set()
            await opening
            await closing
        assert late.opens == 0
        assert all(s.state == "closed" for s in manager.get_all_statuses().values())

    run(scenario())


def test_context_exit_closes_transport_and_allows_reentry(fake_clients):
    async def scenario():
        transport = FakeTransport()
        client = MCPServerClient("time", transport, "stdio")
        with pytest.raises(ValueError, match="business failure"):
            async with client as connected:
                assert connected is client
                raise ValueError("business failure")
        assert client.get_status().state == "disconnected"
        assert transport.closes == 1
        async with client:
            assert client.is_connected()
        assert transport.opens == 2
        await client.aclose()

    run(scenario())


def test_lost_connection_is_reported_and_explicitly_reconnected(fake_clients):
    async def scenario():
        transport = FakeTransport()
        manager = fake_clients({"time": transport})
        try:
            await manager.connect()
            manager.get_client("time").client.connected = False
            assert manager.get_status("time").state == "disconnected"
            assert await manager.get_all_tools() == []
            await manager.connect_server("time")
            assert transport.opens == 2
            assert manager.get_client("time").is_connected()
        finally:
            await manager.aclose()

    run(scenario())


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_connection_timeout_is_rejected(fake_clients, timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        fake_clients({"time": FakeTransport()}, connect_timeout=timeout)


def test_real_fastmcp_in_process_connection_discovery_and_reconnect(monkeypatch):
    server = FastMCP("lifecycle-test")

    @server.tool
    def echo(text: str) -> str:
        return text

    monkeypatch.setattr(
        manager_module, "create_transport", lambda config: FastMCPTransport(server),
    )

    async def scenario():
        manager = MCPServerClientManager(make_config("in_process"))
        try:
            assert await manager.connect() == {"in_process": None}
            info = manager.get_all_server_infos().servers["in_process"]
            assert info.server_info.name == "lifecycle-test"
            catalog = (await manager.get_all_catalogs()).servers["in_process"]
            assert [tool.name for tool in catalog.tools] == ["echo"]
            assert [tool.name for tool in await manager.get_all_tools()] == ["echo"]
            assert [f["name"] for f in await manager.get_all_functions()] == ["echo"]

            result = await manager.call_tool("in_process", "echo", {"text": "before"})
            assert isinstance(result, CallToolResult)
            assert result.content[0].text == "before"

            await manager.disconnect_server("in_process")
            assert manager.get_all_server_infos().servers == {}
            await manager.reconnect_server("in_process")
            result = await manager.call_tool("in_process", "echo", {"text": "after"})
            assert result.content[0].text == "after"
        finally:
            await manager.aclose()
        assert manager.get_status("in_process").state == "closed"

    run(scenario())
