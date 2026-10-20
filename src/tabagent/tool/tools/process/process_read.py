"""查询托管进程的状态和增量输出。"""

import json

from tabagent.core.exceptions import ToolArgumentsError
from tabagent.tool.tools.process.process_manager import ProcessManager, ProcessTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "job_id": {
            "type": "string",
            "description": "Job identifier returned by a managed Shell call or process_list; not an operating-system PID.",
        },
        "cursor": {
            "type": ["string", "null"],
            "description": "Copy this job's previous next_cursor unchanged, or use null to read from the start of its retained output. Old discarded output cannot be recovered.",
        },
        "wait_time": {
            "type": "number",
            "minimum": 0,
            "maximum": 30,
            "description": "Seconds to wait for new output or completion; use 0 for an immediate check.",
        },
        "max_output_chars": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50000,
            "description": "Maximum Unicode characters returned per stream, excluding JSON metadata; normally 10000. Does not change buffer capacity. Read next_cursor again while has_more_output is true.",
        },
    },
    "required": ["job_id", "cursor", "wait_time", "max_output_chars"],
    "additionalProperties": False,
}


def create_process_read(manager: ProcessManager) -> ProcessTool:
    async def process_read(
            job_id: str,
            cursor: str | None = None,
            wait_time: float = 0.0,
            *,
            max_output_chars: int = 10_000,
    ) -> str:
        """Read a managed job's status and new stdout/stderr as JSON.

        Waiting does not stop the process. Pass next_cursor back unchanged to
        avoid repeating output. Old output may be discarded; check truncation
        flags and stdout_dropped_chars/stderr_dropped_chars for characters lost
        since the requested cursor. *_total_chars counts all collected output;
        output_limit_chars is the retained capacity per stream. These counts
        use Unicode characters, not bytes or tokens. output_complete means
        collection finished without a pipe error, not that all historical
        output was retained or returned. Continue reading while has_more_output
        is true, even after the process exits. Check error and exit_code before
        reporting success. A running job is not proof of application readiness.
        Cancelling a read leaves the process running. Completion does not
        automatically notify the model; call this tool to check it.
        """
        # None 表示管理器内部不限单次返回量；公开工具只接受 schema 中的整数。
        if type(max_output_chars) is not int:
            raise ToolArgumentsError("max_output_chars must be an integer between 1 and 50000.")
        result = await manager.read(
            job_id, cursor=cursor, wait_time=wait_time,
            max_output_chars=max_output_chars,
        )
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    return process_read
