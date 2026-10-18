"""文件工具工厂；只绑定默认目录，不自动修改 Agent 或工具注册表。"""

from collections.abc import Callable
from pathlib import Path

from tabagent.tool.tools.file.base_file import BaseFile
from tabagent.tool.tools.file.edit_file import (
    PARAMETERS as EDIT_FILE_PARAMETERS,
    create_edit_file,
)
from tabagent.tool.tools.file.find_paths import (
    PARAMETERS as FIND_PATHS_PARAMETERS,
    create_find_paths,
)
from tabagent.tool.tools.file.list_directory import (
    PARAMETERS as LIST_DIRECTORY_PARAMETERS,
    create_list_directory,
)
from tabagent.tool.tools.file.read_file import (
    PARAMETERS as READ_FILE_PARAMETERS,
    create_read_file,
)
from tabagent.tool.tools.file.search_text import (
    PARAMETERS as SEARCH_TEXT_PARAMETERS,
    create_search_text,
)
from tabagent.tool.tools.file.write_file import (
    PARAMETERS as WRITE_FILE_PARAMETERS,
    create_write_file,
)

FILE_TOOL_PARAMETERS = {
    "list_directory": LIST_DIRECTORY_PARAMETERS,
    "find_paths": FIND_PATHS_PARAMETERS,
    "search_text": SEARCH_TEXT_PARAMETERS,
    "read_file": READ_FILE_PARAMETERS,
    "write_file": WRITE_FILE_PARAMETERS,
    "edit_file": EDIT_FILE_PARAMETERS
}


def create_file_tools(workspace: str | Path) -> dict[str, Callable[..., str]]:
    """为一个固定工作目录创建六个工具函数，供调用方显式注册。"""
    base = BaseFile(workspace)
    factories = (
        create_list_directory,
        create_find_paths,
        create_search_text,
        create_read_file,
        create_write_file,
        create_edit_file
    )
    tools = [
        factory(base)
        for factory in factories
    ]
    return {
        tool.__name__: tool
        for tool in tools
    }


__all__ = [
    "BaseFile",
    "FILE_TOOL_PARAMETERS",
    "create_file_tools"
]
