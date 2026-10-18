"""根据当前系统创建 Shell 工具；实际注册交给 ToolRegistry。"""

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from tabagent.core.exceptions import ToolRegistrationError
from tabagent.tool.tools.shell.base_shell import ShellTool
from tabagent.tool.tools.shell.bash_tool import (
    PARAMETERS as BASH_PARAMETERS,
    create_bash_tool,
)
from tabagent.tool.tools.shell.powershell_tool import (
    PARAMETERS as POWERSHELL_PARAMETERS,
    create_powershell_tool,
)
from tabagent.tool.tools.shell.zsh_tool import (
    PARAMETERS as ZSH_PARAMETERS,
    create_zsh_tool,
)

SHELL_TOOL_PARAMETERS = {
    "powershell": POWERSHELL_PARAMETERS,
    "bash": BASH_PARAMETERS,
    "zsh": ZSH_PARAMETERS,
}


def create_shell_tool(workspace: str | Path) -> ShellTool:
    """只创建当前系统对应的工具，并在初始化时确定解释器及其版本。"""
    if sys.platform == "win32":
        return create_powershell_tool(workspace)
    if sys.platform == "linux":
        return create_bash_tool(workspace)
    if sys.platform == "darwin":
        return create_zsh_tool(workspace)

    raise ToolRegistrationError(
        f"Shell tools are not supported on platform {sys.platform!r}."
    )


def create_shell_tools(
        workspace: str | Path,
) -> list[tuple[ShellTool, dict[str, Any]]]:
    """返回一个工具及其参数定义，供上层 create_tools() 统一汇总。"""
    tool = create_shell_tool(workspace)
    return [
        (
            tool,
            deepcopy(SHELL_TOOL_PARAMETERS[tool.__name__]),
        ),
    ]


__all__ = [
    "SHELL_TOOL_PARAMETERS",
    "create_shell_tool",
    "create_shell_tools",
]
