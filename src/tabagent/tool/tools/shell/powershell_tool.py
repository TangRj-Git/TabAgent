"""Windows PowerShell 工具，优先使用 PowerShell 7。"""

import base64
from pathlib import Path

from tabagent.tool.tools.process import ProcessManager
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
    # 使用编码脚本保留引号和换行，通过 -Command 解码执行。
    # 避免 -EncodedCommand 在重定向输出时将额外输出流序列化为 CLIXML。
    script = (
            "$ProgressPreference = 'SilentlyContinue'\n"
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
    launcher = (
        "& ([ScriptBlock]::Create([Text.Encoding]::Unicode.GetString("
        f"[Convert]::FromBase64String('{encoded}'))))"
    )
    return [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-OutputFormat",
        "Text",
        "-Command",
        launcher,
    ]


def create_powershell_tool(
        workspace: str | Path,
        *,
        process_manager: ProcessManager | None = None,
) -> ShellTool:
    """创建 PowerShell 工具；共享管理器由调用方持有和关闭。"""
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
        process_manager=process_manager,
    )

    async def powershell(
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

    powershell.__doc__ = (
            base.description()
            + "\nWindows PowerShell 5.1 does not support && or ||; "
              "these operators require PowerShell 7 or later."
              "\nWarnings and information are rendered as text and may appear "
              "in stdout. Progress output is disabled. Check status, exit_code, "
              "timed_out, and error before reporting success."
              "\nThe last native program's exit code is preserved, even if "
              "a later PowerShell cmdlet succeeds. Use exit 0 after handling "
              "a native program failure, or exit N to set an explicit code."
    )
    return powershell
