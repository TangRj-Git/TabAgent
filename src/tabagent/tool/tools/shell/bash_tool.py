"""Linux Bash 工具。"""

from pathlib import Path

from tabagent.tool.tools.shell.base_shell import BaseShell, ShellTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Bash command or script. No interactive input.",
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
    return [
        "--noprofile",
        "--norc",
        "-c",
        command,
    ]


def create_bash_tool(workspace: str | Path) -> ShellTool:
    base = BaseShell(
        workspace,
        name="Bash",
        executable_names=("bash",),
        version_arguments=["--version"],
        build_arguments=_build_arguments,
    )

    async def bash(
            command: str,
            cwd: str = ".",
            timeout: float = 120.0,
    ) -> str:
        return await base.run(command, cwd, timeout)

    bash.__doc__ = base.description()
    return bash
