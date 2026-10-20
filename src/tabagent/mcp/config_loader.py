"""只读加载 JSON 配置，不创建配置、不加载 .env、不改写文件。"""

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import MCPClientConfig
from .exceptions import MCPConfigError

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_config_path(config_path: str | Path) -> Path:
    """将调用者明确提供的路径固定为绝对路径。"""
    if not isinstance(config_path, (str, Path)) or not str(config_path).strip():
        raise MCPConfigError("config_path must be a nonempty string or Path.")
    try:
        return Path(config_path).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        raise MCPConfigError("Cannot resolve the MCP configuration path.") from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MCPConfigError("The MCP configuration contains duplicate JSON keys.")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise MCPConfigError("The MCP configuration contains a non-finite JSON number.")


def _expand_environment(value: Any) -> Any:
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


def load_mcp_config(config_path: str | Path) -> MCPClientConfig:
    """加载必填路径；相对 cwd 以配置文件所在目录为基准。"""
    path = resolve_config_path(config_path)
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
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
                entry["transport"] = "http"
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
