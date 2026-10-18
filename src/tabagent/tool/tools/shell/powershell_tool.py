"""Windows PowerShell 工具，优先使用 PowerShell 7。"""

import base64
from pathlib import Path

from tabagent.tool.tools.shell.base_shell import BaseShell, ShellTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "PowerShell command or script. No interactive input.",
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
    # 使用编码脚本传递原始命令，避免额外的命令行引号转义。
    # 统一 PowerShell 编码，并保留本机程序的退出码。
    script = (
            "$ErrorActionPreference = 'Stop'\n"
            "$utf8 = [System.Text.UTF8Encoding]::new($false)\n"
            "[Console]::InputEncoding = $utf8\n"
            "[Console]::OutputEncoding = $utf8\n"
            "$OutputEncoding = $utf8\n"
            "$global:LASTEXITCODE = 0\n"
            "try {\n"
            "    & {\n"
            + command
            + "\n    }\n"
              "    $commandSucceeded = $?\n"
              "    if (-not $commandSucceeded -and $LASTEXITCODE -eq 0) { exit 1 }\n"
              "    exit $LASTEXITCODE\n"
              "} catch {\n"
              "    [Console]::Error.WriteLine($_.ToString())\n"
              "    exit 1\n"
              "}\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        encoded,
    ]


def create_powershell_tool(workspace: str | Path) -> ShellTool:
    base = BaseShell(
        workspace,
        name="PowerShell",
        executable_names=(
            "pwsh",
            "powershell",
        ),
        version_arguments=[
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        ],
        build_arguments=_build_arguments,
    )

    async def powershell(
            command: str,
            cwd: str = ".",
            timeout: float = 120.0,
    ) -> str:
        return await base.run(command, cwd, timeout)

    powershell.__doc__ = (
            base.description()
            + "\nWindows PowerShell 5.1 does not support && or ||; "
              "these operators require PowerShell 7 or later."
    )
    return powershell
