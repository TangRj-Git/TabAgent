from tabagent.middleware.base_middleware import (
    AppInitHandler,
    AppInitRequest,
    BaseMiddleware,
)
from tabagent.tool.tools import create_tools
from tabagent.tool.registry import ToolRegistry


class ToolMiddleware(BaseMiddleware):
    """
    在 App 初始化阶段统一创建并注册默认工具。

    文件工具绑定 AppInitRequest.workspace。
    后续 Agent 运行使用已经注册的工具。
    """

    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        if request.tool_registry is None:
            request.tool_registry = ToolRegistry()

        registry = request.tool_registry
        registered_names = set(registry.get_tools())

        # 创建工具函数，并取得各工具手动定义的参数 schema。
        default_tools = create_tools(
            workspace=request.workspace,
            process_manager=request.process_manager,
        )

        for tool, parameters in default_tools:
            tool_name = tool.__name__

            # 延续现有行为：调用方提供的同名工具优先。
            if tool_name in registered_names:
                continue

            # 显式提供 parameters，跳过自动参数 schema 构建。
            registry.register_tool(
                tool=tool,
                name=tool_name,
                parameters=parameters,
            )

            registered_names.add(tool_name)

        # 将完成工具注册的配置交给下一层。
        await call_next(request)
