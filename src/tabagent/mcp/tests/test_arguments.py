import math

import pytest

from tabagent.mcp._arguments import copy_arguments
from tabagent.mcp.exceptions import MCPRequestError


@pytest.mark.parametrize("arguments", [
    [], {"nested": {1: "a", "1": "b"}}, {"nested": [{False: 1}]},
    {"value": math.nan}, {"value": math.inf}, {"value": (1, 2)}, {"value": object()},
])
def test_invalid_json_rejected(arguments):
    with pytest.raises(MCPRequestError):
        copy_arguments(arguments)


def test_cycles_and_excessive_depth_rejected():
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(MCPRequestError, match="circular"):
        copy_arguments(cyclic)
    nested = {}
    for _ in range(66):
        nested = {"child": nested}
    with pytest.raises(MCPRequestError, match="depth"):
        copy_arguments(nested)


def test_copy_does_not_mutate_caller_and_shared_values_are_valid():
    shared = [True, None, 1.5, {"name": "MCP"}]
    original = {"first": shared, "second": shared}
    copied = copy_arguments(original)
    copied["first"][3]["name"] = "changed"
    assert original["first"][3]["name"] == "MCP"
    assert copied["second"][3]["name"] == "MCP"
    assert copy_arguments(None) == {}
