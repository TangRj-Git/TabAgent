import asyncio
from contextlib import AsyncExitStack

from pydantic import TypeAdapter

from tabagent.mcp_new.create_transport import create_transport
from tabagent.mcp_new.mcp_client import MCPServerClient
from tabagent.mcp_new.mcp_config_loader import MCPConfigLoader
from tabagent.mcp_new.mcp_model import MCPServerCatalog, MCPAllServersCatalog, MCPServerInfo, MCPAllServersInfo


def test_mcp_1() -> None:
    async def run() -> None:
        mcp_config_loader = MCPConfigLoader(
            config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json"
        )

        mcp_config = await mcp_config_loader.load()
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
            server_id=server_id,
            transport=time_stdio,
            transport_type=time.transport,
        )

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


def test_mcp_2() -> None:
    async def run() -> None:
        mcp_config_loader = MCPConfigLoader(
            config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json"
        )
        mcp_config = await mcp_config_loader.load()

        mcp_clients: dict[str, MCPServerClient] = {}

        for server_id, serverConfig in mcp_config.servers.items():
            mcp_clients[server_id] = MCPServerClient(
                server_id=server_id,
                transport=create_transport(serverConfig),
                transport_type=mcp_config.servers[server_id].transport,
            )

        server_infos = MCPAllServersInfo()
        all_servers_catalog = MCPAllServersCatalog()

        async with AsyncExitStack() as stack:
            for server_id, mcp_client in mcp_clients.items():
                client = await stack.enter_async_context(mcp_client.client)
                server_infos.servers[server_id] = MCPServerInfo(
                    server_id=server_id,
                    transport=mcp_config.servers[server_id].transport,
                    instructions=client.instructions,
                    protocol_version=client.protocol_version,
                    server_info=client.server_info,
                    server_capabilities=client.server_capabilities,
                )

                capabilities = client.server_capabilities

                mcp_server_catalog = MCPServerCatalog()

                if capabilities.tools is not None:
                    mcp_server_catalog.tools = await client.list_tools()
                if capabilities.prompts is not None:
                    mcp_server_catalog.prompts = await client.list_prompts()
                if capabilities.resources is not None:
                    mcp_server_catalog.resources = await client.list_resources()
                    mcp_server_catalog.resource_templates = await client.list_resource_templates()

                all_servers_catalog.servers[server_id] = mcp_server_catalog

            # TypeAdapter 是 Pydantic 提供的工具，可以为普通数据类、列表、字典等类型提供校验和序列化功能。
            print(
                TypeAdapter(MCPAllServersInfo).dump_json(
                    server_infos,
                    indent=4,
                    ensure_ascii=False,
                ).decode("utf-8")
            )

            print(
                TypeAdapter(MCPAllServersCatalog).dump_json(
                    all_servers_catalog,
                    indent=4,
                    ensure_ascii=False,
                ).decode("utf-8")
            )

    asyncio.run(run())


def test_mcp_3() -> None:
    async def run() -> None:
        mcp_config_loader = MCPConfigLoader(
            config_path=r"E:\OpenProject\TabAgent\resources\mcp_config.json"
        )
        mcp_config = await mcp_config_loader.load()

        all_server_infos = MCPAllServersInfo()
        all_servers_catalog = MCPAllServersCatalog()

        async with AsyncExitStack() as stack:
            for server_id, serverConfig in mcp_config.servers.items():
                mcp_client = MCPServerClient(
                    server_id=server_id,
                    transport=create_transport(serverConfig),
                    transport_type=serverConfig.transport,
                )
                client = await stack.enter_async_context(mcp_client)
                all_server_infos.servers[server_id] = client.get_server_info()
                all_servers_catalog.servers[server_id] = await client.get_catalog()

        print(
            TypeAdapter(MCPAllServersInfo).dump_json(
                all_server_infos,
                indent=4,
                ensure_ascii=False,
            ).decode("utf-8")
        )

        print(
            TypeAdapter(MCPAllServersCatalog).dump_json(
                all_servers_catalog,
                indent=4,
                ensure_ascii=False,
            ).decode("utf-8")
        )

    asyncio.run(run())
