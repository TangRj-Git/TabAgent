from tabagent.middleware.base_middleware import (
    AppInitHandler,
    AppInitRequest,
    BaseMiddleware,
)
from tabagent.tool.registry import ToolRegistry
from tabagent.tool.tools.calculate_tool import calculate


class ToolMiddleware(BaseMiddleware):
    """
    在 App 初始化阶段统一注册默认工具。

    注册完成后，将配置交给下一层创建 LLM 和 Agent。
    后续每次 Agent 运行都会获得工具注册表的副本。
    """

    async def wrap_init(
            self,
            call_next: AppInitHandler,
            request: AppInitRequest,
    ) -> None:
        # 调用方没有提供工具注册表时，在这里创建。
        if request.tool_registry is None:
            request.tool_registry = ToolRegistry()

        registry = request.tool_registry

        # 默认工具统一在这里维护。
        # 后续添加工具时，导入对应函数并加入这个元组。
        default_tools = (
            calculate,
        )

        for tool in default_tools:
            # 保留已经注册的同名工具，避免重复注册。
            if tool.__name__ in registry.get_tools():
                continue

            # 注册是同步操作，只保存函数及其定义，不执行工具。
            registry.register_tool(tool)

        # 将包含默认工具的配置交给下一层。
        # 最终创建的 Agent 会保存这个工具注册表。
        await call_next(request)
