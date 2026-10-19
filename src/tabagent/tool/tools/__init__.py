"""统一组织默认工具及其参数定义。"""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeAlias

from tabagent.tool.tools.calulate import (
    PARAMETERS as CALCULATE_PARAMETERS,
    calculate,
)
from tabagent.tool.tools.file import (
    FILE_TOOL_PARAMETERS,
    create_file_tools,
)
from tabagent.tool.tools.process import (
    PROCESS_TOOL_PARAMETERS,
    ProcessManager,
    create_process_tools,
)
from tabagent.tool.tools.shell import create_shell_tools

# 每个工具由“可执行函数”和“参数定义”组成。
ToolDefinition: TypeAlias = tuple[
    Callable[..., Any],
    dict[str, Any],
]


def create_tools(
        workspace: str | Path,
        *,
        process_manager: ProcessManager | None = None,
) -> list[ToolDefinition]:
    """
    创建默认工具列表。

    文件和 Shell 工具绑定指定的默认工作目录。
    传入共享管理器时，Shell 与进程查询、列表、停止工具绑定同一实例。
    管理器由调用方创建和关闭，本函数不管理其生命周期。
    未传入管理器时，Shell 等待执行完成，且不创建进程管理工具。
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

    # 只汇总当前系统对应的 Shell 工具。
    tools.extend(create_shell_tools(
        workspace,
        process_manager=process_manager,
    ))

    # 进程工具必须与 Shell 共用管理器，才能查询和停止 Shell 创建的任务。
    if process_manager is not None:
        for name, tool in create_process_tools(process_manager).items():
            tools.append((
                tool,
                deepcopy(PROCESS_TOOL_PARAMETERS[name]),
            ))

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
