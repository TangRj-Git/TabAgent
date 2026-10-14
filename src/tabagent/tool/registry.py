import inspect
from typing import Callable, Any, Optional, get_type_hints

from tabagent.core.function import Function

SCHEMA_TYPE: dict[type, str] = {
    # 数值
    int: "integer",
    float: "number",

    # 字符串
    str: "string",

    # 布尔值
    bool: "boolean",

    # 数组：Python 列表和元组都可以序列化为 JSON 数组
    list: "array",
    tuple: "array",

    # 对象
    dict: "object",

    # 空值：None 对应的类型
    type(None): "null",
}


def _build_parameters(
        tool: Callable[..., Any],
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    signature = inspect.signature(tool)
    type_hints = get_type_hints(tool)

    for name, parameter in signature.parameters.items():

        annotation = type_hints.get(name)
        if annotation not in SCHEMA_TYPE:
            raise ValueError(f"Unsupported type {annotation}")

        properties[name] = {
            "type": SCHEMA_TYPE[annotation],
        }
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[
            str,
            tuple[Callable[..., Any], Function]
        ] = {}

    def register(
            self,
            tool: Callable[..., Any],
            *,
            name: Optional[str] = None,
            description: Optional[str] = None,
            parameters: Optional[dict[str, Any]] = None,
            strict: bool = True,
            output_schema: Optional[dict[str, Any]] = None,
    ):
        tool_name = name if name is not None else tool.__name__
        tool_description = description if description is not None else tool.__doc__
        tool_parameters = parameters if parameters is not None else _build_parameters(tool)

        if tool_name in self._tools:
            raise ValueError(f"Tool {tool_name} already registered")

        function = Function(
            name=tool_name,
            description=tool_description,
            parameters=tool_parameters,
            strict=strict,
            output_schema=output_schema,
        )

        self._tools[tool_name] = (tool, function)
        return function
