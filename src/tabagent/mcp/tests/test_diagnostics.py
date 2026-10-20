from types import SimpleNamespace

import pytest

from tabagent.mcp.diagnostics import error_info


@pytest.mark.parametrize("status,category", [(401, "authentication"), (503, "http")])
def test_http_diagnostics_hide_raw_secrets(status, category):
    inner = RuntimeError("Authorization: Bearer private-token; https://secret.example/path")
    inner.response = SimpleNamespace(status_code=status)
    outer = ExceptionGroup("sensitive group message", [inner])
    info = error_info(server_id="test", operation="connect", exc=outer)
    assert info.category == category
    assert info.status_code == status
    assert "private-token" not in repr(info)
    assert "secret.example" not in repr(info)
    assert "sensitive" not in repr(info)


def test_protocol_code_is_preserved_without_remote_message():
    exc = RuntimeError("private remote request payload")
    exc.error = SimpleNamespace(code=-32602)
    info = error_info(server_id="test", operation="tools", exc=exc)
    assert info.category == "protocol"
    assert info.error_code == -32602
    assert "private" not in repr(info)
