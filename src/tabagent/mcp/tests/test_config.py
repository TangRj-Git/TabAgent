import json

import pytest
from pydantic import ValidationError

from tabagent.mcp import MCPClientManager, MCPConfigError, RemoteConfig, StdioConfig, load_mcp_config


def test_config_path_is_required_and_relative_cwd_uses_config_directory(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    monkeypatch.setenv("TABAGENT_MCP_TEST_TOKEN", "private-value")
    path.write_text(json.dumps({"mcpServers": {
        "local": {"command": "python", "args": ["relative.py"], "env": {"TOKEN": "${TABAGENT_MCP_TEST_TOKEN}"}},
        "remote": {"url": "https://example.invalid/mcp"},
        "disabled": {"enabled": False, "command": "${MISSING_COMMAND}", "cwd": "missing-directory"},
    }}), encoding="utf-8")
    with pytest.raises(TypeError):
        MCPClientManager()
    config = load_mcp_config(path)
    assert config.servers["local"].cwd == str(tmp_path.resolve())
    assert config.servers["local"].args == ["relative.py"]
    assert config.servers["local"].env["TOKEN"].get_secret_value() == "private-value"
    assert config.servers["remote"].transport == "http"
    assert not config.servers["disabled"].enabled
    assert "private-value" not in repr(config)
    assert config.servers["local"].close_timeout == 5.0


@pytest.mark.parametrize("text", [
    "", '{"mcpServers": {}, "mcpServers": {}}',
    '{"mcpServers": {"test": {"command": "python", "unknown": true}}}',
    '{"mcpServers": {"test": {"command": "python", "url": "https://example.invalid"}}}',
    '{"mcpServers": {"test": {"url": "${TABAGENT_MCP_MISSING_ENV_9238}"}}}',
])
def test_bad_configuration_is_rejected(tmp_path, text):
    path = tmp_path / "mcp.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MCPConfigError):
        load_mcp_config(path)


@pytest.mark.parametrize("field", ["close_timeout", "max_discovery_items", "max_cursor_bytes"])
def test_new_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        StdioConfig(command="unused", **{field: 0})


def test_conflicting_authorization_and_duplicate_headers_rejected():
    with pytest.raises(ValidationError):
        RemoteConfig(url="https://example.invalid/mcp", headers={"X-Key": "a", "x-key": "b"})
    with pytest.raises(ValidationError):
        RemoteConfig(
            url="https://example.invalid/mcp", headers={"Authorization": "Bearer a"},
            auth={"type": "bearer", "token": "b"},
        )
