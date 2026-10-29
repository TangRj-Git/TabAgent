from fastmcp import Client
from fastmcp.client.transports import ClientTransport


class MCPServerClient:
    def __init__(
            self,
            name: str,
            transport: ClientTransport,
    ) -> None:
        """FastMCP 的连接和请求操作是异步的。"""
        self.name = f"TabAgent/{name}"
        self.transport = transport

        self.client = Client(
            name=self.name,
            transport=self.transport,
        )
