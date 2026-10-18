"""macOS Zsh 工具。"""

from pathlib import Path

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
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Execution timeout in seconds; normally 120.",
        },
    },
    "required": [
        "command",
        "cwd",
        "timeout",
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


def create_zsh_tool(workspace: str | Path) -> ShellTool:
    base = BaseShell(
        workspace,
        name="Zsh",
        executable_names=("zsh",),
        version_arguments=["--version"],
        build_arguments=_build_arguments,
    )

    async def zsh(
            command: str,
            cwd: str = ".",
            timeout: float = 120.0,
    ) -> str:
        return await base.run(command, cwd, timeout)

    zsh.__doc__ = (
            base.description()
            + "\nOn macOS, utilities such as sed and date may use BSD "
              "options rather than GNU options."
    )
    return zsh
