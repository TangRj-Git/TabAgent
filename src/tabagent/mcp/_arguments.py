"""只复制合法 JSON 参数；Schema 的业务校验仍由 MCP 服务端负责。"""

import math
from typing import Any

from .exceptions import MCPRequestError


def copy_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if not isinstance(arguments, dict):
        raise MCPRequestError("Tool arguments must be an object with string keys.")

    ancestors: set[int] = set()

    def copy(value: Any, depth: int) -> Any:
        if depth > 64:
            raise MCPRequestError("Tool arguments exceed the maximum JSON nesting depth of 64.")
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise MCPRequestError("Tool arguments must not contain non-finite numbers.")
            return value
        if not isinstance(value, (dict, list)):
            raise MCPRequestError("Tool arguments must contain only JSON objects, arrays and scalar values.")
        identity = id(value)
        if identity in ancestors:
            raise MCPRequestError("Tool arguments must not contain circular references.")
        ancestors.add(identity)
        try:
            if isinstance(value, list):
                return [copy(item, depth + 1) for item in value]
            if any(not isinstance(key, str) for key in value):
                raise MCPRequestError("All JSON object keys in tool arguments must be strings.")
            return {key: copy(item, depth + 1) for key, item in value.items()}
        finally:
            ancestors.remove(identity)

    return copy(arguments, 0)
