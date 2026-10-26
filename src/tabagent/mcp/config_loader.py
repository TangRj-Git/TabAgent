"""只读加载 JSON 配置，不创建配置、不加载 .env、不改写文件。"""

import json
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError

from .config import MCPClientConfig
from .exceptions import MCPConfigError

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_config_path(config_path: str | Path) -> Path:
    """
    这个函数负责把传入的配置文件路径转换成绝对路径，并对不合法的输入或路径处理错误给出统一异常。
    """
    if not isinstance(config_path, (str, Path)) or not str(config_path).strip():
        raise MCPConfigError("config_path must be a nonempty string or Path.")
    try:
        return Path(config_path).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        raise MCPConfigError("Cannot resolve the MCP configuration path.") from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """这个函数的作用是：把一组键值对转换成字典，并检查是否存在重复的键。发现重复就报错，避免配置被悄悄覆盖。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MCPConfigError("The MCP configuration contains duplicate JSON keys.")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise MCPConfigError("The MCP configuration contains a non-finite JSON number.")


def _expand_environment(value: Any) -> Any:
    """这个函数的作用是：遍历配置数据，把字符串中的 ${环境变量名} 替换成对应的环境变量值。 如果数据包含嵌套的列表、字典，它会递归处理。"""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise MCPConfigError(f"Required environment variable {name!r} is not set.")
            return os.environ[name]

        return _ENV_REFERENCE.sub(replace, value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        # 只展开值；server_id 和字段名称保持原样。
        return {key: _expand_environment(item) for key, item in value.items()}
    return value


def _infer_remote_transport(url: Any) -> Literal["http", "sse"]:
    """与 FastMCP 一致：URL 路径含 /sse 段时推断为 SSE，其他情况使用 HTTP。"""
    if not isinstance(url, str):
        return "http"
    try:
        path = urlsplit(url).path
    except ValueError:
        # 非法 URL 留给配置模型统一校验，避免在推断阶段泄露原始输入。
        return "http"
    return "sse" if re.search(r"/sse(/|\?|&|$)", path) else "http"


def load_mcp_config(config_path: str | Path) -> MCPClientConfig:
    """加载必填路径；相对 cwd 以配置文件所在目录为基准。"""
    path = resolve_config_path(config_path)
    try:
        # 读取 JSON 配置文件，将其转换成 Python 数据，同时拒绝重复的键和 NaN、Infinity 等特殊数值。
        raw = json.loads(
            path.read_text(encoding="utf-8-sig"),  # path 是一个 Path 对象，read_text() 会读取整个文件并返回字符串。
            # 使用 _unique_object 检查重复键
            object_pairs_hook=_unique_object,  # object_pairs_hook 允许你自定义“如何把 JSON 对象转换成 Python 对象”。
            # 使用 _reject_constant 拒绝特殊数值
            parse_constant=_reject_constant,  # 设置 parse_constant 后，遇到这些标记时，会调用你提供的函数，并传入相应的字符串，例如 "NaN"。
        )
    except OSError:
        raise MCPConfigError("Cannot read the MCP configuration file.") from None
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise MCPConfigError("The MCP configuration must be a valid UTF-8 JSON document.") from None

    if not isinstance(raw, dict) or not isinstance(raw.get("mcpServers"), dict):
        raise MCPConfigError("The MCP configuration must contain an mcpServers object.")

    for server_id, entry in raw["mcpServers"].items():
        if not isinstance(entry, dict):
            raise MCPConfigError(f"Configuration for server {server_id!r} must be an object.")
        entry = dict(entry)
        if entry.get("enabled") is not False:
            entry = _expand_environment(entry)
        # 支持常见的 command/args 或 url 配置；有歧义时必须明确 transport。
        if "transport" not in entry:
            if "command" in entry and "url" not in entry:
                entry["transport"] = "stdio"
            elif "url" in entry and "command" not in entry:
                entry["transport"] = _infer_remote_transport(entry["url"])
        if entry.get("transport") == "streamable-http":
            entry["transport"] = "http"
        if entry.get("transport") == "stdio" and entry.get("enabled") is not False:
            cwd = entry.get("cwd", ".")
            if not isinstance(cwd, str) or not cwd.strip():
                raise MCPConfigError(f"cwd for server {server_id!r} must be a nonempty string.")
            try:
                directory = Path(cwd).expanduser()
                if not directory.is_absolute():
                    directory = path.parent / directory
                directory = directory.resolve()
                if not directory.is_dir():
                    raise MCPConfigError(f"cwd for server {server_id!r} must be an existing directory.")
                entry["cwd"] = str(directory)
            except (OSError, ValueError, RuntimeError):
                raise MCPConfigError(f"Cannot resolve cwd for server {server_id!r}.") from None
        raw["mcpServers"][server_id] = entry

    try:
        return MCPClientConfig.model_validate(raw)
    except ValidationError as exc:
        # 不输出原始 input/context；仅保留我们自己的、未包含输入值的验证说明。
        issues = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'configuration'}: "
            f"{item['msg'] if item['type'] == 'value_error' else item['type']}"
            for item in exc.errors(include_url=False, include_context=False, include_input=False)
        )
        raise MCPConfigError(f"Invalid MCP configuration ({issues}).") from None


r"""
{
  "mcpServers": {
    "python_tools": {
      "transport": "stdio",
      "command": "python",
      "args": ["server.py", "--debug"],
      "env": {
        "API_KEY": "${API_KEY}"
      },
      "enabled": true,
      "required": false,
      "connect_timeout": 30.0,
      "request_timeout": null
    }
  }
}

raw = {
    "mcpServers": {
        "python_tools": {
            "transport": "stdio",
            "command": "python",
            "args": ["server.py", "--debug"],
            "env": {
                "API_KEY": "${API_KEY}"
            },
            "enabled": True,
            "required": False,
            "connect_timeout": 30.0,
            "request_timeout": None,
        }
    }
}

MCPClientConfig(
    servers={
        "python_tools": StdioConfig(
            # JSON 中提供的连接配置
            transport="stdio",
            command="python",
            args=["server.py", "--debug"],

            # 环境变量已经展开，并被包装成 SecretStr
            env={
                "API_KEY": SecretStr("demo-key"),
            },

            # JSON 未指定 cwd，加载器使用配置文件所在目录
            cwd=r"E:\OpenProject\TabAgent\resources",

            # JSON 中显式提供的公共配置
            enabled=True,
            required=False,
            connect_timeout=30.0,
            request_timeout=None,

            # JSON 中没有提供，由模型补上的默认值
            discovery_timeout=60.0,
            close_timeout=5.0,
            max_discovery_pages=250,
            max_discovery_items=10000,
            max_cursor_bytes=65536,
        ),
    },
)
"""
