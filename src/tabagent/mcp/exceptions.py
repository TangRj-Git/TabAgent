"""MCP 客户端的异常；调用方决定如何展示或恢复。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tabagent.core.exceptions import TabAgentError

if TYPE_CHECKING:
    from .models import MCPErrorInfo


class MCPError(TabAgentError):
    """MCP 模块异常的基类。"""

    def __init__(self, message: str, *, info: MCPErrorInfo | None = None) -> None:
        super().__init__(message)
        self.info = info


class MCPConfigError(MCPError):
    """配置文件或配置字段无效。"""


class MCPConnectionError(MCPError):
    """连接、初始化或关闭服务失败。"""


class MCPNotConnectedError(MCPConnectionError):
    """服务尚未连接，或连接已经关闭。"""


class MCPDiscoveryError(MCPError):
    """能力目录查询失败或分页未完整结束。"""


class MCPRequestError(MCPError):
    """工具请求无法完成；不代表远程操作一定没有执行。"""
