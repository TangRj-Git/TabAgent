from tabagent.mcp_new.mcp_config_loader import MCPConfigLoader


def test_mcp_1() -> None:
    mcp_config_loader = MCPConfigLoader(
        config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json"
    )

    mcp_config = mcp_config_loader.load()
    print(
        mcp_config.model_dump_json(
            indent=4,
            by_alias=True,
        )
    )
