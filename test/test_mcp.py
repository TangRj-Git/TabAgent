import asyncio

from pydantic import TypeAdapter

from tabagent.mcp_new.create_transport import create_transport
from tabagent.mcp_new.mcp_client import MCPServerClient
from tabagent.mcp_new.mcp_config_loader import MCPConfigLoader
from tabagent.mcp_new.mcp_model import MCPServerCatalog, MCPAllServersCatalog, MCPServerInfo


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

    server_id = "time"
    time = mcp_config.servers[server_id]
    time_stdio = create_transport(time)

    time_mcp = MCPServerClient(
        name=server_id,
        transport=time_stdio,
    )

    async def run() -> None:
        async with time_mcp.client as client:
            mcp_server_info = MCPServerInfo(
                server_id=server_id,
                transport=time.transport,
                instructions=client.instructions,
                protocol_version=client.protocol_version,
                server_info=client.server_info,
                server_capabilities=client.server_capabilities,
            )
            print(mcp_server_info)

            tools = await client.list_tools()
            prompts = await client.list_prompts()
            resources = await client.list_resources()
            resource_template = await client.list_resource_templates()

            time_catalog = MCPServerCatalog(
                tools=tools,
                prompts=prompts,
                resources=resources,
                resource_templates=resource_template,
            )
            adapter = TypeAdapter(MCPServerCatalog)

            print(
                adapter.dump_json(
                    time_catalog,
                    indent=2,
                    ensure_ascii=False,
                ).decode("utf-8")
            )

            mcp_all_servers_catalog = MCPAllServersCatalog(
                servers={"time": time_catalog}
            )
            print(mcp_all_servers_catalog)

            result = await client.call_tool(
                name="get_current_time",
                arguments={"timezone": "Asia/Shanghai"},
            )
            print(result.structured_content)

    asyncio.run(run())
