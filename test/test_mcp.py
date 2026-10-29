import asyncio

from tabagent.mcp_new.create_transport import create_transport
from tabagent.mcp_new.mcp_client import MCPServerClient
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

    for value in mcp_config.servers.values():
        print(value)

    time = mcp_config.servers["time"]
    print(time)

    time_stdio = create_transport(time)
    print(time_stdio)

    time_mcp = MCPServerClient(
        name="time",
        transport=time_stdio,
    )
    print(time_mcp)
    print(time_mcp.name)

    async def run() -> None:
        async with time_mcp.client as client:
            print(client.name)

            tools = await client.list_tools()
            for tool in tools:
                print(tool.name)
                print(tool.title)
                print(tool.description)
                print(tool.input_schema)

            result = await client.call_tool(
                name="get_current_time",
                arguments={"timezone": "Asia/Shanghai"},
            )
            print(result.structured_content)

    asyncio.run(run())
