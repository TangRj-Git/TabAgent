import asyncio
from unittest.mock import patch

import pytest

from tabagent.mcp import MCPConnectionError, MCPNotConnectedError, MCPRequestError, MCPServerClient, StdioConfig

from .fakes import FakeClient


def wrapper(**config):
    return MCPServerClient(
        server_id="test", config=StdioConfig(command="unused", close_timeout=0.05, **config),
    )


def test_tools_available_before_metadata_and_snapshots_are_independent():
    async def scenario():
        fake = FakeClient(metadata=True)
        fake.metadata_gate = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            try:
                await asyncio.wait_for(client.connect(), 1)
                assert client.get_tools().status == "ready"
                assert client.get_catalog().resources.status == "unloaded"
                snapshot = client.get_tools()
                snapshot.items.clear()
                assert len(client.get_tools().items) == 1
                await client.call_tool(name="echo")
                fake.metadata_gate.set()
                catalog = await client.wait_for_discovery()
                assert all(getattr(catalog, name).status == "ready" for name in (
                    "tools", "resources", "prompts", "resource_templates",
                ))
            finally:
                fake.metadata_gate.set()
                await client.aclose()

    asyncio.run(scenario())


def test_close_interrupts_connect_instead_of_waiting_for_its_lock():
    async def scenario():
        fake = FakeClient()
        fake.enter_gate = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            connecting = asyncio.create_task(client.connect())
            await fake.entered.wait()
            await asyncio.wait_for(client.aclose(), 1)
            result = await asyncio.gather(connecting, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert fake.close_started.is_set()
            assert not fake.active
            assert client.get_server_info().state == "disconnected"

    asyncio.run(scenario())


def test_late_connect_is_closed_after_timeout_and_owned_until_finished():
    async def scenario():
        fake = FakeClient()
        fake.enter_gate = asyncio.Event()
        fake.ignore_enter_cancel = True
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            connecting = asyncio.create_task(client.connect())
            try:
                await fake.entered.wait()
                with pytest.raises(MCPConnectionError, match="still running"):
                    await asyncio.wait_for(client.aclose(), 1)
                info = client.get_server_info()
                assert info.cleanup_pending
                assert info.cleanup_error.category == "timeout"
                with pytest.raises(MCPConnectionError, match="unfinished"):
                    await client.connect()
                with pytest.raises(MCPNotConnectedError):
                    await client.call_tool(name="echo")
            finally:
                fake.enter_gate.set()
                await asyncio.gather(connecting, return_exceptions=True)
                await client.aclose()
            assert not fake.active
            assert fake.close_count >= 2
            assert not client.get_server_info().cleanup_pending

    asyncio.run(scenario())


def test_blocked_transport_close_has_a_deadline_and_can_finish_later():
    async def scenario():
        fake = FakeClient()
        fake.close_gate = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            await client.connect()
            await client.wait_for_discovery()
            try:
                with pytest.raises(MCPConnectionError):
                    await asyncio.wait_for(client.aclose(), 1)
                assert client.get_server_info().cleanup_pending
                assert fake.close_count == 1
            finally:
                fake.close_gate.set()
                await client.aclose()
            assert not client.get_server_info().cleanup_pending

    asyncio.run(scenario())


def test_repeated_cancellation_is_propagated_after_cleanup():
    async def scenario():
        fake = FakeClient()
        fake.close_gate = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            await client.connect()
            closing = asyncio.create_task(client.aclose())
            await fake.close_started.wait()
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            fake.close_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert not fake.active
            assert not client.get_server_info().cleanup_pending

    asyncio.run(scenario())


def test_external_wait_for_cannot_turn_cleanup_into_an_infinite_wait():
    async def scenario():
        fake = FakeClient()
        fake.close_gate = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            await client.connect()
            waiting = asyncio.create_task(asyncio.wait_for(client.aclose(), 0.01))
            try:
                done, _ = await asyncio.wait({waiting}, timeout=0.5)
                assert waiting in done
                with pytest.raises(TimeoutError):
                    waiting.result()
                assert client.get_server_info().cleanup_pending
            finally:
                fake.close_gate.set()
                await asyncio.gather(waiting, return_exceptions=True)
                await client.aclose()

    asyncio.run(scenario())


def test_connection_error_and_cleanup_error_are_both_preserved():
    async def scenario():
        fake = FakeClient()
        missing = FileNotFoundError("private executable and token=secret")
        fake.enter_error = RuntimeError("authorization=secret")
        fake.enter_error.__cause__ = missing
        fake.close_error = RuntimeError("secret cleanup detail")
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            with pytest.raises(MCPConnectionError) as raised:
                await client.connect()
            assert raised.value.info.category == "not_found"
            assert raised.value.__notes__
            info = client.get_server_info()
            assert info.error.operation == "connect"
            assert info.cleanup_error.operation == "close"
            assert "secret" not in str(raised.value)
            assert "secret" not in repr(info)
            fake.close_error = None
            await client.aclose()
            assert client.get_server_info().cleanup_error is None

    asyncio.run(scenario())


def test_refresh_cancelled_by_close_cannot_publish_ready_after_close():
    async def scenario():
        fake = FakeClient()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            await client.connect()
            await client.wait_for_discovery()
            fake.tools_gate = asyncio.Event()
            fake.discovery_started.clear()
            refreshing = asyncio.create_task(client.refresh())
            await fake.discovery_started.wait()
            await client.aclose()
            result = await asyncio.gather(refreshing, return_exceptions=True)
            assert isinstance(result[0], (asyncio.CancelledError, MCPNotConnectedError))
            assert client.get_tools().stale

    asyncio.run(scenario())


def test_tool_timeout_is_not_retried_and_bad_arguments_never_reach_sdk():
    async def scenario():
        fake = FakeClient()
        fake.call_gate = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            async with wrapper(request_timeout=0.02) as client:
                with pytest.raises(MCPRequestError):
                    await client.call_tool(name="echo", arguments={"bad": {1: "value"}})
                assert fake.call_count == 0
                with pytest.raises(MCPRequestError) as raised:
                    await client.call_tool(name="echo")
                assert raised.value.info.category == "timeout"
                assert "unknown" in str(raised.value)
                assert fake.call_count == 1

    asyncio.run(scenario())


def test_close_cancels_owned_tool_request_but_caller_can_handle_it():
    async def scenario():
        fake = FakeClient()
        fake.call_gate = asyncio.Event()
        resumed = asyncio.Event()
        with patch("tabagent.mcp.client.create_client", return_value=fake):
            client = wrapper()
            await client.connect()

            async def caller():
                try:
                    await client.call_tool(name="echo")
                except asyncio.CancelledError:
                    resumed.set()
                return "caller continued"

            task = asyncio.create_task(caller())
            await fake.tool_started.wait()
            await client.aclose()
            assert await task == "caller continued"
            assert resumed.is_set()

    asyncio.run(scenario())
