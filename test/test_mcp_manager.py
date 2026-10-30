import asyncio

from tabagent.mcp.config_loader import MCPConfigLoader
from tabagent.mcp.manager import MCPServerClientManager


def test_mcp_manager_1() -> None:
    async def run() -> None:
        mcp_config = await MCPConfigLoader(
            config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json"
        ).load()

        mcp_manager = MCPServerClientManager(mcp_config)

        try:
            await mcp_manager.connect()

            print(mcp_manager.get_all_server_infos())
            print(await mcp_manager.get_all_catalogs())
            print(await mcp_manager.get_all_tools())
            print(await mcp_manager.get_all_functions())

        finally:
            await mcp_manager.aclose()

    asyncio.run(run())
