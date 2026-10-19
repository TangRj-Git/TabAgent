"""进程工具工厂；所有工具绑定调用方提供的同一个管理器。"""

from tabagent.tool.tools.process.process_list import (
    PARAMETERS as PROCESS_LIST_PARAMETERS,
    create_process_list,
)
from tabagent.tool.tools.process.process_manager import ProcessManager, ProcessTool
from tabagent.tool.tools.process.process_read import (
    PARAMETERS as PROCESS_READ_PARAMETERS,
    create_process_read,
)
from tabagent.tool.tools.process.process_stop import (
    PARAMETERS as PROCESS_STOP_PARAMETERS,
    create_process_stop,
)

PROCESS_TOOL_PARAMETERS = {
    "process_read": PROCESS_READ_PARAMETERS,
    "process_stop": PROCESS_STOP_PARAMETERS,
    "process_list": PROCESS_LIST_PARAMETERS,
}


def create_process_tools(manager: ProcessManager) -> dict[str, ProcessTool]:
    """创建三个异步工具；管理器的创建、关闭和工具注册由调用方负责。"""
    tools = (
        create_process_read(manager),
        create_process_stop(manager),
        create_process_list(manager),
    )
    return {tool.__name__: tool for tool in tools}


__all__ = [
    "ProcessManager",
    "ProcessTool",
    "PROCESS_TOOL_PARAMETERS",
    "create_process_tools",
    "create_process_read",
    "create_process_stop",
    "create_process_list",
]
