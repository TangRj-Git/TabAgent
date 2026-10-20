import asyncio
from types import SimpleNamespace

from mcp_types import CallToolResult, Implementation, ServerCapabilities, TextContent, Tool


class FakeClient:
    protocol_version = "2025-11-25"
    instructions = None

    def __init__(self, *, metadata: bool = False) -> None:
        self.server_info = Implementation(name="fake", version="1")
        self.server_capabilities = ServerCapabilities(
            tools={}, resources={} if metadata else None, prompts={} if metadata else None,
        )
        self.active = False
        self.entered = asyncio.Event()
        self.close_started = asyncio.Event()
        self.tool_started = asyncio.Event()
        self.discovery_started = asyncio.Event()
        self.enter_gate = None
        self.close_gate = None
        self.metadata_gate = None
        self.tools_gate = None
        self.call_gate = None
        self.enter_error = None
        self.close_error = None
        self.tools_error = None
        self.call_error = None
        self.ignore_enter_cancel = False
        self.close_count = 0
        self.call_count = 0
        self.arguments = None
        self.tool_name = "echo"

    async def __aenter__(self):
        self.entered.set()
        if self.enter_gate is not None:
            while not self.enter_gate.is_set():
                try:
                    await self.enter_gate.wait()
                except asyncio.CancelledError:
                    if not self.ignore_enter_cancel:
                        raise
        if self.enter_error is not None:
            raise self.enter_error
        self.active = True
        return self

    def is_connected(self):
        return self.active

    async def close(self):
        self.close_count += 1
        self.close_started.set()
        if self.close_gate is not None:
            await self.close_gate.wait()
        if self.close_error is not None:
            raise self.close_error
        self.active = False

    async def list_tools_mcp(self, **kwargs):
        self.discovery_started.set()
        if self.tools_gate is not None:
            await self.tools_gate.wait()
        if self.tools_error is not None:
            raise self.tools_error
        return SimpleNamespace(
            tools=[Tool(name=self.tool_name, input_schema={"type": "object"})], next_cursor=None,
        )

    async def list_resources_mcp(self, **kwargs):
        if self.metadata_gate is not None:
            await self.metadata_gate.wait()
        return SimpleNamespace(resources=[], next_cursor=None)

    async def list_resource_templates_mcp(self, **kwargs):
        if self.metadata_gate is not None:
            await self.metadata_gate.wait()
        return SimpleNamespace(resource_templates=[], next_cursor=None)

    async def list_prompts_mcp(self, **kwargs):
        if self.metadata_gate is not None:
            await self.metadata_gate.wait()
        return SimpleNamespace(prompts=[], next_cursor=None)

    async def call_tool_mcp(self, **kwargs):
        self.tool_started.set()
        self.arguments = kwargs["arguments"]
        self.call_count += 1
        if self.call_gate is not None:
            await self.call_gate.wait()
        if self.call_error is not None:
            raise self.call_error
        return CallToolResult(content=[TextContent(type="text", text="ok")])
