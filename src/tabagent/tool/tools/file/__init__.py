"""
按操作拆分的文件工具；通过 BaseFile 绑定默认目录和本次运行的临时范围。

应用或 Agent 中间件应在一次完整运行期间保持上下文打开，例如：

    with BaseFile(workspace=project_path) as base:
        base.grant_file(external_file, writable=True)
        for tool in create_file_tools(base):
            run_registry.register_tool(tool)
        # 在此完成本次 Agent 运行的所有模型调用和工具调用。

run_registry 应是本次运行的注册表，不能复用之前绑定到其他 BaseFile 的文件工具。
退出 with 后，已注册的这些工具也会拒绝后续操作。
"""

from collections.abc import Callable
from typing import Any

from .base_file import BaseFile
from .copy_path import build_copy_path
from .create_directory import build_create_directory
from .delete_directory import build_delete_directory
from .delete_file import build_delete_file
from .edit_file import build_edit_file
from .find_paths import build_find_paths
from .list_directory import build_list_directory
from .move_path import build_move_path
from .read_file import build_read_file
from .search_text import build_search_text
from .write_file import build_write_file

__all__ = ["BaseFile", "create_file_tools"]


def create_file_tools(base: BaseFile) -> list[Callable[..., dict[str, Any]]]:
    """
    返回可以直接传入 ToolRegistry.register_tool 的普通函数。

    base 由闭包保存，不会成为模型工具参数。
    每次 Agent 运行创建独立 BaseFile 和工具函数；默认项目路径可以保持相同。
    工具注册表的副本仍会复用函数，不能代替重新绑定 BaseFile。
    授权和关闭方法只供应用调用，不包含在模型工具列表中。
    """
    base.ensure_open()
    return [
        build_list_directory(base),
        build_find_paths(base),
        build_read_file(base),
        build_search_text(base),
        build_write_file(base),
        build_edit_file(base),
        build_create_directory(base),
        build_delete_file(base),
        build_delete_directory(base),
        build_move_path(base),
        build_copy_path(base),
    ]
