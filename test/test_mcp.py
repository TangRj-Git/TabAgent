import asyncio

from tabagent.mcp import MCPClientManager


def test_mcp_1() -> None:
    mcp_client_manager = MCPClientManager(
        config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json",
        startup_concurrency=4,
    )

    print(mcp_client_manager.config_path)
    print(mcp_client_manager.is_open)

    async def run() -> None:
        await mcp_client_manager.connect(wait_for_optional=True)
        print(mcp_client_manager.config_path)
        print(mcp_client_manager.is_open)

        server_infos = mcp_client_manager.get_server_infos()
        print(server_infos)

        catalog = mcp_client_manager.get_catalog()
        print(catalog)

        tools = mcp_client_manager.get_tools()
        print(tools)

    asyncio.run(run())
