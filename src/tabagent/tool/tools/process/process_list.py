"""列出当前管理器持有的进程任务。"""

import json

from tabagent.tool.tools.process.process_manager import ProcessManager, ProcessTool

PARAMETERS = {
    "type": "object",
    "properties": {
        "include_finished": {
            "type": "boolean",
            "description": "Include retained finished jobs; normally false.",
        },
    },
    "required": ["include_finished"],
    "additionalProperties": False,
}


def create_process_list(manager: ProcessManager) -> ProcessTool:
    async def process_list(include_finished: bool = False) -> str:
        """List jobs owned by this manager, including their IDs, commands and states.

        This does not enumerate other system processes. By default, return
        running jobs and jobs still collecting output. Finished jobs are kept
        only up to the manager's retention limit. Use process_read for output.
        """
        result = await manager.list_jobs(include_finished=include_finished)
        return json.dumps(result, ensure_ascii=False, allow_nan=False)

    return process_list
