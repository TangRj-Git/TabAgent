"""停止当前管理器持有的指定进程任务。"""

import json

from tabagent.tool.tools.process.process_manager import ProcessManager, ProcessTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "job_id": {
            "type": "string",
            "description": "Identifier of the managed job to stop.",
        },
    },
    "required": ["job_id"],
    "additionalProperties": False,
}


def create_process_stop(manager: ProcessManager) -> ProcessTool:
    async def process_stop(job_id: str) -> str:
        """Force-stop a managed process tree and return its status and retained output.

        Only jobs owned by this manager can be stopped. Descendants whose root
        has already exited, and detached descendants, are not fully managed.
        Stopping an already finished job preserves its original exit status.
        Check the returned status; termination failures are reported as errors.
        Stopping does not undo earlier side effects.
        """
        result = await manager.stop(job_id)
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    return process_stop
