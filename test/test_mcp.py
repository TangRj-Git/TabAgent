from tabagent.mcp import MCPClientManager


def test_mcp_1() -> None:
    mcp_client_manager = MCPClientManager(
        config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json",
        startup_concurrency=4,
    )

    print(mcp_client_manager.config_path)
    print(mcp_client_manager.is_open)
