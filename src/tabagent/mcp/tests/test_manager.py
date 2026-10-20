import asyncio
from unittest.mock import patch

import pytest

from tabagent.mcp import MCPClientConfig, MCPClientManager, MCPConnectionError, MCPDiscoveryError

from .fakes import FakeClient


def configuration(**servers):
    return MCPClientConfig.model_validate({
        "mcpServers": {
            name: {"transport": "stdio", "command": "unused", "close_timeout": 0.05, **fields}
            for name, fields in servers.items()
        },
    })


def test_parallel_startup_and_optional_background_mode():
    async def scenario():
        first, second = FakeClient(), FakeClient()
        first.enter_gate = asyncio.Event()
        config = configuration(slow={}, healthy={"required": True})
        with (
            patch("tabagent.mcp.manager.load_mcp_config", return_value=config),
            patch("tabagent.mcp.client.create_client", side_effect=lambda name, config: {
                "slow": first, "healthy": second,
            }[name]),
        ):
            manager = MCPClientManager(config_path="unused.json", startup_concurrency=2)
            try:
                await asyncio.wait_for(manager.connect(wait_for_optional=False), 1)
                assert first.entered.is_set()
                assert second.entered.is_set()
                assert [entry.server_id for entry in manager.get_tools()] == ["healthy"]
                await manager.call_tool(server_id="healthy", name="echo")
                first.enter_gate.set()
                await manager.wait_ready(include_metadata=True)
                assert len(manager.get_tools()) == 2
            finally:
                first.enter_gate.set()
                await manager.aclose()

    asyncio.run(scenario())


def test_startup_concurrency_is_bounded_and_required_starts_first():
    async def scenario():
        optional, required = FakeClient(), FakeClient()
        required.enter_gate = asyncio.Event()
        config = configuration(optional={}, required={"required": True})
        with (
            patch("tabagent.mcp.manager.load_mcp_config", return_value=config),
            patch("tabagent.mcp.client.create_client", side_effect=lambda name, config: {
                "optional": optional, "required": required,
            }[name]),
        ):
            manager = MCPClientManager(config_path="unused.json", startup_concurrency=1)
            opening = asyncio.create_task(manager.connect())
            await required.entered.wait()
            assert not optional.entered.is_set()
            required.enter_gate.set()
            await opening
            assert optional.entered.is_set()
            await manager.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["connect", "tools"])
def test_required_failure_rolls_back_all_clients(failure):
    async def scenario():
        bad, good = FakeClient(), FakeClient()
        if failure == "connect":
            bad.enter_error = ConnectionRefusedError("private remote address")
        else:
            bad.tools_error = RuntimeError("private server detail")
        config = configuration(bad={"required": True}, good={})
        with (
            patch("tabagent.mcp.manager.load_mcp_config", return_value=config),
            patch("tabagent.mcp.client.create_client", side_effect=lambda name, config: {
                "bad": bad, "good": good,
            }[name]),
        ):
            manager = MCPClientManager(config_path="unused.json")
            with pytest.raises((MCPConnectionError, MCPDiscoveryError)):
                await manager.connect()
            assert not manager.is_open
            assert not bad.active and not good.active
            assert good.close_started.is_set()

    asyncio.run(scenario())


def test_manager_close_interrupts_startup_and_closes_other_servers():
    async def scenario():
        slow, good = FakeClient(), FakeClient()
        slow.enter_gate = asyncio.Event()
        config = configuration(slow={}, good={})
        with (
            patch("tabagent.mcp.manager.load_mcp_config", return_value=config),
            patch("tabagent.mcp.client.create_client", side_effect=lambda name, config: {
                "slow": slow, "good": good,
            }[name]),
        ):
            manager = MCPClientManager(config_path="unused.json")
            opening = asyncio.create_task(manager.connect())
            await slow.entered.wait()
            await manager.aclose()
            await asyncio.gather(opening, return_exceptions=True)
            assert not manager.is_open
            assert not slow.active and not good.active
            assert slow.close_started.is_set() and good.close_started.is_set()

    asyncio.run(scenario())


def test_one_blocked_cleanup_does_not_prevent_other_server_cleanup():
    async def scenario():
        slow, good = FakeClient(), FakeClient()
        slow.close_gate = asyncio.Event()
        config = configuration(slow={}, good={})
        with (
            patch("tabagent.mcp.manager.load_mcp_config", return_value=config),
            patch("tabagent.mcp.client.create_client", side_effect=lambda name, config: {
                "slow": slow, "good": good,
            }[name]),
        ):
            manager = MCPClientManager(config_path="unused.json")
            await manager.connect()
            try:
                with pytest.raises(MCPConnectionError):
                    await asyncio.wait_for(manager.aclose(), 1)
                assert not good.active
                assert manager.get_server_info("slow").cleanup_pending
                with pytest.raises(MCPConnectionError, match="unfinished"):
                    await manager.connect()
            finally:
                slow.close_gate.set()
                await manager.aclose()

    asyncio.run(scenario())


def test_reconnect_coalesces_and_does_not_reopen_other_servers():
    async def scenario():
        failed, recovered, other = FakeClient(), FakeClient(), FakeClient()
        failed.enter_error = ConnectionRefusedError()
        recovered.enter_gate = asyncio.Event()
        config = configuration(retry={}, other={})
        factories = {"retry": [failed, recovered], "other": [other]}
        counts = {"retry": 0, "other": 0}

        def create(name, config):
            result = factories[name][counts[name]]
            counts[name] += 1
            return result

        with (
            patch("tabagent.mcp.manager.load_mcp_config", return_value=config),
            patch("tabagent.mcp.client.create_client", side_effect=create),
        ):
            async with MCPClientManager(config_path="unused.json") as manager:
                first = asyncio.create_task(manager.reconnect(server_id="retry"))
                second = asyncio.create_task(manager.reconnect(server_id="retry"))
                await recovered.entered.wait()
                recovered.enter_gate.set()
                catalogs = await asyncio.gather(first, second)
                assert all(catalog.tools.status == "ready" for catalog in catalogs)
                assert counts == {"retry": 2, "other": 1}
                assert other.close_count == 0
                assert len(manager.get_tools()) == 2

    asyncio.run(scenario())
