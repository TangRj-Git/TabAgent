import inspect
from copy import deepcopy
from typing import Callable, Any, Optional, get_type_hints

from tabagent.core.exceptions import ToolNotFoundError, ToolRegistrationError
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
        strict: bool,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    try:
        signature = inspect.signature(tool)
        type_hints = get_type_hints(tool)
    except Exception as exc:
        raise ToolRegistrationError(
            "Cannot inspect the tool signature or resolve its type annotations. "
            "Provide a supported function or an explicit parameters schema."
        ) from exc

    for name, parameter in signature.parameters.items():
        if name not in type_hints:
            raise ToolRegistrationError(
                f"Parameter {name!r} is missing a type annotation. "
                "Add an annotation or provide an explicit parameters schema."
            )

        annotation = type_hints.get(name)
        if annotation not in SCHEMA_TYPE:
            raise ToolRegistrationError(
                f"Parameter {name!r} has an unsupported type annotation: "
                f"{annotation!r}. Provide an explicit parameters schema."
            )

        properties[name] = {
            "type": SCHEMA_TYPE[annotation],
        }
        if strict or parameter.default is inspect.Parameter.empty:
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

    def register_tool(
            self,
            tool: Callable[..., Any],
            *,
            name: Optional[str] = None,
            description: Optional[str] = None,
            parameters: Optional[dict[str, Any]] = None,
            strict: bool = True,
            output_schema: Optional[dict[str, Any]] = None,
    ) -> Function:
        if not callable(tool):
            raise ToolRegistrationError("Only callable objects can be registered as tools.")

        tool_name = name if name is not None else getattr(tool, "__name__", None)
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ToolRegistrationError(
                "A non-empty tool name is required. Pass name explicitly "
                "for callables without a __name__ attribute."
            )

        if tool_name in self._tools:
            raise ToolRegistrationError(f"Tool {tool_name!r} is already registered.")

        # 检查函数签名。
        # 即使显式提供 parameters，也必须符合当前支持的参数形式。
        try:
            signature = inspect.signature(tool)
        except (TypeError, ValueError) as exc:
            raise ToolRegistrationError(
                f"Cannot register tool {tool_name!r}: "
                "its function signature could not be inspected."
            ) from exc

        for parameter in signature.parameters.values():
            if parameter.kind not in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
            ):
                raise ToolRegistrationError(
                    f"Tool {tool_name!r} has unsupported parameter "
                    f"{parameter.name!r} ({parameter.kind.name}). "
                    "Only positional-or-keyword and keyword-only "
                    "parameters are supported."
                )

        tool_description = description if description is not None else tool.__doc__
        tool_parameters = parameters if parameters is not None else _build_parameters(tool, strict)

        function = Function(
            name=tool_name,
            description=tool_description,
            parameters=tool_parameters,
            strict=strict,
            output_schema=output_schema,
        )

        self._tools[tool_name] = (tool, function)
        return function

    def unregister_tool(
            self,
            name: str,
    ) -> Optional[Function]:
        registered = self._tools.pop(name, None)

        if registered is None:
            return None

        _, function = registered
        return function

    def get_tool(
            self,
            name: str,
    ) -> Callable[..., Any]:
        try:
            return self._tools[name][0]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool {name!r} is not registered.") from exc

    def get_tools(self) -> dict[str, Callable[..., Any]]:
        return {
            name: tool
            for name, (tool, _) in self._tools.items()
        }

    def get_functions(self) -> list[Function]:
        return [
            function
            for _, function in self._tools.values()
        ]

    def get_copy(self) -> "ToolRegistry":
        registry = ToolRegistry()
        registry._tools = {
            name: (tool, deepcopy(function))
            for name, (tool, function) in self._tools.items()
        }
        return registry
