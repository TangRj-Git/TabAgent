"""查询托管进程的状态和增量输出。"""

import json

from tabagent.tool.tools.process.process_manager import ProcessManager, ProcessTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "job_id": {
            "type": "string",
            "description": "Job identifier returned by the process manager.",
        },
        "cursor": {
            "type": ["string", "null"],
            "description": "Previous next_cursor unchanged, or null to read retained output.",
        },
        "wait_time": {
            "type": "number",
            "minimum": 0,
            "maximum": 30,
            "description": "Seconds to wait for new output or completion; use 0 for an immediate check.",
        },
    },
    "required": ["job_id", "cursor", "wait_time"],
    "additionalProperties": False,
}


def create_process_read(manager: ProcessManager) -> ProcessTool:
    async def process_read(
            job_id: str,
            cursor: str | None = None,
            wait_time: float = 0.0,
    ) -> str:
        """Read a managed job's status and new stdout/stderr as JSON.

        Waiting does not stop the process. Pass next_cursor back unchanged to
        avoid repeating output. Old output may be discarded; check truncation
        flags, error, exit_code, and output_complete. A running job is not proof
        of application readiness. Cancelling a read leaves the process running.
        """
        result = await manager.read(job_id, cursor=cursor, wait_time=wait_time)
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    return process_read
