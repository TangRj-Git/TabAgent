import inspect
from typing import get_type_hints, Callable, Any

from tabagent.tool.registry import SCHEMA_TYPE


def test_function() -> None:
    def add(a: float, b: float) -> float:
        """计算 a 加 b。"""
        return a + b

    signature = inspect.signature(add)
    print(signature)
    print(signature.parameters.items())
    print(signature.return_annotation)

    for name, parameter in signature.parameters.items():
        print(name, parameter)
        print(parameter.kind)
        print(parameter.default)

    type_hints = get_type_hints(add)
    print(type_hints)


def test_function_with_parameter() -> None:
    def add(a: float, b: float) -> float:
        """计算 a 加 b。"""
        return a + b

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

    result = _build_parameters(add)
    print(result)
