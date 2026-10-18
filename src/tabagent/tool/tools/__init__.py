"""统一组织默认工具及其参数定义。"""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeAlias

from tabagent.tool.tools.calculate_tool import (
    PARAMETERS as CALCULATE_PARAMETERS,
    calculate,
)
from tabagent.tool.tools.file import (
    FILE_TOOL_PARAMETERS,
    create_file_tools,
)

# 每个工具由“可执行函数”和“参数定义”组成。
ToolDefinition: TypeAlias = tuple[
    Callable[..., Any],
    dict[str, Any],
]


def create_tools(
        workspace: str | Path
) -> list[ToolDefinition]:
    """
    创建默认工具列表。

    文件工具绑定指定的默认工作目录。
    此处只组织工具，实际注册由调用方完成。
    """

    tools: list[ToolDefinition] = [
        (
            calculate,
            deepcopy(CALCULATE_PARAMETERS)
        ),
    ]

    # 创建文件工具，并与各自的参数定义配对。
    file_tools = create_file_tools(workspace)

    for name, tool in file_tools.items():
        tools.append((
            tool,
            deepcopy(FILE_TOOL_PARAMETERS[name])
        ))

    return tools


__all__ = [
    "ToolDefinition",
    "create_tools"
]
