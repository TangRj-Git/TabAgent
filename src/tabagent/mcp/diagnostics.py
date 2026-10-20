"""提取安全的错误分类和数字错误码，不记录远端异常全文、URL 或凭据。"""

import asyncio

from .exceptions import MCPError
from .models import MCPErrorInfo


def error_info(*, server_id: str, operation: str, exc: BaseException) -> MCPErrorInfo:
    # SDK 可能用 RuntimeError / ExceptionGroup 包装底层错误。
    pending = [exc]
    causes: list[BaseException] = []
    seen: set[int] = set()
    while pending and len(causes) < 32:
        cause = pending.pop()
        if id(cause) in seen:
            continue
        seen.add(id(cause))
        causes.append(cause)
        if isinstance(cause, BaseExceptionGroup):
            pending.extend(reversed(cause.exceptions))
        following = cause.__cause__ or (
            None if cause.__suppress_context__ else cause.__context__
        )
        if following is not None:
            pending.append(following)

    category = "protocol_or_transport"
    reason = "The transport or protocol request failed."
    selected = causes[-1]
    status_code = None
    error_code = None
    for cause in reversed(causes):
        status = getattr(getattr(cause, "response", None), "status_code", None)
        code = getattr(getattr(cause, "error", None), "code", None)
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
            selected, status_code = cause, status
            category = "authentication" if status in (401, 403) else "http"
            reason = f"The server returned HTTP {status}."
        elif isinstance(cause, TimeoutError) or "Timeout" in type(cause).__name__:
            selected, category = cause, "timeout"
            reason = "The operation exceeded its time limit."
        elif isinstance(cause, FileNotFoundError):
            selected, category = cause, "not_found"
            reason = "A required executable or local path was not found."
        elif isinstance(cause, PermissionError):
            selected, category = cause, "permission"
            reason = "The operating system denied access."
        elif isinstance(cause, ConnectionError):
            selected, category = cause, "connection"
            reason = "The connection could not be established or was lost."
        elif isinstance(cause, asyncio.CancelledError):
            if cause is not exc:
                # asyncio.timeout 的 __cause__ 是取消，面向调用者的原因仍是超时。
                continue
            selected, category = cause, "cancelled"
            reason = "The operation was cancelled."
        elif isinstance(code, int) and not isinstance(code, bool):
            selected, category, error_code = cause, "protocol", code
            reason = f"The server returned protocol error {code}."
        elif isinstance(cause, OSError):
            selected, category, error_code = cause, "os", cause.errno
            reason = "An operating system operation failed."
        else:
            continue
        break

    # 本模块生成的错误没有远端原始输入，可以保留具体的分页等失败原因。
    if isinstance(exc, MCPError):
        reason = str(exc)
        category = "validation"
    return MCPErrorInfo(
        server_id=server_id,
        operation=operation,
        message=f"MCP {operation} failed for server {server_id!r}. {reason}",
        exception_type=type(exc).__name__,
        category=category,
        cause_type=type(selected).__name__,
        status_code=status_code,
        error_code=error_code,
    )
