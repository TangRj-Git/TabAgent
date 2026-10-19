"""macOS Zsh 工具。"""

from pathlib import Path

from tabagent.tool.tools.process import ProcessManager
from tabagent.tool.tools.shell.base_shell import BaseShell, ShellTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Zsh command or script. No interactive input.",
        },
        "cwd": {
            "type": "string",
            "description": "Working directory; use '.' for the fixed workspace.",
        },
        "timeout": {
            "type": ["number", "null"],
            "exclusiveMinimum": 0,
            "description": "Total runtime limit in seconds; normally 120, or null for no runtime deadline.",
        },
        "wait_time": {
            "type": "number",
            "minimum": 0,
            "maximum": 30,
            "description": "Seconds to wait before returning a managed job; normally 2. Enables early return only when background execution is configured.",
        },
    },
    "required": [
        "command",
        "cwd",
        "timeout",
        "wait_time",
    ],
    "additionalProperties": False,
}


def _build_arguments(command: str) -> list[str]:
    # -f 关闭常规启动文件加载；系统级 zshenv 仍可能由 Zsh 读取。
    return [
        "-f",
        "-c",
        command,
    ]


def create_zsh_tool(
        workspace: str | Path,
        *,
        process_manager: ProcessManager | None = None,
) -> ShellTool:
    """创建 Zsh 工具；共享管理器由调用方持有和关闭。"""
    base = BaseShell(
        workspace,
        name="Zsh",
        executable_names=("zsh",),
        version_arguments=["--version"],
        build_arguments=_build_arguments,
        process_manager=process_manager,
    )

    async def zsh(
            command: str,
            cwd: str = ".",
            timeout: float | None = 120.0,
            *,
            wait_time: float = 2.0,
    ) -> str:
        return await base.run(
            command=command,
            cwd=cwd,
            timeout=timeout,
            wait_time=wait_time,
        )

    zsh.__doc__ = (
            base.description()
            + "\nOn macOS, utilities such as sed and date may use BSD "
              "options rather than GNU options."
    )
    return zsh
